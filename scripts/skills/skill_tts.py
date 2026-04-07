# スキル: 音声合成（AquesTalk1）

import json
import sys
from pathlib import Path

from skills._common import (
    check_prerequisites,
    ensure_scripts_path,
    get_script_json,
    load_manifest,
    update_phase,
    SkillLogger,
)

ensure_scripts_path()

from tts import generate_audio_from_script
from notifier import notify_error


# ── メインエントリポイント ──────────────────────────────────


def run_tts(run_dir: str | Path) -> dict:
    """音声合成スキルを実行する。

    Args:
        run_dir: パイプラインの実行ディレクトリ（WAVファイルもここに保存される）

    Returns:
        {"wav_files": list[str], "count": int}
    """
    run_dir = Path(run_dir)
    logger = SkillLogger(run_dir, "tts")
    update_phase(run_dir, "tts", "in_progress")

    try:
        # 前提チェック: pronunciation が完了していればそちらを優先、
        # なければ script_gen が完了していれば実行可能
        manifest = load_manifest(run_dir)
        pron_status = manifest["phases"]["pronunciation"]["status"]
        sg_status = manifest["phases"]["script_gen"]["status"]

        if pron_status == "completed":
            pass  # 発音補正済み → OK
        elif sg_status == "completed":
            logger.log("[注意] 発音補正フェーズ未実行。script_gen の出力をそのまま使用します")
        else:
            raise RuntimeError(
                "前提フェーズが未完了です（pronunciation または script_gen が必要）"
            )

        # 台本JSONを読み込む
        script = get_script_json(run_dir)

        logger.log("【音声合成】音声を生成しています...")

        # 音声生成（audio_dir = run_dir そのもの）
        audio_dir = run_dir
        logger.log(f"音声を生成しています → {audio_dir}")
        saved = generate_audio_from_script(script, audio_dir)

        wav_files = [p.name for p in saved]
        logger.log(f"{len(saved)} 件の音声ファイルを保存しました")

        # パイプライン状態を更新
        update_phase(run_dir, "tts", "completed", outputs=wav_files)

        result = {
            "wav_files": wav_files,
            "count": len(saved),
        }
        logger.log("音声合成スキル完了")
        return result

    except Exception as e:
        update_phase(run_dir, "tts", "failed", error=str(e))
        notify_error("音声合成", e)
        raise


# ── CLI ──────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="音声合成スキル")
    parser.add_argument("--run-dir", required=True, help="パイプラインの実行ディレクトリ")
    args = parser.parse_args()

    result = run_tts(args.run_dir)
    print(f"\n生成ファイル数: {result['count']}")
    for wav in result["wav_files"]:
        print(f"  {wav}")


if __name__ == "__main__":
    main()
