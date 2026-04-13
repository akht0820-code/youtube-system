# スキル: 台本生成（タイトル・構成・台本の生成と保存）

import copy
import json
import random
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from skills._common import (
    call_with_retry,
    ensure_scripts_path,
    get_llm,
    load_manifest,
    update_phase,
    SkillLogger,
)

ensure_scripts_path()

import model_config
from characters import get_character_names
from prompts import (
    build_comedy_design_prompt,
    build_script_prompt,
    build_script_prompt_with_suggestions,
    build_structure_prompt,
    build_title_prompt,
    pick_narrative_style,
)
from analyzer import load_suggestions
from notifier import notify_error
from script_repair import extract_json_safe, repair_structure, repair_script, validate_script

# Step 3-δ.5c-1: OUTPUT_DIR module-level 定数は削除.
# - save_script は run_script_gen() から output_dir を受け取る
# - _pick_theme_from_file (CLI main 専用) は themes_path / output_dir を引数で受け取る
# - invariant: run_dir.parent == output_dir (generator._create_run_dir で保証).
#   本 Step は invariant 維持のみ. 相対 outputs 解決モデルは横断設計 (別 Step).

# フォールバック用デフォルト構成
_FALLBACK_STRUCTURE = {
    "sections": [
        {"title": "はじめに",   "type": "intro",   "key_points": ["テーマの概要を紹介します"]},
        {"title": "詳しく解説", "type": "chapter", "key_points": ["メインの内容を説明します"]},
        {"title": "まとめ",     "type": "summary", "key_points": ["重要なポイントをまとめます"]},
    ]
}

_MIN_SCRIPT_CHARS = 6000  # ソフト目標 (これ未満なら再生成)
_HARD_MIN_SCRIPT_CHARS = 5200  # ハード下限 (これ未満は fail-closed)
_MAX_SCRIPT_CHARS = 7500


# ── ヘルパー関数 ──────────────────────────────────────────


def generate_title(theme: str) -> str:
    """テーマからYouTubeタイトルを生成する"""
    llm = get_llm()
    print("タイトルを生成しています...")
    prompt = build_title_prompt(theme)
    try:
        title = call_with_retry(
            llm.generate, prompt, model_config.STANDARD,
            label="タイトル生成"
        ).strip().strip("「」")
    except Exception:
        title = theme  # フォールバック: テーマをそのままタイトルに
        print("  → タイトル生成失敗、テーマ名で代替します")
    print(f"  → {title}")
    return title


def generate_structure(theme: str, channel_id: str = "health") -> dict:
    """テーマから動画構成を生成。

    channel_id="creatures" の場合は hybrid_selector でパターン選択し、
    creatures 専用プロンプトで構成を生成する。
    """
    llm = get_llm()

    if channel_id == "creatures":
        from prompts.hybrid_selector import select_pattern, get_category_name
        from prompts.creatures import build_structure_prompt as creatures_structure_prompt
        pattern = select_pattern(theme)
        opening = pattern["opening"]
        ending = pattern["ending"]
        category = pattern["category"]
        print(f"構成を考えています... [冒頭:{opening} 結末:{ending} カテゴリ:{get_category_name(category)}]")
        prompt = creatures_structure_prompt(theme, opening, ending)
    else:
        style = pick_narrative_style()
        print(f"構成を考えています... [スタイル: {style['name']}]")
        prompt = build_structure_prompt(theme, style)

    try:
        raw = call_with_retry(
            llm.generate, prompt, model_config.CREATIVE,
            label="構成生成"
        )
        data = extract_json_safe(raw)
        structure = repair_structure(data, theme)
        if channel_id == "creatures":
            structure["_opening_pattern"] = opening
            structure["_ending_pattern"] = ending
            structure["_category"] = category
        else:
            structure["_narrative_style"] = style["key"]
    except Exception as e:
        # 2026-04-09事故対策 (Codex Round4): 以前は _FALLBACK_STRUCTURE に差し替えて
        # 続行していたが、構成は公開物の骨格そのもので、壊れたまま generic 3章構成で
        # 進めると『壊れた生成結果が別の定型出力で公開される』再発余地になる。
        # 即失敗 → run.bat の3回リトライに任せる fail-closed 化。
        notify_error("構成生成(即失敗)", e)
        raise RuntimeError(
            f"構成生成失敗(フォールバック禁止): {type(e).__name__}: {e}"
        ) from e

    print(f"  → {len(structure.get('sections', []))} セクション構成が決まりました")
    return structure


def generate_comedy_design(theme: str, structure: dict,
                           channel_id: str = "health") -> dict | None:
    """テーマ・構成から笑いのネタを事前設計する（台本生成の前に呼ぶ）"""
    llm = get_llm()
    print("笑いのネタを設計しています...")
    if channel_id == "creatures":
        from prompts.creatures import build_comedy_design_prompt as creatures_comedy_prompt
        prompt = creatures_comedy_prompt(theme, structure)
    else:
        prompt = build_comedy_design_prompt(theme, structure)
    try:
        raw = call_with_retry(
            llm.generate, prompt, model_config.CREATIVE,
            label="笑いの設計",
            temperature=1.0,
        )
        data = extract_json_safe(raw)
        # 最低限のバリデーション
        if not isinstance(data, dict):
            raise ValueError("笑いの設計結果がJSON objectではありません")
        item_count = sum(1 for k in ("viewer_aruaru", "expectation_reversal", "opening_boke",
                                      "callback", "tendon", "number_impact") if data.get(k))
        print(f"  → {item_count}/6 種類のネタを設計しました")
        return data
    except Exception as e:
        print(f"  → 笑いの設計に失敗しました（台本生成には影響しません）: {e}")
        return None


def _count_consecutive_speakers(script: dict) -> int:
    """同じキャラクターが連続して発言している箇所を数える（報告のみ、修正はしない）。"""
    count = 0
    for section in script.get("sections", []):
        lines = section.get("lines", [])
        for i in range(1, len(lines)):
            c_prev = lines[i - 1].get("character", "")
            c_curr = lines[i].get("character", "")
            if c_prev == c_curr and c_curr != "両者":
                count += 1
    return count


def _fallback_script(theme: str, structure: dict) -> dict:
    """台本生成失敗時の最小フォールバック台本を生成する"""
    sections = []
    for sec in structure.get("sections", _FALLBACK_STRUCTURE["sections"]):
        sec_title = sec.get("title") or sec.get("section") or "解説"
        points = sec.get("key_points", [])
        summary = points[0] if points else ""
        sections.append({
            "section": sec_title,
            "lines": [
                {"character": "霊夢",   "text": f"「{sec_title}」についてです。{summary}", "emotion": "normal"},
                {"character": "魔理沙", "text": "なるほど、もう少し詳しく教えてくれよ。",    "emotion": "normal"},
                {"character": "霊夢",   "text": "今回は台本の生成に失敗しましたが、次回また挑戦します。", "emotion": "normal"},
            ]
        })
    return {"title": theme, "sections": sections}


def _count_script_chars(script: dict) -> int:
    """台本のセリフ合計文字数を返す"""
    return sum(
        len(line.get("text", ""))
        for s in script.get("sections", [])
        for line in s.get("lines", [])
    )


# ── 2ステージ生成: line_typeによるキャラクター機械割り当て ───────────────
_MARISA_LINE_TYPES = {"解説", "ツッコミ", "データ", "根拠", "警告", "まとめ"}
_REIMU_LINE_TYPES  = {"ボケ", "リアクション", "質問", "驚き", "共感", "困惑"}

