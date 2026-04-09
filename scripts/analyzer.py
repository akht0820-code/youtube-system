# 動画統計データをAIで分析し改善提案を生成するモジュール

import json
import re
from datetime import datetime
from pathlib import Path

from analytics_base import AnalysisModel
import model_config
from secrets import get_secret

SUGGESTIONS_PATH = Path(__file__).parent.parent / "suggestions.json"
OUTPUT_DIR = Path(__file__).parent.parent / "output"


def _build_analysis_prompt(stats: list[dict], se_section: str = "") -> str:
    sorted_stats = sorted(stats, key=lambda v: v["views"], reverse=True)
    top10    = sorted_stats[:10]
    bottom10 = sorted_stats[-10:] if len(sorted_stats) > 10 else []

    def fmt(videos):
        lines = []
        for v in videos:
            dur = v.get("duration_sec", 0)
            dur_str = f" 尺:{dur // 60}分{dur % 60}秒" if dur else ""
            lines.append(
                f"  - 「{v['title']}」 再生:{v['views']:,} いいね:{v['likes']:,} "
                f"コメント:{v['comments']:,}{dur_str}"
            )
        return "\n".join(lines) or "（データ不足）"

    total     = len(stats)
    avg_views = int(sum(v["views"] for v in stats) / total) if total else 0
    avg_likes = int(sum(v["likes"] for v in stats) / total) if total else 0

    se_analysis_block = ""
    if se_section:
        se_analysis_block = f"""
{se_section}

"""
        se_perspective = """5. **効果音(SE)の効果**: SE使用数・カテゴリ配分と再生数・エンゲージメントの関連。どのSEカテゴリが効果的か"""
        se_output = ', "se_insights": ["SE使用に関する改善提案1", ...]'
    else:
        se_perspective = ""
        se_output = ""

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
{se_analysis_block}---

上記データを分析して、以下の観点から「次の動画を改善するための具体的な提案」を5〜7点生成してください。

## 分析の観点
1. **タイトルのパターン**: どんなタイトルの動画が伸びているか（フレーズ・数字・キーワード）
2. **テーマの傾向**: どんなテーマ（食材・症状・生活習慣）が視聴者に刺さっているか
3. **エンゲージメント**: いいね率・コメント率が高い動画の特徴
4. **改善点**: 伸び悩んでいる動画から見えるパターン
{se_perspective}

## 出力形式（JSONのみ）

{{
  "analysis": "チャンネル全体の傾向を2〜3文で要約",
  "suggestions": ["提案1（具体的に）", ...],
  "recommended_themes": ["次に作るべきテーマ案1", ...],
  "title_patterns": ["効果的なタイトルパターン1", ...]{se_output}
}}
"""


def _collect_se_stats() -> list[dict]:
    """output/以下の各run_dirからSE割り当て情報を収集する"""
    results = []
    if not OUTPUT_DIR.exists():
        return results
    for run_dir in OUTPUT_DIR.iterdir():
        if not run_dir.is_dir():
            continue
        se_path = run_dir / "se_assignments.json"
        pipeline_path = run_dir / "pipeline.json"
        if not se_path.exists() or not pipeline_path.exists():
            continue
        try:
            se_data = json.loads(se_path.read_text(encoding="utf-8"))
            pipeline = json.loads(pipeline_path.read_text(encoding="utf-8"))
            # SE割り当て数とカテゴリ別内訳
            category_counts: dict[str, int] = {}
            for _idx, info in se_data.items():
                se_id = info.get("se", "") if isinstance(info, dict) else str(info)
                cat = se_id.split("/")[0] if "/" in se_id else "unknown"
                category_counts[cat] = category_counts.get(cat, 0) + 1
            results.append({
                "run_id": pipeline.get("run_id", run_dir.name),
                "theme": pipeline.get("theme", ""),
                "se_total": len(se_data),
                "se_categories": category_counts,
                "has_combo": any(
                    isinstance(v, dict) and v.get("combo")
                    for v in se_data.values()
                ),
                "has_pause": any(
                    isinstance(v, dict) and v.get("pause")
                    for v in se_data.values()
                ),
            })
        except Exception:
            continue
    return results


def _build_se_analysis_section(stats: list[dict], se_stats: list[dict]) -> str:
    """SE使用状況と動画パフォーマンスの相関分析セクションを生成する"""
    if not se_stats:
        return ""

    lines = ["\n## SE(効果音)使用状況の分析データ"]
    lines.append(f"- SE付き動画数: {len(se_stats)} 本\n")

    # テーマ→SE情報のマップ
    theme_se = {s["theme"]: s for s in se_stats if s["theme"]}

    # 動画パフォーマンスとSE数の対応表
    matched = []
    for v in stats:
        title = v.get("title", "")
        # テーマで突合（タイトルに含まれるテーマを探す）
        for theme, se_info in theme_se.items():
            if theme in title or title in theme:
                matched.append({
                    "title": title,
                    "views": v["views"],
                    "likes": v["likes"],
                    "duration_sec": v.get("duration_sec", 0),
                    "se_total": se_info["se_total"],
                    "se_categories": se_info["se_categories"],
                    "has_combo": se_info["has_combo"],
                    "has_pause": se_info["has_pause"],
                })
                break

    if matched:
        lines.append("### 動画別SE使用数 vs パフォーマンス")
        for m in sorted(matched, key=lambda x: x["views"], reverse=True):
            cats = ", ".join(f"{k}:{v}" for k, v in m["se_categories"].items())
            extras = []
            if m["has_combo"]:
                extras.append("combo有")
            if m["has_pause"]:
                extras.append("pause有")
            extra_str = f" ({', '.join(extras)})" if extras else ""
            lines.append(
                f"  - 「{m['title']}」 再生:{m['views']:,} "
                f"SE数:{m['se_total']} [{cats}]{extra_str}"
            )

    # カテゴリ別集計
    all_cats: dict[str, int] = {}
    for s in se_stats:
        for cat, cnt in s["se_categories"].items():
            all_cats[cat] = all_cats.get(cat, 0) + cnt
    if all_cats:
        lines.append("\n### カテゴリ別SE使用回数（全動画合計）")
        for cat, cnt in sorted(all_cats.items(), key=lambda x: -x[1]):
            lines.append(f"  - {cat}: {cnt}回")

    return "\n".join(lines)


class LLMAnalysisModel(AnalysisModel):
    """設定されたLLMプロバイダを使って動画統計を分析する"""

    def __init__(self, model: str = ""):
        from providers import get_llm_client
        self._llm   = get_llm_client()
        self._model = model or model_config.STANDARD

    def analyze(self, stats: list[dict]) -> dict:
        provider = self._llm.__class__.__name__.replace("LLMClient", "")
        print(f"{provider}（{self._model}）で {len(stats)} 本のデータを分析しています...")
        # SE使用状況を収集してプロンプトに含める
        se_stats = _collect_se_stats()
        se_section = _build_se_analysis_section(stats, se_stats) if se_stats else ""
        if se_stats:
            print(f"  SE使用データ: {len(se_stats)}本分を分析に含めます")
        prompt = _build_analysis_prompt(stats, se_section)
        text   = self._llm.generate(prompt, self._model)

        text = re.sub(r"```json\s*", "", text)
        text = re.sub(r"```\s*", "", text).strip()
        return json.loads(text)


# 後方互換エイリアス（既存の import を壊さないため）
GeminiAnalysisModel = LLMAnalysisModel


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
