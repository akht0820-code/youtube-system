# スキル: 効果音(SE)割り当て — Gemini Proが台本の各セリフにSEを判定

import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from skills._common import (
    check_prerequisites,
    ensure_scripts_path,
    get_llm,
    get_script_json,
    call_with_retry,
    load_manifest,
    update_phase,
    save_manifest,
    SkillLogger,
)

ensure_scripts_path()
import model_config

ASSETS_SE = Path(__file__).resolve().parent.parent.parent / "assets" / "se"
SE_CATALOG_PATH = ASSETS_SE / "se_catalog.json"

# SE音量（メインの音声に対する比率）
SE_VOLUME = 0.35


def _load_catalog() -> dict:
    """se_catalog.json を読み込む"""
    if not SE_CATALOG_PATH.exists():
        return {}
    return json.loads(SE_CATALOG_PATH.read_text(encoding="utf-8"))


def _build_catalog_summary(catalog: dict) -> str:
    """AIに渡すカタログ概要を構築する"""
    lines = []
    by_cat: dict[str, list[str]] = {}
    for se_id, info in catalog.items():
        cat = info["category"]
        by_cat.setdefault(cat, []).append(f'{se_id} ({info["description"]})')
    for cat, items in sorted(by_cat.items()):
        lines.append(f"## {cat}")
        for item in items:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def _resolve_se_id(se_id: str, catalog: dict) -> str | None:
    """SE IDをカタログから解決する。見つからなければNone"""
    if se_id in catalog:
        return se_id
    # カテゴリ名だけ指定された場合、そのカテゴリからランダム選択
    matching = [k for k in catalog if k.startswith(se_id + "/") or catalog[k]["category"] == se_id]
    return random.choice(matching) if matching else None


def _validate_se_assignments(assignments: list[dict], catalog: dict, total_lines: int,
                             section_boundaries: "set[int] | None" = None) -> list[dict]:
    """SE割り当て結果をバリデーションする（七ヶ条 Rule 5）

    - 存在しないSE IDを除去
    - offset/pause/comboフィールドを検証・保持
    - 連続SE（4行以内に連続）を間引き（セクション境界ではリセット）
    - SE過多（全体の15%超）を間引き
    - pause/comboの使用数を制限
    """
    _sec_bounds = section_boundaries or set()
    valid_offsets = {"start", "reaction", "end"}
    valid = []
    for a in assignments:
        if not isinstance(a, dict):
            continue
        se_id = a.get("se", "")
        line_idx = a.get("line", -1)
        if not isinstance(line_idx, int) or line_idx < 0:
            continue
        resolved = _resolve_se_id(se_id, catalog)
        if not resolved:
            continue

        entry = {"line": line_idx, "se": resolved}

        # offset検証
        offset = a.get("offset", "start")
        if offset in valid_offsets:
            entry["offset"] = offset

        # pause検証（0.1〜0.5秒に制限）
        pause = a.get("pause")
        if isinstance(pause, (int, float)) and 0.1 <= pause <= 0.5:
            entry["pause"] = round(float(pause), 1)

        # combo検証（2音目のSE）
        combo = a.get("combo", "")
        if combo:
            combo_resolved = _resolve_se_id(combo, catalog)
            if combo_resolved:
                entry["combo"] = combo_resolved
                delay = a.get("combo_delay", 1.0)
                if isinstance(delay, (int, float)) and 0.5 <= delay <= 3.0:
                    entry["combo_delay"] = round(float(delay), 1)
                else:
                    entry["combo_delay"] = 1.0

        valid.append(entry)

    # 連続SE間引き: 4行以内に連続していたら後のものを削除（セクション境界ではリセット）
    valid.sort(key=lambda x: x["line"])
    filtered = []
    last_line = -999
    for a in valid:
        # セクション境界をまたぐ場合は間隔制限をリセット
        if a["line"] in _sec_bounds:
            last_line = -999
        if a["line"] - last_line <= 4:
            continue
        filtered.append(a)
        last_line = a["line"]

    # SE過多チェック: 全体の15%を超えたら削除
    max_se = max(4, int(total_lines * 0.15))
    if len(filtered) > max_se:
        filtered = filtered[:max_se]

    # pause使用数を制限（最大5箇所）
    pause_count = sum(1 for a in filtered if "pause" in a)
    if pause_count > 5:
        removed = 0
        for a in reversed(filtered):
            if removed >= pause_count - 5:
                break
            if "pause" in a:
                del a["pause"]
                removed += 1

    # combo使用数を制限（最大2箇所）
    combo_count = sum(1 for a in filtered if "combo" in a)
    if combo_count > 2:
        removed = 0
        for a in reversed(filtered):
            if removed >= combo_count - 2:
                break
            if "combo" in a:
                del a["combo"]
                del a["combo_delay"]
                removed += 1

    return filtered


