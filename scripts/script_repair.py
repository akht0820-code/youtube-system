# AIの出力データ自動修復モジュール
#
# AIが返すJSONは以下の理由で壊れることがある:
#   - コードブロック・前置きテキストの混入
#   - レスポンスが途中で切れている（truncated）
#   - 必須フィールドの欠落・型の不一致
#   - キャラクター名の誤り・空テキスト
#
# このモジュールは壊れたデータを「使えるレベル」まで自動修復する。
# 修復できない場合は ValueError を送出する（呼び出し元でフォールバックに切り替える）。

import json
import re
from typing import Any

from characters import get_character_names

VALID_EMOTIONS = frozenset({
    "normal", "happy", "surprised", "serious", "worried",
    "excited", "shocked", "embarrassed", "thinking", "sad", "relieved", "angry",
    "curious", "awkward", "smug",
})


# ── JSON抽出（4段階の修復戦略）────────────────────────────

def extract_json_safe(text: str) -> Any:
    """
    AI応答テキストからJSONを抽出する。
    壊れている場合は段階的に修復を試みる。

    戦略1: コードブロック除去 → そのままパース
    戦略2: テキスト内の {...} を抽出してパース
    戦略3: テキスト内の [...] を抽出してパース（タグ等のリスト形式）
    戦略4: 末尾が切れているJSONに閉じ括弧を補完してパース
    """
    if not text or not text.strip():
        raise ValueError("AIから空のレスポンスが返りました")

    # 戦略1: コードブロック除去 → そのままパース
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = re.sub(r"```\s*", "", cleaned).strip()
    result = _try_parse(cleaned)
    if result is not None:
        return result

    # 戦略2: {...} の最外周を抽出
    m = re.search(r"\{[\s\S]*\}", cleaned)
    if m:
        result = _try_parse(m.group())
        if result is not None:
            return result

    # 戦略3: [...] の最外周を抽出
    m = re.search(r"\[[\s\S]*\]", cleaned)
    if m:
        result = _try_parse(m.group())
        if result is not None:
            return result

    # 戦略4: 末尾が切れているJSONを閉じ括弧補完で修復
    result = _try_fix_truncated(cleaned)
    if result is not None:
        _log_repair(f"JSONが途中で切れていたため閉じ括弧を補完して修復しました（{len(text)}文字）")
        return result

    raise ValueError(
        f"JSONの抽出に失敗しました（{len(text)}文字）: {text[:120]!r}"
    )


def _try_parse(text: str) -> Any:
    """JSONパースを試みる。失敗したら None を返す"""
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None


def _try_fix_truncated(text: str) -> Any:
    """
    末尾が切れたJSONに閉じ括弧を補完して修復を試みる。
    {, [ の開きと閉じの差分を数えて補完する。
    """
    start = text.find("{")
    if start == -1:
        start = text.find("[")
    if start == -1:
        return None

    fragment = text[start:]

    open_braces   = fragment.count("{") - fragment.count("}")
    open_brackets = fragment.count("[") - fragment.count("]")
    if open_braces <= 0 and open_brackets <= 0:
        return None  # 切れていない（別の理由でパース失敗）

    # 末尾の不完全なトークンを除去
    trimmed = fragment.rstrip().rstrip(",").rstrip()

    # 末尾が開きっぱなしの文字列（" の数が奇数）なら閉じる
    # ただしエスケープされた \" は除いて数える
    unescaped_quotes = len(re.findall(r'(?<!\\)"', trimmed))
    if unescaped_quotes % 2 == 1:
        trimmed += '"'

    closing = "]" * max(0, open_brackets) + "}" * max(0, open_braces)
    return _try_parse(trimmed + "\n" + closing)


# ── 構成データ修復 ────────────────────────────────────────