# 魔理沙セリフの女性語尾 → 男性語尾の置換ルール（文末パターン）
_MARISA_FEMININE_FIXES = [
    (r"たいわ([！？。…]*)\s*$", r"たいぜ\1"),
    (r"ないわ([！？。…]*)\s*$", r"ないぜ\1"),
    (r"だわ([！？。…]*)\s*$", r"だぜ\1"),
    (r"わよ([！？。…]*)\s*$", r"ぜ\1"),
    (r"のよね([！？。…]*)\s*$", r"んだよな\1"),
    (r"のよ([！？。…]*)\s*$", r"んだ\1"),
    (r"かしら([！？。…]*)\s*$", r"かな\1"),
    (r"そうね([！？。…]*)\s*$", r"そうだな\1"),
    (r"ものね([！？。…]*)\s*$", r"もんな\1"),
]

# 霊夢セリフの男性語尾 → 女性語尾の置換ルール（文末パターン）.
# 注意: 「だぜ」「なんだぜ」「ってことだぜ」「覚えておけよ」「教えてやる」は
# 新しい _MARISA_SPEECH_PATTERNS (validator 対になっている 4-tuple 版) 側で
# 扱うため, ここには入れない.
# 特に「ってことだぜ」は新テーブルで「→ってことなのよ」, こちらに残すと
# 「だぜ$→だわ」が先に発火して「ってことだわ」に化けて新テーブルが死ぬ.
# ここに残っているのは新テーブルに無い fixer-only のパターンのみ.
_REIMU_MASCULINE_FIXES = [
    (r"だろ([！？。…]*)\s*$", r"でしょ\1"),
    (r"だぞ([！？。…]*)\s*$", r"だわよ\1"),
]


def _align_text_to_character(text: str, target_char: str) -> str:
    """character変更時にテキストの一人称・語尾・呼び方を同期修正する。

    character を入れ替えたら必ずこの関数でテキストも修正すること。
    これにより「魔理沙なのに『わよ』」「霊夢なのに『だぜ』」を防ぐ。

    一人称は魔理沙・霊夢ともに「私」が正 (character-design.md 準拠).
    「俺」を使っていたら両キャラ共通で「私」に戻す.

    注意: _fix_role_violations() と同じ正規化セット (4-tuple 統一テーブル
    を含む) をここでも適用する. _sync_all_text() が「最終同期パス」という
    invariant を保つため, テーブル側の差分が出ないように同じ順序で適用.
    引用文 (「...」) の保護も同じ _sub_outside_quotes を使う.
    """
    # 共通: 「俺」→「私」 (魔理沙は女キャラ、一人称は「私」)
    text = _sub_outside_quotes(r"俺(?![\u4e00-\u9fff])", "私", text)
    if target_char == "魔理沙":
        # 女性語尾 → 男性語尾
        for pat, repl in _MARISA_FEMININE_FIXES:
            text = _sub_outside_quotes(pat, repl, text)
        # 霊夢口調の除去 (validator 対のテーブル)
        for pat, repl, _c, _r in _REIMU_SPEECH_PATTERNS:
            text = _sub_outside_quotes(pat, repl, text)
    elif target_char == "霊夢":
        # 男性語尾 (fixer-only) → 女性語尾
        for pat, repl in _REIMU_MASCULINE_FIXES:
            text = _sub_outside_quotes(pat, repl, text)
        # 魔理沙口調の除去 (validator 対のテーブル)
        for pat, repl, _c, _r in _MARISA_SPEECH_PATTERNS:
            text = _sub_outside_quotes(pat, repl, text)
    return text


def _sync_text_for_line(line: dict) -> bool:
    """1行のtext（とsynthesis_text）をcharacterに合わせて同期修正する。
    修正があればTrueを返す。
    """
    char = line.get("character", "")
    if char not in ("魔理沙", "霊夢"):
        return False
    text = line.get("text", "")
    new_text = _align_text_to_character(text, char)
    if new_text != text:
        line["text"] = new_text
        if "synthesis_text" in line:
            line["synthesis_text"] = _align_text_to_character(
                line["synthesis_text"], char)
        return True
    return False


def _sync_all_text(script: dict) -> int:
    """台本全行のテキストをcharacterに同期させる。修正行数を返す。"""
    synced = 0
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            if _sync_text_for_line(line):
                synced += 1
    return synced


# ── 引用符保護ヘルパー ────────────────────────────────────────
# speech_pattern / pronoun / 呼び方 の自動修正・検出は 「...」 で囲まれた
# 引用文を無視する. 例: 魔理沙行で『患者は「知らなかった！」と驚いた』の
# 「知らなかった！」は相手の発言の引用なので、霊夢口調フィルタで書き換えない.
#
# 対応方針:
#  - 整合 (「 と 」 が同数, 入れ子なし): 外側だけに置換/検出
#  - 不整合 (unbalanced) または 入れ子 (「A「B」C」): 保守的に無変更/無検出
#    (引用文を壊すリスクを避ける. 違反は次段の AI 検証 or gate に委ねる)
#
# 台本では入れ子引用は 『...』 で表記される運用で, 「「」」 の入れ子は稀.
# 不整合は AI 生成で起こりうるため安全側に倒す.

_QUOTE_SPLIT_RE = re.compile(r"(「[^」]*」)")
_QUOTE_NEST_RE = re.compile(r"「[^」]*「")


def _quotes_are_safe(text: str) -> bool:
    """text の 「」 が整合 (同数) かつ 入れ子なし なら True."""
    if text.count("「") != text.count("」"):
        return False
    if _QUOTE_NEST_RE.search(text):
        return False
    return True


def _sub_outside_quotes(pat, repl: str, text: str) -> str:
    """「...」 の外側だけに re.sub を適用する.

    pat は文字列または re.Pattern. 文字列の場合は内部で re.sub を使う.
    不整合 / 入れ子 の引用は保守的に無変更で返す.
    """
    if not _quotes_are_safe(text):
        return text
    parts = _QUOTE_SPLIT_RE.split(text)
    for i in range(len(parts)):
        if i % 2 == 0:  # 偶数 index は 「」 の外側
            if isinstance(pat, str):
                parts[i] = re.sub(pat, repl, parts[i])
            else:
                parts[i] = pat.sub(repl, parts[i])
    return "".join(parts)


def _search_outside_quotes(pat, text: str) -> bool:
    """「...」 の外側にマッチがあるかだけを判定する.

    pat は文字列または re.Pattern.
    不整合 / 入れ子 の引用は validator 側では「全文検索にフォールバック」する.
    理由: fixer は壊すリスクを避けるため無変更で通すが, validator が沈黙すると
    malformed 引用の行が fail-open で公開される. 全文検索すれば最悪 false
    positive (引用内の違反を拾う) で gate に止まり再生成が走るため, 安全側.
    """
    if not _quotes_are_safe(text):
        if isinstance(pat, str):
            return re.search(pat, text) is not None
        return pat.search(text) is not None
    parts = _QUOTE_SPLIT_RE.split(text)
    for i in range(len(parts)):
        if i % 2 == 0:
            if isinstance(pat, str):
                if re.search(pat, parts[i]):
                    return True
            else:
                if pat.search(parts[i]):
                    return True
    return False