def assign_se(script: dict, logger: SkillLogger) -> dict:
    """Gemini ProにSE割り当てを判定させる。

    台本の各セリフを渡し、バラエティ番組の音効マンのように
    適切な効果音を選択させる。

    Returns: {global_line_idx: "se_id", ...}
    """
    catalog = _load_catalog()
    if not catalog:
        logger.log("[SE] カタログが空です。scripts/download_se.py を実行してください。")
        return {}

    catalog_summary = _build_catalog_summary(catalog)

    # 全セリフを収集
    all_lines = []
    section_boundaries: set[int] = set()
    for section in script.get("sections", []):
        sec_title = section.get("section", section.get("title", ""))
        sec_type = section.get("type", "")
        section_boundaries.add(len(all_lines))  # セクション先頭行を記録
        for line in section.get("lines", []):
            all_lines.append({
                "idx": len(all_lines),
                "character": line.get("character", ""),
                "text": line.get("text", ""),
                "emotion": line.get("emotion", "normal"),
                "line_type": line.get("line_type", ""),
                "section": sec_title,
                "section_type": sec_type,
            })

    if not all_lines:
        return {}

    # 40行バッチで処理
    llm = get_llm()
    batch_size = 40
    all_assignments = []

    for batch_start in range(0, len(all_lines), batch_size):
        batch = all_lines[batch_start:batch_start + batch_size]
        lines_text = "\n".join(
            f'{l["idx"]}. [{l["character"]}]({l["emotion"]}/{l["line_type"]}) {l["text"][:60]}'
            for l in batch
        )

        prompt = (
            "あなたはゆっくり解説動画の音効担当です。\n"
            "以下の台本に効果音(SE)を付けてください。\n\n"
            "## 最重要ルール: SEは最小限\n"
            "SEは「ここぞ」という場面だけに絞ること。多すぎるSEは視聴者にとってうるさく逆効果。\n"
            "迷ったらSEを付けないこと。静寂も演出の一部。\n\n"
            "## SEを付けるべき場面（これ以外は付けない）\n"
            "- セクション冒頭の場面転換 → transition系（1セクション1回まで）\n"
            "- 視聴者が本当に驚く衝撃データの提示 → serious系（1セクション最大1回）\n"
            "- 霊夢の大きなリアクション（「ええ！？」等、本当に驚く場面のみ）→ surprised系\n"
            "- ボケ・ツッコミのオチ（最も面白い瞬間だけ）→ funny系\n"
            "- 動画の結論・最も重要なメッセージ → positive系\n"
            "- 感動的なクライマックス → emotional系\n\n"
            "## SEを付けてはいけない場面\n"
            "- 淡々とした解説・説明の途中\n"
            "- 軽い相槌（「へー」「なるほど」「そうなんだ」）\n"
            "- 小さな驚き（本当の衝撃ではないリアクション）\n"
            "- 質問や確認（「それってどういうこと？」等）\n\n"
            "## セクション別のSE数ガイドライン\n"
            "- intro(導入): 目標0〜1個（最大2個）— 掴みの1発だけ\n"
            "- chapter(本題): 目標1〜2個（最大3個）— 本当に重要なポイントだけ\n"
            "- summary(まとめ): 目標0〜1個 — 締めの1発だけ\n\n"
            "## SEのタイミング指定\n"
            "offsetフィールドでSEの鳴るタイミングを指定できます:\n"
            '- "start": セリフ開始と同時（デフォルト）\n'
            '- "reaction": セリフ中の驚きポイント（「え！？」「うそ！」等）の直前。0.3秒前に鳴る\n'
            '- "end": セリフ終わりに鳴る（余韻・締め演出に）\n\n'
            "## SE後の「間」\n"
            "特に衝撃的な場面では、pauseフィールドで次のセリフ前の無音時間を指定できます:\n"
            "- 通常は指定不要（pauseなし）\n"
            "- 衝撃の事実、ランキング発表、重大な警告 → pause: 0.3〜0.5\n"
            "- 1動画あたり最大3〜5箇所に限定（使いすぎると逆効果）\n\n"
            "## 連鎖SE（2音コンボ）\n"
            "ランキング1位の発表や最大の衝撃ポイントでは、前兆音+衝撃音の2段構えが使えます:\n"
            '- comboフィールドに2音目のSE ID、combo_delayに秒数を指定\n'
            "- 例: ゴゴゴゴ(1.5秒) → ドーン！\n"
            "- 1動画あたり最大1〜2箇所に限定（ここぞという場面だけ）\n\n"
            f"## 使用可能なSE一覧\n{catalog_summary}\n\n"
            f"## 台本\n{lines_text}\n\n"
            "## 出力形式\n"
            "SEを付ける行だけJSON配列で返してください。\n"
            '[{"line": 行番号, "se": "カテゴリ/ID"'
            ', "offset": "start|reaction|end"'
            ', "pause": 0.0〜0.5（省略可）'
            ', "combo": "カテゴリ/ID"（省略可）'
            ', "combo_delay": 秒数（省略可）}]\n'
            "SEが不要な場合は空配列 [] を返してください。"
        )

        try:
            raw = call_with_retry(
                llm.generate, prompt, model_config.QUALITY,
                label=f"SE割り当て(行{batch_start}-{batch_start + len(batch)})"
            )
            from script_repair import extract_json_safe
            result = extract_json_safe(raw)
            if isinstance(result, list):
                all_assignments.extend(result)
        except Exception as e:
            logger.error(f"SE割り当て失敗(行{batch_start}-): {e}")

    # バリデーション（七ヶ条 Rule 5）
    validated = _validate_se_assignments(all_assignments, catalog, len(all_lines), section_boundaries)
    logger.log(f"[SE] AI判定: {len(all_assignments)}件 → バリデーション後: {len(validated)}件 / 全{len(all_lines)}行")

    # {line_idx: SE情報dict} のマップに変換
    se_map = {}
    for a in validated:
        entry = {"se": a["se"]}
        if a.get("offset", "start") != "start":
            entry["offset"] = a["offset"]
        if "pause" in a:
            entry["pause"] = a["pause"]
        if "combo" in a:
            entry["combo"] = a["combo"]
            entry["combo_delay"] = a.get("combo_delay", 1.0)
        se_map[a["line"]] = entry
        # ログ出力
        desc = catalog.get(a["se"], {}).get("description", "")
        extras = []
        if entry.get("offset"):
            extras.append(f"offset={entry['offset']}")
        if entry.get("pause"):
            extras.append(f"pause={entry['pause']}s")
        if entry.get("combo"):
            combo_desc = catalog.get(entry["combo"], {}).get("description", "")
            extras.append(f"combo={entry['combo']}({combo_desc})")
        extra_str = f" [{', '.join(extras)}]" if extras else ""
        logger.log(f"  行{a['line']}: {a['se']} ({desc}){extra_str}")

    return se_map


