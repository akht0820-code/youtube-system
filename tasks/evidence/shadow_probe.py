"""
Shadow probe v2 - read-only verification (Codex v3 H3 指摘対応).

v1 の目的: sys.path 非干渉で scripts/_atomic.py を importlib.util で load しても shadow しないこと
v2 の追加目的: 設計書が採る実方式 (2 モジュール load + sys.modules 先行注入) でも
             shadow しないことを、ダミーモジュールで完全再現して実測する。

絶対に既存コードを書き換えない (read-only)。
ダミーモジュール (_channel.py / _channel_schema.py 相当) は /tmp/fake_scripts/ に作成。
scripts/ 配下のファイルは secrets.py と _atomic.py を読むだけ。
"""

import sys
import os
import shutil
import tempfile
from pathlib import Path

# プラットフォームに応じた scripts/ パスを選択 (WSL と Windows native 両対応)
if sys.platform == "win32":
    SCRIPTS_DIR = Path(r"C:\Users\user\Desktop\youtube-system\scripts")
else:
    SCRIPTS_DIR = Path("/mnt/c/Users/user/Desktop/youtube-system/scripts")
SECRETS_FILE = SCRIPTS_DIR / "secrets.py"

# ダミー scripts/ を temp に用意 (実際の設計書 §5-3 の 2 モジュール load 方式を再現するため)
FAKE_SCRIPTS_DIR = Path(tempfile.mkdtemp(prefix="shadow_probe_fake_"))
FAKE_SCHEMA = FAKE_SCRIPTS_DIR / "_channel_schema.py"
FAKE_CHANNEL = FAKE_SCRIPTS_DIR / "_channel.py"

# _channel_schema 相当: ChannelConfig + validate_and_build を提供
FAKE_SCHEMA.write_text("""
# fake _channel_schema.py (probe only)
# 実設計と同じく stdlib のみ import する
from dataclasses import dataclass
import secrets as _stdlib_secrets_probe  # ★ shadow 検知用: validate_and_build の scope に stdlib secrets が通っているか

class ChannelSchemaError(Exception):
    pass

@dataclass(frozen=True)
class ChannelConfig:
    id: str

def validate_and_build(raw: dict, file_stem: str) -> ChannelConfig:
    # probe: stdlib secrets が呼べることを確認 (shadow されていれば失敗)
    token = _stdlib_secrets_probe.token_hex(2)
    return ChannelConfig(id=raw["id"])

PROBE_SECRETS_FILE = getattr(_stdlib_secrets_probe, "__file__", "(builtin)")
""", encoding="utf-8")

# _channel 相当: from _channel_schema import ... を使う (実設計と同じ)
FAKE_CHANNEL.write_text("""
# fake _channel.py (probe only)
from _channel_schema import ChannelConfig, ChannelSchemaError, validate_and_build
import secrets as _stdlib_secrets_probe_channel  # ★ shadow 検知用

def load_channel(channel_id: str) -> ChannelConfig:
    # probe: 実設計と同じく id のみ使う
    return validate_and_build({"id": channel_id}, file_stem=channel_id)

PROBE_SECRETS_FILE_IN_CHANNEL = getattr(_stdlib_secrets_probe_channel, "__file__", "(builtin)")
""", encoding="utf-8")

results = []

def r(name, ok, detail=""):
    tag = "PASS" if ok else "FAIL"
    results.append((tag, name, detail))
    print(f"[{tag}] {name}: {detail}")

print("=" * 70)
print("Shadow Probe v2 - 2-module load sequence (Codex v3 H3 response)")
print("=" * 70)

print(f"\npython executable : {sys.executable}")
print(f"python version    : {sys.version.split()[0]}")
print(f"cwd               : {os.getcwd()}")
print(f"sys.path[0]       : {sys.path[0]!r}")
print(f"scripts/secrets.py exists: {SECRETS_FILE.is_file()}")
print(f"fake_scripts dir  : {FAKE_SCRIPTS_DIR}")

r("scripts/secrets.py 実在確認",
  SECRETS_FILE.is_file(),
  str(SECRETS_FILE))

# ============================================================
# 1. cwd/sys.path が scripts/ を含まないことを確認
# ============================================================
scripts_in_sys_path = any(
    Path(p).resolve() == SCRIPTS_DIR.resolve()
    for p in sys.path if p
)
r("sys.path に scripts/ が入っていない (pre-condition)",
  not scripts_in_sys_path,
  f"scripts_in_sys_path={scripts_in_sys_path}")

# ============================================================
# 2. stdlib `secrets` を import - shadow されないはず
# ============================================================
try:
    import secrets as stdlib_secrets
    mod_file = getattr(stdlib_secrets, "__file__", "(builtin)")
    has_token_hex = hasattr(stdlib_secrets, "token_hex")
    token = stdlib_secrets.token_hex(4) if has_token_hex else None
    is_stdlib = (mod_file == "(builtin)") or ("scripts" not in str(mod_file).replace("\\", "/"))
    r("stdlib secrets.token_hex が呼べる",
      has_token_hex and token is not None,
      f"__file__={mod_file!r}")
    r("import secrets が stdlib を指している",
      is_stdlib,
      f"__file__={mod_file!r}")
except Exception as e:
    r("stdlib secrets 取得", False, f"{type(e).__name__}: {e}")

# ============================================================
# 3. 実設計の 2 モジュール load sequence を再現
#    (a) _channel_schema.py を load + sys.modules["_channel_schema"] に登録
#    (b) _channel.py を load (from _channel_schema import ... が解決されるはず)
# ============================================================
import importlib.util

