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

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

# フォールバック用デフォルト構成
_FALLBACK_STRUCTURE = {
    "sections": [
        {"title": "はじめに",   "type": "intro",   "key_points": ["テーマの概要を紹介します"]},
        {"title": "詳しく解説", "type": "chapter", "key_points": ["メインの内容を説明します"]},
        {"title": "まとめ",     "type": "summary", "key_points": ["重要なポイントをまとめます"]},
    ]
}

_MIN_SCRIPT_CHARS = 6000  # これ未満なら再生成
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


def generate_structure(theme: str) -> dict:
    """テーマから動画構成を生成（ナラティブスタイルをランダム選択）"""
    llm = get_llm()
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
        structure["_narrative_style"] = style["key"]   # 後工程で参照できるよう保持
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


def generate_comedy_design(theme: str, structure: dict) -> dict | None:
    """テーマ・構成から笑いのネタを事前設計する（台本生成の前に呼ぶ）"""
    llm = get_llm()
    print("笑いのネタを設計しています...")
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

# 霊夢セリフの男性語尾 → 女性語尾の置換ルール（文末パターン）
_REIMU_MASCULINE_FIXES = [
    (r"だぜ([！？。…]*)\s*$", r"だわ\1"),
    (r"なんだぜ", "なんだわ"),
    (r"ってことだぜ", "ってことだわ"),
    (r"だろ([！？。…]*)\s*$", r"でしょ\1"),
    (r"だぞ([！？。…]*)\s*$", r"だわよ\1"),
    (r"覚えておけよ", "覚えておいてね"),
    (r"教えてやる", "教えてあげる"),
]


def _align_text_to_character(text: str, target_char: str) -> str:
    """character変更時にテキストの一人称・語尾・呼び方を同期修正する。

    character を入れ替えたら必ずこの関数でテキストも修正すること。
    これにより「魔理沙なのに『わよ』」「霊夢なのに『だぜ』」を防ぐ。
    """
    if target_char == "魔理沙":
        # 一人称: 私 → 俺
        text = re.sub(r"私(?![\u4e00-\u9fff])", "俺", text)
        # 語尾: 女性語尾 → 男性語尾
        for pat, repl in _MARISA_FEMININE_FIXES:
            text = re.sub(pat, repl, text)
    elif target_char == "霊夢":
        # 一人称: 俺 → 私
        text = re.sub(r"俺(?![\u4e00-\u9fff])", "私", text)
        # 語尾: 男性語尾 → 女性語尾
        for pat, repl in _REIMU_MASCULINE_FIXES:
            text = re.sub(pat, repl, text)
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



