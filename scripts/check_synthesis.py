# check_synthesis.py — 台本の音声合成テキストを事前チェック・修正する
#
# 使い方:
#   python check_synthesis.py <script.json>          # チェックのみ（レポート出力）
#   python check_synthesis.py <script.json> --fix    # 問題行に synthesis_text を書き込む
#   python check_synthesis.py <script.json> --dict   # 未辞書語を aquestalk_dict.txt に追記候補として出力
#
# チェック内容:
#   - 残存漢字: pykakasi が読めなかった語 → 辞書登録が必要
#   - 残存数字: 数字変換漏れ
#   - 空テキスト: クリーン後に空になる行 → 音声なし
#   - 文頭ん: AquesTalk1 が処理できない（自動変換済みだが確認用）
#   - 極端に短い: 元テキストと比較して情報が欠落している可能性

from __future__ import annotations
import sys
import re
import json
import unicodedata
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(Path(__file__).parent))

from tts_aquestalk import (
    _apply_reading_fixes,
    _normalize_numbers,
    _kanji_to_hira,
    _clean_for_aquestalk,
    _DICT_PATTERNS,
)

# ── 問題検出パターン ─────────────────────────────────────────────────────

_RE_KANJI   = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")   # 残存漢字
_RE_DIGITS  = re.compile(r"\d")                               # 残存数字
_RE_KANA    = re.compile(r"[^\u3041-\u3093\u30a0-\u30fa\u30fc、。\s]")  # 非かなカタカナ


def _run_pipeline(text: str) -> str:
    """TTS パイプラインを実行して AquesTalk1 向けテキストを返す"""
    return _clean_for_aquestalk(
        _kanji_to_hira(
            _normalize_numbers(
                _apply_reading_fixes(text)
            )
        )
    )


def _detect_issues(original: str, aq_text: str) -> list[str]:
    """問題点のリストを返す（空リスト = OK）"""
    issues = []

    # 残存漢字（pykakasi 変換漏れ → 音声から脱落）
    remaining_kanji = _RE_KANJI.findall(aq_text)
    if remaining_kanji:
        issues.append(f"残存漢字: {''.join(set(remaining_kanji))}")

    # 残存数字（数字変換漏れ）
    remaining_digits = _RE_DIGITS.findall(aq_text)
    if remaining_digits:
        issues.append(f"残存数字: {''.join(remaining_digits)}")

    # 空テキスト
    body = aq_text.replace("。", "").replace("、", "").strip()
    if not body:
        issues.append("空テキスト: 音声が生成されません")
        return issues

    # 文頭ん（現在は自動変換済みだが念のため）
    if aq_text.startswith("ん"):
        issues.append("文頭ん: AquesTalk1 処理不可（要確認）")

    # 極端な短縮（元テキストの 1/3 以下）
    orig_len = len(original.replace(" ", ""))
    aq_len   = len(body)
    if orig_len > 5 and aq_len < orig_len * 0.33:
        issues.append(f"極端な短縮: 元{orig_len}字→{aq_len}字（情報欠落の可能性）")

    return issues


# pykakasi が誤読しやすいとわかっている文字を含む語はハイライト
_RISKY_KANJI = frozenset("毛人日下上大道月火水木金土生死出入目口手足耳鼻声音")


def _extract_words_with_readings(text: str) -> list[tuple[str, str, bool]]:
    """
    テキストからpykakasiがトークナイズした語とその読みを返す。

    Returns:
        list of (orig_word, pykakasi_reading, is_in_dict)
    """
    from tts_aquestalk import _get_kakasi
    kks = _get_kakasi()

    # 辞書登録済み語のセット（高速検索用）
    dict_words = {p.pattern.replace("\\", "") for p, _ in _DICT_PATTERNS}

    results = []
    for item in kks.convert(text):
        orig = item.get("orig", "")
        hira = item.get("hira", "") or orig
        # 漢字を含む語のみ対象
        if not re.search(r"[\u4e00-\u9fff]", orig):
            continue
        # 辞書登録済みか判定
        in_dict = orig in dict_words
        results.append((orig, hira, in_dict))
    return results


