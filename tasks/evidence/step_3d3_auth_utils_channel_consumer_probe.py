"""Step 3-δ.3 probe: auth_utils.get_credentials が channel config から paths を解決.

実際の OAuth flow (InstalledAppFlow / Credentials.from_authorized_user_file) は
副作用を持つため probe では走らせない. 代わりに:
[1] AST: auth_utils.py の get_credentials 第一引数が channel_id:str='health',
        CREDENTIALS_PATH/TOKEN_PATH 定数が削除されていること
[2] paths 解決 同等再現: load_channel() の結果を使って旧定数と等価な paths を得る
[3] 4 callers (youtube_uploader / run_monitor / sheets_writer / analytics_collector)
    が get_credentials を引数なしで呼んでいること (no-op 維持)
[4] channel_id='unknown_xyz' で RuntimeError が発生 (fail-closed)

前提:
- Step 3-α (commit a53128b) で creatures.json 追加済
- Step 3-δ.1 / 3-δ.2 (commits 49e25f5, 4c7a409) regression zero
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


# ── [1] AST 検証: auth_utils.py の構造 ──────────────────────
print("[1] AST 検証 (auth_utils 構造)")
auth_src = (SCRIPTS_DIR / "auth_utils.py").read_text(encoding="utf-8")
tree = ast.parse(auth_src)

# module-level 定数 CREDENTIALS_PATH / TOKEN_PATH が存在しないこと
module_assigns = [
    n for n in tree.body
    if isinstance(n, ast.Assign)
]
module_names = set()
for n in module_assigns:
    for target in n.targets:
        if isinstance(target, ast.Name):
            module_names.add(target.id)
expect("CREDENTIALS_PATH" not in module_names,
       "module-level CREDENTIALS_PATH が削除されている")
expect("TOKEN_PATH" not in module_names,
       "module-level TOKEN_PATH が削除されている")
expect("PROJECT_ROOT" in module_names,
       "PROJECT_ROOT は module-level に維持")
expect("SCOPES" in module_names, "SCOPES は module-level に維持")

# get_credentials 関数の signature を検証
get_creds_func = None
for n in tree.body:
    if isinstance(n, ast.FunctionDef) and n.name == "get_credentials":
        get_creds_func = n
        break
expect(get_creds_func is not None, "get_credentials 関数が存在")

if get_creds_func is not None:
    args = get_creds_func.args.args
    expect(len(args) == 1 and args[0].arg == "channel_id",
           f"get_credentials の第一引数が channel_id (got {[a.arg for a in args]})")
    # default='health' であること
    expect(len(get_creds_func.args.defaults) == 1
           and isinstance(get_creds_func.args.defaults[0], ast.Constant)
           and get_creds_func.args.defaults[0].value == "health",
           "get_credentials の channel_id default が 'health'")

    # load_channel が関数内で呼ばれていること (literal 'health' 固定でないこと)
    load_channel_calls = [
        n for n in ast.walk(get_creds_func)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "load_channel"
    ]
    expect(len(load_channel_calls) >= 1, "get_credentials 内で load_channel を呼ぶ")
    for call in load_channel_calls:
        hardcoded_pos = (
            len(call.args) >= 1
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == "health"
        )
        hardcoded_kw = any(
            kw.arg == "channel_id"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == "health"
            for kw in call.keywords
        )
        expect(not (hardcoded_pos or hardcoded_kw),
               "load_channel が literal 'health' 固定でない (変数由来)")


# ── [2] paths 解決 同等再現 ─────────────────────────────────
print("[2] paths 解決 同等再現 (health / creatures)")
from _channel import load_channel, ChannelLoadError

# health
cfg_h = load_channel("health")
cred_h = PROJECT_ROOT / cfg_h.oauth.credentials
token_h = PROJECT_ROOT / cfg_h.oauth.token
expect(cred_h == PROJECT_ROOT / "credentials.json",
       f"health credentials_path == PROJECT_ROOT/credentials.json (got {cred_h})")
expect(token_h == PROJECT_ROOT / "token.json",
       f"health token_path == PROJECT_ROOT/token.json (got {token_h})")

# creatures
cfg_c = load_channel("creatures")
cred_c = PROJECT_ROOT / cfg_c.oauth.credentials
token_c = PROJECT_ROOT / cfg_c.oauth.token
expect(cred_c == PROJECT_ROOT / "credentials_creatures.json",
       f"creatures credentials_path == PROJECT_ROOT/credentials_creatures.json")
expect(token_c == PROJECT_ROOT / "token_creatures.json",
       f"creatures token_path == PROJECT_ROOT/token_creatures.json")


# ── [3] 4 callers が get_credentials を引数なしで呼んでいること ────
print("[3] 4 callers の呼び出し形 (引数なし = default 'health')")
caller_files = [
    SCRIPTS_DIR / "youtube_uploader.py",
    SCRIPTS_DIR / "run_monitor.py",
    SCRIPTS_DIR / "sheets_writer.py",
    SCRIPTS_DIR / "analytics_collector.py",
]
for caller_path in caller_files:
    src = caller_path.read_text(encoding="utf-8")
    caller_tree = ast.parse(src)
    calls = [
        n for n in ast.walk(caller_tree)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "get_credentials"
    ]
    expect(len(calls) >= 1,
           f"{caller_path.name}: get_credentials 呼び出しあり")
    for call in calls:
        # 引数 0 個 (positional も keyword も無い)
        is_no_arg = len(call.args) == 0 and len(call.keywords) == 0
        expect(is_no_arg,
               f"{caller_path.name}: get_credentials() 引数なし "
               f"(args={len(call.args)}, kwargs={len(call.keywords)})")


# ── [4] 不正 channel_id は RuntimeError ────────────────────
print("[4] channel_id='unknown_xyz' → RuntimeError (fail-closed)")
# get_credentials を実際に呼ぶと OAuth flow が走る可能性があるため,
# 内部の load_channel 部分だけを同等再現で検証する.


def resolve_credentials_paths(channel_id: str):
    """auth_utils.get_credentials の paths 解決部分を同等再現."""
    try:
        from _channel import load_channel as _lc, ChannelLoadError as _cle
    except Exception as _ce_imp:
        raise RuntimeError(
            f"_channel モジュール import 失敗 (auth, channel={channel_id}): {_ce_imp}"
        ) from _ce_imp
    try:
        _cfg = _lc(channel_id)
    except _cle as _ce_load:
        raise RuntimeError(
            f"チャンネル設定読込失敗 (auth, channel={channel_id}): {_ce_load}"
        ) from _ce_load
    return PROJECT_ROOT / _cfg.oauth.credentials, PROJECT_ROOT / _cfg.oauth.token


try:
    resolve_credentials_paths("unknown_xyz")
    expect(False, "unknown channel_id で例外なし")
except RuntimeError as e:
    msg = str(e)
    expect("チャンネル設定読込失敗" in msg and "unknown_xyz" in msg,
           f"unknown channel_id で RuntimeError wrap: {msg[:80]}")

# health / creatures は path 解決が通ること
try:
    h_cred, h_token = resolve_credentials_paths("health")
    expect(h_cred == cred_h and h_token == token_h,
           "resolve_credentials_paths('health') が health の paths と一致")
except Exception as e:
    expect(False, f"health 解決中に例外: {e}")

try:
    c_cred, c_token = resolve_credentials_paths("creatures")
    expect(c_cred == cred_c and c_token == token_c,
           "resolve_credentials_paths('creatures') が creatures の paths と一致")
except Exception as e:
    expect(False, f"creatures 解決中に例外: {e}")


# ── [5] None / '' / 非 str は ChannelLoadError 経路で reject ─────
print("[5] 不正型の channel_id (None / '' / 0) は fail-closed")
for bad in (None, "", 0):
    try:
        resolve_credentials_paths(bad)
        expect(False, f"channel_id={bad!r} で例外なし")
    except RuntimeError as e:
        expect(True, f"channel_id={bad!r} → RuntimeError")
    except Exception as e:
        # ChannelLoadError も RuntimeError の前に来る可能性
        expect(False, f"channel_id={bad!r} → 予期しない例外型: {type(e).__name__}: {e}")


# ── 結果 ──────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3D3: auth_utils が channel config から paths を正しく解決")
    sys.exit(0)
