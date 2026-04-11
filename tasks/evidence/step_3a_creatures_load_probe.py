"""Step 3-α probe: creatures.json が load_channel('creatures') で strict validate を通り,
各フィールドが設計値と bit-identical に一致することを検証.

本 Step は no-op 追加 (どの consumer も load_channel('creatures') を呼ばない).
probe は Windows native Python + cwd=scripts/ で本番形態を実測する.
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

# 設計値 (ユーザー承認済み 2026-04-11)
EXPECTED = {
    "schema_version": 1,
    "id": "creatures",
    "paths.output_subdir": "output_creatures",
    "paths.themes_file": "themes_creatures.txt",
    "paths.lock_file": "logs/last_upload_date_creatures.txt",
    "oauth.credentials": "credentials_creatures.json",
    "oauth.token": "token_creatures.json",
    "script.min_chars": 8000,
    "script.max_chars": 10000,
    "tags.default": ("ゆっくり解説", "生き物", "動物", "生態"),
}

errors = []


def expect(cond, msg):
    if cond:
        print(f"  [OK] {msg}")
    else:
        print(f"  [NG] {msg}")
        errors.append(msg)


# ── 1. load_channel('creatures') 成功 ──────────────────────
print("[1] load_channel('creatures')")
from _channel import load_channel, ChannelLoadError

try:
    cfg = load_channel("creatures")
    print("  [OK] ChannelConfig returned (no exception)")
except ChannelLoadError as e:
    print(f"  [NG] ChannelLoadError: {e}")
    errors.append(f"load_channel raised: {e}")
    print("\nPROBE_FAIL: load_channel blocked probe")
    sys.exit(1)

# ── 1b. 生 JSON root key set drift 検知 (Codex 設計レビュー改善案) ─
# 将来 schema が緩和されても raw JSON 側の drift を早期検知する.
print("[1b] raw JSON root key set drift")
import json as _json
_raw = _json.loads((PROJECT_ROOT / "config" / "channels" / "creatures.json").read_text(encoding="utf-8"))
_EXPECTED_ROOT_KEYS = {"schema_version", "id", "paths", "oauth", "script", "tags"}
expect(set(_raw.keys()) == _EXPECTED_ROOT_KEYS,
       f"raw root keys == {sorted(_EXPECTED_ROOT_KEYS)} (got {sorted(_raw.keys())})")
expect(set(_raw["paths"].keys()) == {"output_subdir", "themes_file", "lock_file"},
       f"raw paths keys (got {sorted(_raw['paths'].keys())})")
expect(set(_raw["oauth"].keys()) == {"credentials", "token"},
       f"raw oauth keys (got {sorted(_raw['oauth'].keys())})")
expect(set(_raw["script"].keys()) == {"min_chars", "max_chars"},
       f"raw script keys (got {sorted(_raw['script'].keys())})")
expect(set(_raw["tags"].keys()) == {"default"},
       f"raw tags keys (got {sorted(_raw['tags'].keys())})")

# ── 2. schema_version / id ─────────────────────────────────
print("[2] schema_version / id")
expect(cfg.schema_version == EXPECTED["schema_version"],
       f"schema_version == {EXPECTED['schema_version']} (got {cfg.schema_version})")
expect(cfg.id == EXPECTED["id"],
       f"id == {EXPECTED['id']!r} (got {cfg.id!r})")

# ── 3. paths ───────────────────────────────────────────────
print("[3] paths")
expect(cfg.paths.output_subdir == EXPECTED["paths.output_subdir"],
       f"paths.output_subdir == {EXPECTED['paths.output_subdir']!r} (got {cfg.paths.output_subdir!r})")
expect(cfg.paths.themes_file == EXPECTED["paths.themes_file"],
       f"paths.themes_file == {EXPECTED['paths.themes_file']!r} (got {cfg.paths.themes_file!r})")
expect(cfg.paths.lock_file == EXPECTED["paths.lock_file"],
       f"paths.lock_file == {EXPECTED['paths.lock_file']!r} (got {cfg.paths.lock_file!r})")

# ── 4. oauth ───────────────────────────────────────────────
print("[4] oauth")
expect(cfg.oauth.credentials == EXPECTED["oauth.credentials"],
       f"oauth.credentials == {EXPECTED['oauth.credentials']!r} (got {cfg.oauth.credentials!r})")
expect(cfg.oauth.token == EXPECTED["oauth.token"],
       f"oauth.token == {EXPECTED['oauth.token']!r} (got {cfg.oauth.token!r})")

# ── 5. script ──────────────────────────────────────────────
print("[5] script")
expect(cfg.script.min_chars == EXPECTED["script.min_chars"],
       f"script.min_chars == {EXPECTED['script.min_chars']} (got {cfg.script.min_chars})")
expect(cfg.script.max_chars == EXPECTED["script.max_chars"],
       f"script.max_chars == {EXPECTED['script.max_chars']} (got {cfg.script.max_chars})")
expect(cfg.script.min_chars <= cfg.script.max_chars,
       f"min_chars <= max_chars ({cfg.script.min_chars} <= {cfg.script.max_chars})")

# ── 6. tags ────────────────────────────────────────────────
print("[6] tags")
expect(cfg.tags.default == EXPECTED["tags.default"],
       f"tags.default == {EXPECTED['tags.default']} (got {cfg.tags.default})")
expect(isinstance(cfg.tags.default, tuple),
       f"tags.default is tuple (got {type(cfg.tags.default).__name__})")

# ── 7. health との非衝突 (paths が別物であること) ──────────
print("[7] health との paths 非衝突")
health = load_channel("health")
expect(cfg.paths.output_subdir != health.paths.output_subdir,
       f"output_subdir 分離 ({cfg.paths.output_subdir} vs {health.paths.output_subdir})")
expect(cfg.paths.themes_file != health.paths.themes_file,
       f"themes_file 分離 ({cfg.paths.themes_file} vs {health.paths.themes_file})")
expect(cfg.paths.lock_file != health.paths.lock_file,
       f"lock_file 分離 ({cfg.paths.lock_file} vs {health.paths.lock_file})")
expect(cfg.oauth.credentials != health.oauth.credentials,
       f"oauth.credentials 分離 ({cfg.oauth.credentials} vs {health.oauth.credentials})")
expect(cfg.oauth.token != health.oauth.token,
       f"oauth.token 分離 ({cfg.oauth.token} vs {health.oauth.token})")

# ── 8. health regression 非発生 ───────────────────────────
print("[8] health regression")
expect(health.id == "health", "health.id unchanged")
expect(health.paths.lock_file == "logs/last_upload_date.txt",
       "health.paths.lock_file unchanged")
expect(health.script.min_chars == 6000, "health.script.min_chars unchanged")
expect(health.script.max_chars == 7500, "health.script.max_chars unchanged")

# ── 9. frozen dataclass 性 (tampering 不可) ────────────────
print("[9] frozen dataclass")
try:
    cfg.paths.lock_file = "EVIL"  # type: ignore
    print("  [NG] mutation allowed (frozen broken)")
    errors.append("frozen dataclass allowed mutation")
except Exception:
    print("  [OK] mutation blocked (frozen)")

# ── 結果 ──────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3A: creatures.json loads and bit-identical with design")
    sys.exit(0)