def repair_structure(data: Any, theme: str = "") -> dict:
    """
    構成データ（generate_structure の出力）を修復する。

    修復内容:
      - dict でない → 空 dict に変換
      - sections が存在しない/リストでない/空 → デフォルト3セクション
      - 各セクションが dict でない → 空セクションに変換
      - title キー欠落 → "セクションN" で補完
      - key_points 欠落/非リスト → 空リストで補完
    """
    repairs = []

    if not isinstance(data, dict):
        repairs.append(f"トップレベルが dict でない ({type(data).__name__}) → 空 dict に変換")
        data = {}

    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        repairs.append("sections が存在しない/空 → デフォルト3セクション構成を使用")
        data["sections"] = _default_structure_sections(theme)
    else:
        for i, sec in enumerate(sections):
            if not isinstance(sec, dict):
                data["sections"][i] = {"title": f"セクション{i + 1}", "type": "chapter", "key_points": []}
                repairs.append(f"セクション{i + 1}: dict でない → 空セクションに変換")
                continue
            if not sec.get("title"):
                sec["title"] = f"セクション{i + 1}"
                repairs.append(f"セクション{i + 1}: 'title' キー欠落 → '{sec['title']}' で補完")
            if not isinstance(sec.get("key_points"), list):
                sec["key_points"] = []
                repairs.append(f"[{sec.get('title')}]: key_points が非リスト → 空リストで補完")
            # ホワイトボード: リストでなければ空リストで補完
            wb = sec.get("whiteboard")
            if wb is not None and not isinstance(wb, list):
                sec["whiteboard"] = []
                repairs.append(f"[{sec.get('title')}]: whiteboard が非リスト → 空リストで補完")
            elif isinstance(wb, list):
                # 各項目のバリデーション
                valid_items = []
                for item in wb:
                    if isinstance(item, dict) and "text" in item:
                        item.setdefault("trigger_line", 0)
                        valid_items.append(item)
                sec["whiteboard"] = valid_items

    # whiteboard_summary のバリデーション
    ws = data.get("whiteboard_summary")
    if ws is not None and not isinstance(ws, list):
        data["whiteboard_summary"] = []
        repairs.append("whiteboard_summary が非リスト → 空リストで補完")

    _report_repairs("構成", repairs)
    return data


def _default_structure_sections(theme: str) -> list:
    label = theme or "テーマ"
    return [
        {"title": "はじめに",   "type": "intro",   "key_points": [f"{label}の概要と注目ポイント"]},
        {"title": "詳しく解説", "type": "chapter", "key_points": [f"{label}の詳細な情報"]},
        {"title": "まとめ",     "type": "summary", "key_points": ["重要ポイントのまとめ"]},
    ]


# ── 長文セリフ分割 ────────────────────────────────────────

_SPLIT_DELIMITERS = {"。", "！", "？", "、", "…"}  # 分割可能な区切り文字（順序不問）

def _split_long_line(line: dict) -> list[dict]:
    """40文字超のセリフを句読点で分割する。分割できない場合は元のまま返す。"""
    import copy
    text = line["text"]
    if len(text) <= 40:
        return [line]

    # 先頭40文字以内で区切れる最も後ろの位置を探す
    best_pos = -1
    for i in range(min(40, len(text))):
        if text[i] in _SPLIT_DELIMITERS:
            pos = i + 1
            if pos >= 5 and len(text) - pos >= 5:
                best_pos = pos

    if best_pos < 0:
        return [line]  # 分割できなかった

    line1 = copy.deepcopy(line)
    line2 = copy.deepcopy(line)
    line1["text"] = text[:best_pos].strip()
    line2["text"] = text[best_pos:].strip()
    # synthesis_text の分割: 発音補正前なら text と同一なのでそのまま同期
    # 補正済みの場合は同じ区切り位置で分割を試みる
    if "synthesis_text" in line:
        synth = line["synthesis_text"]
        if synth == text:
            line1["synthesis_text"] = line1["text"]
            line2["synthesis_text"] = line2["text"]
        else:
            # synthesis_text も同じ区切り文字で分割を試みる
            _synth_split = False
            for _si in range(min(len(synth), best_pos + 10)):
                if _si < len(synth) and synth[_si] == text[min(best_pos - 1, len(text) - 1)]:
                    line1["synthesis_text"] = synth[:_si + 1].strip()
                    line2["synthesis_text"] = synth[_si + 1:].strip()
                    _synth_split = True
                    break
            if not _synth_split:
                line1["synthesis_text"] = line1["text"]
                line2["synthesis_text"] = line2["text"]

    if not line1["text"] or not line2["text"]:
        return [line]

    # 2行目以降はvisual_hintを空にする（画像重複防止）
    line2["visual_hint"] = ""

    # 分割後もまだ40文字超なら再帰的に分割
    result = []
    for part in [line1, line2]:
        if len(part["text"]) > 40:
            result.extend(_split_long_line(part))
        else:
            result.append(part)
    return result


# ── 台本データ修復 ────────────────────────────────────────

