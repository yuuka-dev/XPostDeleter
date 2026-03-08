"""
archive_scanner.py
Xアーカイブ（tweets.js + tweets_media/）をスキャンして
顔写真・NSFW画像・テキスト分析を行い delete_hit_list.csv に追記する。

delete_hit_list.csv が既に存在する場合は画像・動画解析をスキップし、
テキスト解析のみ実行する（重い画像処理の二重実行防止）。
"""

import csv
import glob
import json
import os
import re
import traceback
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from image_analyzer import analyze_image, analyze_video
from tqdm import tqdm

# --- 設定 ---
ARCHIVE_DIR = Path(__file__).parent / "XArchive" / "data"
TWEETS_JS = ARCHIVE_DIR / "tweets.js"
MEDIA_DIR = ARCHIVE_DIR / "tweets_media"
OUTPUT_CSV = Path(__file__).parent / "delete_hit_list.csv"

CSV_COLUMNS = ["created_at", "delete_url", "severity", "risk_tags", "full_text", "hapus"]

# severityがこれ以上のものだけCSVに追記する（0にすれば全件）
MIN_SEVERITY = 1

# 並列ワーカー数（CPUコア数に合わせて調整）
MAX_WORKERS = 4


def load_tweets(js_path: Path) -> list:
    with open(js_path, encoding="utf-8-sig") as f:
        raw = f.read()
    json_str = re.sub(r"^window\.\S+ = ", "", raw.strip())
    data = json.loads(json_str)
    return [item["tweet"] for item in data]


def find_media_files(tweet_id: str) -> list[str]:
    """ツイートIDに紐づくメディアファイルを返す"""
    pattern = str(MEDIA_DIR / f"{tweet_id}-*")
    return glob.glob(pattern)


