"""Step 3-δ.2 probe: skill_upload.py が manifest['channel_id'] を consumer することを検証.

設計上は run_upload() の冒頭 10 行 (channel_id resolve + load_channel) のみが本 Step の
差分. run_upload 全体は video_build / thumbnail 成果物を要求し副作用 (upload, LLM,
YouTube API) を持つため, 本 probe では resolve ロジックを AST 解析 + 同等再現 で検証する.

前提:
- Step 3-δ.1 (commit 49e25f5) で create_manifest に channel_id 記録済
- Step 3-α (commit a53128b) で creatures.json 追加済

検証項目:
[1] AST: skill_upload.py の run_upload 内に load_manifest 先行呼び出しと
    channel_id resolve ロジックが存在すること
[2] resolve 同等再現: 以下 7 ケースで期待通りの挙動
    (a) health manifest → _channel_id == 'health', _cfg.id == 'health'
    (b) creatures manifest → _channel_id == 'creatures', _cfg.id == 'creatures'
    (c) 旧 manifest (channel_id key 不在) → 'health' フォールバック
    (d) channel_id=None → RuntimeError (manifest.channel_id 不正)
    (e) channel_id='' → RuntimeError
    (f) channel_id=0 (int) → RuntimeError
    (g) channel_id='unknown_channel_xyz' → ChannelLoadError → RuntimeError wrap
[3] bit-identical: health manifest で得られる _lock_path が
    Step 2-ε の baseline (PROJECT_ROOT/logs/last_upload_date.txt) と一致
"""
import ast
import json
import sys
import tempfile
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


# ── [1] AST 検証: skill_upload.py の run_upload 内構造 ─────────
print("[1] AST 検証 (skill_upload.run_upload 内構造)")
skill_upload_src = (SCRIPTS_DIR / "skills" / "skill_upload.py").read_text(encoding="utf-8")
tree = ast.parse(skill_upload_src)
run_upload_func = None
for node in ast.walk(tree):
    if isinstance(node, ast.FunctionDef) and node.name == "run_upload":
        run_upload_func = node
        break
expect(run_upload_func is not None, "run_upload 関数が存在")

if run_upload_func is not None:
    # run_upload 内で load_manifest(run_dir) 呼び出しが >= 1 回存在すること.
    # Codex adversarial 指摘: 回数固定は不要 (snapshot divergence 防止のため
    # 実装は前提チェック後に manifest を再読込する = 複数回読む設計が正解)
    load_manifest_calls = [
        n for n in ast.walk(run_upload_func)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "load_manifest"
    ]
    expect(len(load_manifest_calls) >= 1,
           f"run_upload 内に load_manifest 呼び出しあり (got {len(load_manifest_calls)})")

    # "channel_id" literal が run_upload の body 内に存在すること
    has_channel_id_key = any(
        isinstance(n, ast.Constant) and n.value == "channel_id"
        for n in ast.walk(run_upload_func)
    )
    expect(has_channel_id_key, "run_upload 内に 'channel_id' literal が存在")

    # load_channel が literal 'health' 固定で呼ばれていないこと.
    # positional / keyword 両対応 (Codex adversarial 指摘).
    load_channel_calls = [
        n for n in ast.walk(run_upload_func)
        if isinstance(n, ast.Call)
        and isinstance(n.func, ast.Name)
        and n.func.id == "load_channel"
    ]
    expect(len(load_channel_calls) >= 1, "run_upload 内に load_channel 呼び出しあり")
    for call in load_channel_calls:
        # positional 第1引数が literal 'health' の場合だけ NG
        hardcoded_pos = (
            len(call.args) >= 1
            and isinstance(call.args[0], ast.Constant)
            and call.args[0].value == "health"
        )
        # kwarg channel_id='health' の場合も NG
        hardcoded_kw = any(
            kw.arg == "channel_id"
            and isinstance(kw.value, ast.Constant)
            and kw.value.value == "health"
            for kw in call.keywords
        )
        expect(not (hardcoded_pos or hardcoded_kw),
               "load_channel 呼び出しが literal 'health' 固定でない (positional / kwarg 両方)")


# ── [2] resolve 同等再現 ────────────────────────────────────
# run_upload 冒頭と同じロジックを関数化して検証する
from _channel import load_channel, ChannelLoadError


def resolve_channel_id(manifest: dict) -> str:
    """run_upload の channel_id resolve ロジックを同等再現 (probe 用)."""
    if "channel_id" not in manifest:
        return "health"
    _channel_id = manifest["channel_id"]
    if not isinstance(_channel_id, str) or not _channel_id:
        raise RuntimeError(f"manifest.channel_id 不正 (upload): {_channel_id!r}")
    return _channel_id


