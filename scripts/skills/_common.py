# スキル共通基盤 — パイプライン状態管理・リトライ・ログ

import json
import os
import sys
import time
import tempfile
from datetime import datetime
from pathlib import Path

# ── video_builder一時ファイル定義（cleanup共有用） ─────────
# 即時削除対象（成功時に消すべき一時ファイル）
TEMP_FILE_GLOBS = [
    "*._*_temp_audio.*",
    "*._*_temp_video.*",
    "*._*_temp_speech.*",
    "*._concat_list.txt",
]
# デバッグ用（失敗時の障害解析に残す。orphan cleanupで時間経過後に削除）
DEBUG_ARTIFACT_GLOBS = [
    "*._speech_concat.log",
    "*._audio_mix.log",
    "*._filter.txt",
    "*.ffmpeg.log",
    "*.mux.log",
]
# 一時ディレクトリ
TEMP_DIR_GLOBS = [
    "._*_resampled",
    "_resampled",
]
# 全パターン（orphan cleanup用）
ALL_TEMP_GLOBS = TEMP_FILE_GLOBS + DEBUG_ARTIFACT_GLOBS


def _safe_unlink(path: Path, retries: int = 3,
                 delays: tuple = (0.5, 1.0, 2.0)) -> bool:
    """ファイル削除をリトライ付きで実行。Windowsのファイルロック対策。"""
    for attempt in range(retries):
        try:
            path.unlink(missing_ok=True)
            return True
        except PermissionError as e:
            winerror = getattr(e, "winerror", None)
            if attempt < retries - 1 and (winerror is None or winerror == 32):
                # winerror=32: ファイル使用中 → リトライ
                time.sleep(delays[min(attempt, len(delays) - 1)])
            else:
                # 権限問題 or 最終リトライ失敗 → ログ出力して諦める
                print(f"  [cleanup] 削除失敗: {path.name} "
                      f"(winerror={winerror}, attempt={attempt + 1})")
                return False
        except Exception:
            return False
    return False


def _safe_rmtree(path: Path, retries: int = 3,
                 delays: tuple = (0.5, 1.0, 2.0)) -> bool:
    """ディレクトリ削除をリトライ付きで実行。"""
    import shutil
    for attempt in range(retries):
        try:
            if path.exists():
                shutil.rmtree(path)
            return True
        except PermissionError:
            if attempt < retries - 1:
                time.sleep(delays[min(attempt, len(delays) - 1)])
            else:
                print(f"  [cleanup] ディレクトリ削除失敗: {path.name}")
                return False
        except Exception:
            return False
    return False


# ── パイプライン状態管理 ──────────────────────────────────

PHASE_ORDER = [
    "script_gen",
    "metadata",
    "pronunciation",
    "tts",
    "video_build",
    "thumbnail",
    "upload",
]


def create_manifest(run_dir: Path, theme: str, run_id: str) -> dict:
    """新しいパイプラインマニフェストを作成する"""
    manifest = {
        "run_id": run_id,
        "theme": theme,
        "status": "in_progress",
        "created_at": datetime.now().isoformat(),
        "phases": {
            phase: {
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "outputs": [],
                "error": None,
                "retries": 0,
                "healing_log": [],
            }
            for phase in PHASE_ORDER
        },
    }
    save_manifest(run_dir, manifest)
    return manifest


