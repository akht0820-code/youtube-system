"""Step 3-δ.5c-3 probe: skill_metadata.py を channel-aware 化.

検証:
[1] AST: module-level の OUTPUT_DIR 代入が存在しない
[2] AST: main() 内 parser.add_argument('--channel', ...)
[3] AST: main() 内 load_channel(args.channel) の呼び出し
[4] AST: main() 内 invariant guard (run_dir.parent != output_dir)
[5] AST: main() 内 run_metadata(_run_dir_resolved) 呼び出し (canonicalization)
[6] 同等再現: health config output_dir が旧 hardcode と等価
[7] 実測 (subprocess): skill_metadata.py --help が exit 0 で --channel を表示
[8] 実測 (subprocess): skill_metadata.py --channel invalid → argparse reject (exit 2)
[9] 実測 (subprocess): --run-dir が channel の output_dir 直下でない → fail-closed exit 1

前提:
- Step 3-δ.5c-2 commit 96417ec regression zero.
- 本 Step は OUTPUT_DIR dead code 削除 + CLI channel-aware 化のみ.
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


md_src = (SKILLS_DIR / "skill_metadata.py").read_text(encoding="utf-8")
tree = ast.parse(md_src)


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


# ── [2] AST: main() 内 --channel argparse ────────────────────
print("[2] AST: main() 内 parser.add_argument('--channel', ...)")
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


# ── [3] AST: main() 内 load_channel(args.channel) ────────────
print("[3] AST: main() 内 load_channel(args.channel)")
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


# ── [4] AST: main() 内 invariant guard ───────────────────────
print("[4] AST: main() 内 invariant guard (run_dir.parent vs output_dir)")
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


# ── [5] AST: main() 内 run_metadata(_run_dir_resolved) ──────
print("[5] AST: main() 内 run_metadata(_run_dir_resolved) 呼び出し")
has_resolved_call = False
if main_fn is not None:
    for x in ast.walk(main_fn):
        if (isinstance(x, ast.Call)
                and isinstance(x.func, ast.Name)
                and x.func.id == "run_metadata"
                and x.args
                and isinstance(x.args[0], ast.Name)
                and x.args[0].id == "_run_dir_resolved"):
            has_resolved_call = True
            break
expect(has_resolved_call,
       "main() に run_metadata(_run_dir_resolved) 呼び出しあり (symlink 整合)")


# ── [6] 同等再現: health config output_dir ───────────────────
print("[6] 同等再現: health config output_dir")
from _channel import load_channel
cfg = load_channel("health")

new_output = PROJECT_ROOT / cfg.paths.output_subdir
old_output = PROJECT_ROOT / "output"

expect(new_output == old_output,
       f"health output_dir bit-identical ({new_output})")


# ── [7] 実測: skill_metadata.py --help ───────────────────────
print("[7] 実測: python -m skills.skill_metadata --help → exit 0 + --channel 表示")
py_exe = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe")
if not py_exe.exists():
    py_exe = Path(sys.executable)
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"

res_help = subprocess.run(
    [str(py_exe), "-X", "utf8", "-m", "skills.skill_metadata", "--help"],
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


# ── [8] 実測: 不正 --channel → argparse reject ────────────────
print("[8] 実測: 不正 --channel → argparse reject (exit 2)")
res_bad = subprocess.run(
    [str(py_exe), "-X", "utf8", "-m", "skills.skill_metadata",
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


# ── [9] 実測: invariant guard (run_dir.parent != output_dir → exit 1) ──
print("[9] 実測: --run-dir が output_dir 外 → fail-closed exit 1")
with tempfile.TemporaryDirectory() as _td:
    _bogus_run = Path(_td) / "20260412_000000_test"
    _bogus_run.mkdir()
    res_guard = subprocess.run(
        [str(py_exe), "-X", "utf8", "-m", "skills.skill_metadata",
         "--run-dir", str(_bogus_run), "--channel", "health"],
        cwd=str(SCRIPTS_DIR),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
expect(res_guard.returncode == 1,
       f"bogus --run-dir exit 1 (got {res_guard.returncode})")
expect("output_dir" in res_guard.stdout or "output_dir" in res_guard.stderr,
       "エラー文言に output_dir が含まれる")


# ── 結果 ──────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3D5C3: skill_metadata が channel config から paths を正しく解決")
    sys.exit(0)
