"""Step 3-δ.5c-4 probe: skill_upload.py の OUTPUT_DIR 定数整理 + CLI channel-aware 化.

検証:
[1] AST: module-level の OUTPUT_DIR 代入が存在しない
[2] AST: run_upload 内に `output_dir = run_dir.parent` 代入が存在
[3] AST: run_upload 内 generate_community_post(..., output_dir) 呼び出し
         (旧 OUTPUT_DIR ではなく run_dir.parent 由来の output_dir を使う)
[4] AST: main() 内 parser.add_argument('--channel', ...)
[5] AST: main() 内 load_channel(args.channel) の呼び出し
[6] AST: main() 内 manifest.channel_id vs args.channel cross-check
         (Codex Round1 指摘: upload 固有の fail-closed)
[7] AST: main() 内 invariant guard (run_dir.parent vs output_dir)
[8] AST: main() 内 run_upload(_run_dir_resolved, ...) 呼び出し (canonicalization)
[9] 同等再現: health config output_dir が旧 hardcode と等価
[10] 実測 (subprocess): skill_upload.py --help が exit 0 で --channel を表示
[11] 実測 (subprocess): skill_upload.py --channel invalid → argparse reject (exit 2)
[12] 実測 (subprocess): --run-dir が channel の output_dir 直下でない → fail-closed exit 1

前提:
- Step 3-δ.5c-3 commit cc8bc6c regression zero.
- 本 Step は OUTPUT_DIR 削除 + CLI channel-aware + manifest cross-check.
"""
import ast
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


up_src = (SKILLS_DIR / "skill_upload.py").read_text(encoding="utf-8")
tree = ast.parse(up_src)


# ── [1] AST: OUTPUT_DIR module-level 代入が存在しない ─────────
print("[1] AST: module-level OUTPUT_DIR 代入が存在しない")
found_output_dir_assign = False
for n in tree.body:
    if isinstance(n, ast.Assign):
        for t in n.targets:
            if isinstance(t, ast.Name) and t.id == "OUTPUT_DIR":
                found_output_dir_assign = True
                break
    if found_output_dir_assign:
        break
expect(not found_output_dir_assign,
       "module-level OUTPUT_DIR 代入が削除されている")


# ── [2] AST: run_upload 内 `output_dir = run_dir.parent` ─────
print("[2] AST: run_upload 内 `output_dir = run_dir.parent`")
run_fn = None
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name == "run_upload":
        run_fn = n
        break
expect(run_fn is not None, "run_upload 関数が存在")
has_output_dir_assign = False
if run_fn is not None:
    for x in ast.walk(run_fn):
        if (isinstance(x, ast.Assign)
                and len(x.targets) == 1
                and isinstance(x.targets[0], ast.Name)
                and x.targets[0].id == "output_dir"
                and isinstance(x.value, ast.Attribute)
                and x.value.attr == "parent"
                and isinstance(x.value.value, ast.Name)
                and x.value.value.id == "run_dir"):
            has_output_dir_assign = True
            break
expect(has_output_dir_assign,
       "run_upload 内に `output_dir = run_dir.parent` 代入あり")


# ── [3] AST: generate_community_post(..., output_dir) ────────
print("[3] AST: run_upload 内 generate_community_post(..., output_dir)")
has_gcp_call = False
if run_fn is not None:
    for x in ast.walk(run_fn):
        if (isinstance(x, ast.Call)
                and isinstance(x.func, ast.Name)
                and x.func.id == "generate_community_post"
                and len(x.args) >= 4
                and isinstance(x.args[3], ast.Name)
                and x.args[3].id == "output_dir"):
            has_gcp_call = True
            break
expect(has_gcp_call,
       "run_upload 内に generate_community_post(..., output_dir) 呼び出しあり")


# ── [4] AST: main() 内 --channel argparse ────────────────────
print("[4] AST: main() 内 parser.add_argument('--channel', ...)")
main_fn = None
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name == "main":
        main_fn = n
        break
