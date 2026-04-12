# スキル: キャッシュクリーンアップ
#
# 不要なキャッシュ・一時ファイルを検出して削除する。
# 単独実行: python scripts/skills/skill_cache_cleanup.py [--run-dir DIR] [--dry-run]
# --run-dir 省略時は output/ 全体を対象にする。

import hashlib
import json
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from skills._common import ensure_scripts_path, SkillLogger, load_manifest, _safe_unlink, _safe_rmtree

ensure_scripts_path()
from notifier import notify_error

BASE_DIR = Path(__file__).resolve().parent.parent.parent
# Step 3-δ.5a: OUTPUT_DIR module-level 定数は削除. 各 helper は output_dir 引数で受け取る.
LOG_DIR = BASE_DIR / "logs"
SCRIPTS_DIR = BASE_DIR / "scripts"

_WAV_KEEP_DAYS = 14            # WAVディレクトリ保持日数
_FAILED_KEEP_DAYS = 7          # 失敗パイプライン保持日数
_ROOT_VIDEO_KEEP_DAYS = 7      # output/直下の古い動画/サムネ保持日数
from skills._common import ALL_TEMP_GLOBS, TEMP_DIR_GLOBS
_TEMP_PATTERNS = ALL_TEMP_GLOBS + ["*.tmp"]

# output/直下の正規ファイル名（先頭が YYYYMMDD_HHMMSS_ または旧形式 YYYYMMDD_）
# 現行: generator.py / skill_script_gen.py は YYYYMMDD_HHMMSS_ で出力。
# 旧形式: 過去の手動運用ファイルは HHMMSS なしで残存している（Codex Round2 指摘）。
# 旧形式の HHMMSS 補完は _parse_root_filename_timestamp() 内で行う（235959 = 保守側）。
# パース不能なファイルは「正規パイプライン外」と判断して削除しない（安全側）。
_ROOT_TIMESTAMP_RE = re.compile(r"^(\d{8})(?:_(\d{6}))?_")


# ── ハッシュ計算 ──────────────────────────────────────────

def _file_md5(path: Path) -> str:
    """ファイルのMD5ハッシュを返す。存在しなければ空文字。"""
    if not path.exists():
        return ""
    h = hashlib.md5()
    h.update(path.read_bytes())
    return h.hexdigest()


def get_pronunciation_hashes() -> dict[str, str]:
    """発音関連ファイルのハッシュを返す（キャッシュ無効化判定用）"""
    return {
        "pronunciation.py": _file_md5(SCRIPTS_DIR / "pronunciation.py"),
        "aquestalk_dict.txt": _file_md5(SCRIPTS_DIR / "aquestalk_dict.txt"),
    }


# ── クリーンアップ対象別の関数 ────────────────────────────

def _get_in_progress_dirs(output_dir: Path) -> set[Path]:
    """現在 in_progress のrun_dirを返す（並行実行保護用）"""
    active = set()
    if not output_dir.exists():
        return active
    for d in output_dir.iterdir():
        if not d.is_dir() or not re.match(r"\d{8}_\d{6}_", d.name):
            continue
        pj = d / "pipeline.json"
        if pj.exists():
            try:
                m = json.loads(pj.read_text(encoding="utf-8"))
                if m.get("status") == "in_progress":
                    active.add(d.resolve())
            except Exception:
                pass
    return active


def cleanup_temp_files(output_dir: Path, dry_run: bool = False) -> list[str]:
    """output/ 以下の一時ファイル・ディレクトリを削除する（in_progress runはスキップ）"""
    deleted = []
    active_dirs = _get_in_progress_dirs(output_dir)
    for pattern in _TEMP_PATTERNS:
        for f in output_dir.rglob(pattern):
            if f.is_file():
                if any(f.resolve().is_relative_to(ad) for ad in active_dirs):
                    continue
                deleted.append(str(f))
                if not dry_run:
                    _safe_unlink(f)
    for pattern in TEMP_DIR_GLOBS:
        for d in output_dir.rglob(pattern):
            if d.is_dir():
                if any(d.resolve().is_relative_to(ad) for ad in active_dirs):
                    continue
                deleted.append(str(d))
                if not dry_run:
                    _safe_rmtree(d)
    return deleted


def cleanup_old_wav_dirs(output_dir: Path, dry_run: bool = False) -> list[str]:
    """_WAV_KEEP_DAYS 日以上前のWAVディレクトリを削除する"""
    cutoff = time.time() - _WAV_KEEP_DAYS * 86400
    deleted = []
    try:
        for d in output_dir.iterdir():
            if d.is_dir() and re.match(r"\d{8}_\d{6}_", d.name):
                if d.stat().st_mtime < cutoff:
                    deleted.append(str(d))
                    if not dry_run:
                        shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass
    return deleted


