# スキル: 動画生成（ffmpeg合成 + YMM4プロジェクト出力）

import json
import os
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

from video_builder import build_video, get_bgm_credit
from ymmp_generator import build_ymmp
from notifier import notify_error

# Step 3-δ.5c-2: OUTPUT_DIR module-level 定数は削除.
# invariant: run_dir.parent == output_dir (generator._create_run_dir で保証).
# run_video_build は run_dir から output_dir を導出し build_ymmp に渡す.


def _fmt_ts(seconds: float) -> str:
    """秒数を M:SS 形式に変換する（例: 65.3 → '1:05'）"""
    m = int(seconds) // 60
    s = int(seconds) % 60
    return f"{m}:{s:02d}"


def _update_timestamps(
    run_dir: Path,
    script: dict,
    section_timestamps: list[float],
    total_duration: float,
    logger: SkillLogger,
) -> None:
    """metadata.json の説明文内タイムスタンプを実際の動画尺に基づいて更新する。

    バリデーション: タイムスタンプが動画尺を超えていたらエラーログを出力してブロック。
    """
    import re as _re

    meta_path = run_dir / "metadata.json"
    if not meta_path.exists():
        return

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    desc = meta.get("description", "")
    if "■目次" not in desc:
        return

    sections = script.get("sections", [])
    if len(section_timestamps) != len(sections):
        logger.log(f"[目次更新] セクション数不一致 ({len(section_timestamps)} vs {len(sections)}) → スキップ")
        return

    # バリデーション: 最終セクションのタイムスタンプが動画尺を超えていないか
    for i, ts in enumerate(section_timestamps):
        if ts > total_duration:
            logger.log(
                f"[目次更新] エラー: セクション{i+1}のタイムスタンプ({_fmt_ts(ts)})が"
                f"動画尺({_fmt_ts(total_duration)})を超えています"
            )
            return

    # 既存の ■目次 ブロックを抽出
    toc_match = _re.search(r"■目次\n(.*?)(?=\n\n|\n■|\Z)", desc, _re.DOTALL)
    if not toc_match:
        return

    old_toc = toc_match.group(0)

    # 新しいタイムスタンプで目次行を再構築
    # 既存の目次から章タイトルを抽出（タイムスタンプ部分を除去）
    old_lines = old_toc.split("\n")[1:]  # ■目次 の行を除く
    new_toc_lines = ["■目次"]

    for i, (ts, sec) in enumerate(zip(section_timestamps, sections)):
        ts_str = _fmt_ts(ts)
        # 既存の章タイトルがあればそれを使う（AI生成の良いタイトルを保持）
        if i < len(old_lines):
            old_line = old_lines[i].strip()
            # タイムスタンプ部分を除去して章タイトルだけ取得
            title_match = _re.match(r"\d+:\d+\s+(.*)", old_line)
            if title_match:
                title = title_match.group(1)
                new_toc_lines.append(f"{ts_str} {title}")
                continue
        # フォールバック: セクション名を使う
        sec_title = sec.get("title", sec.get("section", f"セクション{i+1}"))
        new_toc_lines.append(f"{ts_str} {sec_title}")

    new_toc = "\n".join(new_toc_lines)
    desc = desc.replace(old_toc, new_toc)
    meta["description"] = desc
    meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    logger.log(
        f"[目次更新] タイムスタンプを実際の動画尺({_fmt_ts(total_duration)})に基づいて更新しました"
    )
    for line in new_toc_lines[1:]:
        logger.log(f"  {line}")


# ── メインエントリポイント ──────────────────────────────────


