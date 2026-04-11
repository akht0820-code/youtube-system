"""Step 3-δ.4 probe: generator.py の OUTPUT_DIR / 3 helper を channel-aware 化.

generator.main() は実行しない (副作用を持つため). AST + 同等再現 + 静的解析で
以下を検証する:

[1] AST: OUTPUT_DIR module-level 定数が削除されていること
[2] AST: _pick_theme_from_file / _create_run_dir / _find_resumable_run の
        signature に output_dir 引数が追加されていること
[3] AST: main() 内に _output_dir = _project_root / channel.paths.output_subdir が
        あり, 3 call site が全て _output_dir を渡していること
[4] 同等再現: health / creatures の output_dir 解決が期待値になること
[5] health bit-identical: _project_root / "output" が旧 OUTPUT_DIR と Path 等価

前提:
- Step 3-α/β/γ/3-δ.1/3-δ.2/3-δ.3 全て regression zero
- step_2c probe の signature check も同じ commit で ['themes_path','output_dir'] に更新
"""
import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

errors = []


def expect(cond, msg):
    if cond:
        print(f"  [OK] {msg}")
    else:
        print(f"  [NG] {msg}")
        errors.append(msg)


gen_src = (SCRIPTS_DIR / "generator.py").read_text(encoding="utf-8")
tree = ast.parse(gen_src)


# ── [1] AST: OUTPUT_DIR module-level 定数が削除されている ────────
print("[1] AST: OUTPUT_DIR module-level 定数が削除")
module_assigns = [n for n in tree.body if isinstance(n, ast.Assign)]
module_names = set()
for n in module_assigns:
    for target in n.targets:
        if isinstance(target, ast.Name):
            module_names.add(target.id)
expect("OUTPUT_DIR" not in module_names,
       f"module-level OUTPUT_DIR 削除済 (got module_names={sorted(module_names)})")


# ── [2] AST: 3 helper の signature 検査 ─────────────────────
print("[2] AST: 3 helper の signature")
helper_specs = {
    "_pick_theme_from_file": ["themes_path", "output_dir"],
    "_create_run_dir": ["theme", "output_dir"],
    "_find_resumable_run": ["output_dir"],
}
found_helpers = {}
for n in tree.body:
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


# ── [3] AST: main() 内の _output_dir 解決 + 3 call site ────────
print("[3] AST: main() の _output_dir 解決 + call site")
main_func = None
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name == "main":
        main_func = n
        break
expect(main_func is not None, "main 関数が存在")

if main_func is not None:
    # _output_dir = _project_root / channel.paths.output_subdir
    has_output_dir_assign = False
    for n in ast.walk(main_func):
        if (isinstance(n, ast.Assign)
                and len(n.targets) == 1
                and isinstance(n.targets[0], ast.Name)
                and n.targets[0].id == "_output_dir"):
            # 右辺: _project_root / channel.paths.output_subdir
            if isinstance(n.value, ast.BinOp) and isinstance(n.value.op, ast.Div):
                left = n.value.left
                right = n.value.right
                if (isinstance(left, ast.Name) and left.id == "_project_root"
                        and isinstance(right, ast.Attribute)
                        and isinstance(right.value, ast.Attribute)
                        and right.attr == "output_subdir"
                        and right.value.attr == "paths"):
                    has_output_dir_assign = True
                    break
    expect(has_output_dir_assign,
           "main() 内に _output_dir = _project_root / channel.paths.output_subdir")

    # call site 検査: _find_resumable_run / _pick_theme_from_file / _create_run_dir
    # 全て _output_dir を引数に渡していること
    call_expectations = {
        "_find_resumable_run": {"pos_index": 0, "argname": "_output_dir"},
        "_pick_theme_from_file": {"pos_index": 1, "argname": "_output_dir"},
        "_create_run_dir": {"pos_index": 1, "argname": "_output_dir"},
    }
    found_calls = {k: False for k in call_expectations}
    for n in ast.walk(main_func):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id in call_expectations):
            spec = call_expectations[n.func.id]
            idx = spec["pos_index"]
            if len(n.args) > idx:
                arg = n.args[idx]
                if isinstance(arg, ast.Name) and arg.id == spec["argname"]:
                    found_calls[n.func.id] = True
    for name, ok in found_calls.items():
        expect(ok, f"main() 内の {name}() call が _output_dir を positional 引数で渡す")


# ── [4] 同等再現: health / creatures の output_dir 解決 ───────
print("[4] 同等再現: health / creatures output_dir")
from _channel import load_channel

cfg_h = load_channel("health")
out_h = PROJECT_ROOT / cfg_h.paths.output_subdir
expect(out_h == PROJECT_ROOT / "output",
       f"health output_dir == PROJECT_ROOT/output (got {out_h})")
expect(cfg_h.paths.output_subdir == "output",
       f"health output_subdir == 'output' (got {cfg_h.paths.output_subdir!r})")

cfg_c = load_channel("creatures")
out_c = PROJECT_ROOT / cfg_c.paths.output_subdir
expect(out_c == PROJECT_ROOT / "output_creatures",
       f"creatures output_dir == PROJECT_ROOT/output_creatures (got {out_c})")
expect(cfg_c.paths.output_subdir == "output_creatures",
       f"creatures output_subdir == 'output_creatures' (got {cfg_c.paths.output_subdir!r})")


# ── [5] health bit-identical: 旧 OUTPUT_DIR との Path 等価 ────
print("[5] health bit-identical 検証 (旧 OUTPUT_DIR との等価)")
# 旧実装: OUTPUT_DIR = Path(__file__).parent.parent / "output"
# scripts/generator.py のあった場所なので scripts/../output == PROJECT_ROOT/output
old_output_dir_equivalent = (SCRIPTS_DIR / "generator.py").parent.parent / "output"
expect(old_output_dir_equivalent == out_h,
       f"旧 OUTPUT_DIR equivalent == new _output_dir(health) (got {old_output_dir_equivalent} vs {out_h})")
expect(str(old_output_dir_equivalent) == str(out_h),
       f"str() 比較でも同一 (旧={old_output_dir_equivalent} 新={out_h})")


# ── 結果 ──────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3D4: generator.py が channel config から output_dir を正しく解決")
    sys.exit(0)