def _parse_root_filename_timestamp(name: str) -> float | None:
    """ファイル名先頭の YYYYMMDD_HHMMSS（または旧 YYYYMMDD_）を UNIX 時刻に変換。

    なぜ mtime ではなく filename ベースか:
    - mtime はファイルコピー・手動再保存・サムネ差し替えで簡単に揺れる
    - 一方ファイル名のタイムスタンプは生成時に固定され改変されない
    - パース失敗 → None を返し、呼び出し側で削除対象から外す（安全側に倒す）

    旧命名対応 (Codex Round2 指摘):
    - HHMMSS が無いファイルは 235959 (= その日 23:59:59) として扱う
    - 実際の生成時刻が不明な以上、一番遅い時刻を採用 = 「実時間で7日」を必ず満たす
    - 000000 にすると最大24時間早く消えてしまうため Round3 で 235959 に変更
    """
    m = _ROOT_TIMESTAMP_RE.match(name)
    if not m:
        return None
    date_part = m.group(1)
    time_part = m.group(2) or "235959"
    try:
        dt = datetime.strptime(f"{date_part}_{time_part}", "%Y%m%d_%H%M%S")
        return dt.timestamp()
    except ValueError:
        return None


def cleanup_old_root_videos(output_dir: Path, dry_run: bool = False) -> list[str]:
    """output/ 直下の古い MP4 / サムネ画像を削除する。

    削除対象（_ROOT_VIDEO_KEEP_DAYS 日以上前）:
    - *.mp4
    - *_thumbnail.png（A/B/C などのバリアント含む）
    - *_thumb_bg.jpg

    削除しない（復元入力 / 監査証跡として保持）:
    - *.json（resynth_and_build.py の必須入力。サイズも極小）
    - *_bg.jpg（本編背景。resynth_and_build.py が再利用）
    - その他の未認識ファイル（安全側）

    判定基準（Codex 協議結果）:
    - mtime ではなくファイル名先頭の YYYYMMDD_HHMMSS を使用
    - パース不能なファイルは正規パイプライン外と見做して削除しない
    """
    cutoff = time.time() - _ROOT_VIDEO_KEEP_DAYS * 86400
    deleted: list[str] = []
    failures: list[str] = []
    if not output_dir.exists():
        return deleted

    try:
        entries = list(output_dir.iterdir())
    except OSError as e:
        # iterdir 自体の失敗は監視機能の死亡なのでログに出す
        print(f"  [cleanup] output_dir.iterdir() 失敗: {e}")
        return deleted

    for p in entries:
        if not p.is_file():
            continue
        name = p.name
        # 削除対象サフィックス判定
        is_target = (
            name.endswith(".mp4")
            or name.endswith("_thumb_bg.jpg")
            or (name.endswith(".png") and "_thumbnail" in name)
        )
        if not is_target:
            continue

        ts = _parse_root_filename_timestamp(name)
        if ts is None:
            continue  # 命名規約外 → 安全側で残す
        if ts >= cutoff:
            continue  # まだ新しい

        # Codex Round2 指摘: 削除失敗を成功として集計しない
        # _safe_unlink は失敗時 False を返すので返り値で判定する
        if dry_run:
            deleted.append(str(p))
        else:
            if _safe_unlink(p):
                deleted.append(str(p))
            else:
                # Codex Round3 指摘: _safe_unlink は generic Exception を無言で
                # 握り潰すため、呼び出し側で失敗観測性を補強する
                failures.append(name)
                print(f"  [cleanup] root削除失敗: {name}")

    # 失敗があれば集計を呼び出し側で見えるようにログに出す
    if failures:
        print(
            f"  [cleanup] 古いroot動画/サムネ削除失敗: {len(failures)}件 "
            f"({failures[:3]}...)"
        )

    return deleted


def cleanup_failed_pipelines(output_dir: Path, dry_run: bool = False) -> list[str]:
    """失敗して _FAILED_KEEP_DAYS 日以上経過したパイプラインを削除する"""
    cutoff = time.time() - _FAILED_KEEP_DAYS * 86400
    deleted = []
    try:
        for d in output_dir.iterdir():
            if not d.is_dir() or not re.match(r"\d{8}_\d{6}_", d.name):
                continue
            pipeline_path = d / "pipeline.json"
            if not pipeline_path.exists():
                continue
            try:
                manifest = json.loads(pipeline_path.read_text(encoding="utf-8"))
                if manifest.get("status") == "failed" and d.stat().st_mtime < cutoff:
                    deleted.append(str(d))
                    if not dry_run:
                        shutil.rmtree(d, ignore_errors=True)
            except Exception:
                continue
    except Exception:
        pass
    return deleted


