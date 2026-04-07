# スキル: 発音補正（静的辞書＋AI読みチェック＋AquesTalk事前検査）

import hashlib
import json
import os
import sys
from pathlib import Path

from skills._common import (
    check_prerequisites,
    ensure_scripts_path,
    get_llm,
    load_manifest,
    save_manifest,
    update_phase,
    SkillLogger,
)

ensure_scripts_path()

import re
import model_config
from pronunciation import apply_dict_to_script
from notifier import notify_error

# 読み間違いリスク検出パターン
_RAW_DIGIT_RE = re.compile(r"\d+")                  # 生の数字
_RAW_ALPHA_RE = re.compile(r"[A-Za-z]{2,}")          # 英字2文字以上


# ── ヘルパー ──────────────────────────────────────────────


def _get_script_path(run_dir: Path) -> Path:
    """pipeline.json の script_gen outputs から台本JSONのパスを特定する"""
    manifest = load_manifest(run_dir)
    outputs = manifest["phases"]["script_gen"].get("outputs", [])
    for out in outputs:
        path = run_dir.parent / out if not Path(out).is_absolute() else Path(out)
        if path.exists():
            return path
    # フォールバック: run_dir の親にある .json を探す
    for p in run_dir.parent.glob(f"{run_dir.name.split('_')[0]}*.json"):
        return p
    raise FileNotFoundError(f"台本JSONが見つかりません: {run_dir}")


def _compute_config_hashes() -> dict[str, str]:
    """発音関連設定ファイルのMD5ハッシュを計算する（キャッシュ無効化用）"""
    scripts_dir = Path(__file__).parent.parent
    hashes = {}
    for filename in ("pronunciation.py", "aquestalk_dict.txt"):
        filepath = scripts_dir / filename
        if filepath.exists():
            content = filepath.read_bytes()
            hashes[filename] = hashlib.md5(content).hexdigest()
    return hashes


def _fugashi_to_hira(text: str) -> str:
    """fugashiでテキストをひらがなに変換する（AquesTalkパイプラインと同じ結果を再現）"""
    try:
        from tts_aquestalk import (
            _apply_reading_fixes, _particle_fix, _normalize_symbols,
            _normalize_numbers, _kanji_to_hira,
        )
        # 順序はtts_aquestalk.synthesize()と同一にすること
        text = _particle_fix(text)       # 漢字テキストで助詞を正確に検出
        text = _apply_reading_fixes(text)
        text = _normalize_symbols(text)
        text = _normalize_numbers(text)
        text = _kanji_to_hira(text)
        return text
    except ImportError:
        return ""


# ── AI記号・単位・略語展開（いたちごっこ防止の根本対策）──────────

# 展開対象を検出する正規表現（日本語以外の文字を含む行を抽出）
_NON_JP_RE = re.compile(
    r"[%℃°&=+/①-⑩]"          # 記号
    r"|[A-Za-z]{1,}"             # 英字（略語・単位）
    r"|\d+[A-Za-z%℃°]"          # 数字+単位（12%, 38℃, 100g 等）
)


