# サムネイル AIアートディレクター
#
# Gemini 2.5 Pro（CREATIVEティア）を使って、サムネイルの全クリエイティブ判断を一括生成する。
# 出力は directive dict で、thumbnail_maker.make_thumbnail が受け取って描画する。
#
# 判断項目:
#   - キャプション（サムネ専用コピー。タイトルとは別の短く刺さるテキスト）
#   - 強調ワード（大きく目立たせる単語。最大2個）
#   - 背景配色（テーマに合ったグラデーション上下色）
#   - 強調色（強調ワードの色。背景とのコントラストを考慮）
#   - キャラクター表情（魔理沙・霊夢それぞれ）
#   - 吹き出しテキスト（タイトル連動の掛け合い）
#
# フォールバック: AI失敗時は None を返し、make_thumbnail が従来ロジックで描画する。

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import model_config
from providers import get_llm_client
from script_repair import extract_json_safe


# AIに渡す固定情報
_CANVAS_INFO = """
## サムネイル仕様
- キャンバス: 1280x720px
- 魔理沙（帽子の女の子キャラ）: 左下に固定。高さ約400px。煽り・解説役。
- 霊夢（リボンの女の子キャラ）: 右下に固定。高さ約330px。驚き・共感役。
- メインテキスト: 上部〜中央。1〜3行。白文字+黒縁取り。
- 強調ワード: メインテキスト内の一部を1.7倍大+黄色で描画。最大2個。
- 吹き出し: 魔理沙の上に煽りテキスト、霊夢の頭上に小さい白吹き出し。
- 背景: 上下グラデーション。テーマに合った色。
"""

_EXPRESSIONS = ["normal", "happy", "serious", "surprised", "worried"]

_THEMES = ["food", "sleep", "exercise", "dental", "mental", "warning", "general"]