def load_manifest(run_dir: Path) -> dict:
    """run_dir/pipeline.json を読み込む"""
    path = Path(run_dir) / "pipeline.json"
    if not path.exists():
        raise FileNotFoundError(f"pipeline.json が見つかりません: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def save_manifest(run_dir: Path, manifest: dict) -> None:
    """run_dir/pipeline.json にアトミック書き込み"""
    path = Path(run_dir) / "pipeline.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    # 一時ファイルに書いてからリネーム（クラッシュ時の破損防止）
    tmp_fd, tmp_path = tempfile.mkstemp(
        dir=str(path.parent), suffix=".tmp", prefix="pipeline_"
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
        # Windows では上書きリネームに replace を使う
        Path(tmp_path).replace(path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def update_phase(
    run_dir: Path,
    phase: str,
    status: str,
    outputs: list[str] | None = None,
    error: str | None = None,
) -> dict:
    """指定フェーズのステータスを更新して保存する"""
    manifest = load_manifest(run_dir)
    p = manifest["phases"][phase]
    p["status"] = status

    if status == "in_progress" and p["started_at"] is None:
        p["started_at"] = datetime.now().isoformat()
    elif status in ("completed", "failed"):
        p["completed_at"] = datetime.now().isoformat()

    if outputs is not None:
        p["outputs"] = outputs
    if error is not None:
        p["error"] = error
    if status == "failed":
        p["retries"] = p.get("retries", 0) + 1

    # 全フェーズの完了/失敗を見てパイプライン全体ステータスを更新
    all_phases = manifest["phases"]
    if all(v["status"] == "completed" for v in all_phases.values()):
        manifest["status"] = "completed"
    elif any(v["status"] == "failed" for v in all_phases.values()):
        manifest["status"] = "failed"

    save_manifest(run_dir, manifest)
    return manifest


def check_prerequisites(run_dir: Path, phase: str, depends_on: list[str]) -> bool:
    """前提フェーズが全て completed か確認する"""
    manifest = load_manifest(run_dir)
    for dep in depends_on:
        if manifest["phases"][dep]["status"] != "completed":
            print(f"[スキップ] 前提フェーズ '{dep}' が未完了です")
            return False
    return True


# ── リトライユーティリティ ──────────────────────────────────

_MAX_RETRIES = 3
_RETRY_DELAY = 5  # 秒


def call_with_retry(fn, *args, label: str = "API", **kwargs):
    """API呼び出しを最大3回リトライする。429/503は長めに待機。"""
    last_error = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last_error = e
            err_str = str(e).lower()
            wait = _RETRY_DELAY * (2 ** (attempt - 1))
            if "429" in err_str or "quota" in err_str:
                wait = max(wait, 30)
            if attempt < _MAX_RETRIES:
                print(f"  [{label}] エラー({attempt}/{_MAX_RETRIES}): {e} → {wait}秒後にリトライ")
                time.sleep(wait)
            else:
                print(f"  [{label}] {_MAX_RETRIES}回失敗: {e}")
    raise last_error


# ── スキルログ ──────────────────────────────────────────────

class SkillLogger:
    """各スキル専用のログファイルに書き込むロガー"""

    def __init__(self, run_dir: Path, skill_name: str):
        self.log_dir = Path(run_dir) / "skill_logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.log_path = self.log_dir / f"{skill_name}.log"
        self.skill_name = skill_name

    def log(self, message: str) -> None:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] [{self.skill_name}] {message}\n"
        with open(self.log_path, "a", encoding="utf-8") as f:
            f.write(line)
        # stdout にも出力（run.log に記録されるように）
        print(message)

    def error(self, message: str) -> None:
        self.log(f"[ERROR] {message}")


# ── LLMクライアント遅延初期化 ──────────────────────────────

_llm_instance = None


def get_llm():
    """LLMクライアントをシングルトンで取得"""
    global _llm_instance
    if _llm_instance is None:
        # scripts/ を path に追加（スキルから呼ぶ場合に必要）
        scripts_dir = str(Path(__file__).parent.parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        from providers import get_llm_client
        _llm_instance = get_llm_client()
    return _llm_instance


# ── run_dir ユーティリティ ──────────────────────────────────

def get_script_json(run_dir: Path) -> dict:
    """run_dir 内の台本JSONを読み込む"""
    manifest = load_manifest(run_dir)
    outputs = manifest["phases"]["script_gen"].get("outputs", [])
    for out in outputs:
        path = Path(run_dir).parent / out if not Path(out).is_absolute() else Path(out)
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    # フォールバック: run_dir の親にある .json を探す
    run_path = Path(run_dir)
    for p in run_path.parent.glob(f"{run_path.name.split('_')[0]}*.json"):
        return json.loads(p.read_text(encoding="utf-8"))
    raise FileNotFoundError(f"台本JSONが見つかりません: {run_dir}")


def ensure_scripts_path():
    """sys.path に scripts/ を追加"""
    scripts_dir = str(Path(__file__).parent.parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)


# ── メモリ管理 ──────────────────────────────────────────────

_MIN_MEMORY_MB = 2048   # 最低確保したい空きメモリ (2 GB)
_WARN_MEMORY_MB = 1536  # これ未満ならntfy警告 (1.5 GB)

# WSL側で安全にkillできるプロセス名パターン
_KILLABLE_WSL_PATTERNS = [
    "chrome",          # Playwright MCP のChrome
    "playwright-mcp",  # Playwright MCP本体
    "http.server",     # プレビュー用HTTPサーバー
]

# Windows側で安全に終了できるプロセス名（動画生成に不要なもの）
_KILLABLE_WIN_PROCESSES = [
    "Microsoft.Media.Player.exe",  # 動画プレビュー残り
    "Photos.exe",                   # サムネプレビュー残り
]


def _get_available_memory_mb() -> int:
    """利用可能メモリをMB単位で返す（Windows/WSL両対応）"""
    # Windows環境
    if sys.platform == "win32":
        try:
            import ctypes
            class MEMORYSTATUSEX(ctypes.Structure):
                _fields_ = [
                    ("dwLength", ctypes.c_ulong),
                    ("dwMemoryLoad", ctypes.c_ulong),
                    ("ullTotalPhys", ctypes.c_ulonglong),
                    ("ullAvailPhys", ctypes.c_ulonglong),
                    ("ullTotalPageFile", ctypes.c_ulonglong),
                    ("ullAvailPageFile", ctypes.c_ulonglong),
                    ("ullTotalVirtual", ctypes.c_ulonglong),
                    ("ullAvailVirtual", ctypes.c_ulonglong),
                    ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                ]
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(stat)
            ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
            return int(stat.ullAvailPhys // (1024 * 1024))
        except Exception:
            pass
    # WSL/Linux環境
    try:
        with open("/proc/meminfo") as f:
            for line in f:
                if line.startswith("MemAvailable:"):
                    return int(line.split()[1]) // 1024
    except Exception:
        pass
    return 9999  # 取得失敗時は十分にあると仮定


def _cleanup_temp_files() -> int:
    """output/以下の一時ファイル・ディレクトリを削除してディスクキャッシュを解放する。"""
    cleaned = 0
    try:
        output_dir = Path(__file__).parent.parent.parent / "output"
        if not output_dir.exists():
            return 0
        # ファイル削除
        for pattern in ALL_TEMP_GLOBS:
            for f in output_dir.rglob(pattern):
                try:
                    if f.is_file():
                        size_mb = f.stat().st_size / (1024 * 1024)
                        f.unlink()
                        cleaned += int(size_mb)
                except Exception:
                    pass
        # ディレクトリ削除
        import shutil
        for pattern in TEMP_DIR_GLOBS:
            for d in output_dir.rglob(pattern):
                try:
                    if d.is_dir():
                        size_mb = sum(
                            f.stat().st_size for f in d.rglob("*") if f.is_file()
                        ) / (1024 * 1024)
                        shutil.rmtree(d, ignore_errors=True)
                        cleaned += int(size_mb)
                except Exception:
                    pass
    except Exception:
        pass
    return cleaned


if sys.platform == "win32":
    _KILL_PIDS_PATH = Path("C:/Users/user/Desktop/youtube-system/logs/kill_pids.txt")
else:
    _KILL_PIDS_PATH = Path("/mnt/c/Users/user/Desktop/youtube-system/logs/kill_pids.txt")


def _taskkill_elevated(pids: list[int]) -> bool:
    """スケジュールタスク経由で管理者権限でプロセスを終了する（UAC確認なし）。

    事前に register_kill_task.bat でYukkuriProcessKillタスクを登録済みであること。
    PIDリストをファイルに書き出し、タスクを起動、タスク側のelevated_kill.ps1が処理する。
    """
    if not pids:
        return False
    import subprocess as _sp
    try:
        _KILL_PIDS_PATH.parent.mkdir(parents=True, exist_ok=True)
        _KILL_PIDS_PATH.write_text("\n".join(str(p) for p in pids), encoding="utf-8")
        schtasks = "/mnt/c/Windows/System32/schtasks.exe"
        if sys.platform == "win32":
            schtasks = "schtasks.exe"
        result = _sp.run(
            [schtasks, "/run", "/tn", "YukkuriProcessKill"],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode == 0:
            # タスク完了を待つ（最大10秒）
            for _ in range(20):
                time.sleep(0.5)
                if not _KILL_PIDS_PATH.exists():
                    return True
            return True
        return False
    except Exception:
        return False


def _kill_wsl_bloat() -> list[str]:
    """不要なプロセスを終了してメモリを解放する（WSL側+Windows側）。"""
    killed = []
    if sys.platform == "win32":
        # Windows側: プレビュー残りのアプリを終了
        try:
            import subprocess as _sp
            for proc_name in _KILLABLE_WIN_PROCESSES:
                result = _sp.run(
                    ["taskkill", "/IM", proc_name, "/F"],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    killed.append(proc_name)
        except Exception:
            pass
        # WSL側: 不要プロセスを終了
        try:
            import subprocess as _sp
            for pattern in _KILLABLE_WSL_PATTERNS:
                result = _sp.run(
                    ["wsl", "pkill", "-f", pattern],
                    capture_output=True, text=True, timeout=10,
                )
                if result.returncode == 0:
                    killed.append(pattern)
        except Exception:
            pass
    else:
        # WSL/Linux環境
        import subprocess as _sp
        import signal
        # WSL側の不要プロセスをkill
        try:
            for pid_dir in Path("/proc").iterdir():
                if not pid_dir.name.isdigit():
                    continue
                pid = int(pid_dir.name)
                if pid == os.getpid():
                    continue
                try:
                    cmdline = (pid_dir / "cmdline").read_text().replace("\x00", " ").lower()
                except Exception:
                    continue
                for pattern in _KILLABLE_WSL_PATTERNS:
                    if pattern in cmdline:
                        try:
                            os.kill(pid, signal.SIGTERM)
                            killed.append(f"PID {pid} ({pattern})")
                        except (ProcessLookupError, PermissionError):
                            pass
                        break
        except Exception:
            pass
        # Windows側の不要プロセスを管理者権限で一括終了
        try:
            result = _sp.run(
                ["/mnt/c/Windows/System32/tasklist.exe"],
                capture_output=True, text=True, timeout=10,
            )
            kill_pids = []
            kill_names = []
            for line in result.stdout.splitlines():
                for proc_name in _KILLABLE_WIN_PROCESSES:
                    if proc_name.lower() in line.lower():
                        parts = line.split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            kill_pids.append(int(parts[1]))
                            kill_names.append(proc_name)
                        break
            if kill_pids and _taskkill_elevated(kill_pids):
                killed.extend(kill_names)
        except Exception:
            pass
    return killed


def force_kill_pipeline_processes() -> list[str]:
    """失敗したパイプラインの残留python/ffmpegプロセスを強制終了する。

    自PID(と親PID)以外のpython.exe/ffmpeg*.exeを管理者権限で終了する。
    ensure_memory()から呼ばれるほか、手動実行も可能。
    """
    import subprocess as _sp
    killed = []
    try:
        result = _sp.run(
            ["/mnt/c/Windows/System32/tasklist.exe"],
            capture_output=True, text=True, timeout=10,
        )
    except Exception:
        return killed

    # 自分自身のWindows PIDを除外するため親プロセスチェーン取得
    my_pids = set()
    try:
        my_pids.add(os.getpid())
        my_pids.add(os.getppid())
    except Exception:
        pass

    kill_pids = []
    kill_labels = []
    for line in result.stdout.splitlines():
        line_lower = line.lower()
        if "python.exe" not in line_lower and "ffmpeg" not in line_lower:
            continue
        parts = line.split()
        if len(parts) < 2 or not parts[1].isdigit():
            continue
        pid = int(parts[1])
        if pid in my_pids:
            continue
        # メモリ使用量が小さい(<5MB)プロセスはスキップ（無関係な常駐）
        try:
            mem_str = parts[-2].replace(",", "").replace(".", "")
            mem_kb = int(mem_str)
            if mem_kb < 5000:
                continue
        except (ValueError, IndexError):
            pass
        kill_pids.append(pid)
        kill_labels.append(f"PID {pid} ({parts[0]})")

    if kill_pids and _taskkill_elevated(kill_pids):
        killed.extend(kill_labels)
    return killed


def ensure_memory(label: str = "起動時") -> dict:
    """メモリ使用量をチェックし、不足時は不要プロセスを自動解放する。

    Returns:
        {"before_mb": int, "after_mb": int, "killed": list, "warning": bool}
    """
    import gc

    result = {"before_mb": 0, "after_mb": 0, "killed": [], "warning": False}
    before = _get_available_memory_mb()
    result["before_mb"] = before

    if before < _MIN_MEMORY_MB:
        # GC実行
        gc.collect()

        # 一時ファイル削除（ディスクキャッシュがRAMを圧迫するため）
        cleaned_mb = _cleanup_temp_files()
        if cleaned_mb > 0:
            print(f"  [メモリ解放] 一時ファイル削除: {cleaned_mb} MB")

        # 不要プロセスを終了（WSL側+Windows側）
        killed = _kill_wsl_bloat()
        result["killed"] = killed

        if killed:
            # プロセス終了を少し待つ
            import time
            time.sleep(3)
            print(f"  [メモリ解放] {len(killed)} プロセスを終了: {', '.join(killed)}")

        after = _get_available_memory_mb()

        # それでもまだ不足 → 残留パイプラインプロセスを管理者権限で強制終了
        if after < _WARN_MEMORY_MB:
            pipeline_killed = force_kill_pipeline_processes()
            if pipeline_killed:
                import time
                time.sleep(3)
                killed.extend(pipeline_killed)
                result["killed"] = killed
                after = _get_available_memory_mb()
                print(f"  [メモリ解放] 残留プロセス強制終了: {', '.join(pipeline_killed)}")

        result["after_mb"] = after

        if after < _WARN_MEMORY_MB:
            result["warning"] = True
            try:
                ensure_scripts_path()
                from notifier import notify_error
                notify_error(
                    f"メモリ不足警告({label})",
                    RuntimeError(
                        f"空きメモリ {after} MB（閾値 {_WARN_MEMORY_MB} MB未満）。"
                        f"クリーンアップ前: {before} MB → 後: {after} MB。"
                        f"解放プロセス: {len(killed)} 件"
                    ),
                )
            except Exception:
                pass
            print(f"  [警告] メモリ不足: {after} MB（閾値 {_WARN_MEMORY_MB} MB）")
        else:
            print(f"  [メモリ確認OK] {before} MB → {after} MB（解放後）")
    else:
        result["after_mb"] = before

    return result
