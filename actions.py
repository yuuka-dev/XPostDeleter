"""
actions.py
削除・RT取り消しのメインルーチン
"""

import csv
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from browser import navigate_to
from human import human_browse_page, human_move_click_element, human_pause
from rich.console import Console
from selenium import webdriver
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from utils import _make_bar

LIMIT_PER_DAY = 50  # 1回の実行あたりのデフォルト上限


def _is_post_unavailable(driver: webdriver.Chrome) -> bool:
    """ポストが削除済み・非公開かどうかを判定する。"""
    try:
        src = driver.page_source
        markers = [
            "このポストは利用できません",
            "This post is unavailable",
            "このページは存在しません",
            "This page doesn't exist",
            "Hmm...this page doesn't exist",
            "Something went wrong",
        ]
        return any(m in src for m in markers)
    except Exception:
        return False


def human_like_delete(
    driver: webdriver.Chrome,
    limit_per_run: int = LIMIT_PER_DAY,
    allow_low_severity: bool = False,
    debug_rt: bool = False,
) -> None:
    """
    バトルルーチン、セット！イン！
    特定のURL（ウイルス）をデリートするためのフロントエンド・スキャン。
    """
    df = pd.read_csv("delete_hit_list.csv")

    pending_mask = df["hapus"] != "sudah"
    severity_mask = df["severity"] >= 1

    high_priority = df[pending_mask & severity_mask]
    low_pending_all = df[pending_mask & ~severity_mask]

    high_total = len(high_priority)
    low_total = len(low_pending_all)

    targets_high = high_priority.head(limit_per_run)

    if allow_low_severity:
        remaining_slots = max(0, limit_per_run - len(targets_high))
        targets_low = (
            low_pending_all.head(remaining_slots)
            if remaining_slots > 0
            else low_pending_all.iloc[0:0]
        )
    else:
        targets_low = low_pending_all.iloc[0:0]

    targets = pd.concat([targets_high, targets_low])

    if targets.empty:
        print("[ロックマン.exe]Semua sudah hapus!（すべて削除済だよ！）")
        return

    print(
        f"Pending severity>=3: {high_total} 件, "
        f"severity<3: {low_total} 件, "
        f"今回処理: {len(targets)} 件"
    )

    wait = WebDriverWait(driver, 15)
    total_overall = len(df)
    console = Console(highlight=False)
    session_done = 0

    def _show_progress() -> None:
        overall_done = int((df["hapus"] == "sudah").sum())
        console.print(
            f"  [bold cyan]今回セッション[/] {_make_bar(session_done, len(targets))}"
            f"  [bold green]全体[/] {_make_bar(overall_done, total_overall)}"
        )

    for index, (_, row) in enumerate(targets.iterrows(), start=1):
        url = row["delete_url"]
        full_text = str(row.get("full_text", "")).strip()

        # RT形態のポストは別CSVに逃がしてスキップ
        if full_text.startswith("RT @"):
            rt_csv = Path("rt_hit_list.csv")
            rt_row = row.to_dict()
            rt_file_exists = rt_csv.exists()
            with open(rt_csv, "a", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rt_row.keys()))
                if not rt_file_exists:
                    writer.writeheader()
                writer.writerow(rt_row)
            print(f"[ロックマン.exe] RT検出 → rt_hit_list.csv に退避: {url}")
            df.loc[df["delete_url"] == url, "hapus"] = "sudah"
            df.to_csv("delete_hit_list.csv", index=False)
            session_done += 1
            _show_progress()
            continue

        print(
            f"[{index}/{len(targets)}] [ロックマン.exe]"
            f"コンピューターウイルスを捕捉、ウイルスバスティング開始するね！: {url}"
        )

        try:
            parsed = urlparse(url)
            parts = parsed.path.strip("/").split("/")
            base_article_xpath = "//article[@data-testid='tweet']"
            menu_xpath = "//article//button[@aria-haspopup='menu']"
            status_id = None

            if len(parts) >= 3 and parts[1] == "status":
                status_id = parts[2]
                base_article_xpath = f"//article[@data-testid='tweet' and .//a[contains(@href, '{status_id}')]]"
                menu_xpath = f"{base_article_xpath}//button[@aria-haspopup='menu']"

            if driver is not None:
                if status_id:
                    print(f"[NAV] goto status_id={status_id} url={url}")
                navigate_to(driver, url, status_id=status_id, timeout_sec=20)
            human_pause(1.8, 0.3, min_sec=1.2)
            human_browse_page(driver)

            if _is_post_unavailable(driver):
                print(f"[ロックマン.exe] ポスト削除済み検出 → sudah: {url}")
                df.loc[df["delete_url"] == url, "hapus"] = "sudah"
                df.to_csv("delete_hit_list.csv", index=False)
                human_pause(2.0, 0.3)
                session_done += 1
                _show_progress()
                continue

            # --- RT検出デバッグ（--debug-rt 時のみ） ---
            if debug_rt:
                n_articles = len(driver.find_elements(By.XPATH, base_article_xpath))
                n_unrt_global = len(
                    driver.find_elements(By.XPATH, "//button[@data-testid='unretweet']")
                )
                n_retweet_global = len(
                    driver.find_elements(By.XPATH, "//button[@data-testid='retweet']")
                )
                unrt_xpath_debug = (
                    f"{base_article_xpath}//button[@data-testid='unretweet']"
                )
                n_unrt_scoped = len(driver.find_elements(By.XPATH, unrt_xpath_debug))
                print(
                    f"[DEBUG-RT] status_id={status_id!r}, base_article_xpath に一致する article 数: {n_articles}, "
                    f"ページ内 unretweet ボタン数: {n_unrt_global}, retweet ボタン数: {n_retweet_global}, "
                    f"スコープ内 unretweet 数: {n_unrt_scoped}"
                )
                print(f"[DEBUG-RT] unrt_xpath = {unrt_xpath_debug}")

            action_performed = False

            # 1) まずリポスト専用ボタン（緑のリポストマーク）を優先的に探す
            try:
                scoped_unrt_xpath = (
                    f"{base_article_xpath}//button[@data-testid='unretweet']"
                )
                try:
                    unretweet_btn = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, scoped_unrt_xpath))
                    )
                    if debug_rt:
                        print(
                            f"[DEBUG-RT] scoped unretweet でヒット: {scoped_unrt_xpath}"
                        )
                except TimeoutException:
                    global_unrt_xpath = "//button[@data-testid='unretweet']"
                    unrt_elems = driver.find_elements(By.XPATH, global_unrt_xpath)
                    if debug_rt:
                        print(
                            f"[DEBUG-RT] scoped unretweet 見つからず。global={len(unrt_elems)} 個"
                        )
                    if len(unrt_elems) != 1:
                        raise
                    unretweet_btn = unrt_elems[0]
                    if debug_rt:
                        print(
                            f"[DEBUG-RT] global unretweet を使用: {global_unrt_xpath}"
                        )

                human_move_click_element(
                    driver,
                    unretweet_btn,
                    "unretweet_button",
                    scroll=True,
                    jitter_px=1.5,
                )
                human_pause(1.2, 0.3)
                try:
                    confirm_xpath = (
                        "//div[@role='menuitem']//span[contains(text(), 'ポストを取り消す')] | "
                        "//div[@role='menuitem']//span[contains(text(), 'Undo repost')] | "
                        "//button[@data-testid='confirmationSheetConfirm']"
                    )
                    confirm_btn = WebDriverWait(driver, 3).until(
                        EC.element_to_be_clickable((By.XPATH, confirm_xpath))
                    )
                    human_move_click_element(
                        driver,
                        confirm_btn,
                        "unretweet_confirmation",
                        scroll=False,
                        jitter_px=1.5,
                    )
                    action_performed = True
                    print(f"[DEBUG]{action_performed}")
                except Exception as e:
                    print(
                        f"\n[ロックマン.exe] うーん、リポスト取り消しダイアログが見つからなかった...: {e}"
                    )
                    ans = (
                        input(
                            "[ロックマン.exe]熱斗くん、手動でリポスト取り消ししてくれた？[y/N]: "
                        )
                        .strip()
                        .lower()
                    )
                    if ans in ("y", "yes"):
                        action_performed = True

            except TimeoutException:
                if debug_rt:
                    print(
                        "[DEBUG-RT] unretweet ボタンがタイムアウト。メニュー削除フローへフォールバック。"
                    )
                pass

            # 2) 通常のメニューからの削除 / リポスト取り消し
            if not action_performed:
                menu_btn = wait.until(
                    EC.element_to_be_clickable((By.XPATH, menu_xpath))
                )
                human_move_click_element(
                    driver,
                    menu_btn,
                    "menu_button",
                    scroll=True,
                    jitter_px=2.5,
                )
                human_pause(1.8, 0.4, min_sec=0.8)

                delete_xpath = (
                    "//div[@role='menu']"
                    "//*[@data-testid='tweetDeleteMenuItem'"
                    " or @data-testid='unretweet'"
                    " or (@role='menuitem' and .//span["
                    "contains(text(), '削除') or contains(text(), 'Delete')"
                    " or contains(text(), 'ポストを取り消す') or contains(text(), 'Undo repost')"
                    "])]"
                )
                delete_btn = wait.until(
                    EC.element_to_be_clickable((By.XPATH, delete_xpath))
                )
                human_move_click_element(
                    driver,
                    delete_btn,
                    "delete_button",
                    scroll=False,
                    jitter_px=1.5,
                )
                human_pause(1.4, 0.4, min_sec=0.6)

                confirm_btn = wait.until(
                    EC.element_to_be_clickable(
                        (By.XPATH, "//button[@data-testid='confirmationSheetConfirm']")
                    )
                )
                human_move_click_element(
                    driver,
                    confirm_btn,
                    "delete_confirmation_button",
                    scroll=False,
                    jitter_px=1.0,
                )

            print(
                f"[ロックマン.exe] 成功: コンピューターウイルス"
                f" {row['delete_url']} をデリート / リポスト取り消しできたよ！"
            )

            df.loc[df["delete_url"] == row["delete_url"], "hapus"] = "sudah"
            human_pause(6.0, 0.5, min_sec=3.0)
            df.to_csv("delete_hit_list.csv", index=False)

            human_pause(4.0, 0.6, min_sec=1.5)
            session_done += 1
            _show_progress()

        except Exception as e:
            if _is_post_unavailable(driver):
                print(f"[ロックマン.exe] エラー後に削除済み確認 → sudah: {url}")
                df.loc[df["delete_url"] == url, "hapus"] = "sudah"
                df.to_csv("delete_hit_list.csv", index=False)
            else:
                print(
                    f"失敗（禁忌）: {url} でエラー。要素が変わっとるかも。詳細: {e}"
                )
            human_pause(8.0, 0.5, min_sec=4.0)
            session_done += 1
            _show_progress()
            continue


