"""Step 3-δ.5a probe: skill_cache_cleanup.py の OUTPUT_DIR / 5 helper を channel-aware 化.

検証:
[1] AST: skill_cache_cleanup.py の module-level OUTPUT_DIR 定数が削除されている
[2] AST: 5 helper + run_cache_cleanup の signature に output_dir が追加されている
[3] AST: run_cache_cleanup 本体に `run_dir is None and output_dir is None` で
        TypeError を raise する分岐が存在
[4] AST: skill_cache_cleanup.__main__ に --channel 引数が追加されている
[5] AST: generator.py:280 近傍が run_cache_cleanup(output_dir=_output_dir) を呼ぶ
[6] AST: run_monitor.py:322 近傍が run_cache_cleanup(output_dir=OUTPUT_DIR) を呼ぶ
[7] 実測: run_cache_cleanup() 引数なし呼び出しが TypeError を raise
[8] 実測: run_cache_cleanup(output_dir=TMP, dry_run=True) が正常に辞書返却
[9] 実測: health output_dir 解決 (BASE_DIR / cfg.paths.output_subdir) が旧等価

前提:
- Step 3-δ.1 / 3-δ.2 / 3-δ.3 / 3-δ.4 全て regression zero
- generator.py main() は実行しない (副作用を持つため)
"""
import ast
import inspect
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


cache_src = (SKILLS_DIR / "skill_cache_cleanup.py").read_text(encoding="utf-8")
cache_tree = ast.parse(cache_src)


# ── [1] AST: OUTPUT_DIR module-level 定数削除 ─────────────────
print("[1] AST: skill_cache_cleanup.py OUTPUT_DIR module-level 定数削除")
module_assigns = [n for n in cache_tree.body if isinstance(n, ast.Assign)]
module_names = set()
for n in module_assigns:
    for target in n.targets:
        if isinstance(target, ast.Name):
            module_names.add(target.id)
expect("OUTPUT_DIR" not in module_names,
       f"module-level OUTPUT_DIR 削除済 (module_names keys count={len(module_names)})")


# ── [2] AST: 5 helper + run_cache_cleanup signature ──────────
print("[2] AST: helper signatures")
helper_specs = {
    "_get_in_progress_dirs": ["output_dir"],
    "cleanup_temp_files": ["output_dir", "dry_run"],
    "cleanup_old_wav_dirs": ["output_dir", "dry_run"],
    "cleanup_old_root_videos": ["output_dir", "dry_run"],
    "cleanup_failed_pipelines": ["output_dir", "dry_run"],
    "run_cache_cleanup": ["run_dir", "dry_run", "output_dir"],
}
found_helpers = {}
for n in cache_tree.body:
    if isinstance(n, ast.FunctionDef) and n.name in helper_specs:
        found_helpers[n.name] = n
for name, expected_params in helper_specs.items():
    func = found_helpers.get(name)
    expect(func is not None, f"{name} 関数が存在")
    if func is None:
        continue
    actual_params = [a.arg for a in func.args.args]
    expect(actual_params == expected_params,
           f"{name} signature == {expected_params} (got {actual_params})")


# ── [3] AST: run_cache_cleanup に TypeError 分岐 ──────────────
print("[3] AST: run_cache_cleanup TypeError 分岐 (fail-closed)")
run_func = found_helpers.get("run_cache_cleanup")
has_type_error_raise = False
if run_func is not None:
    for n in ast.walk(run_func):
        if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call):
            if isinstance(n.exc.func, ast.Name) and n.exc.func.id == "TypeError":
                has_type_error_raise = True
                break
expect(has_type_error_raise,
       "run_cache_cleanup 本体に raise TypeError(...) が存在")


# ── [4] AST: __main__ に --channel 引数 ──────────────────────
print("[4] AST: __main__ --channel 引数追加")
# add_argument('--channel', ...) の Call を探索
has_channel_arg = False
for n in ast.walk(cache_tree):
    if (isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "add_argument"):
        if n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "--channel":
            has_channel_arg = True
            break
