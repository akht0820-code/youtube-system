"""Step 2-β 本番 import 形態 実測 probe (code-change-zero)

目的:
    Step 2-α の Codex Medium advisory (「次 Step で generator.py から
    `from scripts._channel import load_channel` を呼ぶと ModuleNotFoundError」)
    が、本番 generator.py の実際の sys.path 前提 (run.bat:3 `cd /d ...\\scripts`
    により sys.path[0] == scripts/) と食い違うことを実測で証明する。

    本 probe は subprocess で本番形態 (cwd=scripts/, python.exe <script>.py) を
    再現し、`from _channel import load_channel` が通ることと、error path 4 件が
    正しく ChannelLoadError で弾かれることを検証する。

前提:
    - Windows native Python 3.11 で実行する
    - 実行コマンド例:
        cmd.exe /c "cd /d C:\\Users\\user\\Desktop\\youtube-system && ^
            set PYTHONIOENCODING=utf-8 && ^
            C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python311\\python.exe ^
            tasks\\evidence\\step_2b_prod_import_probe.py"
    - probe 自体は 10:00 健康チャンネル定時タスクに一切影響しない
      (コード変更ゼロ、read-only 実測のみ)

成功条件:
    child プロセスの stdout に PROBE_OK が含まれ、exit code == 0
"""
from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

# 本番 generator.py 起動形態を再現する child payload
# run.bat:3 "cd /d <project>/scripts" + "python.exe generator.py" と同じ sys.path 状態
# (Python は script ディレクトリを sys.path[0] に入れる。-c の場合は cwd を sys.path[0] に入れる)
PAYLOAD = textwrap.dedent(
    """
    import sys, os
    print(f"cwd={os.getcwd()}")
    print(f"sys.path[0]={sys.path[0]}")
    print(f"python={sys.version.split()[0]}")

    # 本番 generator.py と同じ呼び出し形式: from _channel import ...
    from _channel import load_channel, ChannelLoadError
    from _channel_schema import ChannelConfig

    cfg = load_channel('health')
    assert isinstance(cfg, ChannelConfig), f"expected ChannelConfig got {type(cfg).__name__}"
    print(f"OK happy: id={cfg.id} themes={cfg.paths.themes_file} lock={cfg.paths.lock_file}")
    print(f"OK happy: schema_version={cfg.schema_version} script_min={cfg.script.min_chars} script_max={cfg.script.max_chars}")
    print(f"OK happy: tags_count={len(cfg.tags.default)}")

    # error path 4 件
    bad_cases = [
        ('nonexistent', 'missing_file'),
        ('../etc', 'regex_violation_dotdot'),
        ('Foo', 'regex_violation_upper'),
        ('', 'empty_string'),
    ]
    for bad_id, label in bad_cases:
        try:
            load_channel(bad_id)
            print(f"FAIL {label}: unexpected success for {bad_id!r}")
            sys.exit(1)
        except ChannelLoadError:
            print(f"OK error: {label}")

    # stdlib secrets shadow 状態の観察 (assertion なし、informational のみ)
    import secrets as secrets_mod
    secrets_file = getattr(secrets_mod, '__file__', None) or '<builtin>'
    is_scripts_shadow = 'youtube-system' in secrets_file and 'scripts' in secrets_file.replace('/', '\\\\')
    print(f"INFO secrets.__file__={secrets_file}")
    print(f"INFO secrets_is_shadowed_by_scripts={is_scripts_shadow}")

    # _channel / _channel_schema が stdlib secrets に依存していないことを間接確認
    # (依存していれば scripts/secrets.py に置き換わった時点で attribute error が出る)
    import _channel as _ch
    import _channel_schema as _sc
    assert not hasattr(_ch, 'secrets'), '_channel should not import secrets'
    assert not hasattr(_sc, 'secrets'), '_channel_schema should not import secrets'
    print("OK module: _channel / _channel_schema do not reference stdlib secrets")

    print("PROBE_OK")
    """
).strip()


def main() -> int:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"

    # Windows native python を優先
    py_exe = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe")
    if not py_exe.exists():
        py_exe = Path(sys.executable)

    print(f"[probe] python_exe={py_exe}")
    print(f"[probe] child_cwd={SCRIPTS_DIR}")
    print(f"[probe] ---- child stdout ----")

    result = subprocess.run(
        [str(py_exe), "-X", "utf8", "-c", PAYLOAD],
        cwd=str(SCRIPTS_DIR),
        env=env,
        capture_output=True,
        text=True,
    )
    if result.stdout:
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print(f"[probe] ---- child stderr ----")
        print(result.stderr, end="" if result.stderr.endswith("\n") else "\n")
    print(f"[probe] ---- child exit: {result.returncode} ----")

    if result.returncode != 0 or "PROBE_OK" not in result.stdout:
        print("[probe] RESULT: FAIL")
        return 1
    print("[probe] RESULT: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