def run_se_assign(run_dir: str | Path) -> dict:
    """SE割り当てスキルを実行する"""
    run_dir = Path(run_dir)
    logger = SkillLogger(run_dir, "se_assign")
    logger.log("=== SE割り当て開始 ===")

    try:
        update_phase(run_dir, "se_assign", "in_progress")
        script = get_script_json(run_dir)
        se_map = assign_se(script, logger)

        # 台本JSONにSE情報を書き込む
        manifest = load_manifest(run_dir)
        script_outputs = manifest["phases"]["script_gen"].get("outputs", [])
        script_path = None
        for out in script_outputs:
            p = run_dir.parent / out if not Path(out).is_absolute() else Path(out)
            if p.exists():
                script_path = p
                break

        if script_path and se_map:
            script_data = json.loads(script_path.read_text(encoding="utf-8"))
            idx = 0
            for section in script_data.get("sections", []):
                for line in section.get("lines", []):
                    if idx in se_map:
                        se_entry = se_map[idx]
                        line["se"] = se_entry["se"]
                        if se_entry.get("offset"):
                            line["se_offset"] = se_entry["offset"]
                        if se_entry.get("pause"):
                            line["se_pause"] = se_entry["pause"]
                        if se_entry.get("combo"):
                            line["se_combo"] = se_entry["combo"]
                            line["se_combo_delay"] = se_entry.get("combo_delay", 1.0)
                    idx += 1
            script_path.write_text(
                json.dumps(script_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.log(f"台本JSONにSE情報を書き込みました ({len(se_map)}件)")

        # SE割り当て結果を保存
        se_result_path = run_dir / "se_assignments.json"
        se_result_path.write_text(
            json.dumps(se_map, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        logger.log(f"=== SE割り当て完了: {len(se_map)}件 ===")
        update_phase(run_dir, "se_assign", "completed", outputs=["se_assignments.json"])
        return {"se_count": len(se_map), "se_map": se_map}

    except Exception as e:
        logger.error(f"SE割り当てエラー: {e}")
        update_phase(run_dir, "se_assign", "failed", error=str(e))
        return {"se_count": 0, "se_map": {}}


# ── CLI ──

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="SE割り当てスキル")
    parser.add_argument("--run-dir", required=True, help="パイプラインの実行ディレクトリ")
    args = parser.parse_args()
    result = run_se_assign(args.run_dir)
    print(f"SE割り当て: {result['se_count']}件")
