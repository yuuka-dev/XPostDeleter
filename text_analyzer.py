"""
text_analyzer.py
3段活用テキスト解析: キーワード → Gemini → Claude

Stage 1: KeywordAnalyzer  — ローカル辞書で即判定（無料・高速）
Stage 2: GeminiAnalyzer   — バッチ送信で文脈込み判定（安価）
Stage 3: ClaudeAnalyzer   — Gemini がグレー判定したものだけ精査（高精度）
"""

import ast
import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

KEYWORDS_PATH = Path(__file__).parent / "keywords.json"
GEMINI_MODEL = "gemini-2.0-flash"
CLAUDE_MODEL = "claude-haiku-4-5-20251001"

BATCH_SIZE = 25
GEMINI_HIGH = 0.7   # これ以上 → 確定 hit
GEMINI_LOW = 0.3    # これ以下 → 確定 miss、その間は Claude へ
RPM_SLEEP = 4.5     # Gemini 無料枠 15 RPM 対策 (60 / 15 + 余裕)

_SEVERITY_BY_TIER = {"high": 3, "medium": 2, "low": 1}

_PROMPT = """\
あなたはソーシャルメディアのコンテンツ分析AIです。
以下のツイートを分析し、MtF・FtM・女装・男の娘・トランスジェンダー・性転換・TS/TG関連など、
特定コミュニティに関連する・匂わせる内容が含まれているかを判定してください。

判定基準（すべて含む）：
- 直接的な用語の使用
- コミュニティ特有のスラング・隠語・当て字
- 文脈から読み取れる匂わせ・遠回しな表現
- 当該コミュニティの文化・話題・イベントへの言及

ツイート一覧（JSON）：
{tweets_json}

以下の JSON 形式のみで回答してください（余分なテキスト不要）：
{{"results": [{{"id": "ツイートID", "flagged": true, "confidence": 0.85, "reason": "判定理由"}}]}}
"""


@dataclass
class TweetAnalysis:
    tweet_id: str
    flagged: bool
    confidence: float   # 0.0 〜 1.0
    reason: str
    stage: str          # "keyword" | "gemini" | "claude" | "skipped"
    risk_tag: str = "TEXT_MATCH"

    def severity_delta(self) -> int:
        if not self.flagged:
            return 0
        if self.confidence >= 0.8:
            return 3
        if self.confidence >= 0.5:
            return 2
        return 1


class KeywordAnalyzer:
    def __init__(self, path: Path = KEYWORDS_PATH):
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        # "_comment" キーを除外
        self._tiers: dict[str, list[str]] = {
            k: v for k, v in raw.items() if not k.startswith("_")
        }

    def analyze(
        self, tweets: list[dict]
    ) -> tuple[list[TweetAnalysis], list[dict]]:
        """ヒットしたものと、LLM に回すべき残りを返す。"""
        hits: list[TweetAnalysis] = []
        remaining: list[dict] = []

        for t in tweets:
            text = t.get("text", "")
            matched_tier: str | None = None
            matched_kw: str | None = None

            for tier in ("high", "medium", "low"):
                for kw in self._tiers.get(tier, []):
                    if kw.lower() in text.lower():
                        matched_tier = tier
                        matched_kw = kw
                        break
                if matched_tier:
                    break

            if matched_tier:
                hits.append(
                    TweetAnalysis(
                        tweet_id=t["id"],
                        flagged=True,
                        confidence=1.0,
                        reason=f"keyword({matched_tier}): {matched_kw}",
                        stage="keyword",
                        risk_tag="TEXT_KEYWORD",
                    )
                )
            else:
                remaining.append(t)

        return hits, remaining


class GeminiAnalyzer:
    def __init__(self) -> None:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY が .env に設定されていません")
        from google import genai  # type: ignore[import-untyped]

        self._client = genai.Client(api_key=api_key)

    def analyze_batch(self, tweets: list[dict]) -> list[TweetAnalysis]:
        payload = [{"id": t["id"], "text": t["text"]} for t in tweets]
        prompt = _PROMPT.format(
            tweets_json=json.dumps(payload, ensure_ascii=False, indent=2)
        )
        resp = self._client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        results = json.loads(resp.text).get("results", [])
        return [
            TweetAnalysis(
                tweet_id=r["id"],
                flagged=bool(r.get("flagged", False)),
                confidence=float(r.get("confidence", 0.0)),
                reason=r.get("reason", ""),
                stage="gemini",
                risk_tag="TEXT_GEMINI",
            )
            for r in results
        ]


