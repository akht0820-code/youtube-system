"""Step 3-δ.5c-6 probe: _common._cleanup_temp_files() channel-aware 化.

検証:
[1] AST: _cleanup_temp_files 内に config/channels glob
[2] AST: _cleanup_temp_files 内に load_channel 呼び出し
[3] AST: legacy 'output' fallback 分岐が存在
[4] AST: output_dirs dedup ロジック (if not in list)
[5] AST: ChannelLoadError 個別 skip (continue)
[6] 同等再現: health config の output_dir が PROJECT_ROOT/output と一致
[7] 実測: fake project_root で health + creatures 両方の temp file を削除
[8] 実測: config/channels/ 不在でも legacy 'output' fallback で動く
[9] 実測: 同一 output_subdir 重複 channel で dedup が効く
[10] 実測: 物理的に output_dir が無ければ skip される
[11] 実測: health 単独 run で現行動作と bit-identical (ALL_TEMP_GLOBS 削除)
[12] 実測: ChannelLoadError の channel が混在しても他 channel は cleanup 続行

前提:
- Step 3-δ.5c-5 commit aae98c2 regression zero.
- 本 Step は _common の単一関数 channel-aware 化.
"""
import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SKILLS_DIR = SCRIPTS_DIR / "skills"
sys.path.insert(0, str(SCRIPTS_DIR))

errors = []


def expect(cond, msg):
    if cond:
        print(f"  [OK] {msg}")
    else:
        print(f"  [NG] {msg}")
        errors.append(msg)


cm_src = (SKILLS_DIR / "_common.py").read_text(encoding="utf-8")
tree = ast.parse(cm_src)

# _cleanup_temp_files 関数を取得
fn = None
for n in ast.walk(tree):
    if isinstance(n, ast.FunctionDef) and n.name == "_cleanup_temp_files":
        fn = n
        break
expect(fn is not None, "_cleanup_temp_files 関数が存在")
fn_src = ast.unparse(fn) if fn and hasattr(ast, "unparse") else ""


# ── [1] AST: config/channels glob ────────────────────────────
print("[1] AST: config/channels glob 呼び出し")
# ast.unparse は single-quote で出力するので 'config' / 'channels' と照合
expect("'config'" in fn_src and "'channels'" in fn_src and ".glob(" in fn_src,
       "config/channels/*.json glob コードあり")


# ── [2] AST: load_channel 呼び出し ──────────────────────────
print("[2] AST: load_channel 呼び出し")
has_load = False
for x in ast.walk(fn) if fn else []:
    if (isinstance(x, ast.Call)
            and isinstance(x.func, ast.Name)
            and x.func.id == "load_channel"):
        has_load = True
        break
expect(has_load, "_cleanup_temp_files 内に load_channel 呼び出し")


# ── [3] AST: legacy 'output' fallback 分岐 ───────────────────
print("[3] AST: legacy 'output' fallback")
expect("legacy_output" in fn_src and "project_root / 'output'" in fn_src,
       "legacy_output = project_root / 'output' fallback あり")


# ── [4] AST: dedup ロジック ──────────────────────────────────
print("[4] AST: output_dirs dedup")
expect("not in output_dirs" in fn_src,
       "dedup ロジック 'if ... not in output_dirs' あり")


# ── [5] AST: ChannelLoadError 個別 skip ──────────────────────
print("[5] AST: ChannelLoadError 個別 skip (continue)")
has_cle_continue = False
for x in ast.walk(fn) if fn else []:
    if isinstance(x, ast.ExceptHandler):
        if x.type and isinstance(x.type, ast.Name) and x.type.id == "ChannelLoadError":
            for stmt in ast.walk(x):
                if isinstance(stmt, ast.Continue):
                    has_cle_continue = True
                    break
expect(has_cle_continue, "ChannelLoadError の except に continue あり")