def load_module_from_file(name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # ★ 実設計と同じく先行注入
    spec.loader.exec_module(mod)
    return mod

# (a) _channel_schema を先行 load
try:
    schema_mod = load_module_from_file("_channel_schema", FAKE_SCHEMA)
    r("_channel_schema 相当 load 成功",
      hasattr(schema_mod, "validate_and_build"),
      f"PROBE_SECRETS_FILE={schema_mod.PROBE_SECRETS_FILE!r}")
    r("_channel_schema 内の import secrets が stdlib を指している",
      "scripts" not in str(schema_mod.PROBE_SECRETS_FILE).replace("\\", "/"),
      f"{schema_mod.PROBE_SECRETS_FILE!r}")
except Exception as e:
    r("_channel_schema 相当 load", False, f"{type(e).__name__}: {e}")

# (b) _channel を load (from _channel_schema import ... が解決されるはず)
try:
    channel_mod = load_module_from_file("_channel", FAKE_CHANNEL)
    r("_channel 相当 load 成功 (from _channel_schema import が解決)",
      hasattr(channel_mod, "load_channel"),
      f"PROBE_SECRETS_FILE_IN_CHANNEL={channel_mod.PROBE_SECRETS_FILE_IN_CHANNEL!r}")
    r("_channel 内の import secrets が stdlib を指している",
      "scripts" not in str(channel_mod.PROBE_SECRETS_FILE_IN_CHANNEL).replace("\\", "/"),
      f"{channel_mod.PROBE_SECRETS_FILE_IN_CHANNEL!r}")
except Exception as e:
    r("_channel 相当 load", False, f"{type(e).__name__}: {e}")

# (c) load_channel("health") を実行 → validate_and_build 内部で token_hex 呼出
try:
    cfg = channel_mod.load_channel("health")
    r("load_channel('health') 成功 (validate_and_build で token_hex 呼べた)",
      cfg.id == "health",
      f"cfg={cfg}")
except Exception as e:
    r("load_channel('health') 実行", False, f"{type(e).__name__}: {e}")

# ============================================================
# 4. load 後も sys.path に scripts/ が混入していないことを再確認
# ============================================================
scripts_in_sys_path_post = any(
    Path(p).resolve() == SCRIPTS_DIR.resolve()
    for p in sys.path if p
)
r("2 モジュール load 後も sys.path に scripts/ が入っていない",
  not scripts_in_sys_path_post,
  f"scripts_in_sys_path_post={scripts_in_sys_path_post}")

# ============================================================
# 5. load 後も stdlib secrets が健全か再確認
# ============================================================
try:
    # キャッシュから再取得 (stdlib_secrets と同じ module object のはず)
    import secrets as stdlib_secrets2
    mod_file2 = getattr(stdlib_secrets2, "__file__", "(builtin)")
    token2 = stdlib_secrets2.token_hex(4)
    is_still_stdlib = "scripts" not in str(mod_file2).replace("\\", "/")
    r("2 モジュール load 後も stdlib secrets.token_hex が呼べる",
      is_still_stdlib,
      f"__file__={mod_file2!r}, token={token2!r}")
except Exception as e:
    r("load 後の stdlib secrets", False, f"{type(e).__name__}: {e}")

# ============================================================
# 6. sys.modules cleanup 検証 (Codex M1 への対応)
# ============================================================
sys.modules.pop("_channel", None)
sys.modules.pop("_channel_schema", None)
r("sys.modules cleanup 可能",
  "_channel" not in sys.modules and "_channel_schema" not in sys.modules,
  "_channel / _channel_schema を sys.modules から削除成功")

# ============================================================
# 7. ネガティブケース: sys.path[0] = scripts/ で shadow 発生
# ============================================================
print("\n--- Negative case: sys.path[0] = scripts/ ---")
for mod_name in ("secrets", "stdlib_secrets", "stdlib_secrets2"):
    sys.modules.pop(mod_name, None)
sys.path.insert(0, str(SCRIPTS_DIR))
try:
    import secrets as shadowed_secrets
    mod_file3 = getattr(shadowed_secrets, "__file__", "(builtin)")
    is_shadowed = "scripts" in str(mod_file3).replace("\\", "/")
    r("sys.path[0]=scripts/ 下では shadow が実際に発生する (negative)",
      is_shadowed,
      f"__file__={mod_file3!r}")
except ModuleNotFoundError as e:
    r("sys.path[0]=scripts/ 下で shadow 発生 (scripts/secrets.py 経由の ModuleNotFoundError が証拠)",
      "dotenv" in str(e),
      f"{type(e).__name__}: {e}")
except Exception as e:
    r("sys.path[0]=scripts/ 下 negative 検証",
      True,
      f"shadow 発生時の例外: {type(e).__name__}: {e}")
finally:
    if str(SCRIPTS_DIR) in sys.path:
        sys.path.remove(str(SCRIPTS_DIR))
    sys.modules.pop("secrets", None)

# ============================================================
# Cleanup
# ============================================================
try:
    shutil.rmtree(FAKE_SCRIPTS_DIR)
except Exception:
    pass

# ============================================================
# Summary
# ============================================================
print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
total = len(results)
passed = sum(1 for tag, _, _ in results if tag == "PASS")
for tag, name, _ in results:
    print(f"  [{tag}] {name}")
print(f"\n{passed} / {total} passed")

if passed == total:
    print("\n結論 (v2 probe):")
    print("  - 実設計の 2 モジュール load sequence (_channel_schema sys.modules 先行注入 + _channel load)")
    print("    でも sys.path に scripts/ は混入せず、stdlib secrets は shadow されない")
    print("  - load_channel() 内部の validate_and_build で token_hex が呼べる")
    print("  - sys.modules の cleanup も実行可能")
    print("  - ネガティブケース (sys.path[0]=scripts/) では shadow が実際に発生")
    sys.exit(0)
else:
    print("\n結論: 一部ケース失敗。")
    sys.exit(1)