expect(main_fn is not None, "main 関数が存在")
has_channel_arg = False
if main_fn is not None:
    for x in ast.walk(main_fn):
        if (isinstance(x, ast.Call)
                and isinstance(x.func, ast.Attribute)
                and x.func.attr == "add_argument"
                and x.args
                and isinstance(x.args[0], ast.Constant)
                and x.args[0].value == "--channel"):
            has_channel_arg = True
            break
expect(has_channel_arg, "main() に --channel argparse 引数あり")


# ── [5] AST: main() 内 load_channel(args.channel) ────────────
print("[5] AST: main() 内 load_channel(args.channel)")
has_load_channel = False
if main_fn is not None:
    for x in ast.walk(main_fn):
        if (isinstance(x, ast.Call)
                and isinstance(x.func, ast.Name)
                and x.func.id == "load_channel"
                and x.args
                and isinstance(x.args[0], ast.Attribute)
                and x.args[0].attr == "channel"):
            has_load_channel = True
            break
expect(has_load_channel, "main() に load_channel(args.channel) 呼び出しあり")


# ── [6] AST: main() 内 manifest.channel_id cross-check ───────
print("[6] AST: main() 内 manifest.channel_id vs args.channel cross-check")
has_cross_check = False
if main_fn is not None:
    src = ast.unparse(main_fn) if hasattr(ast, "unparse") else ""
    # manifest.channel_id を get で取り, args.channel と比較するロジックが存在
    has_cross_check = (
        "channel_id" in src
        and "_manifest_channel" in src
        and "args.channel" in src
    )
expect(has_cross_check,
       "main() に manifest.channel_id と args.channel の cross-check あり")


# ── [7] AST: main() 内 invariant guard ───────────────────────
print("[7] AST: main() 内 invariant guard (run_dir.parent vs output_dir)")
has_guard = False
if main_fn is not None:
    has_run_dir_resolve = False
    has_output_dir_resolve = False
    for x in ast.walk(main_fn):
        if (isinstance(x, ast.Call)
                and isinstance(x.func, ast.Attribute)
                and x.func.attr == "resolve"):
            src = ast.unparse(x) if hasattr(ast, "unparse") else ""
            if "args.run_dir" in src:
                has_run_dir_resolve = True
            if "_output_dir" in src:
                has_output_dir_resolve = True
    has_guard = has_run_dir_resolve and has_output_dir_resolve
expect(has_guard,
       "main() に Path(args.run_dir).resolve() + _output_dir.resolve() 比較あり")


# ── [8] AST: main() 内 run_upload(_run_dir_resolved, ...) ────
print("[8] AST: main() 内 run_upload(_run_dir_resolved, ...) 呼び出し")
has_resolved_call = False
if main_fn is not None:
    for x in ast.walk(main_fn):
        if (isinstance(x, ast.Call)
                and isinstance(x.func, ast.Name)
                and x.func.id == "run_upload"
                and x.args
                and isinstance(x.args[0], ast.Name)
                and x.args[0].id == "_run_dir_resolved"):
            has_resolved_call = True
            break
expect(has_resolved_call,
       "main() に run_upload(_run_dir_resolved, ...) 呼び出しあり (symlink 整合)")


# ── [9] 同等再現: health config output_dir ───────────────────
print("[9] 同等再現: health config output_dir")
from _channel import load_channel
cfg = load_channel("health")

new_output = PROJECT_ROOT / cfg.paths.output_subdir
old_output = PROJECT_ROOT / "output"

expect(new_output == old_output,
       f"health output_dir bit-identical ({new_output})")


# ── [10] 実測: skill_upload.py --help ────────────────────────
print("[10] 実測: python -m skills.skill_upload --help → exit 0 + --channel 表示")
py_exe = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe")
if not py_exe.exists():
    py_exe = Path(sys.executable)
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"