class ClaudeAnalyzer:
    def __init__(self) -> None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY が .env に設定されていません")
        import anthropic  # type: ignore[import-untyped]

        self._client = anthropic.Anthropic(api_key=api_key)

    def analyze_batch(self, tweets: list[dict]) -> list[TweetAnalysis]:
        payload = [{"id": t["id"], "text": t["text"]} for t in tweets]
        prompt = _PROMPT.format(
            tweets_json=json.dumps(payload, ensure_ascii=False, indent=2)
        )
        resp = self._client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        )
        text = resp.content[0].text
        results = json.loads(text).get("results", [])
        return [
            TweetAnalysis(
                tweet_id=r["id"],
                flagged=bool(r.get("flagged", False)),
                confidence=float(r.get("confidence", 0.0)),
                reason=r.get("reason", ""),
                stage="claude",
                risk_tag="TEXT_CLAUDE",
            )
            for r in results
        ]


class TextAnalyzer:
    """
    3段活用オーケストレーター。
    利用可能な LLM を自動検出（APIキーがなければその段をスキップ）。
    """

    def __init__(self) -> None:
        self._keyword = KeywordAnalyzer()
        self._gemini: GeminiAnalyzer | None = None
        self._claude: ClaudeAnalyzer | None = None

        try:
            self._gemini = GeminiAnalyzer()
            print("[TextAnalyzer] Gemini: 有効")
        except Exception as e:
            print(f"[TextAnalyzer] Gemini: スキップ ({e})")

        try:
            self._claude = ClaudeAnalyzer()
            print("[TextAnalyzer] Claude: 有効")
        except Exception as e:
            print(f"[TextAnalyzer] Claude: スキップ ({e})")

    def analyze(self, tweets: list[dict]) -> list[TweetAnalysis]:
        """
        全ツイートを3段階で解析し、TweetAnalysis のリストを返す。
        flagged=False のものも含む（呼び出し側でフィルタ）。
        """
        results: dict[str, TweetAnalysis] = {}

        # Stage 1: Keyword
        kw_hits, remaining = self._keyword.analyze(tweets)
        for hit in kw_hits:
            results[hit.tweet_id] = hit
        print(
            f"[TextAnalyzer] Stage1 keyword: {len(kw_hits)} hit, "
            f"{len(remaining)} → LLM"
        )

        if not remaining:
            return list(results.values())

        # Stage 2: Gemini
        uncertain: list[dict] = []
        if self._gemini:
            gemini_hits = 0
            gemini_miss = 0
            for i in range(0, len(remaining), BATCH_SIZE):
                batch = remaining[i : i + BATCH_SIZE]
                try:
                    batch_results = self._gemini.analyze_batch(batch)
                    for r in batch_results:
                        if r.confidence >= GEMINI_HIGH:
                            results[r.tweet_id] = r
                            gemini_hits += 1
                        elif r.confidence <= GEMINI_LOW:
                            results[r.tweet_id] = r
                            gemini_miss += 1
                        else:
                            # グレーゾーン → Claude へ
                            uncertain.append(
                                next(t for t in batch if t["id"] == r.tweet_id)
                            )
                except Exception as e:
                    print(f"[TextAnalyzer] Gemini バッチエラー: {e}")
                    uncertain.extend(batch)  # エラー時は Claude に回す
                time.sleep(RPM_SLEEP)

            print(
                f"[TextAnalyzer] Stage2 Gemini: {gemini_hits} hit, "
                f"{gemini_miss} miss, {len(uncertain)} uncertain → Claude"
            )
        else:
            # Gemini なし → remaining を全部 Claude へ
            uncertain = remaining

        # Stage 3: Claude
        if uncertain and self._claude:
            claude_hits = 0
            for i in range(0, len(uncertain), BATCH_SIZE):
                batch = uncertain[i : i + BATCH_SIZE]
                try:
                    batch_results = self._claude.analyze_batch(batch)
                    for r in batch_results:
                        results[r.tweet_id] = r
                        if r.flagged:
                            claude_hits += 1
                except Exception as e:
                    print(f"[TextAnalyzer] Claude バッチエラー: {e}")
            print(f"[TextAnalyzer] Stage3 Claude: {claude_hits} hit")
        elif uncertain:
            print(f"[TextAnalyzer] Stage3 Claude スキップ: {len(uncertain)} 件未判定")

        return list(results.values())


def merge_text_into_row(
    row: dict, analysis: TweetAnalysis
) -> dict:
    """
    既存の画像解析行にテキスト解析結果をマージする。
    risk_tags を追記し、severity を加算（上限5）。
    """
    try:
        tags: list = ast.literal_eval(row["risk_tags"])
    except Exception:
        tags = []
    if analysis.risk_tag not in tags:
        tags.append(analysis.risk_tag)
    row["risk_tags"] = str(tags)
    row["severity"] = min(5, int(row["severity"]) + analysis.severity_delta())
    return row
