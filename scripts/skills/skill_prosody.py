# スキル: プロソディ（抑揚）割り当て — Gemini Proが台本の各セリフに声の高さ・速さ・音量を判定
#
# PROSODY_ENABLED=false で即座に無効化可能（.env）

import json
import os
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
    SkillLogger,
)

ensure_scripts_path()
import model_config

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent.parent / ".env")

# プロソディ有効/無効トグル（.envで制御）
PROSODY_ENABLED = os.getenv("PROSODY_ENABLED", "true").lower() == "true"

# パラメータ安全範囲
_SPEED_MIN, _SPEED_MAX = 0.93, 1.10
_PITCH_MIN, _PITCH_MAX = -2.0, 3.0
_VOLUME_MIN, _VOLUME_MAX = -3.0, 4.0


# 魔理沙はベース速度が速いため、speed変化を最小限に抑える
_MARISA_SPEED_MIN, _MARISA_SPEED_MAX = 0.93, 1.03


def _validate_prosody(assignments: list[dict], total_lines: int,
                      line_characters: dict[int, str] | None = None) -> list[dict]:
    """プロソディ割り当てをバリデーションする（七ヶ条 Rule 5）

    - 値域クリップ（キャラクター別）
    - 「両者」行を除外
    - 同じ値が4行以上連続したらリセット（単調防止）
    - 変化のある行が全体の60%以下であること
    """
    if line_characters is None:
        line_characters = {}

    valid = []
    for a in assignments:
        if not isinstance(a, dict):
            continue
        line_idx = a.get("line", -1)
        if not isinstance(line_idx, int) or line_idx < 0:
            continue

        speed = a.get("speed", 1.0)
        pitch = a.get("pitch", 0.0)
        volume = a.get("volume", 0.0)

        # 型チェック
        try:
            speed = float(speed)
            pitch = float(pitch)
            volume = float(volume)
        except (TypeError, ValueError):
            continue

        # キャラクター別の速度範囲
        char = line_characters.get(line_idx, "")
        if char == "魔理沙":
            speed = max(_MARISA_SPEED_MIN, min(_MARISA_SPEED_MAX, speed))
        else:
            speed = max(_SPEED_MIN, min(_SPEED_MAX, speed))
        pitch = max(_PITCH_MIN, min(_PITCH_MAX, pitch))
        volume = max(_VOLUME_MIN, min(_VOLUME_MAX, volume))

        # ほぼデフォルトなら省略（ノイズ除去）
        is_default = (abs(speed - 1.0) < 0.03 and abs(pitch) < 0.3 and abs(volume) < 0.5)
        if is_default:
            continue

        valid.append({
            "line": line_idx,
            "speed": round(speed, 2),
            "pitch": round(pitch, 1),
            "volume": round(volume, 1),
        })

    # 行番号順にソート
    valid.sort(key=lambda x: x["line"])

    # 同じspeed値が4行連続したらリセット（単調防止）
    filtered = []
    streak_speed = None
    streak_count = 0
    for a in valid:
        if a["speed"] == streak_speed:
            streak_count += 1
        else:
            streak_speed = a["speed"]
            streak_count = 1
        if streak_count >= 4:
            continue  # 単調な連続を間引き
        filtered.append(a)

    # 変化行が全体の60%を超えたら上位60%に絞る
    max_prosody = max(4, int(total_lines * 0.60))
    if len(filtered) > max_prosody:
        filtered = filtered[:max_prosody]

    return filtered


