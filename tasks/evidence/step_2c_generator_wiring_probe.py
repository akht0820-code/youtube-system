"""Step 2-γ generator.py 配線 smoke probe

目的:
    scripts/generator.py に load_channel('health') を配線したことで, 本番形態
    (cwd=scripts/, Windows native python) で以下が全て通ることを実測する.

    1. `from _channel import load_channel, ChannelLoadError` が通る
    2. `load_channel('health')` が通り ChannelConfig を返す
    3. `Path(__file__).parent.parent / cfg.paths.themes_file` が実在する
    4. `Path(__file__).parent.parent / cfg.paths.lock_file` の親 (logs/) が実在する
       (lock_file 自体は当日分のみ存在するので親のみ検証)
    5. `python -c "import generator"` が通る (syntax + import chain)

前提:
    - cwd=scripts/ で子プロセスを起動する (run.bat:3 と等価)
    - Windows native Python 3.11 を優先
    - 成功時 stdout に PROBE_OK, exit code == 0

実行:
    cmd.exe /c "cd /d C:\\Users\\user\\Desktop\\youtube-system && ^
        set PYTHONIOENCODING=utf-8 && ^
        C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python311\\python.exe ^
        tasks\\evidence\\step_2c_generator_wiring_probe.py"
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# Codex advisory (2nd round): cwd=scripts/ を明示することが重要
# _channel.py は import 形に実行文脈依存の前提があるため
PAYLOAD_CHANNEL = textwrap.dedent(
    """
    import sys, os
    from pathlib import Path
    print(f"cwd={os.getcwd()}")
    print(f"sys.path[0]={sys.path[0]}")
    print(f"python={sys.version.split()[0]}")

    # (1) import
    from _channel import load_channel, ChannelLoadError
    from _channel_schema import ChannelConfig
    print("OK step1: from _channel import ... succeeded")

    # (2) load_channel('health')
    cfg = load_channel('health')
    assert isinstance(cfg, ChannelConfig), f"expected ChannelConfig got {type(cfg).__name__}"
    print(f"OK step2: load_channel('health') -> id={cfg.id} themes={cfg.paths.themes_file} lock={cfg.paths.lock_file}")

    # (3) themes_file が実在
    # generator.py と同じ解決: Path(__file__).parent.parent / cfg.paths.themes_file
    # probe は scripts/ に居るので Path.cwd() == scripts/; parent == project_root
    project_root = Path.cwd().parent
    themes_path = project_root / cfg.paths.themes_file
    assert themes_path.exists(), f"themes_path not found: {themes_path}"
    print(f"OK step3: themes_path exists: {themes_path}")

    # (4) lock_file の親が実在
    lock_path = project_root / cfg.paths.lock_file
    assert lock_path.parent.exists(), f"lock_path parent not found: {lock_path.parent}"
    print(f"OK step4: lock_path parent exists: {lock_path.parent}")

    # (5) 現行ハードコードと bit-identical 検証
    expected_themes = project_root / 'themes.txt'
    expected_lock = project_root / 'logs' / 'last_upload_date.txt'
    assert themes_path == expected_themes, f"themes mismatch: {themes_path} vs {expected_themes}"
    assert lock_path == expected_lock, f"lock mismatch: {lock_path} vs {expected_lock}"
    print("OK step5: bit-identical with current hardcoded paths")

    print("PROBE_OK_CHANNEL")
    """
).strip()

# generator.py の import chain が壊れていないか (syntax + transitive import)
# 注: generator.main() は実行しない. 単に import generator のみで import chain を検査する.
PAYLOAD_IMPORT_GEN = textwrap.dedent(
    """
    import sys, os
    print(f"cwd={os.getcwd()}")
    # generator.py は top-level で notifier, skills.self_healing を import する.
    # cwd=scripts/ 前提なので sys.path[0]==scripts/ で解決可能.
    import generator
    print(f"OK import generator: file={generator.__file__}")

    # main 関数の存在確認 (実行はしない)
    assert callable(getattr(generator, 'main', None)), "generator.main not callable"
    # _pick_theme_from_file signature が themes_path / output_dir を受けることを確認
    # Step 3-δ.4: output_dir 引数追加 (OUTPUT_DIR module-level 定数削除)
    import inspect
    sig = inspect.signature(generator._pick_theme_from_file)
    params = list(sig.parameters.keys())
    assert params == ['themes_path', 'output_dir'], f"unexpected signature params: {params}"
    print(f"OK _pick_theme_from_file signature: {sig}")

    print("PROBE_OK_IMPORT")
    """
).strip()


def _run_child(label: str, payload: str, env: dict, py_exe: Path) -> bool:
    print(f"[probe] ---- {label} ----")
    print(f"[probe] python_exe={py_exe}")
    print(f"[probe] child_cwd={SCRIPTS_DIR}")
    result = subprocess.run(
        [str(py_exe), "-X", "utf8", "-c", payload],
        cwd=str(SCRIPTS_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(f"[probe] ---- {label} stderr ----")
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    print(f"[probe] ---- {label} exit: {result.returncode} ----")

    ok_marker = "PROBE_OK_CHANNEL" if "CHANNEL" in label else "PROBE_OK_IMPORT"
    if result.returncode != 0 or ok_marker not in result.stdout:
        print(f"[probe] {label} RESULT: FAIL")
        return False
    print(f"[probe] {label} RESULT: OK")
    return True


def main() -> int:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    py_exe = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe")
    if not py_exe.exists():
        py_exe = Path(sys.executable)

    all_ok = True
    all_ok &= _run_child("CHANNEL probe", PAYLOAD_CHANNEL, env, py_exe)
    all_ok &= _run_child("IMPORT GENERATOR probe", PAYLOAD_IMPORT_GEN, env, py_exe)

    if all_ok:
        print("[probe] RESULT: ALL OK")
        return 0
    print("[probe] RESULT: FAIL (one or more child probes failed)")
    return 1


if __name__ == "__main__":
    sys.exit(main())