def load_existing_urls(csv_path: Path) -> set:
    """既存CSVのdelete_urlセットを返す（重複チェック用）"""
    if not csv_path.exists():
        return set()
    urls = set()
    try:
        with open(csv_path, encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                urls.add(row.get("delete_url", ""))
    except Exception as e:
        print(f"[WARN] 既存CSV読み込みエラー: {e}")
    return urls


def analyze_tweet_media(args: tuple) -> dict | None:
    """
    1ツイート分のメディアを解析してCSV行データを返す
    ProcessPoolExecutor から呼ばれるトップレベル関数
    """
    tweet, media_files = args
    tweet_id = tweet.get("id_str", "")
    created_at = tweet.get("created_at", "")
    full_text = tweet.get("full_text", "").replace("\n", " ")
    delete_url = f"https://x.com/i/status/{tweet_id}"

    best_severity = 0
    all_risk_tags = []

    for media_path in media_files:
        ext = os.path.splitext(media_path)[1].lower()
        try:
            if ext in (".jpg", ".jpeg", ".png", ".webp"):
                result = analyze_image(media_path)
            elif ext in (".mp4", ".mov", ".webm"):
                result = analyze_video(media_path)
            else:
                continue
            if result["severity"] > best_severity:
                best_severity = result["severity"]
            for tag in result["risk_tags"]:
                if tag not in all_risk_tags:
                    all_risk_tags.append(tag)
        except Exception:
            pass

    if best_severity < MIN_SEVERITY:
        return None

    return {
        "created_at": created_at,
        "delete_url": delete_url,
        "severity": best_severity,
        "risk_tags": str(all_risk_tags),
        "full_text": full_text,
        "hapus": "",
    }


def main(enable_text: bool = False):
    print(f"tweets.js 読み込み中: {TWEETS_JS}")
    try:
        tweets = load_tweets(TWEETS_JS)
    except Exception as e:
        print(f"[ERROR] tweets.js 読み込み失敗: {e}")
        traceback.print_exc()
        return
    print(f"  ツイート数: {len(tweets)}")

    existing_urls = load_existing_urls(OUTPUT_CSV)
    print(f"  既存CSV件数: {len(existing_urls)}")

    # CSV が存在すれば画像・動画解析をスキップ
    skip_image = OUTPUT_CSV.exists()
    if skip_image:
        print("  [INFO] delete_hit_list.csv が存在するため画像・動画解析をスキップ → テキスト解析のみ実行")

    # 未処理ツイートを全件抽出（テキスト解析対象）
    all_unprocessed = [
        t for t in tweets
        if f"https://x.com/i/status/{t.get('id_str', '')}" not in existing_urls
    ]
    print(f"  未処理ツイート: {len(all_unprocessed)}")

    if not all_unprocessed:
        print("処理対象なし。")
        return

    # tweet_id → row_dict（このrunで生成した行を蓄積）
    run_rows: dict[str, dict] = {}

    # --- 画像・動画解析（CSV未存在時のみ） ---
    if not skip_image:
        media_targets = [
            (t, files)
            for t in all_unprocessed
            if (files := find_media_files(t.get("id_str", "")))
        ]
        print(f"\n画像・動画解析対象: {len(media_targets)} 件（ワーカー数: {MAX_WORKERS}）")

        if media_targets:
            error_count = 0
            with ProcessPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {
                    executor.submit(analyze_tweet_media, args): args
                    for args in media_targets
                }
                with tqdm(total=len(media_targets), unit="tweet", dynamic_ncols=True) as pbar:
                    for future in as_completed(futures):
                        try:
                            row = future.result()
                            if row is not None:
                                tweet_id = row["delete_url"].split("/")[-1]
                                run_rows[tweet_id] = row
                                pbar.set_postfix(hits=len(run_rows), errors=error_count)
                        except Exception:
                            error_count += 1
                            pbar.set_postfix(hits=len(run_rows), errors=error_count)
                        finally:
                            pbar.update(1)

            print(f"  画像・動画 検出: {len(run_rows)} 件  エラー: {error_count}")

    # --- テキスト解析（--text フラグ指定時のみ） ---
    if enable_text:
        from text_analyzer import TextAnalyzer, merge_text_into_row

        print(f"\nテキスト解析開始: {len(all_unprocessed)} 件")
        analyzer = TextAnalyzer()
        tweet_dicts = [
            {"id": t.get("id_str", ""), "text": t.get("full_text", "")}
            for t in all_unprocessed
        ]
        text_results = analyzer.analyze(tweet_dicts)

        text_hit = 0
        for ta in text_results:
            if not ta.flagged:
                continue
            if ta.tweet_id in run_rows:
                # 同一ツイートに画像ヒットもある → マージ
                run_rows[ta.tweet_id] = merge_text_into_row(run_rows[ta.tweet_id], ta)
            else:
                # テキストのみのヒット → 新規行
                tweet = next(
                    (t for t in all_unprocessed if t.get("id_str") == ta.tweet_id), None
                )
                if tweet is None:
                    continue
                severity = ta.severity_delta()
                if severity < MIN_SEVERITY:
                    continue
                run_rows[ta.tweet_id] = {
                    "created_at": tweet.get("created_at", ""),
                    "delete_url": f"https://x.com/i/status/{ta.tweet_id}",
                    "severity": severity,
                    "risk_tags": str([ta.risk_tag]),
                    "full_text": tweet.get("full_text", "").replace("\n", " "),
                    "hapus": "",
                }
            text_hit += 1

        print(f"  テキスト 検出: {text_hit} 件")
    else:
        print("\n[INFO] テキスト解析スキップ（有効にするには --text を指定）")

    new_rows = list(run_rows.values())
    print(f"\n合計追記件数: {len(new_rows)}")

    if not new_rows:
        print("追記なし。")
        return

    # CSV追記（なければ新規作成）
    try:
        file_exists = OUTPUT_CSV.exists()
        with open(OUTPUT_CSV, "a", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
            if not file_exists:
                writer.writeheader()
            writer.writerows(new_rows)
        print(f"CSV追記完了: {OUTPUT_CSV}  ({len(new_rows)}件)")
    except Exception as e:
        print(f"[ERROR] CSV書き込み失敗: {e}")
        traceback.print_exc()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Xアーカイブをスキャンして delete_hit_list.csv を生成する")
    parser.add_argument(
        "--text",
        action="store_true",
        help="テキスト解析（キーワード + Gemini + Claude）を有効にする。デフォルトは画像・動画解析のみ。",
    )
    args = parser.parse_args()
    main(enable_text=args.text)