def check_script(script_path: Path, fix: bool = False, show_dict: bool = False) -> int:
    """
    スクリプト JSON を検査する。

    Returns:
        問題のある行数（0 = 全OK）
    """
    data = json.loads(script_path.read_text(encoding="utf-8"))
    title = data.get("title", script_path.name)
    print(f"\n{'='*60}")
    print(f" 台本チェック: {title}")
    print(f"{'='*60}")

    issues_found = 0
    line_num = 0
    undicted_words: list[str] = []
    modified = False

    for section in data.get("sections", []):
        for line in section.get("lines", []):
            line_num += 1
            char = line.get("character", "?")
            text = line.get("synthesis_text") or line.get("text", "")

            aq_text = _run_pipeline(text)
            issues = _detect_issues(text, aq_text)

            if issues:
                issues_found += 1
                print(f"\n[{line_num:03d}] {char}: {text[:50]}{'…' if len(text)>50 else ''}")
                print(f"      AQ : {aq_text}")
                for issue in issues:
                    print(f"      [!] {issue}")

                if fix:
                    # synthesis_text に AQ 向けテキスト（パイプライン出力前の段階）を書き込む
                    # クリーン前テキストを保存することで、誤読を手動確認しやすくする
                    pre_clean = _kanji_to_hira(_normalize_numbers(_apply_reading_fixes(text)))
                    line["synthesis_text"] = pre_clean
                    modified = True
                    print(f"      FIX: synthesis_text を更新: {pre_clean[:60]}")

            # (show_dict は後でまとめて処理)

    print(f"\n{'─'*60}")
    if issues_found == 0:
        print(f" [OK] 全 {line_num} 行 問題なし")
    else:
        print(f" 問題あり: {issues_found} / {line_num} 行")

    if fix and modified:
        script_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f" 修正済み JSON を保存しました: {script_path}")

    if show_dict:
        # 台本全行から pykakasi の読みを収集（辞書未登録語のみ）
        seen: dict[str, str] = {}  # orig → reading
        risky: set[str] = set()
        all_texts = [
            line.get("synthesis_text") or line.get("text", "")
            for section in data.get("sections", [])
            for line in section.get("lines", [])
        ]
        for t in all_texts:
            for orig, hira, in_dict in _extract_words_with_readings(t):
                if not in_dict and orig not in seen:
                    seen[orig] = hira
                    if any(c in _RISKY_KANJI for c in orig):
                        risky.add(orig)

        if seen:
            print(f"\n{'─'*60}")
            print(" pykakasi 読み確認リスト（辞書未登録語）")
            print(" * = 誤読リスクが高い文字を含む語")
            print(f" {'語':<12} {'pykakasi読み':<20} {'辞書追加コマンド例'}")
            print(f" {'─'*11} {'─'*19} {'─'*30}")
            for orig in sorted(seen, key=lambda w: (w not in risky, len(w)), reverse=False):
                hira = seen[orig]
                mark = "*" if orig in risky else " "
                print(f" {mark} {orig:<11} {hira:<20}   {orig}\t{hira}")
            print()
            print(" ※ 読みが間違っている語は aquestalk_dict.txt に追記してください")
            print("   フォーマット: 語<TAB>正しい読み")
            print("   例: 換毛<TAB>かんもう")

    print()
    return issues_found


def main():
    import argparse
    parser = argparse.ArgumentParser(description="台本の音声合成テキストをチェック・修正する")
    parser.add_argument("script", help="台本 JSON ファイルのパス")
    parser.add_argument("--fix",  action="store_true", help="問題行の synthesis_text を自動修正")
    parser.add_argument("--dict", action="store_true", help="辞書未登録語を表示する")
    args = parser.parse_args()

    script_path = Path(args.script)
    if not script_path.exists():
        print(f"エラー: ファイルが見つかりません: {script_path}")
        sys.exit(1)

    issues = check_script(script_path, fix=args.fix, show_dict=args.dict)
    sys.exit(0 if issues == 0 else 1)


if __name__ == "__main__":
    main()