def assign_prosody(script: dict, logger: SkillLogger) -> dict:
    """Gemini Proにプロソディ（抑揚）を判定させる。

    Returns: {global_line_idx: {"speed": float, "pitch": float, "volume": float}, ...}
    """
    if not PROSODY_ENABLED:
        logger.log("[プロソディ] PROSODY_ENABLED=false のためスキップ")
        return {}

    # 全セリフを収集
    all_lines = []
    for section in script.get("sections", []):
        sec_title = section.get("section", section.get("title", ""))
        for line in section.get("lines", []):
            all_lines.append({
                "idx": len(all_lines),
                "character": line.get("character", ""),
                "text": line.get("text", ""),
                "emotion": line.get("emotion", "normal"),
                "line_type": line.get("line_type", ""),
                "section": sec_title,
            })

    if not all_lines:
        return {}

    # 両者行のインデックスを記録（プロソディ対象外）
    ryousha_indices = {l["idx"] for l in all_lines if l["character"] == "両者"}

    llm = get_llm()
    batch_size = 40
    all_assignments = []

    for batch_start in range(0, len(all_lines), batch_size):
        batch = all_lines[batch_start:batch_start + batch_size]
        # 両者行を除外
        batch_filtered = [l for l in batch if l["idx"] not in ryousha_indices]
        if not batch_filtered:
            continue

        lines_text = "\n".join(
            f'{l["idx"]}. [{l["character"]}]({l["emotion"]}) {l["text"][:80]}'
            for l in batch_filtered
        )

        prompt = (
            "あなたはゆっくり解説動画の音声ディレクターです。\n"
            "以下の台本に発話の抑揚（プロソディ）を付けてください。\n\n"
            "## パラメータ\n"
            "- speed: 話速の倍率。1.0=標準。0.90(ゆっくり)〜1.10(早口)\n"
            "- pitch: 声の高さ(半音)。0=標準。-2(低い)〜+3(高い)\n"
            "- volume: 音量(dB)。0=標準。-3(小声)〜+4(大声)\n\n"
            "## ディレクション方針\n"
            "- 解説の「普通」の行はデフォルト(1.0/0/0)のまま。変えない\n"
            "- 変化を付けるのは全体の30〜50%程度。メリハリが命\n"
            "- 驚き・衝撃リアクション → やや速い(1.05〜1.10) + 高め(+1〜+2) + 大きめ(+2〜+3)\n"
            "- 深刻な警告・注意喚起 → ゆっくり(0.92〜0.95) + やや低め(-1) + 少し大きめ(+1)\n"
            "- 希望・ポジティブ・解決策 → やや速い(1.03〜1.08) + 高め(+1〜+2) + やや大きめ(+1〜+2)\n"
            "- ボケ・ツッコミ・ユーモア → 速い(1.06〜1.10) + 高め(+2〜+3) + 大きめ(+2〜+3)\n"
            "- ささやき・不安・恐怖 → 遅い(0.90〜0.93) + 低め(-1〜-2) + 小さめ(-2〜-3)\n"
            "- 重要な結論・まとめ → やや遅い(0.93〜0.96) + 標準(0) + やや大きめ(+1)\n"
            "- 霊夢（聞き手）: リアクションを大きく。驚き・感嘆を豊かに表現\n"
            "- 魔理沙（解説役）: 解説はデフォルト、衝撃的な事実提示は強調。speed変化は最小限(0.93〜1.03)に抑えること\n"
            "- 同じパラメータを連続で使わない。バリエーションを出すこと\n"
            "- デフォルトのままにする行は含めないこと\n\n"
            f"## 台本\n{lines_text}\n\n"
            "## 出力形式\n"
            "変化を付ける行だけJSON配列で返してください。\n"
            '[{"line": 行番号, "speed": 1.08, "pitch": 1.5, "volume": 2.0}]\n'
            "全てデフォルトの場合は空配列 [] を返してください。"
        )

        try:
            raw = call_with_retry(
                llm.generate, prompt, model_config.QUALITY,
                label=f"プロソディ(行{batch_start}-{batch_start + len(batch)})"
            )
            from script_repair import extract_json_safe
            result = extract_json_safe(raw)
            if isinstance(result, list):
                all_assignments.extend(result)
        except Exception as e:
            logger.error(f"プロソディ割り当て失敗(行{batch_start}-): {e}")

    # キャラクター別速度制限用マップ
    line_characters = {l["idx"]: l["character"] for l in all_lines}

    # バリデーション
    validated = _validate_prosody(all_assignments, len(all_lines), line_characters)
    logger.log(
        f"[プロソディ] AI判定: {len(all_assignments)}件 → "
        f"バリデーション後: {len(validated)}件 / 全{len(all_lines)}行"
    )

    # {line_idx: {speed, pitch, volume}} のマップに変換
    prosody_map = {}
    for a in validated:
        prosody_map[a["line"]] = {
            "speed": a["speed"],
            "pitch": a["pitch"],
            "volume": a["volume"],
        }
        logger.log(
            f"  行{a['line']}: speed={a['speed']}, "
            f"pitch={a['pitch']:+.1f}st, volume={a['volume']:+.1f}dB"
        )

    return prosody_map


def run_prosody(run_dir: str | Path) -> dict:
    """プロソディ割り当てスキルを実行する"""
    run_dir = Path(run_dir)
    logger = SkillLogger(run_dir, "prosody")
    logger.log("=== プロソディ割り当て開始 ===")

    try:
        update_phase(run_dir, "prosody", "in_progress")
        script = get_script_json(run_dir)
        prosody_map = assign_prosody(script, logger)

        if not prosody_map:
            logger.log("=== プロソディ割り当て完了: 0件（デフォルト使用）===")
            update_phase(run_dir, "prosody", "completed")
            return {"prosody_count": 0, "prosody_map": {}}

        # 台本JSONにプロソディ情報を書き込む
        manifest = load_manifest(run_dir)
        script_outputs = manifest["phases"]["script_gen"].get("outputs", [])
        script_path = None
        for out in script_outputs:
            p = run_dir.parent / out if not Path(out).is_absolute() else Path(out)
            if p.exists():
                script_path = p
                break

        if script_path and prosody_map:
            script_data = json.loads(script_path.read_text(encoding="utf-8"))
            idx = 0
            for section in script_data.get("sections", []):
                for line in section.get("lines", []):
                    if idx in prosody_map:
                        line["prosody"] = prosody_map[idx]
                    idx += 1
            script_path.write_text(
                json.dumps(script_data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.log(f"台本JSONにプロソディ情報を書き込みました ({len(prosody_map)}件)")

        logger.log(f"=== プロソディ割り当て完了: {len(prosody_map)}件 ===")
        update_phase(run_dir, "prosody", "completed")
        return {"prosody_count": len(prosody_map), "prosody_map": prosody_map}

    except Exception as e:
        logger.error(f"プロソディエラー: {e}")
        update_phase(run_dir, "prosody", "failed", error=str(e))
        return {"prosody_count": 0, "prosody_map": {}}


# ── CLI ──

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="プロソディ割り当てスキル")
    parser.add_argument("--run-dir", required=True, help="パイプラインの実行ディレクトリ")
    args = parser.parse_args()
    result = run_prosody(args.run_dir)
    print(f"プロソディ割り当て: {result['prosody_count']}件")