def _ai_expand_non_japanese(
    script: dict, llm, model: str, logger: SkillLogger,
) -> tuple[dict, int]:
    """Gemini Proで記号・単位・英略語を日本語読みに展開する。

    いたちごっこの個別パターン追加ではなく、AIが文脈を理解して
    全ての非日本語テキストを適切な読みに変換する包括的な安全網。

    例:
    - "12%"    → "12パーセント"
    - "38℃"   → "38度"
    - "DHA"    → "ディーエイチエー"
    - "100g"   → "100グラム"
    - "WHO"    → "ダブリューエイチオー"
    """
    from script_repair import extract_json_safe

    # 展開が必要な行を収集
    targets: list[dict] = []
    line_idx = 0
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            synth = line.get("synthesis_text") or line.get("text", "")
            if _NON_JP_RE.search(synth):
                targets.append({
                    "id": line_idx,
                    "character": line.get("character", "?"),
                    "text": synth,
                })
            line_idx += 1

    if not targets:
        logger.log("[記号展開] 展開対象なし")
        return script, 0

    logger.log(f"[記号展開] {len(targets)}行に非日本語文字を検出 → Gemini Proで展開")

    all_fixes: list[dict] = []
    batch_size = 40
    for batch_start in range(0, len(targets), batch_size):
        batch = targets[batch_start:batch_start + batch_size]
        lines_text = "\n".join(
            f'{t["id"]}. [{t["character"]}] {t["text"]}' for t in batch
        )

        prompt = (
            "以下のゆっくり解説動画の台本に、音声合成エンジンが読めない文字が含まれています。\n"
            "**記号・単位・英略語を日本語の読みに置き換えてください。**\n\n"
            "## ルール\n"
            "- 数字はそのまま残す（数字の読みは別の処理で行う）\n"
            "- 記号・単位は日本語カタカナ/ひらがなに変換:\n"
            "  % → パーセント、℃/°C → 度、g → グラム、mg → ミリグラム\n"
            "  kg → キログラム、cm → センチ、km → キロ、kcal → キロカロリー\n"
            "  ml → ミリリットル、L → リットル、dB → デシベル\n"
            "- 英略語は文脈に応じて:\n"
            "  DNA → ディーエヌエー、WHO → ダブリューエイチオー\n"
            "  DHA → ディーエイチエー、pH → ピーエイチ\n"
            "  RPG/BMIなど一般的な略語はそのままカタカナ読み\n"
            "- 矢印 → は「から」、/ は「と」に変換\n"
            "- 丸数字 ①②③ は「第一、第二、第三、」に変換\n"
            "- 全角記号（％＋＝：等）は半角にしてから変換\n"
            "- 変更不要な行は含めないこと\n"
            "- 元のテキストの意味を変えないこと\n\n"
            f"## 台本\n{lines_text}\n\n"
            "## 出力形式\n"
            "変更が必要な行だけJSON配列で返してください。\n"
            '[{"id": 行番号, "text": "変換後のテキスト全文"}]\n'
            "- textにはセリフ本文のみを入れること（[霊夢]等のキャラ名は含めない）\n"
            "- 行番号やキャラ名のプレフィックスは絶対に含めないこと\n"
            "変更不要な場合は空配列 [] を返してください。"
        )

        try:
            from skills._common import call_with_retry
            raw = call_with_retry(
                llm.generate, prompt, model,
                label=f"記号展開(行{batch_start}-{batch_start + len(batch)})"
            )
            result = extract_json_safe(raw)
            if isinstance(result, list):
                all_fixes.extend(result)
        except Exception as e:
            logger.error(f"記号展開失敗(行{batch_start}-): {e}")

    if not all_fixes:
        logger.log("[記号展開] AIチェック完了: 変換不要")
        return script, 0

    # 修正を適用（AIが[キャラ名]プレフィックスを付けてしまった場合を除去）
    _PREFIX_RE = re.compile(r"^\[(?:霊夢|魔理沙|両者)\]\s*")
    fixes_by_id: dict[int, str] = {}
    for fix in all_fixes:
        if isinstance(fix, dict) and "id" in fix and "text" in fix:
            clean_text = _PREFIX_RE.sub("", fix["text"])
            fixes_by_id[int(fix["id"])] = clean_text

    fix_count = 0
    line_idx = 0
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            if line_idx in fixes_by_id:
                old = line.get("synthesis_text") or line.get("text", "")
                new = fixes_by_id[line_idx]
                if old != new:
                    line["synthesis_text"] = new
                    logger.log(f"  展開: {old[:50]} → {new[:50]}")
                    fix_count += 1
            line_idx += 1

    logger.log(f"[記号展開] {fix_count}行を展開しました")
    return script, fix_count