# ── [6] 同等再現: health config ──────────────────────────────
print("[6] 同等再現: health config の output_dir が PROJECT_ROOT/output")
from _channel import load_channel
cfg = load_channel("health")
new_out = PROJECT_ROOT / cfg.paths.output_subdir
old_out = PROJECT_ROOT / "output"
expect(new_out == old_out,
       f"health output_dir bit-identical ({new_out})")


# ── subprocess probe helper ───────────────────────────────────
py_exe = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe")
if not py_exe.exists():
    py_exe = Path(sys.executable)
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"


def _run_cleanup(
    tmp_project_root: Path,
    fake_channels: dict[str, dict] | None,  # channel_id -> config dict or None
    temp_files: list[tuple[str, str]],  # (output_subdir, rel_path)
    temp_dirs: list[tuple[str, str]] = None,  # (output_subdir, rel_path)
) -> tuple[int, str, str]:
    """tempdir を project_root に見立てて _cleanup_temp_files を呼ぶ subprocess."""
    temp_dirs = temp_dirs or []
    inline = f'''
import sys, json
from pathlib import Path
sys.path.insert(0, r"{SCRIPTS_DIR}")
sys.path.insert(0, r"{SCRIPTS_DIR / "skills"}")

fake_root = Path(r"{tmp_project_root}")

# config/channels/*.json を生成
fake_channels = {repr(fake_channels)}
if fake_channels is not None:
    cfg_dir = fake_root / "config" / "channels"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    for cid, cfg_body in fake_channels.items():
        (cfg_dir / f"{{cid}}.json").write_text(
            json.dumps(cfg_body), encoding="utf-8"
        )

# temp ファイルを配置
temp_files = {repr(temp_files)}
for subdir, rel in temp_files:
    p = fake_root / subdir / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * (1024 * 1024 * 2))  # 2MB dummy

# temp ディレクトリを配置
temp_dirs = {repr(temp_dirs)}
for subdir, rel in temp_dirs:
    d = fake_root / subdir / rel
    d.mkdir(parents=True, exist_ok=True)
    (d / "dummy.wav").write_bytes(b"y" * (1024 * 1024))

import _common
# Path(__file__).parent.parent.parent が fake_root になるよう __file__ を差し替え.
_common.__file__ = str(fake_root / "scripts" / "skills" / "_common.py")

cleaned = _common._cleanup_temp_files()
print("CLEANED_MB:", cleaned)
# 結果: 残存ファイル/ディレクトリを列挙
remaining = []
for subdir, rel in temp_files:
    if (fake_root / subdir / rel).exists():
        remaining.append(f"FILE:{{subdir}}/{{rel}}")
for subdir, rel in temp_dirs:
    if (fake_root / subdir / rel).exists():
        remaining.append(f"DIR:{{subdir}}/{{rel}}")
print("REMAINING:", ",".join(remaining) if remaining else "NONE")
'''
    res = subprocess.run(
        [str(py_exe), "-X", "utf8", "-c", inline],
        cwd=str(SCRIPTS_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    return res.returncode, res.stdout, res.stderr


# ── valid channel config factory ─────────────────────────────
def _channel_body(cid: str, subdir: str) -> dict:
    return {
        "schema_version": 1,
        "id": cid,
        "paths": {
            "output_subdir": subdir,
            "themes_file": f"themes_{cid}.txt",
            "lock_file": f"logs/last_upload_{cid}.txt",
        },
        "oauth": {
            "credentials": f"credentials_{cid}.json",
            "token": f"token_{cid}.json",
        },
        "script": {"min_chars": 6000, "max_chars": 7500},
        "tags": {"default": ["ゆっくり解説", cid]},
    }


# ── [7] 実測: health + creatures 両方の temp file を削除 ─────
print("[7] 実測: health + creatures の temp file を両方削除")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    channels = {
        "health": _channel_body("health", "output"),
        "creatures": _channel_body("creatures", "output_creatures"),
    }
    files = [
        ("output", "20260412_000000_test/._test_temp_audio.wav"),
        ("output_creatures", "20260412_000000_c/._c_temp_video.mp4"),
    ]
    rc, out, err = _run_cleanup(_tmp_root, channels, files)
    expect(rc == 0 and "REMAINING: NONE" in out,
           f"health+creatures 両方削除 (rc={rc}) stdout={out[:400]} stderr={err[:300]}")


# ── [8] 実測: config/channels 不在 → legacy fallback ─────────
print("[8] 実測: config/channels 不在でも legacy 'output' fallback で動く")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    files = [
        ("output", "20260412_000000_test/._test_temp_audio.wav"),
    ]
    rc, out, err = _run_cleanup(_tmp_root, None, files)
    expect(rc == 0 and "REMAINING: NONE" in out,
           f"config/channels 無しでも output/ 削除 (rc={rc}) stdout={out[:400]} stderr={err[:300]}")


# ── [9] 実測: 同一 output_subdir の重複 channel で dedup ─────
print("[9] 実測: 重複 output_subdir で dedup")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    # 2 channel が同じ output_subdir を指す
    channels = {
        "health": _channel_body("health", "output"),
        "duplicate": _channel_body("duplicate", "output"),
    }
    files = [
        ("output", "20260412_000000_test/._test_temp_audio.wav"),
    ]
    rc, out, err = _run_cleanup(_tmp_root, channels, files)
    expect(rc == 0 and "REMAINING: NONE" in out,
           f"重複 output_subdir で dedup + 削除 (rc={rc}) stdout={out[:400]} stderr={err[:300]}")


# ── [10] 実測: 物理的に output_dir が無ければ skip ───────────
print("[10] 実測: 物理的に output_dir が無い channel は skip")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    # creatures は config にあるが output_creatures/ は物理的に作らない
    channels = {
        "health": _channel_body("health", "output"),
        "creatures": _channel_body("creatures", "output_creatures"),
    }
    files = [
        ("output", "20260412_000000_test/._test_temp_audio.wav"),
    ]
    rc, out, err = _run_cleanup(_tmp_root, channels, files)
    expect(rc == 0 and "REMAINING: NONE" in out,
           f"物理 dir 不在でも crash せず health は削除 (rc={rc}) stdout={out[:400]} stderr={err[:300]}")


# ── [11] 実測: health 単独 run で現行動作と bit-identical ────
print("[11] 実測: health 単独 run で現行動作と bit-identical")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    channels = {"health": _channel_body("health", "output")}
    files = [
        ("output", "20260412_000000_test/._test_temp_audio.wav"),
        ("output", "20260412_000000_test/._test_temp_video.mp4"),
        ("output", "20260412_000000_test/._concat_list.txt"),
    ]
    dirs = [
        ("output", "20260412_000000_test/_resampled"),
    ]
    rc, out, err = _run_cleanup(_tmp_root, channels, files, dirs)
    expect(rc == 0 and "REMAINING: NONE" in out,
           f"health 単独 ALL_TEMP_GLOBS+TEMP_DIR_GLOBS 全削除 (rc={rc}) stdout={out[:400]} stderr={err[:300]}")


# ── [12] 実測: ChannelLoadError 混在でも他 channel は続行 ────
print("[12] 実測: ChannelLoadError 混在で他 channel cleanup 続行")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    # 'broken' は schema 不正 → ChannelLoadError
    broken = _channel_body("broken", "output_broken")
    del broken["oauth"]  # 必須 key 欠如 → schema error
    channels = {
        "health": _channel_body("health", "output"),
        "broken": broken,
    }
    files = [
        ("output", "20260412_000000_test/._test_temp_audio.wav"),
    ]
    rc, out, err = _run_cleanup(_tmp_root, channels, files)
    expect(rc == 0 and "REMAINING: NONE" in out,
           f"broken channel 混在でも health cleanup 続行 (rc={rc}) stdout={out[:400]} stderr={err[:300]}")


# ── 結果 ──────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3D5C6: _common._cleanup_temp_files が channel-aware + legacy fallback")
    sys.exit(0)
