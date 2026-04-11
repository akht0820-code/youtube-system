"""Step 3-δ.5b probe: preflight_runtime.py の 3 helper + main() を channel-aware 化.

検証:
[1] AST: 5 helper の signature
   - _check_network() — 不変
   - _check_token_json(token_path) — hardcode 削除
   - _check_credentials(cred_path) — hardcode 削除
   - _check_disk_space() — 不変
   - _check_duplicate_upload(lock_path) — load_channel 削除
[2] AST: main() 内に argparse parser.add_argument('--channel', ...) が存在
[3] AST: main() 内に load_channel(args.channel) の呼び出しが存在
[4] AST: main() 内で _check_network / _check_disk_space が cfg 非依存に呼ばれる
        (より正確には: _run_check("ネットワーク接続", ...) と
         _run_check("ディスク容量", ...) が main() 内に存在)
[5] 同等再現: health config から token/cred/lock paths が旧 hardcode と等価
[6] 実測 (subprocess): python preflight_runtime.py --help が exit 0 で --channel を表示
[7] 実測 (subprocess): python preflight_runtime.py --channel invalid → argparse reject (exit 2)

前提:
- Step 3-δ.1-5a 全て regression zero
- main() は 09:55 task で実行される実本体なので subprocess 実行は --help のみで止める
"""
import ast
import os
import subprocess
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


pf_src = (SCRIPTS_DIR / "preflight_runtime.py").read_text(encoding="utf-8")
tree = ast.parse(pf_src)


# ── [1] AST: 5 helper signatures ─────────────────────────────
print("[1] AST: 5 helper signatures")
helper_specs = {
    "_check_network": [],
    "_check_token_json": ["token_path"],
    "_check_credentials": ["cred_path"],
    "_check_disk_space": [],
    "_check_duplicate_upload": ["lock_path"],
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


# ── [2] AST: main() 内 --channel argparse ────────────────────
print("[2] AST: main() 内 parser.add_argument('--channel', ...)")
main_func = None
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name == "main":
        main_func = n
        break
expect(main_func is not None, "main 関数が存在")

has_channel_arg = False
if main_func is not None:
    for n in ast.walk(main_func):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "add_argument"):
            if n.args and isinstance(n.args[0], ast.Constant) and n.args[0].value == "--channel":
                has_channel_arg = True
                break
expect(has_channel_arg,
       "main() 内に parser.add_argument('--channel', ...) が存在")


# ── [3] AST: main() 内 load_channel(args.channel) ────────────
print("[3] AST: main() 内 load_channel(args.channel)")
has_load_channel_call = False
if main_func is not None:
    for n in ast.walk(main_func):
        if (isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "load_channel"):
            # args.channel を受けているか
            if n.args and isinstance(n.args[0], ast.Attribute):
                if n.args[0].attr == "channel":
                    has_load_channel_call = True
                    break
expect(has_load_channel_call,
       "main() 内に load_channel(args.channel) call が存在")


# ── [4] AST: main() 内 channel 非依存 check が cfg 前に実行 ──
print("[4] AST: network/disk checks は load_channel より前 (channel 非依存保証)")
# 方針: ast.walk の順序は構文順 → load_channel 呼び出しと _check_network/_check_disk_space
# の相対位置を確認
if main_func is not None:
    # 本体 (body) の stmt 順で検索
    load_channel_stmt_idx = None
    network_call_before = False
    disk_call_before = False

    def _find_name_calls(node, target_names):
        """ast.walk で node 内に target_names 関数呼び出しがあれば True を返す"""
        found = set()
        for x in ast.walk(node):
            if isinstance(x, ast.Call):
                # _run_check("ネットワーク接続", _check_network) の
                # 2 番目引数が Name: target_names のいずれか
                if (isinstance(x.func, ast.Name)
                        and x.func.id == "_run_check"
                        and len(x.args) >= 2
                        and isinstance(x.args[1], ast.Name)
                        and x.args[1].id in target_names):
                    found.add(x.args[1].id)
                # 直接 _check_xxx() 呼び出しも受理
                if isinstance(x.func, ast.Name) and x.func.id in target_names:
                    found.add(x.func.id)
        return found

    def _has_load_channel_call(node):
        for x in ast.walk(node):
            if (isinstance(x, ast.Call)
                    and isinstance(x.func, ast.Name)
                    and x.func.id == "load_channel"):
                return True
        return False

    for i, stmt in enumerate(main_func.body):
        if _has_load_channel_call(stmt):
            load_channel_stmt_idx = i
            break

    if load_channel_stmt_idx is None:
        expect(False, "main() body に load_channel 呼び出し stmt が見つからない")
    else:
        # load_channel stmt より前に network/disk チェック呼び出しがあるか
        before_stmts = main_func.body[:load_channel_stmt_idx]
        found_before = set()
        for s in before_stmts:
            found_before |= _find_name_calls(s, {"_check_network", "_check_disk_space"})
        expect("_check_network" in found_before,
               "_check_network は load_channel より前に呼ばれる")
        expect("_check_disk_space" in found_before,
               "_check_disk_space は load_channel より前に呼ばれる")


# ── [5] 同等再現: health config paths ────────────────────────
print("[5] 同等再現: health config token/cred/lock paths")
from _channel import load_channel
cfg = load_channel("health")

new_token = PROJECT_ROOT / cfg.oauth.token
new_cred = PROJECT_ROOT / cfg.oauth.credentials
new_lock = PROJECT_ROOT / cfg.paths.lock_file

old_token = PROJECT_ROOT / "token.json"
old_cred = PROJECT_ROOT / "credentials.json"
old_lock = PROJECT_ROOT / "logs" / "last_upload_date.txt"

expect(new_token == old_token,
       f"health token_path bit-identical ({new_token})")
expect(new_cred == old_cred,
       f"health cred_path bit-identical ({new_cred})")
expect(new_lock == old_lock,
       f"health lock_path bit-identical ({new_lock})")


# ── [6] 実測: preflight_runtime.py --help ─────────────────────
print("[6] 実測: python preflight_runtime.py --help が exit 0 + --channel 表示")
py_exe = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe")
if not py_exe.exists():
    py_exe = Path(sys.executable)
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"

res_help = subprocess.run(
    [str(py_exe), "-X", "utf8", "scripts/preflight_runtime.py", "--help"],
    cwd=str(PROJECT_ROOT),
    env=env,
    capture_output=True,
    text=True,
    encoding="utf-8",
    errors="replace",
)
expect(res_help.returncode == 0,
       f"--help exit 0 (got {res_help.returncode})")
expect("--channel" in res_help.stdout,
       "--help 出力に --channel が含まれる")


# ── [7] 実測: 不正 --channel → argparse reject ────────────────
print("[7] 実測: 不正 --channel → argparse reject (exit 2)")
res_bad = subprocess.run(
    [str(py_exe), "-X", "utf8", "scripts/preflight_runtime.py", "--channel", "bogus"],
    cwd=str(PROJECT_ROOT),
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


# ── 結果 ──────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3D5B: preflight_runtime が channel config から paths を正しく解決")
    sys.exit(0)