def generate_directive(theme: str, title: str, *,
                       script: dict | None = None,
                       metadata: dict | None = None) -> dict | None:
    """AIアートディレクターにサムネイルのクリエイティブ判断を一括生成させる。

    Args:
        theme: 動画のテーマ（台本から取得）
        title: YouTubeタイトル
        script: 台本JSON（セクション名・セリフ等）
        metadata: メタデータ（概要欄・タグ等）

    Returns:
        directive dict or None（AI失敗時）
    """
    # 台本から主要情報を抽出（プロンプトに含める）
    script_summary = ""
    if script:
        sections = script.get("sections", [])
        section_lines = []
        for sec in sections:
            sec_name = sec.get("section", sec.get("name", ""))
            # 各セクションから最初の数行を抽出（全文は長すぎるので要約）
            lines = sec.get("lines", [])
            preview = " ".join(l.get("text", "") for l in lines[:3])
            if len(preview) > 100:
                preview = preview[:100] + "..."
            section_lines.append(f"- {sec_name}: {preview}")
        script_summary = "\n".join(section_lines)

    meta_info = ""
    if metadata:
        desc = metadata.get("description", "")
        tags = metadata.get("tags", [])
        if desc:
            # 概要欄の冒頭部分（目次含む）
            meta_info += f"\n概要欄:\n{desc[:500]}"
        if tags:
            meta_info += f"\nタグ: {', '.join(tags[:15])}"

    prompt = f"""YouTubeサムネイルを設計してください。ゆっくり解説チャンネル（健康系・40〜60代ターゲット）です。
タイトルとサムネイルを**セットで**最適化してください。

## 動画情報
テーマ: {title}
{"" if not script_summary else f"台本要約: {script_summary[:300]}"}
{meta_info}

## YouTubeタイトル（最重要）
爆発的にクリックされるタイトルを考えてください。
- 15〜22文字以内
- 「実は」「意外と」「知らないと損」等の意外性ワード必須
- ●●伏せ字: 答え・原因・方法のみ隠す。主語・動詞は隠さない。使わなくてもOK
- 数字を使うと信頼感UP（「2週間で」「3倍」「1日たった〇g」）
- 食べ物・飲み物には動詞を明示（「飲み続ける」「食べると」）
- 企業名は直接書かない（「某有名〇〇」等はOK）
- バズるパターン: 「〇〇を毎日飲み続けると実は●●になっていた」「〇〇をやめたら体に起きた衝撃の変化」「医者が教えてくれない〇〇の真実」
- 刺さるキーワード: 白髪・老化・疲労・血糖値・腹の脂肪・血圧・免疫・腸・認知症・動脈硬化

## サムネキャプション（最重要: 短く・強く・クリックさせる）
タイトルとは別の、サムネ用短文コピー。2行で動画の核心を伝える。
- 「|」で区切り、**1行目→2行目を続けて読んで自然な日本語になること**
- **各行6文字以内、合計12文字以内（厳守）**
- 短いほどフォントが大きくなりインパクト増。冗長な表現は削ぎ落とす
- 助詞は最小限に。体言止めや命令形を活用（「寿命が半減」「絶対やめろ」）
- **必ず以下のいずれかを含む**: 恐怖（死・病気・老化）、損失回避（知らないと損）、意外性（実は逆効果）、具体的数字（3倍・半減）
- バズるパターン: 「寿命が半減」「脳が壊れる」「医者が警告」「逆効果だった」「99%が誤解」
- NGパターン: 「タバコより危険」（7文字で長い→「タバコ超え」5文字）、「寿命が縮むサイン」（8文字→「寿命が半減」5文字）

## 強調ワード（emphasis_words）の選び方
キャプション内で**黄色く大きく表示する**ワードを最大2個選ぶ。視聴者の目を最も引く部分。
- 短い方がデカく表示されてインパクト大（2〜4文字がベスト）
- 良い例: 「消えた」「禁止」「3倍」「激減」「崩壊」「危険」
- 悪い例: 「エレベーター」（長すぎて大きく表示できない）
- キャプションの中に含まれている文字列を正確に指定すること

## 〇〇伏せ字の判断
- 〇〇を使うかどうかはあなたが判断する。**無理に使わなくてよい**
- 効果的な場面: 結果や意外な部分を1箇所だけ隠して好奇心を煽る
- 使う場合は〇〇（全角丸2つ）で統一。キャプション内に直接入れる
- 良い例: 「〇〇をやめたら|腹の脂肪が消えた」
- 悪い例: 「〇〇を〇〇すると|〇〇が〇〇」（隠しすぎ）

## タイトルとサムネの関係
- タイトルとサムネキャプションは**補完関係**にする（同じことを言わない）
- タイトルで興味を引き、サムネで「見なきゃ」と思わせる
- 例: タイトル「エレベーターをやめたら実は【腹の脂肪】に衝撃変化が！」→ サムネ「階段にしただけで|腹の脂肪が消えた」

## バズるサムネの鉄則
- 背景は**暗色**（紺・黒・深赤）で白文字を浮かせる
- 強調ワードが**黄色でデカく**表示される。だから短いパワーワードを選ぶ
- 背景の彩度はやや高め（くすんだ色はスクロールで埋もれる）
- 答えを出し切らない（動画を見たくなるギャップを作る）

## 出力項目
- **youtube_title**: YouTubeタイトル（15〜22文字）
- **caption**: サムネキャプション「行1|行2」形式
- **emphasis_words**: 強調ワード最大2個（「禁止」「消えた」「3倍」等）
- **bg_top/bg_bottom**: 背景グラデーションRGB（暗め・高彩度）
- **emphasis_color**: 強調色RGB（黄色(255,230,0)が万能）
- **theme_category**: {_THEMES} から1つ
- **marisa_expression/reimu_expression**: {_EXPRESSIONS} から選択。**吹き出しテキストの感情に必ず合わせること**（煽り→serious、驚き→surprised、楽しい→happy、心配→worried）
- **marisa_bubble**: 煽り男口調15文字以内 / **reimu_bubble**: 共感女口調12文字以内
- **reactions**: 2ch風ネタコメント**必ず3個**（各15文字以内、テーマ固有）
- **irasutoya_keywords**: いらすとや検索ワード2個（「人物+行動」優先。例: 「コーヒー 飲む 人」）

## 出力（JSONのみ）
```json
{{
  "youtube_title": "タイトル",
  "caption": "行1|行2",
  "emphasis_words": ["ワード1"],
  "bg_top": [R, G, B],
  "bg_bottom": [R, G, B],
  "emphasis_color": [R, G, B],
  "theme_category": "food",
  "marisa_expression": "serious",
  "reimu_expression": "surprised",
  "marisa_bubble": "セリフ",
  "reimu_bubble": "セリフ",
  "reactions": ["コメント1", "コメント2", "コメント3"],
  "irasutoya_keywords": ["人物+行動", "具体物"]
}}
```"""

    try:
        llm = get_llm_client()
        raw = llm.generate(prompt, model_config.CREATIVE)
        result = extract_json_safe(raw)
        if not isinstance(result, dict):
            print(f"  [AD] JSON解析失敗")
            return None

        # バリデーション
        directive = _validate_directive(result)
        if directive:
            print(f"  [AD] アートディレクション生成成功:")
            if directive.get('youtube_title'):
                print(f"    タイトル: {directive['youtube_title']}")
            print(f"    キャプション: {directive['caption']}")
            print(f"    強調: {directive['emphasis_words']}")
            print(f"    配色: {directive['bg_top']} → {directive['bg_bottom']}")
            print(f"    魔理沙: {directive['marisa_expression']}「{directive['marisa_bubble']}」")
            print(f"    霊夢: {directive['reimu_expression']}「{directive['reimu_bubble']}」")
            if directive.get('reactions'):
                print(f"    リアクション: {directive['reactions']}")
            if directive.get('irasutoya_keywords'):
                print(f"    いらすとや: {directive['irasutoya_keywords']}")
        return directive

    except Exception as e:
        print(f"  [AD] アートディレクション生成失敗: {e}")
        return None