def run_video_build(run_dir: str | Path) -> dict:
    """動画生成スキルを実行する。

    Args:
        run_dir: パイプラインの実行ディレクトリ（WAVファイルが格納されている）

    Returns:
        {"video_path": str, "ymmp_path": str|None}
    """
    run_dir = Path(run_dir)
    # Step 3-δ.5c-2: invariant `run_dir.parent == output_dir` を本 Step でも維持.
    output_dir = run_dir.parent
    logger = SkillLogger(run_dir, "video_build")
    update_phase(run_dir, "video_build", "in_progress")

    try:
        # 前提チェック: tts が完了していること
        if not check_prerequisites(run_dir, "video_build", ["tts"]):
            raise RuntimeError("前提フェーズ 'tts' が未完了です")

        # 台本JSONを読み込む
        script = get_script_json(run_dir)

        # パスの決定
        # audio_dir = run_dir（TTS スキルが run_dir に WAV を保存している）
        audio_dir = run_dir

        # 台本JSONファイルのパスを取得して .mp4 に変換
        manifest = load_manifest(run_dir)
        script_outputs = manifest["phases"]["script_gen"].get("outputs", [])
        script_json_path = None
        for out in script_outputs:
            p = Path(run_dir).parent / out if not Path(out).is_absolute() else Path(out)
            if p.exists():
                script_json_path = p
                break
        if script_json_path is None:
            # サイレントフォールバック禁止（2026-04-09事故対策）
            # manifest の script_gen.outputs に記載が無い/実体が無い場合は失敗終了
            raise FileNotFoundError(
                f"台本JSONが manifest outputs で見つかりません: {run_dir} "
                f"outputs={script_outputs}"
            )

        video_path = script_json_path.with_suffix(".mp4")

        # 背景画像パスの取得（metadata フェーズの出力から）
        bg_path = None
        meta_outputs = manifest["phases"]["metadata"].get("outputs", [])
        for out in meta_outputs:
            if out.endswith("_bg.jpg") or out.endswith("_bg.png"):
                candidate = run_dir.parent / out if not Path(out).is_absolute() else Path(out)
                if candidate.exists():
                    bg_path = candidate
                    break

        # メモリ確保: 不要プロセスkill + GC + メモリ確認
        try:
            from skills._common import ensure_memory
            ensure_memory("video_build_preflight")
        except Exception as _mem_e:
            logger.log(f"  [メモリ確保警告] {_mem_e}")

        logger.log("【動画生成】動画を生成しています...")
        logger.log(f"  音声ディレクトリ: {audio_dir}")
        logger.log(f"  出力先: {video_path}")
        if bg_path:
            logger.log(f"  背景画像: {bg_path}")

        # 動画生成
        _, used_bgm_paths, section_timestamps, total_duration = build_video(
            script, audio_dir, video_path, bg_path=bg_path,
        )
        logger.log(f"動画を生成しました: {video_path} ({total_duration:.0f}秒)")

        # BGMクレジットを収集してmetadata.jsonの説明文に追記
        bgm_credits = []
        for bp in used_bgm_paths:
            credit = get_bgm_credit(bp)
            if credit:
                title, author, url = credit
                bgm_credits.append(f"{title} / {author} ({url})")
        if bgm_credits:
            meta_path = run_dir / "metadata.json"
            if meta_path.exists():
                import json as _json
                meta = _json.loads(meta_path.read_text(encoding="utf-8"))
                desc = meta.get("description", "")
                # 既存の[BGM]ブロックを置換または末尾に追記
                bgm_block = "■BGM\n" + "\n".join(bgm_credits)
                if "■BGM" in desc:
                    import re as _re
                    desc = _re.sub(r"■BGM\n.*?(?=\n\n|\Z)", bgm_block, desc, flags=_re.DOTALL)
                else:
                    desc = desc.rstrip() + "\n\n" + bgm_block
                meta["description"] = desc
                meta_path.write_text(_json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
                logger.log(f"BGMクレジットをmetadata.jsonに記録しました: {bgm_credits}")

        # 目次タイムスタンプを実際の動画尺に基づいて更新
        _update_timestamps(run_dir, script, section_timestamps, total_duration, logger)

        # YMM4プロジェクトファイル生成（YMMP_ENABLED=falseで無効化可能）
        ymmp_path = None
        if os.getenv("YMMP_ENABLED", "false").lower() in ("true", "1", "yes"):
            try:
                ymmp_path = build_ymmp(
                    script,
                    output_dir=output_dir,
                    audio_dir=audio_dir,
                )
                logger.log(f"YMM4プロジェクト: {ymmp_path}")
            except Exception as e:
                logger.log(f"  [!] YMM4プロジェクト生成失敗: {e} → スキップ")

        # パイプライン状態を更新
        output_files = [str(video_path.name)]
        if ymmp_path:
            output_files.append(str(Path(ymmp_path).name))
        update_phase(run_dir, "video_build", "completed", outputs=output_files)

        result = {
            "video_path": str(video_path),
            "ymmp_path": str(ymmp_path) if ymmp_path else None,
        }
        logger.log("動画生成スキル完了")
        return result

    except Exception as e:
        update_phase(run_dir, "video_build", "failed", error=str(e))
        notify_error("動画生成", e)
        raise


# ── CLI ──────────────────────────────────────────────────


def main():
    import argparse
    import sys as _sys
    parser = argparse.ArgumentParser(description="動画生成スキル")
    parser.add_argument("--run-dir", required=True, help="パイプラインの実行ディレクトリ")
    parser.add_argument("--channel", default="health", choices=["health", "creatures"],
                        help="チャンネルID")
    args = parser.parse_args()

    # Step 3-δ.5c-2: channel config 読込 (fail-closed, generator.py と同形の二段 try).
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
    _output_dir = _project_root / channel.paths.output_subdir

    # Step 3-δ.5c-2: invariant guard (Codex 対立レビュー指摘).
    _run_dir_resolved = Path(args.run_dir).resolve()
    _output_dir_resolved = _output_dir.resolve()
    if _run_dir_resolved.parent != _output_dir_resolved:
        print(f"エラー: --run-dir の親 ({_run_dir_resolved.parent}) が")
        print(f"       channel '{args.channel}' の output_dir ({_output_dir_resolved}) と一致しません")
        print(f"       --run-dir は output_dir 直下の run ディレクトリを指定してください")
        _sys.exit(1)

    # Step 3-δ.5c-2: canonicalization 整合 (Codex Round2 指摘).
    # guard で resolved された path をそのまま run_video_build に渡すことで
    # symlink / junction 経由の --run-dir でも output_dir 実体が揺らがない.
    result = run_video_build(_run_dir_resolved)
    print(f"\n動画: {result['video_path']}")
    if result["ymmp_path"]:
        print(f"YMM4: {result['ymmp_path']}")


if __name__ == "__main__":
    main()