def resolve_and_load(manifest: dict):
    _channel_id = resolve_channel_id(manifest)
    try:
        _cfg = load_channel(_channel_id)
    except (ImportError, ChannelLoadError) as _ce:
        raise RuntimeError(
            f"チャンネル設定読込失敗 (upload, channel={_channel_id}): {_ce}"
        ) from _ce
    return _channel_id, _cfg


# (a) health manifest
print("[2a] health manifest (生産経路)")
cid, cfg = resolve_and_load({"channel_id": "health", "run_id": "r", "theme": "t"})
expect(cid == "health", f"_channel_id == 'health' (got {cid!r})")
expect(cfg.id == "health", f"_cfg.id == 'health' (got {cfg.id!r})")

# (b) creatures manifest
print("[2b] creatures manifest (将来 Step 3-δ.5)")
cid, cfg = resolve_and_load({"channel_id": "creatures", "run_id": "r", "theme": "t"})
expect(cid == "creatures", f"_channel_id == 'creatures' (got {cid!r})")
expect(cfg.id == "creatures", f"_cfg.id == 'creatures' (got {cfg.id!r})")

# (c) 旧 manifest (channel_id key 不在)
print("[2c] 旧 manifest (channel_id key 不在) → 'health' フォールバック")
cid, cfg = resolve_and_load({"run_id": "legacy", "theme": "legacy"})
expect(cid == "health", f"legacy manifest → 'health' (got {cid!r})")
expect(cfg.id == "health", f"legacy manifest _cfg.id == 'health'")

# (d) channel_id=None → RuntimeError
print("[2d] channel_id=None → RuntimeError")
try:
    resolve_channel_id({"channel_id": None, "run_id": "r"})
    expect(False, "channel_id=None で例外なし (想定外)")
except RuntimeError as e:
    expect("channel_id 不正" in str(e), f"channel_id=None で RuntimeError: {e}")

# (e) channel_id='' → RuntimeError
print("[2e] channel_id='' → RuntimeError")
try:
    resolve_channel_id({"channel_id": "", "run_id": "r"})
    expect(False, "channel_id='' で例外なし")
except RuntimeError as e:
    expect("channel_id 不正" in str(e), f"channel_id='' で RuntimeError: {e}")

# (f) channel_id=0 (int) → RuntimeError
print("[2f] channel_id=0 (int) → RuntimeError")
try:
    resolve_channel_id({"channel_id": 0, "run_id": "r"})
    expect(False, "channel_id=0 で例外なし")
except RuntimeError as e:
    expect("channel_id 不正" in str(e), f"channel_id=0 で RuntimeError: {e}")

# (g) channel_id='unknown_channel_xyz' → load_channel fail → RuntimeError wrap
print("[2g] channel_id='unknown_channel_xyz' → RuntimeError wrap (ChannelLoadError 経由)")
try:
    resolve_and_load({"channel_id": "unknown_channel_xyz", "run_id": "r"})
    expect(False, "未知 channel_id で例外なし")
except RuntimeError as e:
    msg = str(e)
    expect("チャンネル設定読込失敗" in msg and "unknown_channel_xyz" in msg,
           f"未知 channel_id で RuntimeError wrap: {msg[:80]}")


# ── [3] bit-identical 検証 ───────────────────────────────
print("[3] health manifest で _lock_path が Step 2-ε baseline と一致")
cid, cfg = resolve_and_load({"channel_id": "health", "run_id": "r", "theme": "t"})
# skill_upload.py と同じパス解決
import importlib.util
skill_upload_path = SCRIPTS_DIR / "skills" / "skill_upload.py"
_lock_path_new = skill_upload_path.parent.parent.parent / cfg.paths.lock_file
_baseline = PROJECT_ROOT / "logs" / "last_upload_date.txt"
expect(_lock_path_new == _baseline,
       f"_lock_path == {_baseline} (got {_lock_path_new})")
expect(cfg.paths.lock_file == "logs/last_upload_date.txt",
       f"cfg.paths.lock_file == 'logs/last_upload_date.txt' (got {cfg.paths.lock_file!r})")


# ── [4] Step 3-δ.1 regression: pipeline.json の channel_id 記録を確認 ────
print("[4] Step 3-δ.1 regression: create_manifest channel_id 記録")
from skills._common import create_manifest, load_manifest

with tempfile.TemporaryDirectory(prefix="step3d2_regression_") as _td:
    run_dir = Path(_td)
    create_manifest(run_dir, theme="t", run_id="r", channel_id="creatures")
    m = load_manifest(run_dir)
    expect(m.get("channel_id") == "creatures",
           "create_manifest(channel_id='creatures') → manifest['channel_id'] == 'creatures'")
    # resolve で繋がること
    cid, cfg = resolve_and_load(m)
    expect(cid == "creatures" and cfg.id == "creatures",
           "resolve chain: create_manifest → load_manifest → resolve → _cfg")


# ── 結果 ──────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3D2: skill_upload が manifest.channel_id を consumer として正しく解決")
    sys.exit(0)