def _fix_role_violations(script: dict) -> tuple[dict, int]:
    """台本生成直後にテキスト・表情の口調逸脱を修正する。

    修正内容（キャラクター名は変更しない）:
    1. 呼び方修正: 魔理沙が「君」→「お前」に置換
    2. 一人称修正: 魔理沙・霊夢ともに「俺」→「私」(両者とも正=「私」, character-design.md 準拠)
    3. 魔理沙の女性語尾修正: 「だわ」→「だぜ」等
    4. 霊夢の男性語尾修正: 「だぜ」→「だわ」等
    5. line_type 正規化: 自キャラ専用でない line_type を空文字化 (観測用に _original_line_type に退避)
    6. 表情修正: 魔理沙に embarrassed → normal に強制

    ※キャラクター入替は行わない（最終AI検証に一本化）

    戻り値は (script, 修正行数)
    """
    fixed = 0
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            char = line.get("character", "")
            text = line.get("text", "")
            modified = False

            # 「両者」（ハモり行）は修正対象外
            if char == "両者":
                continue

            # ── 魔理沙の呼び方修正 ──
            # 「君」「あなた」→霊夢への呼びかけなら「お前」
            # 「あなたたち」→視聴者への呼びかけは「みんな」
            # 引用文 (「...」) は他者のセリフなので対象外.
            if line.get("character") == "魔理沙":
                new_text = text
                new_text = _sub_outside_quotes(r"君([のはがをもにだ、。！？])", r"お前\1", new_text)
                new_text = _sub_outside_quotes(r"あなたたち", "みんな", new_text)
                new_text = _sub_outside_quotes(r"あなた([のはがをもにだ、。！？])", r"みんな\1", new_text)
                if new_text != text:
                    line["text"] = new_text
                    if "synthesis_text" in line:
                        s = line["synthesis_text"]
                        s = _sub_outside_quotes(r"君([のはがをもにだ、。！？])", r"お前\1", s)
                        s = _sub_outside_quotes(r"あなたたち", "みんな", s)
                        s = _sub_outside_quotes(r"あなた([のはがをもにだ、。！？])", r"みんな\1", s)
                        line["synthesis_text"] = s
                    text = new_text
                    modified = True

            # ── 一人称修正 ──
            # 魔理沙・霊夢 とも一人称は「私」が正解 (character-design.md 準拠).
            # 魔理沙=女キャラなので「俺」への強制変換はしない.
            # 両キャラともに「俺」を使っていたら「私」に戻す.
            # 引用文 (「...」) は他者のセリフなので対象外.
            if line.get("character") in ("霊夢", "魔理沙"):
                new_text = _sub_outside_quotes(r"俺(?![\u4e00-\u9fff])", "私", text)
                if new_text != text:
                    line["text"] = new_text
                    if "synthesis_text" in line:
                        line["synthesis_text"] = _sub_outside_quotes(
                            r"俺(?![\u4e00-\u9fff])", "私",
                            line["synthesis_text"],
                        )
                    text = new_text  # 下流語尾修正が古い text を参照しないよう更新
                    modified = True

            # ── 魔理沙の女性語尾修正 ──
            # 引用文 (「...」) は他者のセリフなので対象外.
            if line.get("character") == "魔理沙":
                new_text = text
                for pat, repl in _MARISA_FEMININE_FIXES:
                    new_text = _sub_outside_quotes(pat, repl, new_text)
                if new_text != text:
                    line["text"] = new_text
                    if "synthesis_text" in line:
                        s = line["synthesis_text"]
                        for pat, repl in _MARISA_FEMININE_FIXES:
                            s = _sub_outside_quotes(pat, repl, s)
                        line["synthesis_text"] = s
                    text = new_text
                    modified = True

            # ── 霊夢の男性語尾修正 ──
            # 引用文 (「...」) は他者のセリフなので対象外.
            if line.get("character") == "霊夢":
                new_text = text
                for pat, repl in _REIMU_MASCULINE_FIXES:
                    new_text = _sub_outside_quotes(pat, repl, new_text)
                if new_text != text:
                    line["text"] = new_text
                    if "synthesis_text" in line:
                        s = line["synthesis_text"]
                        for pat, repl in _REIMU_MASCULINE_FIXES:
                            s = _sub_outside_quotes(pat, repl, s)
                        line["synthesis_text"] = s
                    text = new_text
                    modified = True

            # ── 魔理沙の表情修正: embarrassed → normal ──
            if line.get("character") == "魔理沙":
                if line.get("emotion") == "embarrassed":
                    line["emotion"] = "normal"
                    modified = True

            # ── speech_pattern 自動修正 (validator と同じテーブルを参照) ──
            # 霊夢のセリフ → 魔理沙口調を除去, 魔理沙のセリフ → 霊夢口調を除去.
            # 引用文 (「...」 で囲まれた部分) は他者の発言のため対象外.
            if char == "霊夢":
                new_text = text
                for pat, repl, _conf, _reason in _MARISA_SPEECH_PATTERNS:
                    new_text = _sub_outside_quotes(pat, repl, new_text)
                if new_text != text:
                    line["text"] = new_text
                    if "synthesis_text" in line:
                        s = line["synthesis_text"]
                        for pat, repl, _conf, _reason in _MARISA_SPEECH_PATTERNS:
                            s = _sub_outside_quotes(pat, repl, s)
                        line["synthesis_text"] = s
                    text = new_text
                    modified = True
            elif char == "魔理沙":
                new_text = text
                for pat, repl, _conf, _reason in _REIMU_SPEECH_PATTERNS:
                    new_text = _sub_outside_quotes(pat, repl, new_text)
                if new_text != text:
                    line["text"] = new_text
                    if "synthesis_text" in line:
                        s = line["synthesis_text"]
                        for pat, repl, _conf, _reason in _REIMU_SPEECH_PATTERNS:
                            s = _sub_outside_quotes(pat, repl, s)
                        line["synthesis_text"] = s
                    text = new_text
                    modified = True

            # ── name_call 除去 (行頭限定) ──
            # 自キャラ名の行頭 vocative を削除. 削除後の text が極端に短くなる場合
            # (意味を失うケース) は削除をロールバックして gate に任せる.
            _NAME_CALL_PREFIX_MIN = 5  # 行頭 vocative 削除後の最小許容文字数
            if char == "霊夢":
                m = re.match(r"^霊夢[、,！!？?…　 ]+", text)
                if m:
                    trimmed = text[m.end():]
                    if len(trimmed) >= _NAME_CALL_PREFIX_MIN:
                        line["text"] = trimmed
                        if "synthesis_text" in line:
                            s = line["synthesis_text"]
                            sm = re.match(r"^霊夢[、,！!？?…　 ]+", s)
                            if sm:
                                line["synthesis_text"] = s[sm.end():]
                        text = trimmed
                        modified = True
            elif char == "魔理沙":
                m = re.match(r"^魔理沙[、,！!？?…　 ]+", text)
                if m:
                    trimmed = text[m.end():]
                    if len(trimmed) >= _NAME_CALL_PREFIX_MIN:
                        line["text"] = trimmed
                        if "synthesis_text" in line:
                            s = line["synthesis_text"]
                            sm = re.match(r"^魔理沙[、,！!？?…　 ]+", s)
                            if sm:
                                line["synthesis_text"] = s[sm.end():]
                        text = trimmed
                        modified = True

            # ── line_type 正規化 ──
            # 自キャラ専用でない line_type が付いていたら「汎用」に置換.
            # 空文字にすると下流の se_assign/prosody プロンプトで
            # `(normal/)` という壊れた hint になるため「汎用」を採用.
            # (元の値は _original_line_type に退避して観測用に残す.
            #  この内部フィールドは JSON 保存前に _type_locked と同様に除去する.)
            lt = line.get("line_type", "")
            if char == "霊夢" and lt in _MARISA_LINE_TYPES:
                line["_original_line_type"] = lt
                line["line_type"] = "汎用"
                modified = True
            elif char == "魔理沙" and lt in _REIMU_LINE_TYPES:
                line["_original_line_type"] = lt
                line["line_type"] = "汎用"
                modified = True

            if modified:
                fixed += 1

    return script, fixed