def repair_script(data: Any, theme: str = "") -> dict:
    """
    台本データ（generate_script の出力）を修復する。

    修復内容:
      - dict でない → 空 dict に変換
      - sections が存在しない/リストでない → 空リストに初期化
      - 各セクションが dict でない → 空セクションに変換
      - 'section' キー（タイトル）欠落 → "セクションN" で補完
      - lines が欠落/非リスト → 空リストに初期化
      - 各行の character 欠落/不正 → 直前の行と交互に割り当て
      - 各行の text 欠落/空文字 → その行を削除
      - 各行の emotion 欠落/不正 → "normal" で補完
    """
    repairs = []

    if not isinstance(data, dict):
        repairs.append(f"トップレベルが dict でない ({type(data).__name__}) → 空 dict に変換")
        data = {}

    if not isinstance(data.get("sections"), list):
        repairs.append("sections が存在しないかリストでない → 空リストに初期化")
        data["sections"] = []

    valid_chars = get_character_names()
    total_kept = 0
    total_removed = 0

    for sec_idx, section in enumerate(data["sections"]):
        if not isinstance(section, dict):
            data["sections"][sec_idx] = {"section": f"セクション{sec_idx + 1}", "lines": []}
            repairs.append(f"セクション{sec_idx + 1}: dict でない → 空セクションに変換")
            continue

        # section キー（タイトル）の補完
        if not section.get("section"):
            # "title" で代替されている場合は変換する
            if section.get("title"):
                section["section"] = section["title"]
                repairs.append(f"セクション{sec_idx + 1}: 'section' キー欠落 → 'title' の値で補完")
            else:
                section["section"] = f"セクション{sec_idx + 1}"
                repairs.append(f"セクション{sec_idx + 1}: 'section' キー欠落 → '{section['section']}' で補完")

        # lines の確保
        if not isinstance(section.get("lines"), list):
            section["lines"] = []
            repairs.append(f"[{section['section']}]: lines が非リスト → 空リストに初期化")
            continue

        valid_lines = []
        last_char_idx = 0

        for line_idx, line in enumerate(section["lines"]):
            if not isinstance(line, dict):
                repairs.append(f"[{section['section']}] 行{line_idx + 1}: dict でない → スキップ")
                total_removed += 1
                continue

            # text の検証（空行は削除）
            text = line.get("text", "")
            if not isinstance(text, str) or not text.strip():
                repairs.append(f"[{section['section']}] 行{line_idx + 1}: text が空/欠落 → 行を削除")
                total_removed += 1
                continue
            line["text"] = text.strip()

            # character の修復（「両者」はハモり演出用の正規キャラクター）
            char = line.get("character", "")
            if char == "両者":
                pass  # ハモり行はそのまま通す
            elif char not in valid_chars:
                # 直前の行と異なるキャラを割り当てる
                prev_char = valid_lines[-1]["character"] if valid_lines else None
                new_char = valid_chars[(last_char_idx + 1) % len(valid_chars)] \
                    if prev_char == valid_chars[last_char_idx % len(valid_chars)] \
                    else valid_chars[last_char_idx % len(valid_chars)]
                repairs.append(
                    f"[{section['section']}] 行{line_idx + 1}: "
                    f"character={char!r} が不正 → {new_char!r} に修正"
                )
                line["character"] = new_char
            else:
                last_char_idx = valid_chars.index(line["character"])

            # emotion の補完
            if line.get("emotion") == "joyful":
                line["emotion"] = "excited"  # joyful は廃止、excited で代替
            if line.get("emotion") not in VALID_EMOTIONS:
                line["emotion"] = "normal"
            # 魔理沙に照れ顔(embarrassed)は健康解説に不適切 → 普通顔
            if line.get("character") == "魔理沙" and line.get("emotion") == "embarrassed":
                line["emotion"] = "normal"

            # 40文字超の行を自動分割（字幕途切れ防止）
            if len(line["text"]) > 40 and line.get("character") != "両者":
                _split_lines = _split_long_line(line)
                if len(_split_lines) > 1:
                    repairs.append(
                        f"[{section['section']}] 行{line_idx + 1}: "
                        f"{len(line['text'])}文字 → {len(_split_lines)}行に分割"
                    )
                    for _sl in _split_lines:
                        valid_lines.append(_sl)
                        total_kept += 1
                    continue
            valid_lines.append(line)
            total_kept += 1

        section["lines"] = valid_lines

    _report_repairs(
        "台本",
        repairs,
        extra=f"有効行: {total_kept}、削除行: {total_removed}",
    )

    # 表情ミスマッチを後処理で修正
    _fix_emotion_mismatches(data)

    return data