def _ai_reading_check(
    script: dict, llm, model: str, logger: SkillLogger,
) -> tuple[dict, int]:
    """上位モデルで読み間違い検出+会話の自然さを一括検証する。

    synthesis_textをfugashiでひらがな化し、キャラクター情報と共に
    上位モデルに渡して、人間らしい判断で全ての読み問題を検出・修正する。

    チェック観点:
    - 音読み/訓読みの誤り、促音便・連濁の不自然さ
    - 助詞「は」「へ」の誤変換
    - 英字・略語が読みに変換されず残っている箇所
    - TPO（場面・文脈に応じた読み替え）
    - キャラクターの口調に合った読み方
    """
    from script_repair import extract_json_safe

    try:
        import fugashi
    except ImportError:
        logger.log("[AI読み検証] fugashi未インストール → スキップ")
        return script, 0

    # 全行のキャラクター+テキスト+ひらがなを収集
    entries: list[dict] = []
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            synth = line.get("synthesis_text", "")
            if not synth:
                continue
            hira = _fugashi_to_hira(synth)
            if hira:
                entries.append({
                    "id": len(entries),
                    "character": line.get("character", "?"),
                    "text": line.get("text", ""),
                    "synthesis": synth,
                    "reading": hira,
                })

    if not entries:
        return script, 0

    all_fixes: list[dict] = []
    batch_size = 40
    for i in range(0, len(entries), batch_size):
        batch = entries[i:i + batch_size]
        lines = []
        for e in batch:
            lines.append(f'{e["id"]}. [{e["character"]}] {e["text"]}')
            lines.append(f'   読み: {e["reading"]}')
        batch_text = "\n".join(lines)

        prompt = (
            "あなたは日本語ネイティブの視聴者です。\n"
            "ゆっくり解説動画（霊夢と魔理沙の掛け合い）を聞いています。\n"
            "以下の各セリフが音声で読み上げられたとき、「読み」の通りに聞こえます。\n"
            "聞いていて**明らかにおかしい・違和感がある**箇所だけを指摘してください。\n\n"
            "## キャラクター\n"
            "- 魔理沙: 一人称「おれ」、フランクな男口調（だぜ、なんだ等）\n"
            "- 霊夢: 一人称「わたし」、女性的な口調（よ、わ、なの等）\n\n"
            "## セリフと読み\n" + batch_text + "\n\n"
            "## 判断基準\n"
            "あなたが動画を聞いていて「ん？今の読み方おかしくない？」と思うものを報告。\n"
            "具体的に気になるパターン:\n"
            "- 漢字の読み間違い（「私」を「わたくし」、「一歩」を「いちほ」等）\n"
            "- 英字がそのまま残っている（RPG等→読み方を提案）\n"
            "- 文脈と合わない読み（「3日坊主」を「さんにちぼうず」等）\n"
            "- 漢字の音読み/訓読みの取り違え（特に頻出パターン）:\n"
            "  「間」: いつの間に→まに(○) あいだに(×) / 人間→にんげん(○)\n"
            "  「年」: 年のせい→としのせい(○) ねんのせい(×) / 年齢→ねんれい(○)\n"
            "  「下」: 下げる→さげる(○) / 以下→いか(○)\n"
            "  「行」: 行う→おこなう(○) いく(×) / 銀行→ぎんこう(○)\n"
            "  「何」: 何か→なにか(○) なんか(△) / 何故→なぜ(○)\n"
            "- 日常会話で普通に使う読み方と異なる場合は必ず報告すること\n\n"
            "## 助詞「は」「へ」について（重要）\n"
            "読みの中で助詞の「は」は「わ」、「へ」は「え」に変換済みです。\n"
            "これは音声合成エンジンの仕様上の正しい処理であり、修正不要です。\n"
            "例: 「じつわ」(実は)、「それわ」(それは) → これらは正しい。報告しないこと。\n"
            "※「○○派」の「は」は漢字の読みであり助詞ではない。「こつこつは」が正しい\n\n"
            "## 小数点の読みについて（重要）\n"
            "小数の「てん」の前に長音・促音便が入るのは自然な日本語の読み方です。修正不要。\n"
            "- にいてんご(2.5)、ごおてんご(5.5) → 長音挿入で正しい。「にてんご」「ごてんご」に直さないこと\n"
            "- いってん(1.)、はってん(8.)、じゅってん(10.) → 促音便で正しい\n"
            "- さんてん(3.)、よんてん(4.)、ろくてん(6.)、ななてん(7.) → そのままで正しい\n\n"
            "## 重要\n"
            "- 技術的に正しいかではなく、**聞いて自然かどうか**で判断する\n"
            "- 助詞の「は→わ」「へ→え」変換だけは報告しない（これは正しい処理）\n"
            "- それ以外の読み違和感は積極的に報告する。見逃しは誤読として視聴者に届く\n"
            "- 問題なければ空配列 [] を返す\n"
            "- JSONの配列形式のみ（前置き不要）\n\n"
            "## 出力形式\n"
            '[{"id": 行番号, "word": "該当箇所", "wrong": "現在の読み", '
            '"correct": "自然な読み", "reason": "理由（10字以内）"}]'
        )

        try:
            raw = llm.generate(prompt, model)
            fixes = extract_json_safe(raw)
            if isinstance(fixes, list):
                all_fixes.extend(fixes)
        except Exception as e:
            logger.log(f"[AI読み検証] AI呼び出し失敗: {e}")

    if not all_fixes:
        logger.log("[AI読み検証] 上位モデル検証完了: 問題なし")
        return script, 0

    # 修正を適用
    fixes_by_id: dict[int, list[dict]] = {}
    for fix in all_fixes:
        if isinstance(fix, dict) and fix.get("word") and fix.get("correct"):
            fid = fix.get("id", -1)
            fixes_by_id.setdefault(fid, []).append(fix)
            reason = fix.get("reason", "")
            logger.log(
                f"  自然さ修正: [{entries[fid]['character'] if isinstance(fid, int) and fid < len(entries) else '?'}] "
                f"「{fix['word']}」{fix.get('wrong', '?')} → {fix['correct']}"
                f" ({reason})"
            )

    fix_count = 0
    line_idx = 0
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            synth = line.get("synthesis_text", "")
            if not synth:
                continue
            if line_idx in fixes_by_id:
                new_synth = synth
                for fix in fixes_by_id[line_idx]:
                    new_synth = new_synth.replace(fix["word"], fix["correct"], 1)
                if new_synth != synth:
                    line["synthesis_text"] = new_synth
                    fix_count += 1
            line_idx += 1

    logger.log(f"[AI読み検証] {len(all_fixes)} 件修正 ({fix_count} 行)")

    # 学習蓄積: AI が検出した修正パターンを lessons.md に記録（再発防止）
    if all_fixes:
        _record_reading_fixes(all_fixes, logger)

    return script, fix_count