# ── 決定論的バリデーション ──────────────────────────────────────────

# validator と fixer で同じテーブルを参照するため
# (pattern, replacement, confidence, reason) の 4-tuple に統一.
# replacement は re.sub() に渡す文字列 (後方参照 \1, \2 可).
# validator は pattern+confidence+reason を使い, fixer は pattern+replacement を使う.

# 霊夢のセリフに出現したら違反（魔理沙の口調）→ 霊夢らしい語尾に置換.
# 順序依存: 長いパターンを先に置く (短い "だぜ$" が先に発火すると
# "ってことだぜ" → "ってことだわ" で停止し, 専用の置換が効かなくなる).
_MARISA_SPEECH_PATTERNS = [
    (re.compile(r"ってことだぜ"), "ってことなのよ", 1.0, "「ってことだぜ」は魔理沙専用"),
    (re.compile(r"なんだぜ"), "なんだわ", 1.0, "「なんだぜ」は魔理沙専用"),
    (re.compile(r"覚えておけよ"), "覚えておいてね", 0.95, "教える側の口調"),
    (re.compile(r"教えてやる"), "教えてあげる", 0.95, "解説役の口調"),
    (re.compile(r"だぜ([！？。…!?.]*)(\s*)$"), r"だわ\1\2", 1.0, "「だぜ」は魔理沙専用の語尾"),
]

# 魔理沙のセリフに出現したら違反（霊夢の口調）→ 魔理沙らしい語尾に置換.
# 注意: 「知らなかった」「そうなの」は meaning-level の違反 (魔理沙=知識豊富).
# 語尾だけ直しても意味は変わらないが, gate 通過 + 観測記録で次回改善する戦略.
_REIMU_SPEECH_PATTERNS = [
    (re.compile(r"知らなかった([！!])"), r"知らなかったぜ\1", 0.7, "聞き手のリアクション"),
    (re.compile(r"そうなの([？?])"), r"そうなのか\1", 0.7, "聞き手の確認"),
]


def deterministic_validate_roles(script: dict) -> list[dict]:
    """AI検証の後に実行する決定論的バリデーション。

    キャラクターの入れ替わり違反を検出して報告する（修正はしない）。
    戻り値が空リストなら全チェック合格。

    各違反は {"global_idx": int, "check_type": str, "character": str,
              "detail": str, "confidence": float} の辞書。
    """
    all_lines: list[dict] = []
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            all_lines.append(line)

    violations: list[dict] = []

    for i, line in enumerate(all_lines):
        char = line.get("character", "")
        text = line.get("text", "")
        lt = line.get("line_type", "")

        if char == "両者":
            continue

        # ── チェック1: 連続発言 ──
        if i > 0:
            prev_char = all_lines[i - 1].get("character", "")
            if char == prev_char and char != "両者" and prev_char != "両者":
                violations.append({
                    "global_idx": i,
                    "check_type": "consecutive",
                    "character": char,
                    "detail": f"行{i-1}と行{i}が同じキャラ({char})で連続",
                    "confidence": 1.0,
                })

        # ── チェック2: line_type整合性 ──
        if char == "霊夢" and lt in _MARISA_LINE_TYPES:
            violations.append({
                "global_idx": i,
                "check_type": "line_type",
                "character": char,
                "detail": f"霊夢に魔理沙専用line_type「{lt}」が付いている",
                "confidence": 1.0,
            })
        elif char == "魔理沙" and lt in _REIMU_LINE_TYPES:
            violations.append({
                "global_idx": i,
                "check_type": "line_type",
                "character": char,
                "detail": f"魔理沙に霊夢専用line_type「{lt}」が付いている",
                "confidence": 1.0,
            })

        # ── チェック3: 口調パターン ──
        # 引用文 (「...」) は他者のセリフなので検査対象外 (fixer と対称).
        if char == "霊夢":
            for pat, _repl, conf, reason in _MARISA_SPEECH_PATTERNS:
                if _search_outside_quotes(pat, text):
                    violations.append({
                        "global_idx": i,
                        "check_type": "speech_pattern",
                        "character": char,
                        "detail": f"霊夢のセリフに魔理沙の口調: {reason}",
                        "confidence": conf,
                    })
                    break  # 1行につき最初のマッチのみ
        elif char == "魔理沙":
            for pat, _repl, conf, reason in _REIMU_SPEECH_PATTERNS:
                if _search_outside_quotes(pat, text):
                    violations.append({
                        "global_idx": i,
                        "check_type": "speech_pattern",
                        "character": char,
                        "detail": f"魔理沙のセリフに霊夢の口調: {reason}",
                        "confidence": conf,
                    })
                    break

        # ── チェック4: 名前呼び (行頭限定) ──
        # 中間出現は引用/言及の可能性があるため flag しない.
        # fixer も行頭の vocative のみ削除する.
        if char == "霊夢" and re.match(r"霊夢[、,！!？?…　 ]", text):
            violations.append({
                "global_idx": i,
                "check_type": "name_call",
                "character": char,
                "detail": "霊夢のセリフで行頭「霊夢」呼びかけ（魔理沙のセリフ）",
                "confidence": 0.95,
            })
        elif char == "魔理沙" and re.match(r"魔理沙[、,！!？?…　 ]", text):
            violations.append({
                "global_idx": i,
                "check_type": "name_call",
                "character": char,
                "detail": "魔理沙のセリフで行頭「魔理沙」呼びかけ（霊夢のセリフ）",
                "confidence": 0.95,
            })

        # ── チェック5: 一人称 ──
        # 魔理沙・霊夢ともに一人称は「私」が正 (character-design.md 準拠).
        # どちらか一方でも「俺」を使っていたら違反.
        # 引用文 (「...」) の中の「俺」は他者のセリフなので検査対象外.
        if char in ("魔理沙", "霊夢") and _search_outside_quotes(r"俺(?![\u4e00-\u9fff])", text):
            violations.append({
                "global_idx": i,
                "check_type": "pronoun",
                "character": char,
                "detail": f"{char}が一人称「俺」を使用（「私」が正しい）",
                "confidence": 0.95,
            })

    return violations


def _snapshot_violations(script: dict, label: str) -> int:
    """現在の台本の違反数と連続発言数をログ出力する（計測用）。戻り値は違反数。"""
    violations = deterministic_validate_roles(script)
    consec = _count_consecutive_speakers(script)
    print(f"  [計測] {label}: 違反{len(violations)}件, 連続発言{consec}箇所")
    return len(violations)