def _validate_directive(raw: dict) -> dict | None:
    """AIの出力をバリデーションし、安全な directive dict を返す。"""
    try:
        # YouTubeタイトル（任意: なければNone）
        yt_title = raw.get("youtube_title", "")
        if not isinstance(yt_title, str) or len(yt_title) < 5:
            yt_title = None  # 短すぎる場合は無視

        caption = raw.get("caption", "")
        if not caption or not isinstance(caption, str):
            print(f"  [AD] キャプションが空")
            return None
        # 各行7文字以内に切り詰め（AIに6文字指示済み、1文字余裕）
        _cap_parts = caption.split("|")
        _cap_parts = [p.strip()[:7] for p in _cap_parts if p.strip()][:2]
        caption = "|".join(_cap_parts) if _cap_parts else caption

        emphasis = raw.get("emphasis_words", [])
        if not isinstance(emphasis, list):
            emphasis = []
        emphasis = [w for w in emphasis if isinstance(w, str) and len(w) <= 10][:2]

        def _parse_rgb(val, default):
            if isinstance(val, (list, tuple)) and len(val) == 3:
                return tuple(max(0, min(255, int(c))) for c in val)
            return default

        bg_top = _parse_rgb(raw.get("bg_top"), (60, 190, 80))
        bg_bottom = _parse_rgb(raw.get("bg_bottom"), (25, 130, 45))
        emph_color = _parse_rgb(raw.get("emphasis_color"), (255, 240, 20))

        theme_cat = raw.get("theme_category", "general")
        if theme_cat not in _THEMES:
            theme_cat = "general"

        marisa_expr = raw.get("marisa_expression", "serious")
        reimu_expr = raw.get("reimu_expression", "surprised")
        if marisa_expr not in _EXPRESSIONS:
            marisa_expr = "serious"
        if reimu_expr not in _EXPRESSIONS:
            reimu_expr = "surprised"

        marisa_bubble = raw.get("marisa_bubble", "")
        reimu_bubble = raw.get("reimu_bubble", "")
        # ●●禁止
        marisa_bubble = marisa_bubble.replace("●●", "").replace("●", "")
        reimu_bubble = reimu_bubble.replace("●●", "").replace("●", "")

        if not marisa_bubble or not reimu_bubble:
            print(f"  [AD] 吹き出しテキストが空")
            return None

        # リアクションコメント（2〜3個、各15文字以内）
        reactions_raw = raw.get("reactions", [])
        if not isinstance(reactions_raw, list):
            reactions_raw = []
        reactions = [r for r in reactions_raw if isinstance(r, str) and 0 < len(r) <= 20][:3]

        # いらすとや検索キーワード（2〜3個、具体物名）
        ira_kws_raw = raw.get("irasutoya_keywords", [])
        if not isinstance(ira_kws_raw, list):
            ira_kws_raw = []
        ira_kws = [k for k in ira_kws_raw if isinstance(k, str) and 0 < len(k) <= 15][:3]

        return {
            "youtube_title": yt_title,
            "caption": caption,
            "emphasis_words": emphasis,
            "bg_top": bg_top,
            "bg_bottom": bg_bottom,
            "emphasis_color": emph_color,
            "theme_category": theme_cat,
            "marisa_expression": marisa_expr,
            "reimu_expression": reimu_expr,
            "marisa_bubble": marisa_bubble,
            "reimu_bubble": reimu_bubble,
            "reactions": reactions,
            "irasutoya_keywords": ira_kws,
        }
    except Exception as e:
        print(f"  [AD] バリデーションエラー: {e}")
        return None