expect(has_channel_arg,
       "__main__ に parser.add_argument('--channel', ...) が存在")


# ── [5] AST: generator.py:280 近傍 run_cache_cleanup(output_dir=_output_dir) ──
print("[5] AST: generator.py run_cache_cleanup(output_dir=_output_dir)")
gen_tree = ast.parse((SCRIPTS_DIR / "generator.py").read_text(encoding="utf-8"))
has_gen_call = False
for n in ast.walk(gen_tree):
    if (isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "run_cache_cleanup"):
        for kw in n.keywords:
            if (kw.arg == "output_dir"
                    and isinstance(kw.value, ast.Name)
                    and kw.value.id == "_output_dir"):
                has_gen_call = True
                break
        if has_gen_call:
            break
expect(has_gen_call,
       "generator.py 内に run_cache_cleanup(output_dir=_output_dir) call が存在")


# ── [6] AST: run_monitor.py run_cache_cleanup(output_dir=OUTPUT_DIR) ──
print("[6] AST: run_monitor.py run_cache_cleanup(output_dir=OUTPUT_DIR)")
mon_tree = ast.parse((SCRIPTS_DIR / "run_monitor.py").read_text(encoding="utf-8"))
has_mon_call = False
for n in ast.walk(mon_tree):
    if (isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "run_cache_cleanup"):
        for kw in n.keywords:
            if (kw.arg == "output_dir"
                    and isinstance(kw.value, ast.Name)
                    and kw.value.id == "OUTPUT_DIR"):
                has_mon_call = True
                break
        if has_mon_call:
            break
expect(has_mon_call,
       "run_monitor.py 内に run_cache_cleanup(output_dir=OUTPUT_DIR) call が存在")


# ── [7] 実測: run_cache_cleanup() 引数なしで TypeError ───────
print("[7] 実測: run_cache_cleanup() 引数なし → TypeError")
# skills パッケージとして import
sys.path.insert(0, str(SCRIPTS_DIR))
from skills.skill_cache_cleanup import run_cache_cleanup

raised_type_error = False
try:
    run_cache_cleanup()
except TypeError:
    raised_type_error = True
except Exception as e:
    print(f"  [NG] 予期せぬ例外: {type(e).__name__}: {e}")
expect(raised_type_error,
       "run_cache_cleanup() 引数なし呼び出しで TypeError raise")


# ── [8] 実測: output_dir 指定 dry_run 呼び出しが dict 返却 ────
print("[8] 実測: run_cache_cleanup(output_dir=TMP, dry_run=True) が dict 返却")
with tempfile.TemporaryDirectory() as tmp:
    tmp_path = Path(tmp)
    try:
        report = run_cache_cleanup(output_dir=tmp_path, dry_run=True)
        expect(isinstance(report, dict),
               f"return type == dict (got {type(report).__name__})")
        expect("temp_files" in report and "old_wav_dirs" in report,
               f"report keys contain temp_files/old_wav_dirs (got {list(report.keys())})")
    except Exception as e:
        expect(False, f"output_dir 指定呼び出しで例外: {type(e).__name__}: {e}")


# ── [9] 実測: health output_dir 解決が旧等価 ─────────────────
print("[9] 実測: health output_dir 解決 bit-identical")
from _channel import load_channel
cfg_h = load_channel("health")
new_out = PROJECT_ROOT / cfg_h.paths.output_subdir
old_equiv = PROJECT_ROOT / "output"
expect(new_out == old_equiv,
       f"health output_dir == PROJECT_ROOT/output (got {new_out})")
expect(str(new_out) == str(old_equiv),
       f"str 等価 (new={new_out} old={old_equiv})")


# ── 結果 ──────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3D5A: skill_cache_cleanup が channel config から output_dir を正しく受け取る")
    sys.exit(0)