def cleanup_stale_wav_for_run(run_dir: Path, dry_run: bool = False) -> list[str]:
    """発音辞書が変更された場合、該当run_dirのWAVファイルを削除する"""
    run_dir = Path(run_dir)
    deleted = []

    pipeline_path = run_dir / "pipeline.json"
    if not pipeline_path.exists():
        return deleted

    try:
        manifest = json.loads(pipeline_path.read_text(encoding="utf-8"))
    except Exception:
        return deleted

    # マニフェストに保存されたハッシュと現在のハッシュを比較
    # 新形式: phases.pronunciation.config_hashes / 旧形式: config_hash
    saved_hashes = (
        manifest.get("phases", {}).get("pronunciation", {}).get("config_hashes")
        or manifest.get("config_hash", {})
    )
    if not saved_hashes:
        return deleted  # ハッシュ未記録 = 初回 → 削除不要

    current_hashes = get_pronunciation_hashes()
    changed = False
    for key, current in current_hashes.items():
        if saved_hashes.get(key, "") != current:
            changed = True
            break

    if not changed:
        return deleted

    # WAVファイルを削除
    wav_files = list(run_dir.glob("*.wav"))
    for f in wav_files:
        deleted.append(str(f))
        if not dry_run:
            _safe_unlink(f)

    if deleted:
        # pipeline.json の tts フェーズをリセット
        if not dry_run:
            manifest["phases"]["tts"]["status"] = "pending"
            manifest["phases"]["tts"]["outputs"] = []
            manifest["phases"]["tts"]["error"] = None
            manifest["phases"]["video_build"]["status"] = "pending"
            manifest["phases"]["video_build"]["outputs"] = []
            manifest["status"] = "in_progress"
            pipeline_path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    return deleted


# ── メイン実行 ────────────────────────────────────────────

def run_cache_cleanup(
    run_dir: str | Path | None = None,
    dry_run: bool = False,
    output_dir: Path | None = None,
) -> dict:
    """キャッシュクリーンアップを実行する。
    run_dir 指定時はそのディレクトリの発音キャッシュのみ対象。
    run_dir 省略時は output_dir 全体を対象（output_dir 必須）。
    """
    # Step 3-δ.5a: silent None fallback を排除. caller は run_dir か output_dir の
    # どちらかを必ず渡す. 両方 None は設計上あり得ない.
    if run_dir is None and output_dir is None:
        raise TypeError(
            "run_cache_cleanup: run_dir と output_dir の両方 None は不可"
        )
    log_dir = Path(run_dir) if run_dir is not None else output_dir
    logger = SkillLogger(log_dir, "cache_cleanup")
    logger.log("=== キャッシュクリーンアップ開始 ===")
    mode = "[DRY-RUN] " if dry_run else ""

    report = {
        "temp_files": [],
        "old_wav_dirs": [],
        "old_root_videos": [],
        "failed_pipelines": [],
        "stale_wav": [],
    }

    if run_dir:
        # 特定run_dirの発音キャッシュ無効化のみ
        stale = cleanup_stale_wav_for_run(Path(run_dir), dry_run)
        report["stale_wav"] = stale
        if stale:
            logger.log(f"{mode}発音変更により {len(stale)} WAVファイルを削除")
    else:
        # output_dir 全体のクリーンアップ
        temp = cleanup_temp_files(output_dir, dry_run)
        report["temp_files"] = temp
        if temp:
            logger.log(f"{mode}一時ファイル {len(temp)} 件削除")

        old = cleanup_old_wav_dirs(output_dir, dry_run)
        report["old_wav_dirs"] = old
        if old:
            logger.log(f"{mode}古いWAVディレクトリ {len(old)} 件削除")

        old_root = cleanup_old_root_videos(output_dir, dry_run)
        report["old_root_videos"] = old_root
        if old_root:
            logger.log(f"{mode}古いroot動画/サムネ {len(old_root)} 件削除")

        failed = cleanup_failed_pipelines(output_dir, dry_run)
        report["failed_pipelines"] = failed
        if failed:
            logger.log(f"{mode}失敗パイプライン {len(failed)} 件削除")

    total = sum(len(v) for v in report.values())
    logger.log(f"=== クリーンアップ完了: {mode}{total} 件処理 ===")
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="キャッシュクリーンアップ")
    parser.add_argument("--run-dir", default=None, help="対象ディレクトリ（省略時: --channel から resolve）")
    parser.add_argument("--dry-run", action="store_true", help="削除せず対象を表示のみ")
    # Step 3-δ.5a: --channel 追加. creatures 開放は 5c-8 (script char / tags
    # fallback channel-aware 化) 完了後.
    parser.add_argument("--channel", default="health", choices=["health"],
                        help="チャンネルID (creatures は 5c-8 完了後に開放)")
    args = parser.parse_args()

    # --run-dir 未指定の場合のみ channel config から output_dir を解決
    output_dir = None
    if args.run_dir is None:
        try:
            from _channel import load_channel, ChannelLoadError
        except Exception as _ce_imp:
            print(f"[致命的] _channel モジュール import 失敗: {_ce_imp}")
            sys.exit(1)
        try:
            cfg = load_channel(args.channel)
        except ChannelLoadError as _ce_load:
            print(f"[致命的] チャンネル設定読込失敗 ({args.channel}): {_ce_load}")
            sys.exit(1)
        output_dir = BASE_DIR / cfg.paths.output_subdir
        print(f"[cleanup] channel={args.channel} output_dir={output_dir}")

    report = run_cache_cleanup(args.run_dir, args.dry_run, output_dir=output_dir)

    # 結果表示
    for category, items in report.items():
        if items:
            print(f"\n[{category}]")
            for item in items:
                print(f"  {item}")