def _fix_emotion_mismatches(data: dict) -> None:
    """
    セリフの内容と表情が明らかにミスマッチしている行を修正する。

    ルール:
      - 医療データ・研究結果の説明中は happy/worried を normal/serious に変換
      - 「よかった」「正直」を含んでも医療データ文脈なら normal
      - 「危険」「リスク」「死亡」「注意」を含む行は worried/serious
      - 明確にポジティブな結論（「安心」「解消」「改善した」）のみ happy を許可
    """
    # 医療データ中の happy → normal に変換するトリガーワード
    _DATA_KEYWORDS = [
        "研究", "調査", "データ", "論文", "大学", "学会", "によると", "によれば",
        "リスク", "確率", "%", "倍", "万人", "症例", "統計",
        "フロス", "歯周病", "糖尿病", "癌", "がん", "血糖", "血圧", "コレステロール",
        "カロリー", "ナトリウム", "摂取", "栄養素", "成分", "含有",
    ]
    # 警告系 → worried/serious
    _WARNING_KEYWORDS = ["危険", "リスクが高", "死亡", "致死", "毒", "要注意", "やめてください"]
    # 明確なポジティブ結論（happy を維持できる）
    _POSITIVE_KEYWORDS = ["安心した", "良かった！", "やった！", "解消できる", "改善した", "最高だな"]

    fixed_count = 0
    for section in data.get("sections", []):
        for line in section.get("lines", []):
            emotion   = line.get("emotion", "normal")
            text      = line.get("text", "")
            character = line.get("character", "")

            # 警告キーワード → worried（既に serious/worried なら変えない）
            if emotion not in ("serious", "worried"):
                if any(kw in text for kw in _WARNING_KEYWORDS):
                    line["emotion"] = "worried"
                    fixed_count += 1
                    continue

            # 魔理沙が解説中に surprised/shocked → normal（役割ルール）
            if character == "魔理沙" and emotion in ("surprised", "shocked"):
                if any(kw in text for kw in _DATA_KEYWORDS + ["実はな", "研究", "大学", "によると"]):
                    line["emotion"] = "serious"
                    fixed_count += 1
                    continue

            # happy/excited の場合だけ詳細チェック
            if emotion not in ("happy", "excited"):
                continue

            # 明確ポジティブなら維持
            if any(kw in text for kw in _POSITIVE_KEYWORDS):
                continue

            # データキーワードが含まれていれば serious に変換
            if any(kw in text for kw in _DATA_KEYWORDS):
                line["emotion"] = "serious"
                fixed_count += 1
                continue

            # セリフが長め（50文字超）の説明文 → normal に変換
            if len(text) > 50:
                line["emotion"] = "normal"
                fixed_count += 1

    if fixed_count:
        print(f"  [表情補正] {fixed_count} 行の表情ミスマッチを修正しました")


# ── 検証 ─────────────────────────────────────────────────

def validate_script(script: dict, min_lines: int = 30, min_chars: int = 2000) -> tuple[bool, list[str]]:
    """
    台本データが動画生成に使えるレベルかを検証する。

    Args:
        min_lines: 最低セリフ行数（デフォルト30行。30行未満は明らかに短すぎる）
        min_chars: 最低セリフ文字数（デフォルト2000文字。2000文字未満はフォールバック対象）

    Returns:
        (is_valid, issues): 有効かどうか と 問題リスト
    """
    issues = []
    valid_chars = set(get_character_names()) | {"両者"}

    sections = script.get("sections", [])
    if not sections:
        issues.append("sections が空")
        return False, issues

    total_lines = sum(len(s.get("lines", [])) for s in sections)
    if total_lines < min_lines:
        issues.append(f"セリフ数が不足 ({total_lines} 行 < 最低 {min_lines} 行)")

    total_chars = sum(
        len(line.get("text", ""))
        for s in sections
        for line in s.get("lines", [])
    )
    if total_chars < min_chars:
        issues.append(
            f"セリフ合計文字数が不足 ({total_chars} 文字 < 最低 {min_chars} 文字。"
            f"目標: 6,000〜7,500 文字)"
        )

    for sec in sections:
        for line in sec.get("lines", []):
            if line.get("character") not in valid_chars:
                issues.append(f"不正なキャラクター: {line.get('character')!r}")
                break
            if not line.get("text", "").strip():
                issues.append("空のテキスト行が含まれている")
                break

    return len(issues) == 0, issues


# ── 内部ユーティリティ ────────────────────────────────────

def _report_repairs(label: str, repairs: list[str], extra: str = "") -> None:
    """修復内容をコンソールとログに出力する"""
    if not repairs:
        return

    suffix = f"（{extra}）" if extra else ""
    print(f"  [!] {label}データを {len(repairs)} 箇所修復しました{suffix}")
    for r in repairs[:10]:
        print(f"    - {r}")
    if len(repairs) > 10:
        print(f"    ... 他 {len(repairs) - 10} 件")

    try:
        from error_logger import log_info
        log_info(
            f"{label}修復: {len(repairs)} 箇所{(' / ' + extra) if extra else ''}\n"
            + "\n".join(f"  - {r}" for r in repairs)
        )
    except Exception:
        pass