def _fix_role_violations(script: dict) -> tuple[dict, int]:
    """台本生成直後にテキスト・表情の口調逸脱を修正する。

    修正内容（キャラクター名は変更しない）:
    1. 呼び方修正: 魔理沙が「君」→「お前」に置換
    2. 一人称修正: 魔理沙が「私」→「俺」/ 霊夢が「俺」→「私」
    3. 魔理沙の女性語尾修正: 「だわ」→「だぜ」等
    4. 表情修正: 魔理沙に embarrassed → normal に強制

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
            if line.get("character") == "魔理沙":
                new_text = re.sub(r"君([のはがをもにだ、。！？])", r"お前\1", text)
                new_text = re.sub(r"あなたたち", "みんな", new_text)
                new_text = re.sub(r"あなた([のはがをもにだ、。！？])", r"みんな\1", new_text)
                if new_text != text:
                    line["text"] = new_text
                    if "synthesis_text" in line:
                        line["synthesis_text"] = re.sub(
                            r"君([のはがをもにだ、。！？])", r"お前\1",
                            line["synthesis_text"],
                        )
                        line["synthesis_text"] = re.sub(
                            r"あなたたち", "みんな",
                            line["synthesis_text"],
                        )
                        line["synthesis_text"] = re.sub(
                            r"あなた([のはがをもにだ、。！？])", r"みんな\1",
                            line["synthesis_text"],
                        )
                    text = new_text
                    modified = True

            # ── 一人称修正 ──
            if line.get("character") == "魔理沙":
                # 魔理沙が「私」→「俺」
                # blocklist方式: 私+漢字（私立・私服等の熟語）以外は全て置換
                new_text = re.sub(r"私(?![\u4e00-\u9fff])", "俺", text)
                if new_text != text:
                    line["text"] = new_text
                    if "synthesis_text" in line:
                        line["synthesis_text"] = re.sub(
                            r"私(?![\u4e00-\u9fff])", "俺",
                            line["synthesis_text"],
                        )
                    text = new_text
                    modified = True

            elif line.get("character") == "霊夢":
                # 霊夢が「俺」→「私」
                new_text = re.sub(r"俺(?![\u4e00-\u9fff])", "私", text)
                if new_text != text:
                    line["text"] = new_text
                    if "synthesis_text" in line:
                        line["synthesis_text"] = re.sub(
                            r"俺(?![\u4e00-\u9fff])", "私",
                            line["synthesis_text"],
                        )
                    modified = True

            # ── 魔理沙の女性語尾修正 ──
            if line.get("character") == "魔理沙":
                new_text = text
                for pat, repl in _MARISA_FEMININE_FIXES:
                    new_text = re.sub(pat, repl, new_text)
                if new_text != text:
                    line["text"] = new_text
                    if "synthesis_text" in line:
                        for pat, repl in _MARISA_FEMININE_FIXES:
                            line["synthesis_text"] = re.sub(
                                pat, repl, line["synthesis_text"],
                            )
                    text = new_text
                    modified = True

            # ── 霊夢の男性語尾修正 ──
            if line.get("character") == "霊夢":
                new_text = text
                for pat, repl in _REIMU_MASCULINE_FIXES:
                    new_text = re.sub(pat, repl, new_text)
                if new_text != text:
                    line["text"] = new_text
                    if "synthesis_text" in line:
                        for pat, repl in _REIMU_MASCULINE_FIXES:
                            line["synthesis_text"] = re.sub(
                                pat, repl, line["synthesis_text"],
                            )
                    text = new_text
                    modified = True

            # ── 魔理沙の表情修正: embarrassed → normal ──
            if line.get("character") == "魔理沙":
                if line.get("emotion") == "embarrassed":
                    line["emotion"] = "normal"
                    modified = True

            if modified:
                fixed += 1

    return script, fixed




# ── 決定論的バリデーション ──────────────────────────────────────────

# 霊夢のセリフに出現したら違反（魔理沙の口調）
_MARISA_SPEECH_PATTERNS = [
    (re.compile(r"だぜ[！？。…!?.]*\s*$"), 1.0, "「だぜ」は魔理沙専用の語尾"),
    (re.compile(r"なんだぜ"), 1.0, "「なんだぜ」は魔理沙専用"),
    (re.compile(r"ってことだぜ"), 1.0, "「ってことだぜ」は魔理沙専用"),
    (re.compile(r"覚えておけよ"), 0.95, "教える側の口調"),
    (re.compile(r"教えてやる"), 0.95, "解説役の口調"),
]

# 魔理沙のセリフに出現したら違反（霊夢の口調）— confidence低めで慎重に
_REIMU_SPEECH_PATTERNS = [
    (re.compile(r"知らなかった[！!]"), 0.7, "聞き手のリアクション"),
    (re.compile(r"そうなの[？?]"), 0.7, "聞き手の確認"),
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
        if char == "霊夢":
            for pat, conf, reason in _MARISA_SPEECH_PATTERNS:
                if pat.search(text):
                    violations.append({
                        "global_idx": i,
                        "check_type": "speech_pattern",
                        "character": char,
                        "detail": f"霊夢のセリフに魔理沙の口調: {reason}",
                        "confidence": conf,
                    })
                    break  # 1行につき最初のマッチのみ
        elif char == "魔理沙":
            for pat, conf, reason in _REIMU_SPEECH_PATTERNS:
                if pat.search(text):
                    violations.append({
                        "global_idx": i,
                        "check_type": "speech_pattern",
                        "character": char,
                        "detail": f"魔理沙のセリフに霊夢の口調: {reason}",
                        "confidence": conf,
                    })
                    break

        # ── チェック4: 名前呼び ──
        if char == "霊夢" and re.search(r"霊夢[、,！!？?…　 ]", text):
            violations.append({
                "global_idx": i,
                "check_type": "name_call",
                "character": char,
                "detail": "霊夢のセリフで「霊夢」と呼びかけている（魔理沙のセリフ）",
                "confidence": 0.95,
            })
        elif char == "魔理沙" and re.search(r"魔理沙[、,！!？?…　 ]", text):
            violations.append({
                "global_idx": i,
                "check_type": "name_call",
                "character": char,
                "detail": "魔理沙のセリフで「魔理沙」と呼びかけている（霊夢のセリフ）",
                "confidence": 0.95,
            })

        # ── チェック5: 一人称 ──
        if char == "魔理沙" and re.search(r"私(?![\u4e00-\u9fff])", text):
            violations.append({
                "global_idx": i,
                "check_type": "pronoun",
                "character": char,
                "detail": "魔理沙が一人称「私」を使用（「俺」が正しい）",
                "confidence": 0.95,
            })
        elif char == "霊夢" and re.search(r"俺(?![\u4e00-\u9fff])", text):
            violations.append({
                "global_idx": i,
                "check_type": "pronoun",
                "character": char,
                "detail": "霊夢が一人称「俺」を使用（「私」が正しい）",
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
                    comedy_design: dict | None = None) -> dict:
    """構成から台本を生成（文字数不足時は最大2回再生成）"""
    llm = get_llm()
    print("台本を生成しています...")
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
            prompt = base_prompt + f"\n\n【緊急指示】前回の生成は {prev_chars} 文字しかなかった。今回は必ず 6,500 文字以上になるよう、各セクションを大幅に拡充して出力すること。特に各章を最低40行以上にすること。"
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
        if total_chars >= _MIN_SCRIPT_CHARS:
            script = candidate
            break
        print(f"  → {total_chars} 文字（目標 {_MIN_SCRIPT_CHARS} 文字未満）")
        prev_chars = total_chars

        # 3回目でも不足の場合、既存台本を膨らませる
        if attempt >= 3 and total_chars < _MIN_SCRIPT_CHARS:
            print(f"  → 3回とも文字数不足。既存台本を拡充します...")
            expand_prompt = (
                f"以下のJSON台本はセリフ合計が{total_chars}文字しかありません。\n"
                f"目標は6,500〜8,000文字です。あと{_MIN_SCRIPT_CHARS - total_chars}文字以上足りません。\n\n"
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
            if expanded_chars < _MIN_SCRIPT_CHARS:
                # 拡充後も不足なら fail-closed（3000〜5999字で通してた穴を塞ぐ）
                raise RuntimeError(
                    f"拡充後も文字数不足(フォールバック禁止): "
                    f"{expanded_chars}文字 < {_MIN_SCRIPT_CHARS}文字"
                )
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

    # 文字数チェック
    total_chars = _count_script_chars(script)
    print(f"  → セリフ合計文字数: {total_chars} 文字", end="")
    if total_chars < _MIN_SCRIPT_CHARS:
        est_min = total_chars / 400
        print(f" [不足] 目標 {_MIN_SCRIPT_CHARS}〜{_MAX_SCRIPT_CHARS} 文字、推定尺: 約{est_min:.0f}分")
        # Codex Round5: 文字数不足は notify_error だけで通していたが fail-closed 化
        notify_error("台本文字数不足", ValueError(f"セリフ合計 {total_chars} 文字（目標 {_MIN_SCRIPT_CHARS}〜{_MAX_SCRIPT_CHARS}）"))
        raise RuntimeError(
            f"台本文字数不足(フォールバック禁止): {total_chars}文字 < {_MIN_SCRIPT_CHARS}文字"
        )
    elif total_chars > _MAX_SCRIPT_CHARS:
        est_min = total_chars / 400
        print(f" [超過] 目標 {_MIN_SCRIPT_CHARS}〜{_MAX_SCRIPT_CHARS} 文字、推定尺: 約{est_min:.0f}分")
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
            notify_error(
                "台本最終品質ゲート残存違反",
                ValueError(f"{len(non_consec)} 件の非連続違反"),
            )
            raise RuntimeError(
                f"台本最終品質ゲートに非連続違反 {len(non_consec)} 件(フォールバック禁止)"
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
            for field in ("text", "synthesis_text"):
                val = line.get(field)
                if val and _STAGE_DIR_RE.search(val):
                    line[field] = _STAGE_DIR_RE.sub("", val).strip()

    # Codex Round5: 注釈除去後に再度文字数を検証（strip で MIN 割れを検知）
    post_strip_chars = _count_script_chars(script)
    if post_strip_chars < _MIN_SCRIPT_CHARS:
        raise RuntimeError(
            f"ト書き除去後に文字数不足(フォールバック禁止): "
            f"{post_strip_chars}文字 < {_MIN_SCRIPT_CHARS}文字"
        )

    return script, raw_sections


def save_script(theme: str, script: dict) -> Path:
    """台本をJSONファイルとして保存"""
    OUTPUT_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # ファイル名に使えない文字を除去
    safe_theme = re.sub(r'[\\/:*?"<>|]', "", theme)[:30]
    filename = f"{timestamp}_{safe_theme}.json"

    output_path = OUTPUT_DIR / filename
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    return output_path


def _pick_theme_from_file() -> str:
    """themes.txt からランダムにテーマを1つ選ぶ（output/ で使用済みのテーマは除外）"""
    themes_path = Path(__file__).parent.parent.parent / "themes.txt"
    if not themes_path.exists():
        raise FileNotFoundError("themes.txt が見つかりません")
    lines = [l.strip() for l in themes_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        raise ValueError("themes.txt にテーマが入っていません")

    # output/ のサブディレクトリ名から使用済み safe_theme を取得
    used: set[str] = set()
    try:
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir() and re.match(r"\d{8}_\d{6}_", d.name):
                used.add(d.name[16:])
    except Exception:
        pass  # OUTPUT_DIR が読めなくてもテーマ選択は続行

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
    logger = SkillLogger(run_dir, "script_gen")
    update_phase(run_dir, "script_gen", "in_progress")

    try:
        # ── フェーズ1: タイトル + 構成を並列生成 ─────────────
        logger.log("【フェーズ1】タイトル・構成を並列生成しています...")
        structure = None
        with ThreadPoolExecutor(max_workers=2) as ex:
            ft = ex.submit(generate_title, theme)
            fs = ex.submit(generate_structure, theme)

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
                comedy_design = generate_comedy_design(theme, structure)
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
                script, raw_sections = generate_script(theme, structure, comedy_design=comedy_design)
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
        _total_chars = _count_script_chars(script)
        _FATAL_THRESHOLD = 3000  # この文字数未満は明らかに失敗
        if _total_chars < _FATAL_THRESHOLD:
            _msg = f"台本が致命的に短い: {_total_chars}文字（最低{_FATAL_THRESHOLD}文字）。API障害の可能性。"
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
            output_path = save_script(theme, script)
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
    args = parser.parse_args()

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
        theme = _pick_theme_from_file()
        print(f"テーマを自動選択しました: 「{theme}」")

    result = run_script_gen(args.run_dir, theme, external_script)
    print(f"\n台本保存先: {result['script_path']}")
    print(f"タイトル: {result['youtube_title']}")


if __name__ == "__main__":
    main()