def generate_script(theme: str, structure: dict,
                    comedy_design: dict | None = None,
                    soft_min_chars: int = _MIN_SCRIPT_CHARS,
                    hard_min_chars: int = _HARD_MIN_SCRIPT_CHARS,
                    max_chars: int = _MAX_SCRIPT_CHARS,
                    channel_id: str = "health") -> dict:
    """構成から台本を生成（文字数不足時は最大2回再生成）"""
    llm = get_llm()
    print("台本を生成しています...")

    if channel_id == "creatures":
        from prompts.creatures import build_script_prompt as creatures_script_prompt
        base_prompt = creatures_script_prompt(theme, structure, comedy_design=comedy_design)
    else:
        suggestions = load_suggestions()
        if suggestions.get("suggestions"):
            print(f"  → 改善提案 {len(suggestions['suggestions'])} 件を反映します")
            base_prompt = build_script_prompt_with_suggestions(
                theme, structure, suggestions, comedy_design=comedy_design)
        else:
            base_prompt = build_script_prompt(theme, structure, comedy_design=comedy_design)

    script = None
    prev_chars = 0
    for attempt in range(1, 4):  # 最大3回試みる
        if attempt > 1:
            print(f"  → 文字数不足のため再生成します（{attempt}回目）")
        # 2回目以降は文字数不足の強調を追加
        if attempt > 1:
            _retry_target = int(soft_min_chars * 1.08)  # ソフト目標の108%を指示
            prompt = base_prompt + f"\n\n【緊急指示】前回の生成は {prev_chars} 文字しかなかった。今回は必ず {_retry_target:,} 文字以上になるよう、各セクションを大幅に拡充して出力すること。特に各章を最低40行以上にすること。"
        else:
            prompt = base_prompt
        # 全試行でCREATIVE（Pro）を使用（Flashは長文生成が弱いため）
        _model = model_config.CREATIVE
        try:
            raw = call_with_retry(
                llm.generate, prompt, _model,
                label=f"台本生成({attempt})",
                temperature=1.0,
            )
            data = extract_json_safe(raw)
            candidate = repair_script(data, theme)
        except (ConnectionError, OSError, TimeoutError) as e:
            # ネットワーク障害は即座にraiseしてフォールバック禁止
            raise RuntimeError(f"台本生成中にネットワーク障害(試行{attempt}): {e}") from e
        except Exception as e:
            # 2026-04-09事故対策: 以前は _fallback_script() で続行していたが、
            # 定型台本がそのまま公開物になる経路を残さないため即失敗に変更。
            notify_error("台本生成(試行失敗)", e)
            raise RuntimeError(
                f"台本生成失敗(試行{attempt}/3, フォールバック禁止): {type(e).__name__}: {e}"
            ) from e

        # 修復後の品質チェック
        is_valid, issues = validate_script(candidate)
        if not is_valid:
            print(f"  [!] 台本が品質基準を満たしていません: {', '.join(issues)}")
            if attempt < 3:
                continue
            # 2026-04-09事故対策: 品質不足でもフォールバック禁止
            notify_error("台本品質不足", ValueError(", ".join(issues)))
            raise RuntimeError(
                f"台本品質基準を満たせず3回とも失敗(フォールバック禁止): {', '.join(issues)}"
            )

        total_chars = _count_script_chars(candidate)
        if total_chars >= soft_min_chars:
            script = candidate
            break
        print(f"  → {total_chars} 文字（目標 {soft_min_chars} 文字未満）")
        prev_chars = total_chars

        # 3回目でも不足の場合、既存台本を膨らませる
        if attempt >= 3 and total_chars < soft_min_chars:
            print(f"  → 3回とも文字数不足。既存台本を拡充します...")
            _expand_target_hi = int(max_chars * 1.07)  # max_chars の 107% を上限目安に
            expand_prompt = (
                f"以下のJSON台本はセリフ合計が{total_chars}文字しかありません。\n"
                f"目標は{soft_min_chars:,}〜{_expand_target_hi:,}文字です。あと{soft_min_chars - total_chars}文字以上足りません。\n\n"
                f"【拡充のルール】\n"
                f"- 視聴者が「へぇー！」と思う具体的な研究データ・統計・実験結果を追加する\n"
                f"- 「例えば〜」で始まる日常生活での具体例やたとえ話を追加する\n"
                f"- 霊夢の素朴な疑問→魔理沙の意外な回答、という掛け合いで深掘りする\n"
                f"- 既存の内容と矛盾しない、テーマに直結した情報だけ追加する\n"
                f"- 薄い一般論や繰り返しは絶対に追加しない\n"
                f"- 既存のセリフはそのまま残し、間に新しいセリフを挿入する形で拡充する\n"
                f"- 1セリフは15〜40文字を守る\n"
                f"- 出力は完全なJSON台本として返すこと\n\n"
                f"```json\n{json.dumps(candidate, ensure_ascii=False, indent=2)}\n```"
            )
            try:
                raw_expanded = call_with_retry(
                    llm.generate, expand_prompt, model_config.CREATIVE,
                    label="台本拡充",
                    temperature=0.8,
                )
                expanded_data = extract_json_safe(raw_expanded)
                expanded = repair_script(expanded_data, theme)
            except Exception as e:
                # 2026-04-09事故対策: 拡充失敗は握りつぶさず即失敗
                notify_error("台本拡充失敗", e)
                raise RuntimeError(
                    f"台本拡充に失敗(フォールバック禁止): {type(e).__name__}: {e}"
                ) from e
            # Codex Round5: 拡充後も必ず validate_script() を再実行
            # (旧実装は文字数だけ見て採用していた。構造が荒れた拡充結果を通す穴)
            exp_valid, exp_issues = validate_script(expanded)
            if not exp_valid:
                notify_error("台本拡充の品質不足", ValueError(", ".join(exp_issues)))
                raise RuntimeError(
                    f"拡充後の台本が品質基準を満たしません(フォールバック禁止): "
                    f"{', '.join(exp_issues)}"
                )
            expanded_chars = _count_script_chars(expanded)
            print(f"  → 拡充後: {expanded_chars} 文字")
            # 2段階しきい値: ソフト目標未達でもハード下限以上なら採用.
            # 2026-04-12: 拡充後 5714 字 で即死していた. ハード未満のみ fail-closed.
            if expanded_chars < hard_min_chars:
                raise RuntimeError(
                    f"拡充後も致命的文字数不足(フォールバック禁止): "
                    f"{expanded_chars}文字 < ハード下限 {hard_min_chars}文字"
                )
            if expanded_chars < soft_min_chars:
                print(f"  [警告] 拡充後 {expanded_chars} 文字 < ソフト目標 "
                      f"{soft_min_chars} 文字だが、ハード下限 "
                      f"{hard_min_chars} 以上のため採用")
            candidate = expanded
            script = candidate
            break

    if script is None:
        # 2026-04-09事故対策: ループ全通過したのに script 未設定は生成ロジックのバグ。
        # フォールバック台本で公開物を生やさず、即失敗。
        raise RuntimeError(
            "台本生成ループが script を未設定のまま終了しました(フォールバック禁止)"
        )

    total_lines = sum(len(s.get("lines", [])) for s in script.get("sections", []))
    print(f"  → {total_lines} 行の台本が生成されました")

    # 文字数チェック (ハード下限基準, channel config 由来)
    total_chars = _count_script_chars(script)
    print(f"  → セリフ合計文字数: {total_chars} 文字", end="")
    if total_chars < hard_min_chars:
        est_min = total_chars / 400
        print(f" [致命的不足] ハード下限 {hard_min_chars} 文字未満、推定尺: 約{est_min:.0f}分")
        notify_error("台本文字数致命的不足", ValueError(f"セリフ合計 {total_chars} 文字 < ハード下限 {hard_min_chars}"))
        raise RuntimeError(
            f"台本文字数致命的不足(フォールバック禁止): {total_chars}文字 < {hard_min_chars}文字"
        )
    elif total_chars < soft_min_chars:
        est_min = total_chars / 400
        print(f" [警告] ソフト目標 {soft_min_chars} 未達だが採用、推定尺: 約{est_min:.0f}分")
    elif total_chars > max_chars:
        est_min = total_chars / 400
        print(f" [超過] 目標 {soft_min_chars}〜{max_chars} 文字、推定尺: 約{est_min:.0f}分")
    else:
        est_min = total_chars / 400
        print(f" [OK] 推定尺: 約{est_min:.0f}分")

    # ── Gemini生出力を保存（計測用） ──
    script["_raw_sections"] = copy.deepcopy(script.get("sections", []))

    # ── 計測: Gemini生出力の違反数 ──
    _snapshot_violations(script, "Gemini生出力")

    # テキスト補正（一人称・語尾・表情の口調統一。キャラクター名は変更しない）
    # Geminiのcharacter指定は99%正しいので、characterは変えずテキストだけ補正する
    script, role_fixed = _fix_role_violations(script)
    if role_fixed > 0:
        print(f"  → テキスト補正: {role_fixed} 行")

    # 最終テキスト同期（全修正が終わった後の安全弁）
    final_synced = _sync_all_text(script)
    if final_synced > 0:
        print(f"  → 最終テキスト同期: {final_synced} 行")

    # 最終品質ゲート: 非連続系違反は fail-closed（Codex Round5）
    # 連続発言(consecutive)は Gemini の意図的な演出として feedback 済み（修正禁止）
    final_violations = deterministic_validate_roles(script)
    if final_violations:
        non_consec = [v for v in final_violations if v["check_type"] != "consecutive"]
        consec = [v for v in final_violations if v["check_type"] == "consecutive"]
        if non_consec:
            print(f"  [品質ゲート] 残存違反: {len(non_consec)} 件（連続発言除く）")
            for v in non_consec[:10]:
                print(f"      行{v['global_idx']}: [{v['check_type']}] {v['detail']}")
            # Round5: log only では公開物が通ってしまう → raise
            # 2026-04-12: print() だけでは stdout にしか残らず診断不能だった.
            # RuntimeError には先頭5件の detail を埋め込み, notify_error には
            # 短縮版サマリを渡して Discord/daily log で即診断可能にする.
            _summary_items = [
                f"行{v['global_idx']}:[{v['check_type']}]{v['detail']}"
                for v in non_consec[:5]
            ]
            _summary_short = " / ".join(_summary_items)
            if len(non_consec) > 5:
                _summary_short += f" ... 他{len(non_consec) - 5}件"
            notify_error(
                "台本最終品質ゲート残存違反",
                ValueError(f"{len(non_consec)} 件の非連続違反: {_summary_short}"),
            )
            raise RuntimeError(
                f"台本最終品質ゲートに非連続違反 {len(non_consec)} 件"
                f"(フォールバック禁止): {_summary_short}"
            )
        if consec:
            print(f"  [情報] 連続発言: {len(consec)} 箇所（Gemini生出力のまま維持）")
    else:
        print("  → 品質ゲート: 全項目合格")

    # ── 計測: Gemini生出力 vs 最終出力の差分 ──
    raw_sections = script.pop("_raw_sections", [])
    raw_lines = [l for s in raw_sections for l in s.get("lines", [])]
    final_lines = [l for s in script.get("sections", []) for l in s.get("lines", [])]
    char_changes = 0
    for r, f in zip(raw_lines, final_lines):
        if r.get("character") != f.get("character"):
            char_changes += 1
    print(f"  [計測] フィルター差分: {char_changes}/{len(raw_lines)} 行でcharacterが変更されました")

    # 内部フラグ _type_locked を除去（台本JSONには保存しない）
    # ト書き・演出注釈を text / synthesis_text から除去
    # 2026-04-09事故: 「コールバック」が字幕に残り、音声には出ない現象が発生。
    # 原因: 旧regexが特定キーワードに限定 + キーワードは括弧直後にある必要があった。
    # 対策(Codex Round3反映):
    #   (a) キーワード辞書を大幅拡張
    #   (b) 括弧『直後』に限定して false positive を防止
    #       (例: 『（3日の間）』『（人間ドックで）』『（仲間と）』を誤除去しないため)
    #   (c) 半角/全角括弧 + 【】 を対象化
    # Codex Round3/Round5指摘: 広すぎる語は本文で false positive を起こすため除外。
    # Round3で除外: 驚き/ネタ/笑顔/苦笑/真顔/見せ場/オチ
    # Round5で除外: 大声/小声/独り言/声色/ドヤ顔/繰り返し/演出/沈黙/一拍/間を取/リアクション
    #   (例: 『大声で話すと血圧が上がる』『独り言でも脳は反応する』『繰り返し継続すると』等は自然文)
    # 残すのは「健康ナレーション本文ではまず出現しない、台本注釈固有の語彙」のみ。
    _STAGE_DIR_KEYWORDS = (
        # お笑い構造（健康テーマ本文ではまず出ない語）
        "天丼", "伏線回収", "前振り", "前フリ",
        "コールバック", "callback", "Callback",
        # 演出指示（注釈固有）
        "効果音", "BGM", "ナレ", "ナレーション",
    )
    _STAGE_DIR_ALT = "|".join(re.escape(k) for k in _STAGE_DIR_KEYWORDS)
    # 括弧直後（先頭に空白・改行が入る場合も含む）にキーワードが現れる塊のみを除去
    # 例: "（ コールバック回収 ）"、"（\nBGMフェード\n）" も対象
    _STAGE_DIR_RE = re.compile(
        rf"[（(【][\s　]*(?:{_STAGE_DIR_ALT})[^）)】]*[）)】]",
        re.DOTALL,
    )
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            line.pop("_type_locked", None)
            line.pop("_original_line_type", None)  # 観測用の内部フィールドを除去
            for field in ("text", "synthesis_text"):
                val = line.get(field)
                if val and _STAGE_DIR_RE.search(val):
                    line[field] = _STAGE_DIR_RE.sub("", val).strip()

    # Codex Round5: 注釈除去後に再度文字数を検証（strip で下限割れを検知）
    # 2026-04-12: ソフト目標ではなくハード下限で評価.
    post_strip_chars = _count_script_chars(script)
    if post_strip_chars < hard_min_chars:
        raise RuntimeError(
            f"ト書き除去後に致命的文字数不足(フォールバック禁止): "
            f"{post_strip_chars}文字 < ハード下限 {hard_min_chars}文字"
        )

    return script, raw_sections