res_help = subprocess.run(
    [str(py_exe), "-X", "utf8", "-m", "skills.skill_upload", "--help"],
    cwd=str(SCRIPTS_DIR),
    env=env,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
expect(res_help.returncode == 0,
       f"--help exit 0 (got {res_help.returncode}) stderr={res_help.stderr[:200]}")
expect("--channel" in res_help.stdout,
       "--help 出力に --channel が含まれる")


# ── [11] 実測: 不正 --channel → argparse reject ───────────────
print("[11] 実測: 不正 --channel → argparse reject (exit 2)")
res_bad = subprocess.run(
    [str(py_exe), "-X", "utf8", "-m", "skills.skill_upload",
     "--run-dir", "dummy", "--channel", "bogus"],
    cwd=str(SCRIPTS_DIR),
    env=env,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
expect(res_bad.returncode == 2,
       f"invalid --channel exit 2 (got {res_bad.returncode})")
expect("invalid choice" in res_bad.stderr or "choices" in res_bad.stderr,
       "stderr に argparse choices エラー文言")


# ── [12] 実測: invariant guard (run_dir.parent != output_dir → exit 1) ──
# upload は先に manifest.channel_id cross-check を通る必要があるため, 有効な
# pipeline.json をもつ tempdir を作って guard 段階まで到達させる.
print("[12] 実測: --run-dir が output_dir 外 → fail-closed exit 1")
import json as _json
with tempfile.TemporaryDirectory() as _td:
    _bogus_run = Path(_td) / "20260412_000000_test"
    _bogus_run.mkdir()
    # manifest.channel_id='health' の minimal pipeline.json を置く.
    # (main() の load_manifest を通して args.channel='health' と一致させる)
    (_bogus_run / "pipeline.json").write_text(
        _json.dumps({"channel_id": "health", "phases": {}}),
        encoding="utf-8",
    )
    res_guard = subprocess.run(
        [str(py_exe), "-X", "utf8", "-m", "skills.skill_upload",
         "--run-dir", str(_bogus_run), "--channel", "health"],
        cwd=str(SCRIPTS_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
expect(res_guard.returncode == 1,
       f"bogus --run-dir exit 1 (got {res_guard.returncode}) "
       f"stdout={res_guard.stdout[:200]} stderr={res_guard.stderr[:200]}")
expect("output_dir" in res_guard.stdout or "output_dir" in res_guard.stderr,
       "エラー文言に output_dir が含まれる")


# ── [13] 実測: manifest.channel_id mismatch → cross-check fail-closed ──
# Codex Round2 指摘: cross-check の実測が無い.
# manifest.channel_id='creatures' と --channel=health で不一致 → exit 1.
print("[13] 実測: manifest.channel_id と --channel 不一致 → exit 1")
with tempfile.TemporaryDirectory() as _td2:
    _mm_run = Path(_td2) / "20260412_000000_mismatch"
    _mm_run.mkdir()
    (_mm_run / "pipeline.json").write_text(
        _json.dumps({"channel_id": "creatures", "phases": {}}),
        encoding="utf-8",
    )
    res_mm = subprocess.run(
        [str(py_exe), "-X", "utf8", "-m", "skills.skill_upload",
         "--run-dir", str(_mm_run), "--channel", "health"],
        cwd=str(SCRIPTS_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
expect(res_mm.returncode == 1,
       f"mismatch --channel exit 1 (got {res_mm.returncode}) "
       f"stdout={res_mm.stdout[:200]} stderr={res_mm.stderr[:200]}")
expect("manifest.channel_id" in res_mm.stdout or "manifest.channel_id" in res_mm.stderr,
       "エラー文言に manifest.channel_id が含まれる")
expect("creatures" in res_mm.stdout or "creatures" in res_mm.stderr,
       "エラー文言に不一致 channel 名 (creatures) が含まれる")


# ── 結果 ──────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3D5C4: skill_upload が channel config から paths を正しく解決")
    sys.exit(0)