def _record_reading_fixes(fixes: list[dict], logger: SkillLogger) -> None:
    """AIが検出した誤読パターンを tasks/lessons.md に蓄積する。"""
    lessons_path = Path(__file__).resolve().parent.parent.parent / "tasks" / "lessons.md"
    if not lessons_path.exists():
        return
    try:
        content = lessons_path.read_text(encoding="utf-8")
        new_entries = []
        for fix in fixes:
            word = fix.get("word", "")
            correct = fix.get("correct", "")
            if not word or not correct:
                continue
            # 既に lessons.md に記載済みなら重複追加しない
            if word in content:
                continue
            new_entries.append(f"- 誤読検出: 「{word}」→「{correct}」({fix.get('reason', '')})")
        if new_entries:
            addition = "\n".join(new_entries) + "\n"
            content = content.rstrip() + "\n" + addition
            lessons_path.write_text(content, encoding="utf-8")
            logger.log(f"[学習蓄積] {len(new_entries)} 件の誤読パターンを lessons.md に記録")
    except Exception as e:
        logger.log(f"[学習蓄積] lessons.md 書き込み失敗: {e}")


def _validate_synthesis_text(script: dict, logger: SkillLogger) -> int:
    """synthesis_text に残った生の数字・英字を検出して警告する。

    Returns:
        検出したリスク箇所の合計数
    """
    risks: list[str] = []

    for section in script.get("sections", []):
        for line in section.get("lines", []):
            synth = line.get("synthesis_text", "")
            if not synth:
                continue

            line_num = line.get("line_number", "?")
            char = line.get("character", "?")

            for m in _RAW_DIGIT_RE.finditer(synth):
                risks.append(
                    f"  数字残存 [{char} L{line_num}]: "
                    f"「{m.group()}」← {synth[:40]}"
                )

            for m in _RAW_ALPHA_RE.finditer(synth):
                risks.append(
                    f"  英字残存 [{char} L{line_num}]: "
                    f"「{m.group()}」← {synth[:40]}"
                )

    if risks:
        logger.log(f"[残存リスク] {len(risks)} 件:")
        for r in risks[:20]:
            logger.log(r)
        if len(risks) > 20:
            logger.log(f"  ... 他 {len(risks) - 20} 件")
    else:
        logger.log("[残存リスク] なし")

    return len(risks)