def save_script(theme: str, script: dict, output_dir: Path) -> Path:
    """台本をJSONファイルとして保存.

    Step 3-δ.5c-1: output_dir を引数で受け取る (旧 module-level OUTPUT_DIR 廃止).
    Codex 設計レビュー: channel schema は paths.output_subdir に 'foo/bar' のような
    相対サブパスも許容するため, parents=True で mkdir する.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # ファイル名に使えない文字を除去
    safe_theme = re.sub(r'[\\/:*?"<>|]', "", theme)[:30]
    filename = f"{timestamp}_{safe_theme}.json"

    output_path = output_dir / filename
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    return output_path


def _pick_theme_from_file(themes_path: Path, output_dir: Path) -> str:
    """themes.txt からランダムにテーマを1つ選ぶ（output_dir で使用済みのテーマは除外）.

    Step 3-δ.5c-1: themes_path / output_dir を引数で受け取る (CLI main 専用).
    """
    if not themes_path.exists():
        raise FileNotFoundError(f"themes.txt が見つかりません: {themes_path}")
    lines = [l.strip() for l in themes_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        raise ValueError("themes.txt にテーマが入っていません")

    # output_dir のサブディレクトリ名から使用済み safe_theme を取得
    used: set[str] = set()
    try:
        for d in output_dir.iterdir():
            if d.is_dir() and re.match(r"\d{8}_\d{6}_", d.name):
                used.add(d.name[16:])
    except Exception:
        pass  # output_dir が読めなくてもテーマ選択は続行

    # safe_theme 変換して比較
    unused = [t for t in lines if re.sub(r'[\\/:*?"<>|]', "", t)[:30] not in used]
    candidates = unused if unused else lines  # 全消費済みなら循環利用
    if unused and len(unused) < len(lines):
        print(f"[テーマ] 残り未使用: {len(unused)}/{len(lines)} 件")
    return random.choice(candidates)


# ── メインエントリポイント ──────────────────────────────────


def run_script_gen(run_dir: str | Path, theme: str, external_script: dict | None = None) -> dict:
    """台本生成スキルを実行する。

    Args:
        run_dir: パイプラインの実行ディレクトリ
        theme: 動画のテーマ
        external_script: 外部台本JSON（指定時はAI生成をスキップ）

    Returns:
        {"youtube_title": str, "structure": dict, "script": dict, "script_path": Path}
    """
    run_dir = Path(run_dir)
    # Step 3-δ.5c-1: invariant `run_dir.parent == output_dir` を本 Step でも維持.
    # generator._create_run_dir() が `output_dir / "{ts}_{theme}"` で作るので成立.
    output_dir = run_dir.parent
    logger = SkillLogger(run_dir, "script_gen")
    update_phase(run_dir, "script_gen", "in_progress")

    # Step 3-δ.5c-8: channel config から文字数閾値を取得.
    # manifest.channel_id は generator.py create_manifest() で必ず書き込まれる.
    _manifest = load_manifest(run_dir)
    _ch_id = _manifest.get("channel_id", "health")
    try:
        from _channel import load_channel
        _ch_cfg = load_channel(_ch_id)
    except Exception as _ce:
        raise RuntimeError(f"channel config 読込失敗 (script_gen, channel={_ch_id}): {_ce}") from _ce
    _soft_min = _ch_cfg.script.min_chars
    _hard_min = _ch_cfg.script.hard_min_chars
    _max_chars = _ch_cfg.script.max_chars

    try:
        # ── フェーズ1: タイトル + 構成を並列生成 ─────────────
        logger.log("【フェーズ1】タイトル・構成を並列生成しています...")
        structure = None
        with ThreadPoolExecutor(max_workers=2) as ex:
            ft = ex.submit(generate_title, theme)
            fs = ex.submit(generate_structure, theme, _ch_id)

            try:
                youtube_title = ft.result()
            except Exception as e:
                notify_error("タイトル生成", e)
                logger.error(f"タイトル生成: {e}")
                youtube_title = theme

            try:
                structure = fs.result()
            except Exception as e:
                # 2026-04-09事故対策 (Codex Round4): _FALLBACK_STRUCTURE 続行を撤廃。
                # generate_structure() 内部で既に RuntimeError を raise するが、
                # Future経由の再raiseに備えてこちらでも fail-closed。
                notify_error("構成生成(Future)", e)
                logger.error(f"構成生成: {e} → 即失敗(フォールバック禁止)")
                raise RuntimeError(
                    f"構成生成失敗(フォールバック禁止): {type(e).__name__}: {e}"
                ) from e

        logger.log("フェーズ1完了")

        # ── フェーズ1.5: 笑いの事前設計 ──────────────────────
        comedy_design = None
        if not external_script:
            try:
                comedy_design = generate_comedy_design(theme, structure, _ch_id)
                if comedy_design:
                    logger.log(f"笑いの設計完了: {sum(1 for k in comedy_design if comedy_design.get(k))}/6 種類")
            except Exception as e:
                logger.error(f"笑いの設計: {e}（台本生成には影響しません）")

        # ── フェーズ2: 台本生成 ─────────────────────────────
        raw_sections = None
        if external_script:
            logger.log("【フェーズ2】外部台本JSONを使用します（AI生成スキップ）")
            script = external_script
            script = repair_script(script, theme)
            total_lines = sum(len(s.get("lines", [])) for s in script.get("sections", []))
            logger.log(f"  → {total_lines} 行の台本を外部から受け取りました")
        else:
            try:
                script, raw_sections = generate_script(
                    theme, structure, comedy_design=comedy_design,
                    soft_min_chars=_soft_min, hard_min_chars=_hard_min,
                    max_chars=_max_chars, channel_id=_ch_id)
            except (ConnectionError, OSError, TimeoutError) as e:
                # ネットワーク障害は即失敗。フォールバック台本で続行しない。
                # run.batの3回リトライで回復を試みる。
                notify_error("台本生成(ネットワーク障害)", e)
                logger.error(f"台本生成: ネットワーク障害 → 即失敗(フォールバック禁止): {e}")
                raise RuntimeError(f"台本生成中にネットワーク障害: {e}") from e
            except Exception as e:
                # 2026-04-09事故対策: JSONパース崩れやschema崩れでフォールバック
                # 定型台本に差し替えると『壊れた生成結果が公開物になる』経路が残る。
                # ネットワーク障害以外も即失敗とし、run.batの3回リトライで再試行する。
                notify_error("台本生成(生成結果不正)", e)
                logger.error(
                    f"台本生成: {type(e).__name__}: {e} → 即失敗(フォールバック禁止)"
                )
                raise RuntimeError(f"台本生成失敗(生成結果不正): {e}") from e

        # ── 致命的な文字数不足チェック（全フェーズ無駄走り防止） ──
        # AI生成パスは generate_script() 内でチェック済みだが、
        # external_script パスはここが唯一のゲート。channel config の
        # hard_min_chars を使って creatures でも正しくブロックする。
        _total_chars = _count_script_chars(script)
        if _total_chars < _hard_min:
            _msg = f"台本が致命的に短い: {_total_chars}文字（ハード下限{_hard_min}文字）。"
            if external_script:
                _msg += " 外部台本の文字数がチャンネル設定の下限を満たしていません。"
            else:
                _msg += " API障害の可能性。"
            logger.error(_msg)
            notify_error("台本生成致命的失敗", ValueError(_msg))
            raise RuntimeError(_msg)

        logger.log("フェーズ2完了")

        # ── 構成のホワイトボードデータを台本JSONにマージ ──
        # LLMの台本出力にはwhiteboardが含まれないことがあるため、構成から転写する
        struct_sections = structure.get("sections", [])
        script_sections = script.get("sections", [])
        _wb_merged = 0
        if len(struct_sections) != len(script_sections):
            logger.log(f"  [!] 構成({len(struct_sections)}セクション)と台本({len(script_sections)}セクション)のセクション数不一致")
        # タイトルベースで対応するセクションを探す（インデックスずれに対応）
        for s_sec in struct_sections:
            wb = s_sec.get("whiteboard", [])
            if not wb:
                continue
            s_title = s_sec.get("title", "")
            # まずタイトル一致で探す
            matched = None
            for sc_sec in script_sections:
                sc_title = sc_sec.get("title", sc_sec.get("section", ""))
                if sc_title == s_title and not sc_sec.get("whiteboard"):
                    matched = sc_sec
                    break
            # 見つからなければインデックスでフォールバック
            if matched is None:
                idx = struct_sections.index(s_sec)
                if idx < len(script_sections) and not script_sections[idx].get("whiteboard"):
                    matched = script_sections[idx]
            if matched is not None:
                matched["whiteboard"] = wb
                _wb_merged += len(wb)
        wb_summary = structure.get("whiteboard_summary", [])
        if wb_summary and not script.get("whiteboard_summary"):
            script["whiteboard_summary"] = wb_summary
        if _wb_merged > 0:
            logger.log(f"ホワイトボード: 構成から {_wb_merged} 項目をマージしました")

        # ── Gemini生出力をraw_script.jsonとして保存（計測用） ──
        if raw_sections is not None:
            raw_path = run_dir / "raw_script.json"
            try:
                raw_data = copy.deepcopy(script)
                raw_data["sections"] = raw_sections
                raw_data.pop("youtube_title", None)
                with open(raw_path, "w", encoding="utf-8") as f:
                    json.dump(raw_data, f, ensure_ascii=False, indent=2)
                logger.log(f"Gemini生出力を保存: {raw_path.name}")
            except Exception:
                pass  # 計測データの保存失敗は無視

        # ── 台本を保存 ───────────────────────────────────
        script["youtube_title"] = youtube_title
        try:
            output_path = save_script(theme, script, output_dir)
            logger.log(f"台本を保存しました: {output_path}")
        except Exception as e:
            notify_error("台本保存", e)
            raise RuntimeError(f"台本保存に失敗しました: {e}") from e

        # パイプライン状態を更新
        update_phase(
            run_dir, "script_gen", "completed",
            outputs=[output_path.name],
        )

        result = {
            "youtube_title": youtube_title,
            "structure": structure,
            "script": script,
            "script_path": output_path,
        }
        logger.log("台本生成スキル完了")
        return result

    except Exception as e:
        update_phase(run_dir, "script_gen", "failed", error=str(e))
        raise


# ── CLI ──────────────────────────────────────────────────

def main():
    import argparse
    import sys as _sys
    parser = argparse.ArgumentParser(description="台本生成スキル")
    parser.add_argument("--run-dir", required=True, help="パイプラインの実行ディレクトリ")
    parser.add_argument("--theme", default="", help="テーマを直接指定（未指定時は themes.txt からランダム選択）")
    parser.add_argument("--script-file", default="", help="外部台本JSONファイルのパス")
    parser.add_argument("--channel", default="health", choices=["health", "creatures"],
                        help="チャンネルID")
    args = parser.parse_args()

    # Step 3-δ.5c-1: channel config 読込 (fail-closed, generator.py と同形の二段 try).
    # ensure_scripts_path は module-level (L20) で既に呼ばれているため再呼び出し不要.
    try:
        from _channel import load_channel, ChannelLoadError
    except Exception as _ce_imp:
        print(f"エラー: _channel モジュール import 失敗: {_ce_imp}")
        _sys.exit(1)
    try:
        channel = load_channel(args.channel)
    except ChannelLoadError as _ce_load:
        print(f"エラー: channel config 読込失敗 ({args.channel}): {_ce_load}")
        _sys.exit(1)

    _project_root = Path(__file__).parent.parent.parent
    _themes_path = _project_root / channel.paths.themes_file
    _output_dir = _project_root / channel.paths.output_subdir

    # Step 3-δ.5c-1: invariant guard (Codex 対立レビュー指摘).
    # CLI 経路では --run-dir の親が channel の _output_dir と一致することを
    # fail-closed で強制する. これが無いと save_script (run_dir.parent 基準)
    # とテーマ選択 (_output_dir 基準) が別ディレクトリを見る silent bug に
    # なりうる. resolve() で絶対パス化して比較.
    _run_dir_resolved = Path(args.run_dir).resolve()
    _output_dir_resolved = _output_dir.resolve()
    if _run_dir_resolved.parent != _output_dir_resolved:
        print(f"エラー: --run-dir の親 ({_run_dir_resolved.parent}) が")
        print(f"       channel '{args.channel}' の output_dir ({_output_dir_resolved}) と一致しません")
        print(f"       --run-dir は output_dir 直下の run ディレクトリを指定してください")
        _sys.exit(1)

    # --theme と --script-file の併用禁止（theme/script不整合 silent bug防止）
    if args.theme and args.script_file:
        print("エラー: --theme と --script-file は同時指定できません。")
        print("  --script-file 指定時は外部台本のtitleがthemeとして使われます。")
        _sys.exit(1)

    # 外部台本の読み込み（先に実行してthemeとの整合を取る）
    # 2026-04-09事故対策:
    #  1. 読込失敗時のAIフォールバックを削除（fail-closed）
    #  2. --script-file指定時は themes.txt からの自動選択を禁止し、外部台本のtitleをthemeに使う
    #     （以前は先にテーマ自動選択していて、外部台本の中身とthemeが食い違う silent bug）
    external_script = None
    if args.script_file:
        try:
            with open(args.script_file, encoding="utf-8") as f:
                external_script = json.load(f)
        except FileNotFoundError:
            print(f"エラー: 外部台本JSONが見つかりません: {args.script_file}")
            _sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"エラー: 外部台本JSONのパース失敗: {args.script_file}")
            print(f"  {e}")
            _sys.exit(1)
        except Exception as e:
            print(f"エラー: 外部台本JSON読込失敗: {args.script_file}")
            print(f"  {e}")
            _sys.exit(1)
        # 最低限のschema検証
        _errs = []
        if not isinstance(external_script, dict):
            _errs.append("ルートがdictでない")
        else:
            if not (external_script.get("title") or external_script.get("youtube_title")):
                _errs.append("title または youtube_title がない")
            _sections = external_script.get("sections")
            if not isinstance(_sections, list) or not _sections:
                _errs.append("sections が list でないか空")
            else:
                for _i, _sec in enumerate(_sections):
                    _lines = _sec.get("lines") if isinstance(_sec, dict) else None
                    if not isinstance(_lines, list) or not _lines:
                        _errs.append(f"sections[{_i}].lines が list でないか空")
                        break
        if _errs:
            print(f"エラー: 外部台本JSONのschema不備: {args.script_file}")
            for _e in _errs:
                print(f"  - {_e}")
            _sys.exit(1)
        print(f"外部台本JSONを読み込みました: {args.script_file}")

    # テーマ決定
    if args.theme:
        theme = args.theme
    elif external_script:
        # --script-file指定時は外部台本のtitleをthemeに使う（themes.txt自動選択はしない）
        theme = external_script.get("title") or external_script.get("youtube_title") or "外部台本"
        print(f"テーマは外部台本から取得: 「{theme}」")
    else:
        theme = _pick_theme_from_file(_themes_path, _output_dir)
        print(f"テーマを自動選択しました: 「{theme}」")

    result = run_script_gen(args.run_dir, theme, external_script)
    print(f"\n台本保存先: {result['script_path']}")
    print(f"タイトル: {result['youtube_title']}")


if __name__ == "__main__":
    main()
