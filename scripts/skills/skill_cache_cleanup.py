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
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from skills._common import ensure_scripts_path, SkillLogger, load_manifest

ensure_scripts_path()
from notifier import notify_error

BASE_DIR = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"
SCRIPTS_DIR = BASE_DIR / "scripts"

_WAV_KEEP_DAYS = 14       # WAVディレクトリ保持日数
_FAILED_KEEP_DAYS = 7     # 失敗パイプライン保持日数
from skills._common import ALL_TEMP_GLOBS, TEMP_DIR_GLOBS
_TEMP_PATTERNS = ALL_TEMP_GLOBS + ["*.tmp"]


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

def cleanup_temp_files(dry_run: bool = False) -> list[str]:
    """output/ 以下の一時ファイル・ディレクトリを削除する"""
    import shutil
    deleted = []
    for pattern in _TEMP_PATTERNS:
        for f in OUTPUT_DIR.rglob(pattern):
            if f.is_file():
                deleted.append(str(f))
                if not dry_run:
                    try:
                        f.unlink()
                    except OSError as e:
                        print(f"  [警告] 削除失敗: {f} ({e})")
    for pattern in TEMP_DIR_GLOBS:
        for d in OUTPUT_DIR.rglob(pattern):
            if d.is_dir():
                deleted.append(str(d))
                if not dry_run:
                    try:
                        shutil.rmtree(d)
                    except OSError as e:
                        print(f"  [警告] ディレクトリ削除失敗: {d} ({e})")
    return deleted


def cleanup_old_wav_dirs(dry_run: bool = False) -> list[str]:
    """_WAV_KEEP_DAYS 日以上前のWAVディレクトリを削除する"""
    cutoff = time.time() - _WAV_KEEP_DAYS * 86400
    deleted = []
    try:
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir() and re.match(r"\d{8}_\d{6}_", d.name):
                if d.stat().st_mtime < cutoff:
                    deleted.append(str(d))
                    if not dry_run:
                        shutil.rmtree(d, ignore_errors=True)
    except Exception:
        pass
    return deleted


def cleanup_failed_pipelines(dry_run: bool = False) -> list[str]:
    """失敗して _FAILED_KEEP_DAYS 日以上経過したパイプラインを削除する"""
    cutoff = time.time() - _FAILED_KEEP_DAYS * 86400
    deleted = []
    try:
        for d in OUTPUT_DIR.iterdir():
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
    saved_hashes = manifest.get("config_hash", {})
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
            try:
                f.unlink()
            except OSError:
                pass

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
) -> dict:
    """キャッシュクリーンアップを実行する。
    run_dir 指定時はそのディレクトリの発音キャッシュのみ対象。
    run_dir 省略時は output/ 全体を対象。
    """
    log_dir = OUTPUT_DIR if run_dir is None else Path(run_dir)
    logger = SkillLogger(log_dir, "cache_cleanup")
    logger.log("=== キャッシュクリーンアップ開始 ===")
    mode = "[DRY-RUN] " if dry_run else ""

    report = {
        "temp_files": [],
        "old_wav_dirs": [],
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
        # output/ 全体のクリーンアップ
        temp = cleanup_temp_files(dry_run)
        report["temp_files"] = temp
        if temp:
            logger.log(f"{mode}一時ファイル {len(temp)} 件削除")

        old = cleanup_old_wav_dirs(dry_run)
        report["old_wav_dirs"] = old
        if old:
            logger.log(f"{mode}古いWAVディレクトリ {len(old)} 件削除")

        failed = cleanup_failed_pipelines(dry_run)
        report["failed_pipelines"] = failed
        if failed:
            logger.log(f"{mode}失敗パイプライン {len(failed)} 件削除")

    total = sum(len(v) for v in report.values())
    logger.log(f"=== クリーンアップ完了: {mode}{total} 件処理 ===")
    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="キャッシュクリーンアップ")
    parser.add_argument("--run-dir", default=None, help="対象ディレクトリ（省略時: output/全体）")
    parser.add_argument("--dry-run", action="store_true", help="削除せず対象を表示のみ")
    args = parser.parse_args()

    report = run_cache_cleanup(args.run_dir, args.dry_run)

    # 結果表示
    for category, items in report.items():
        if items:
            print(f"\n[{category}]")
            for item in items:
                print(f"  {item}")