# ── メインエントリポイント ──────────────────────────────────


def run_pronunciation(run_dir: str | Path) -> dict:
    """発音補正スキルを実行する。

    Args:
        run_dir: パイプラインの実行ディレクトリ

    Returns:
        {"dict_count": int, "ai_count": int, "aquestalk_fixes": int}
    """
    run_dir = Path(run_dir)
    logger = SkillLogger(run_dir, "pronunciation")
    update_phase(run_dir, "pronunciation", "in_progress")

    try:
        # 前提チェック
        if not check_prerequisites(run_dir, "pronunciation", ["script_gen"]):
            raise RuntimeError("前提フェーズ 'script_gen' が未完了です")

        # 台本JSONを読み込む
        script_path = _get_script_path(run_dir)
        script = json.loads(script_path.read_text(encoding="utf-8"))

        # ── Step1: 静的辞書補正+数字正規化 ──
        logger.log("【発音補正】を実行しています...")
        script, dict_count = apply_dict_to_script(script)
        if dict_count > 0:
            logger.log(f"  → 静的辞書+数字正規化: {dict_count} 行を補正しました")
        else:
            logger.log("  → 静的辞書: 置換対象なし")

        # ── Step1.5: AI記号・単位・略語展開（Gemini Proが包括的に変換）──
        llm = get_llm()
        script, expand_count = _ai_expand_non_japanese(script, llm, model_config.QUALITY, logger)

        # ── Step2: AI読み検証（誤読検出+英字変換+会話自然さを一括検証）──
        script, verify_count = _ai_reading_check(script, llm, model_config.QUALITY, logger)

        # ── Step4: AquesTalk事前チェック（AquesTalk使用時のみ）──
        aquestalk_fixes = 0
        if os.environ.get("TTS_PROVIDER", "aquestalk").lower() == "aquestalk":
            try:
                from check_synthesis import check_script
                # 先に補正済みスクリプトを保存（check_scriptがファイルを読み直すため）
                with open(script_path, "w", encoding="utf-8") as f:
                    json.dump(script, f, ensure_ascii=False, indent=2)
                issues = check_script(script_path, fix=True, show_dict=False)
                if issues:
                    # 修正済み JSON を再読み込み
                    script = json.loads(script_path.read_text(encoding="utf-8"))
                    aquestalk_fixes = issues
                    logger.log(f"[音声チェック] {issues} 行を自動修正しました")
                else:
                    logger.log("[音声チェック] 全行OK")
            except Exception as e:
                logger.log(f"[音声チェック] スキップ: {e}")

        # ── Step5: 残存リスク検出（数字・英字の最終チェック）──
        risk_count = _validate_synthesis_text(script, logger)

        # 台本JSONを保存（AquesTalkパスで既に保存済みの場合も最終版で上書き）
        with open(script_path, "w", encoding="utf-8") as f:
            json.dump(script, f, ensure_ascii=False, indent=2)
        logger.log(f"補正済み台本を保存しました: {script_path}")

        # 設定ハッシュをpipeline.jsonに保存（キャッシュ無効化用）
        config_hashes = _compute_config_hashes()
        manifest = load_manifest(run_dir)
        manifest["phases"]["pronunciation"]["config_hashes"] = config_hashes
        save_manifest(run_dir, manifest)

        # パイプライン状態を更新
        update_phase(run_dir, "pronunciation", "completed", outputs=[script_path.name])

        result = {
            "dict_count": dict_count,
            "expand_count": expand_count,
            "verify_count": verify_count,
            "aquestalk_fixes": aquestalk_fixes,
        }
        logger.log("発音補正スキル完了")
        return result

    except Exception as e:
        update_phase(run_dir, "pronunciation", "failed", error=str(e))
        notify_error("発音補正", e)
        raise


# ── CLI ──────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="発音補正スキル")
    parser.add_argument("--run-dir", required=True, help="パイプラインの実行ディレクトリ")
    args = parser.parse_args()

    result = run_pronunciation(args.run_dir)
    print(f"\n静的辞書+数字: {result['dict_count']} 行")
    print(f"AI読み検証: {result['verify_count']} 行修正")
    print(f"AquesTalk修正: {result['aquestalk_fixes']} 行")


if __name__ == "__main__":
    main()