def human_like_unretweet(
    driver: webdriver.Chrome,
    limit_per_run: int = LIMIT_PER_DAY,
    debug_rt: bool = False,
) -> None:
    """
    RT取り消し専用ルーチン。
    rt_hit_list.csv を読んで、unretweetボタン操作に特化した処理を行う。
    """
    rt_csv = Path("rt_hit_list.csv")
    if not rt_csv.exists():
        print(
            "[ロックマン.exe] rt_hit_list.csv が見つからんで。"
            "先に通常モードを実行してRT一覧を生成してや。"
        )
        return

    df = pd.read_csv(rt_csv)

    pending = df[df["hapus"] != "sudah"]
    targets = pending.head(limit_per_run)

    if targets.empty:
        print("[ロックマン.exe] 熱斗くん、rt_hit_list.csv の全RT、もう取り消し済みだよ!")
        return

    print(f"RT取り消し対象: {len(targets)} 件 / 残り合計: {len(pending)} 件")

    total_overall = len(df)
    console = Console(highlight=False)
    session_done = 0

    def _show_progress() -> None:
        overall_done = int((df["hapus"] == "sudah").sum())
        console.print(
            f"  [bold cyan]今回セッション[/] {_make_bar(session_done, len(targets))}"
            f"  [bold green]全体[/] {_make_bar(overall_done, total_overall)}"
        )

    for index, (_, row) in enumerate(targets.iterrows(), start=1):
        url = row["delete_url"]
        print(f"[{index}/{len(targets)}] [ロックマン.exe] RT取り消し開始: {url}")

        try:
            parsed = urlparse(url)
            parts = parsed.path.strip("/").split("/")
            status_id = None
            base_article_xpath = "//article[@data-testid='tweet']"

            if len(parts) >= 3 and parts[1] == "status":
                status_id = parts[2]
                base_article_xpath = (
                    f"//article[@data-testid='tweet'"
                    f" and .//a[contains(@href, '{status_id}')]]"
                )

            navigate_to(driver, url, status_id=status_id, timeout_sec=20)
            human_pause(1.8, 0.3, min_sec=1.2)

            if _is_post_unavailable(driver):
                print(f"[ロックマン.exe] 熱斗くん、ポスト削除済みされてるよ → sudah: {url}")
                df.loc[df["delete_url"] == url, "hapus"] = "sudah"
                df.to_csv(rt_csv, index=False)
                human_pause(2.0, 0.3)
                session_done += 1
                _show_progress()
                continue

            human_browse_page(driver)

            scoped_unrt_xpath = (
                f"{base_article_xpath}//button[@data-testid='unretweet']"
            )
            if debug_rt:
                print(f"[DEBUG-RT] scoped_unrt_xpath={scoped_unrt_xpath}")

            try:
                unretweet_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, scoped_unrt_xpath))
                )
                if debug_rt:
                    print("[DEBUG-RT] scoped unretweet でヒット")
            except TimeoutException:
                global_elems = driver.find_elements(
                    By.XPATH, "//button[@data-testid='unretweet']"
                )
                if debug_rt:
                    print(f"[DEBUG-RT] global unretweet 候補数: {len(global_elems)}")
                if len(global_elems) == 1:
                    unretweet_btn = global_elems[0]
                else:
                    print(
                        f"[ロックマン.exe] unretweetボタンが見つからん"
                        f"（既に取り消し済みかも）→ sudah: {url}"
                    )
                    df.loc[df["delete_url"] == url, "hapus"] = "sudah"
                    df.to_csv(rt_csv, index=False)
                    human_pause(3.0, 0.3)
                    session_done += 1
                    _show_progress()
                    continue

            human_move_click_element(
                driver, unretweet_btn, "unretweet_button", scroll=True, jitter_px=1.5
            )
            human_pause(1.2, 0.3)

            try:
                confirm_xpath = (
                    "//div[@role='menuitem']//span[contains(text(), 'ポストを取り消す')] | "
                    "//div[@role='menuitem']//span[contains(text(), 'Undo repost')] | "
                    "//button[@data-testid='confirmationSheetConfirm']"
                )
                confirm_btn = WebDriverWait(driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, confirm_xpath))
                )
                human_move_click_element(
                    driver,
                    confirm_btn,
                    "unretweet_confirmation",
                    scroll=False,
                    jitter_px=1.5,
                )
                print(f"[ロックマン.exe] RT取り消し成功: {url}")
                df.loc[df["delete_url"] == url, "hapus"] = "sudah"
                df.to_csv(rt_csv, index=False)
                human_pause(6.0, 0.5, min_sec=3.0)
            except TimeoutException:
                print(f"[ロックマン.exe] 確認ダイアログが出んかった、スキップ: {url}")
                human_pause(3.0, 0.3)

            human_pause(4.0, 0.6, min_sec=1.5)
            session_done += 1
            _show_progress()

        except Exception as e:
            if _is_post_unavailable(driver):
                print(f"[ロックマン.exe] エラー後に削除済み確認 → sudah: {url}")
                df.loc[df["delete_url"] == url, "hapus"] = "sudah"
                df.to_csv(rt_csv, index=False)
            else:
                print(f"失敗: {url} でエラー。詳細: {e}")
            human_pause(8.0, 0.5, min_sec=4.0)
            session_done += 1
            _show_progress()
            continue
