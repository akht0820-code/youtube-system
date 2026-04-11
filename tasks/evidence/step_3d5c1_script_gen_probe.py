"""Step 3-δ.5c-1 probe: skill_script_gen.py を channel-aware 化.

検証:
[1] AST: module-level の OUTPUT_DIR 代入が存在しない
[2] AST: save_script signature == (theme, script, output_dir)
[3] AST: _pick_theme_from_file signature == (themes_path, output_dir)
[4] AST: run_script_gen 内に save_script(theme, script, output_dir) の呼び出し
         (正確には args 3つ, かつ 3番目が output_dir という Name)
[5] AST: main() 内 parser.add_argument('--channel', ...)
[6] AST: main() 内 load_channel(args.channel) の呼び出し
[7] 同等再現: health config から themes_path / output_dir が旧 hardcode と等価
[8] 実測 (subprocess): skill_script_gen.py --help が exit 0 で --channel を表示
[9] 実測 (subprocess): skill_script_gen.py --channel invalid → argparse reject (exit 2)
[10] 実測 (subprocess): --run-dir が channel の output_dir 直下でない → fail-closed exit 1

前提:
- Step 3-δ.1-5b regression zero.
- 本 Step は invariant `run_dir.parent == output_dir` 維持. 相対 outputs
  解決モデルは横断設計で別 Step 対象.
"""
import ast
import os
import subprocess
import sys
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


sg_src = (SKILLS_DIR / "skill_script_gen.py").read_text(encoding="utf-8")
tree = ast.parse(sg_src)


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


# ── [2] AST: save_script signature ───────────────────────────
print("[2] AST: save_script(theme, script, output_dir)")
save_script_fn = None
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name == "save_script":
        save_script_fn = n
        break
expect(save_script_fn is not None, "save_script 関数が存在")
if save_script_fn is not None:
    actual = [a.arg for a in save_script_fn.args.args]
    expect(actual == ["theme", "script", "output_dir"],
           f"save_script signature == ['theme','script','output_dir'] (got {actual})")


# ── [3] AST: _pick_theme_from_file signature ─────────────────
print("[3] AST: _pick_theme_from_file(themes_path, output_dir)")
pick_fn = None
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name == "_pick_theme_from_file":
        pick_fn = n
        break
expect(pick_fn is not None, "_pick_theme_from_file 関数が存在")
if pick_fn is not None:
    actual = [a.arg for a in pick_fn.args.args]
    expect(actual == ["themes_path", "output_dir"],
           f"_pick_theme_from_file signature == ['themes_path','output_dir'] (got {actual})")


# ── [4] AST: run_script_gen 内で save_script(theme, script, output_dir) ──
print("[4] AST: run_script_gen 内に save_script(theme, script, output_dir) 呼び出し")
run_fn = None
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name == "run_script_gen":
        run_fn = n
        break
expect(run_fn is not None, "run_script_gen 関数が存在")
has_save_call = False
if run_fn is not None:
    for x in ast.walk(run_fn):
        if (isinstance(x, ast.Call)
                and isinstance(x.func, ast.Name)
                and x.func.id == "save_script"
                and len(x.args) == 3
                and isinstance(x.args[2], ast.Name)
                and x.args[2].id == "output_dir"):
            has_save_call = True
            break
expect(has_save_call,
       "run_script_gen 内に save_script(theme, script, output_dir) 呼び出しあり")


# ── [5] AST: main() 内 --channel argparse ────────────────────
print("[5] AST: main() 内 parser.add_argument('--channel', ...)")
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


# ── [6] AST: main() 内 load_channel(args.channel) ────────────
print("[6] AST: main() 内 load_channel(args.channel)")
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


# ── [7] 同等再現: health config paths ────────────────────────
print("[7] 同等再現: health config themes_path / output_dir")
from _channel import load_channel
cfg = load_channel("health")

new_themes = PROJECT_ROOT / cfg.paths.themes_file
new_output = PROJECT_ROOT / cfg.paths.output_subdir

old_themes = PROJECT_ROOT / "themes.txt"
old_output = PROJECT_ROOT / "output"

expect(new_themes == old_themes,
       f"health themes_path bit-identical ({new_themes})")
expect(new_output == old_output,
       f"health output_dir bit-identical ({new_output})")


# ── [8] 実測: skill_script_gen.py --help ──────────────────────
print("[8] 実測: python -m skills.skill_script_gen --help → exit 0 + --channel 表示")
py_exe = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe")
if not py_exe.exists():
    py_exe = Path(sys.executable)
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"

res_help = subprocess.run(
    [str(py_exe), "-X", "utf8", "-m", "skills.skill_script_gen", "--help"],
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


# ── [9] 実測: 不正 --channel → argparse reject ────────────────
print("[9] 実測: 不正 --channel → argparse reject (exit 2)")
res_bad = subprocess.run(
    [str(py_exe), "-X", "utf8", "-m", "skills.skill_script_gen",
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


# ── [10] 実測: invariant guard (run_dir.parent != output_dir → exit 1) ──
print("[10] 実測: --run-dir が output_dir 外 → fail-closed exit 1")
import tempfile
with tempfile.TemporaryDirectory() as _td:
    _bogus_run = Path(_td) / "20260412_000000_test"
    _bogus_run.mkdir()
    res_guard = subprocess.run(
        [str(py_exe), "-X", "utf8", "-m", "skills.skill_script_gen",
         "--run-dir", str(_bogus_run), "--theme", "dummy", "--channel", "health"],
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
    print("\nPROBE_OK_STEP_3D5C1: skill_script_gen が channel config から paths を正しく解決")
    sys.exit(0)
