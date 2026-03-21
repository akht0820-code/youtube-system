# 動画統計データをAIで分析し改善提案を生成するモジュール

import json
import re
from datetime import datetime
from pathlib import Path

from analytics_base import AnalysisModel
import model_config
from secrets import get_secret

SUGGESTIONS_PATH = Path(__file__).parent.parent / "suggestions.json"


def _build_analysis_prompt(stats: list[dict]) -> str:
    sorted_stats = sorted(stats, key=lambda v: v["views"], reverse=True)
    top10    = sorted_stats[:10]
    bottom10 = sorted_stats[-10:] if len(sorted_stats) > 10 else []

    def fmt(videos):
        return "\n".join(
            f"  - 「{v['title']}」 再生:{v['views']:,} いいね:{v['likes']:,} コメント:{v['comments']:,}"
            for v in videos
        ) or "（データ不足）"

    total     = len(stats)
    avg_views = int(sum(v["views"] for v in stats) / total) if total else 0
    avg_likes = int(sum(v["likes"] for v in stats) / total) if total else 0

    return f"""
あなたは健康ゆっくり解説YouTubeチャンネルのデータアナリストです。

## チャンネルの動画統計データ
- 総動画数: {total} 本
- 平均再生数: {avg_views:,} 回
- 平均いいね数: {avg_likes:,}

## 再生数トップ10
{fmt(top10)}

## 再生数ワースト10
{fmt(bottom10)}

---

上記データを分析して、以下の観点から「次の動画を改善するための具体的な提案」を5〜7点生成してください。

## 分析の観点
1. **タイトルのパターン**: どんなタイトルの動画が伸びているか（フレーズ・数字・キーワード）
2. **テーマの傾向**: どんなテーマ（食材・症状・生活習慣）が視聴者に刺さっているか
3. **エンゲージメント**: いいね率・コメント率が高い動画の特徴
4. **改善点**: 伸び悩んでいる動画から見えるパターン

## 出力形式（JSONのみ）

{{
  "analysis": "チャンネル全体の傾向を2〜3文で要約",
  "suggestions": ["提案1（具体的に）", ...],
  "recommended_themes": ["次に作るべきテーマ案1", ...],
  "title_patterns": ["効果的なタイトルパターン1", ...]
}}
"""


class GeminiAnalysisModel(AnalysisModel):
    """Gemini APIを使って動画統計を分析する"""

    def __init__(self, model: str = ""):
        from google import genai
        self._client = genai.Client(api_key=get_secret("GEMINI_API_KEY"))
        self._model  = model or model_config.STANDARD

    def analyze(self, stats: list[dict]) -> dict:
        print(f"Gemini（{self._model}）で {len(stats)} 本のデータを分析しています...")
        prompt   = _build_analysis_prompt(stats)
        response = self._client.models.generate_content(model=self._model, contents=prompt)

        text = re.sub(r"```json\s*", "", response.text)
        text = re.sub(r"```\s*", "", text).strip()
        return json.loads(text)


# ── 保存・読み込みユーティリティ（generator.py から使用） ────────

def save_suggestions(result: dict) -> None:
    result["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
    SUGGESTIONS_PATH.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"分析結果を保存しました: {SUGGESTIONS_PATH}")


def load_suggestions() -> dict:
    """suggestions.jsonを読み込む（存在しなければ空のdictを返す）"""
    if not SUGGESTIONS_PATH.exists():
        return {}
    try:
        return json.loads(SUGGESTIONS_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}
