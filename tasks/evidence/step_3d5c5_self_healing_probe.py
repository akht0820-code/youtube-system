"""Step 3-δ.5c-5 probe: self_healing._fix_delete_token_reauth() channel-aware 化.

検証 (Codex Round1+2 指摘反映後):
[1] AST: _fix_delete_token_reauth 内に load_manifest 呼び出し
[2] AST: _fix_delete_token_reauth 内に `from _channel import load_channel` (local import)
[3] AST: _fix_delete_token_reauth 内に `cfg.oauth.token` 参照
[4] AST: '削除中止' 経路が複数ある (Round2 fail-closed 強化)
[5] 同等再現: health manifest で解決される token_path が PROJECT_ROOT/token.json と一致
[6] 実測: manifest.channel_id='health' 明示 → 削除成功
[7] 実測: manifest 欠損 → legacy fallback 'health' で削除成功
[8] 実測: manifest.channel_id='bogus' (明示 non-health, load fail) → 削除中止
[9] 実測: token.json 既に不在 → "削除不要" 返却 (Round1 Medium point3)
[10] 実測: manifest に channel_id key 不在 → legacy fallback で削除成功
[11] 実測: manifest 破損 JSON → 削除中止 (Round2 High point1)
[12] 実測: manifest.channel_id=123 (int) → 削除中止 (Round2 High point2)
[13] 実測: manifest.channel_id='' (空文字) → 削除中止 (Round2 High point2)
[14] 実測: manifest が dict ではない (list) → 削除中止 (Round2 High point1)

前提:
- Step 3-δ.5c-4 commit 414ed38 regression zero.
- 本 Step は self_healing の単一関数 channel-aware 化.
- health では bit-identical (PROJECT_ROOT/token.json).
- legacy 'health' fallback を許す条件は2つだけ:
  (a) pipeline.json 不在
  (b) pipeline.json は dict で channel_id key 不在
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


sh_src = (SKILLS_DIR / "self_healing.py").read_text(encoding="utf-8")
tree = ast.parse(sh_src)

# _fix_delete_token_reauth 関数を取得
fix_fn = None
for n in ast.walk(tree):
    if isinstance(n, ast.FunctionDef) and n.name == "_fix_delete_token_reauth":
        fix_fn = n
        break
expect(fix_fn is not None, "_fix_delete_token_reauth 関数が存在")


# ── [1] AST: load_manifest 呼び出し ──────────────────────────
print("[1] AST: _fix_delete_token_reauth 内に load_manifest 呼び出し")
has_load_manifest = False
if fix_fn is not None:
    for x in ast.walk(fix_fn):
        if (isinstance(x, ast.Call)
                and isinstance(x.func, ast.Name)
                and x.func.id == "load_manifest"):
            has_load_manifest = True
            break
expect(has_load_manifest, "_fix_delete_token_reauth 内で load_manifest(run_dir) 呼び出し")


# ── [2] AST: from _channel import load_channel (local import) ─
print("[2] AST: _fix_delete_token_reauth 内に local import _channel")
has_local_import = False
if fix_fn is not None:
    for x in ast.walk(fix_fn):
        if isinstance(x, ast.ImportFrom) and x.module == "_channel":
            names = [a.name for a in x.names]
            if "load_channel" in names and "ChannelLoadError" in names:
                has_local_import = True
                break
expect(has_local_import,
       "_fix_delete_token_reauth 内に from _channel import load_channel, ChannelLoadError")


# ── [3] AST: cfg.oauth.token 参照 ─────────────────────────────
print("[3] AST: _fix_delete_token_reauth 内に cfg.oauth.token 参照")
has_oauth_token = False
if fix_fn is not None:
    src = ast.unparse(fix_fn) if hasattr(ast, "unparse") else ""
    has_oauth_token = "oauth.token" in src
expect(has_oauth_token, "_fix_delete_token_reauth 内に cfg.oauth.token 参照")


# ── [4] AST: '削除中止' 複数経路 (Round2 fail-closed) ─────────
print("[4] AST: '削除中止' 経路が複数ある (Round2 fail-closed)")
chushi_count = 0
if fix_fn is not None:
    src = ast.unparse(fix_fn) if hasattr(ast, "unparse") else ""
    chushi_count = src.count("削除中止")
expect(chushi_count >= 5,
       f"'削除中止' 分岐 >= 5 経路 (実測 {chushi_count}): "
       "manifest 破損/非dict/channel_id 不正/import 失敗/ChannelLoadError")


# ── [5] 同等再現: health config ───────────────────────────────
print("[5] 同等再現: health config の token_path が bit-identical")
from _channel import load_channel
cfg = load_channel("health")
new_token = PROJECT_ROOT / cfg.oauth.token
old_token = PROJECT_ROOT / "token.json"
expect(new_token == old_token,
       f"health token bit-identical ({new_token})")


# ── subprocess probe helper ───────────────────────────────────
py_exe = Path(r"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe")
if not py_exe.exists():
    py_exe = Path(sys.executable)
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"


def _run_probe(
    tmp_project_root: Path,
    manifest_raw: str | None,  # None = manifest 不在, str = そのまま書き込む (破損/非dict/dict いずれも文字列で指定)
    create_token: bool = True,
) -> tuple[int, str, str]:
    """tempdir を project_root に見立てて _fix_delete_token_reauth を呼ぶ subprocess."""
    inline = f'''
import sys
from pathlib import Path
sys.path.insert(0, r"{SCRIPTS_DIR}")
sys.path.insert(0, r"{SCRIPTS_DIR / "skills"}")

fake_root = Path(r"{tmp_project_root}")
fake_token = fake_root / "token.json"
if {repr(create_token)}:
    fake_token.write_text("dummy", encoding="utf-8")

import self_healing as sh
# Path(__file__).parent.parent.parent が fake_root になるよう __file__ を差し替え.
sh.__file__ = str(fake_root / "scripts" / "skills" / "self_healing.py")

run_dir = fake_root / "output" / "20260412_000000_test"
run_dir.mkdir(parents=True, exist_ok=True)
manifest_raw = {repr(manifest_raw)}
if manifest_raw is not None:
    (run_dir / "pipeline.json").write_text(manifest_raw, encoding="utf-8")

result = sh._fix_delete_token_reauth(run_dir, RuntimeError("OAuth expired"), {{}})
print("RESULT:", result)
print("TOKEN_EXISTS:", fake_token.exists())
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


# ── [6] 実測: manifest.channel_id='health' 明示で token 削除 ─
print("[6] 実測: channel_id='health' 明示 manifest で削除成功")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    rc, out, err = _run_probe(
        _tmp_root, json.dumps({"channel_id": "health", "phases": {}})
    )
    expect(rc == 0 and "TOKEN_EXISTS: False" in out and "削除成功" in out,
           f"health 明示で削除成功 (rc={rc}) stdout={out[:300]} stderr={err[:300]}")
    expect("health" in out, "返却文字列に 'health' が含まれる")


# ── [7] 実測: manifest 欠損 → legacy fallback (health) で削除 ─
print("[7] 実測: manifest 欠損 → legacy 'health' fallback で削除成功")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    rc, out, err = _run_probe(_tmp_root, None)
    expect(rc == 0 and "TOKEN_EXISTS: False" in out and "削除成功" in out,
           f"manifest 欠損でも削除成功 (rc={rc}) stdout={out[:300]} stderr={err[:300]}")
    expect("health" in out, "manifest 欠損時は 'health' fallback")


# ── [8] 実測: channel_id='bogus' 明示 → 削除中止 ──────────────
print("[8] 実測: channel_id='bogus' 明示 → 削除中止, token 残存")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    rc, out, err = _run_probe(
        _tmp_root, json.dumps({"channel_id": "bogus", "phases": {}})
    )
    expect(rc == 0 and "TOKEN_EXISTS: True" in out and "削除中止" in out,
           f"'bogus' 明示で削除中止 (rc={rc}) stdout={out[:300]} stderr={err[:300]}")
    expect("bogus" in out, "返却文字列に元の channel_id 'bogus' が含まれる")


# ── [9] 実測: token 既に不在 → "削除不要" ────────────────────
print("[9] 実測: token 既に不在 → '削除不要' 返却")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    rc, out, err = _run_probe(
        _tmp_root,
        json.dumps({"channel_id": "health", "phases": {}}),
        create_token=False,
    )
    expect(rc == 0 and "削除不要" in out,
           f"token 不在で '削除不要' 返却 (rc={rc}) stdout={out[:300]} stderr={err[:300]}")


# ── [10] 実測: channel_id key 不在 manifest → legacy fallback ─
print("[10] 実測: channel_id key 不在 → legacy 'health' fallback で削除成功")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    rc, out, err = _run_probe(_tmp_root, json.dumps({"phases": {}}))
    expect(rc == 0 and "TOKEN_EXISTS: False" in out and "削除成功" in out,
           f"channel_id key 不在でも削除成功 (rc={rc}) stdout={out[:300]} stderr={err[:300]}")
    expect("health" in out, "channel_id key 不在時は 'health' fallback")


# ── [11] 実測: manifest 破損 JSON → 削除中止 (Round2) ─────────
print("[11] 実測: manifest 破損 JSON → 削除中止, token 残存")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    # 不正 JSON (JSONDecodeError を引き起こす)
    rc, out, err = _run_probe(_tmp_root, "{not: valid json,,,")
    expect(rc == 0 and "TOKEN_EXISTS: True" in out and "削除中止" in out,
           f"manifest 破損で削除中止 (rc={rc}) stdout={out[:300]} stderr={err[:300]}")
    expect("manifest 読込失敗" in out, "manifest 破損時は '読込失敗' 明示")


# ── [12] 実測: channel_id=123 (int) → 削除中止 (Round2) ──────
print("[12] 実測: channel_id=123 (int) → 削除中止, token 残存")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    rc, out, err = _run_probe(
        _tmp_root, json.dumps({"channel_id": 123, "phases": {}})
    )
    expect(rc == 0 and "TOKEN_EXISTS: True" in out and "削除中止" in out,
           f"channel_id=int で削除中止 (rc={rc}) stdout={out[:300]} stderr={err[:300]}")
    expect("manifest.channel_id が不正" in out, "値不正時は 'channel_id が不正' 明示")


# ── [13] 実測: channel_id='' (空文字) → 削除中止 (Round2) ─────
print("[13] 実測: channel_id='' (空文字) → 削除中止, token 残存")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    rc, out, err = _run_probe(
        _tmp_root, json.dumps({"channel_id": "", "phases": {}})
    )
    expect(rc == 0 and "TOKEN_EXISTS: True" in out and "削除中止" in out,
           f"channel_id='' で削除中止 (rc={rc}) stdout={out[:300]} stderr={err[:300]}")
    expect("manifest.channel_id が不正" in out, "空文字時は 'channel_id が不正' 明示")


# ── [14] 実測: manifest が list → 削除中止 (Round2) ───────────
print("[14] 実測: manifest が dict ではない (list) → 削除中止, token 残存")
with tempfile.TemporaryDirectory() as _td:
    _tmp_root = Path(_td)
    rc, out, err = _run_probe(_tmp_root, json.dumps(["not", "a", "dict"]))
    expect(rc == 0 and "TOKEN_EXISTS: True" in out and "削除中止" in out,
           f"manifest=list で削除中止 (rc={rc}) stdout={out[:300]} stderr={err[:300]}")
    expect("dict ではない" in out, "非 dict 時は 'dict ではない' 明示")


# ── 結果 ──────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3D5C5: self_healing._fix_delete_token_reauth が channel-aware + fail-closed (Round2)")
    sys.exit(0)
