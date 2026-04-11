"""Step 2-α: チャンネル設定 strict validation + load_channel のテスト.

実行方法 (Windows native Python, cp932 locale 対策で PYTHONIOENCODING=utf-8):
    cmd.exe /c "cd /d C:\\Users\\user\\Desktop\\youtube-system && ^
                set PYTHONIOENCODING=utf-8 && ^
                C:\\Users\\user\\AppData\\Local\\Programs\\Python\\Python311\\python.exe ^
                tests\\test_channel.py -v"

設計要点:
- sys.path を一切触らない (scripts/secrets.py shadow を誘発しないため)
- scripts/_channel_schema.py と scripts/_channel.py を importlib.util で
  直接 load + sys.modules 先行注入する (shadow_probe v2 で検証済みの手順)
- tearDownModule で sys.modules から cleanup (副作用を残さない)
- happy path / 全 path-like field × 全 bad pattern matrix / error path を網羅
"""

from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


# --- テスト対象モジュールの load ---------------------------------------------

_THIS_FILE = Path(__file__).resolve()
_PROJECT_ROOT = _THIS_FILE.parent.parent
_SCRIPTS_DIR = _PROJECT_ROOT / "scripts"
_SCHEMA_FILE = _SCRIPTS_DIR / "_channel_schema.py"
_CHANNEL_FILE = _SCRIPTS_DIR / "_channel.py"


def _load_module_from_file(name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    if spec is None or spec.loader is None:
        raise RuntimeError(f"spec_from_file_location 失敗: {name} {file_path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # _channel.py の `from _channel_schema import ...` 解決のため先行注入
    spec.loader.exec_module(mod)
    return mod


# _channel_schema -> _channel の順で load (from _channel_schema import ... の依存解決)
_schema_mod = _load_module_from_file("_channel_schema", _SCHEMA_FILE)
_channel_mod = _load_module_from_file("_channel", _CHANNEL_FILE)

ChannelConfig = _schema_mod.ChannelConfig
ChannelPaths = _schema_mod.ChannelPaths
ChannelOAuth = _schema_mod.ChannelOAuth
ChannelScript = _schema_mod.ChannelScript
ChannelTags = _schema_mod.ChannelTags
ChannelSchemaError = _schema_mod.ChannelSchemaError
validate_and_build = _schema_mod.validate_and_build

ChannelLoadError = _channel_mod.ChannelLoadError
load_channel = _channel_mod.load_channel


def tearDownModule():
    """Codex M1 対応: sys.modules の cleanup (他テストへの汚染防止)."""
    sys.modules.pop("_channel", None)
    sys.modules.pop("_channel_schema", None)


# --- 共通ヘルパ ---------------------------------------------------------------

def _valid_raw_dict() -> dict:
    """validate_and_build に通る最小健全 dict (health.json と同値)."""
    return {
        "schema_version": 1,
        "id": "health",
        "paths": {
            "output_subdir": "output",
            "themes_file": "themes.txt",
            "lock_file": "logs/last_upload_date.txt",
        },
        "oauth": {
            "credentials": "credentials.json",
            "token": "token.json",
        },
        "script": {
            "min_chars": 6000,
            "max_chars": 7500,
        },
        "tags": {
            "default": ["ゆっくり解説", "健康"],
        },
    }


# =============================================================================
# T01-T09: happy path (health.json を実ファイルから load)
# =============================================================================

class TestHealthLoad(unittest.TestCase):
    """health.json を実ファイルから load し、全フィールドが期待値通りか検証."""

    @classmethod
    def setUpClass(cls):
        cls.cfg = load_channel("health")

    def test_T01_returns_channel_config(self):
        self.assertIsInstance(self.cfg, ChannelConfig)

    def test_T02_schema_version(self):
        self.assertEqual(self.cfg.schema_version, 1)

    def test_T03_id(self):
        self.assertEqual(self.cfg.id, "health")

    def test_T04_paths(self):
        self.assertIsInstance(self.cfg.paths, ChannelPaths)
        self.assertEqual(self.cfg.paths.output_subdir, "output")
        self.assertEqual(self.cfg.paths.themes_file, "themes.txt")
        self.assertEqual(self.cfg.paths.lock_file, "logs/last_upload_date.txt")

    def test_T05_oauth(self):
        self.assertIsInstance(self.cfg.oauth, ChannelOAuth)
        self.assertEqual(self.cfg.oauth.credentials, "credentials.json")
        self.assertEqual(self.cfg.oauth.token, "token.json")

    def test_T06_script(self):
        self.assertIsInstance(self.cfg.script, ChannelScript)
        self.assertEqual(self.cfg.script.min_chars, 6000)
        self.assertEqual(self.cfg.script.max_chars, 7500)

    def test_T07_tags(self):
        self.assertIsInstance(self.cfg.tags, ChannelTags)
        self.assertEqual(self.cfg.tags.default, ("ゆっくり解説", "健康"))

    def test_T08_frozen_dataclass(self):
        # frozen=True なので属性代入は失敗する
        with self.assertRaises(Exception):
            self.cfg.id = "creatures"  # type: ignore[misc]

    def test_T09_tags_default_is_tuple(self):
        # list ではなく tuple として凍結されていること (frozen dataclass 整合)
        self.assertIsInstance(self.cfg.tags.default, tuple)


# =============================================================================
# T10: channel_id regex rejection
# =============================================================================

class TestChannelIdValidation(unittest.TestCase):

    def test_T10_bad_channel_ids(self):
        bad_ids = [
            "",                 # 空
            "Health",           # 大文字始まり
            "1health",          # 数字始まり
            "health-channel",   # ハイフン
            "health.channel",   # ドット
            "health/other",     # スラッシュ
            "..",               # traversal
            "../health",        # traversal
            "health\x00",       # NUL
            " health",          # 先頭空白
            "health ",          # 末尾空白
            "_health",          # 先頭アンダースコア
        ]
        for bad in bad_ids:
            with self.subTest(channel_id=bad):
                with self.assertRaises(ChannelLoadError):
                    load_channel(bad)

    def test_T10b_non_string_channel_id(self):
        for bad in (None, 123, [], {}, True):
            with self.subTest(channel_id=bad):
                with self.assertRaises(ChannelLoadError):
                    load_channel(bad)  # type: ignore[arg-type]


# =============================================================================
# T11, T13-T16: strict schema (validate_and_build を直接叩く)
# =============================================================================

class TestStrictSchema(unittest.TestCase):

    def test_T11_unknown_top_level_key(self):
        raw = _valid_raw_dict()
        raw["extra_key"] = "x"
        with self.assertRaises(ChannelSchemaError) as ctx:
            validate_and_build(raw, file_stem="health")
        self.assertIn("未知のキー", str(ctx.exception))

    def test_T11b_unknown_nested_key(self):
        raw = _valid_raw_dict()
        raw["paths"]["extra"] = "x"
        with self.assertRaises(ChannelSchemaError):
            validate_and_build(raw, file_stem="health")

    def test_T13_schema_version_must_be_1(self):
        for bad in (0, 2, -1, 100):
            with self.subTest(schema_version=bad):
                raw = _valid_raw_dict()
                raw["schema_version"] = bad
                with self.assertRaises(ChannelSchemaError):
                    validate_and_build(raw, file_stem="health")

    def test_T13b_schema_version_must_be_int(self):
        for bad in ("1", 1.0, True, None, [1]):
            with self.subTest(schema_version=bad):
                raw = _valid_raw_dict()
                raw["schema_version"] = bad
                with self.assertRaises(ChannelSchemaError):
                    validate_and_build(raw, file_stem="health")

    def test_T14_id_must_match_file_stem(self):
        raw = _valid_raw_dict()
        raw["id"] = "creatures"
        with self.assertRaises(ChannelSchemaError) as ctx:
            validate_and_build(raw, file_stem="health")
        self.assertIn("不一致", str(ctx.exception))

    def test_T15_min_chars_must_be_le_max(self):
        raw = _valid_raw_dict()
        raw["script"]["min_chars"] = 8000
        raw["script"]["max_chars"] = 7000
        with self.assertRaises(ChannelSchemaError):
            validate_and_build(raw, file_stem="health")

    def test_T15b_min_chars_positive(self):
        for bad in (0, -1):
            with self.subTest(min_chars=bad):
                raw = _valid_raw_dict()
                raw["script"]["min_chars"] = bad
                with self.assertRaises(ChannelSchemaError):
                    validate_and_build(raw, file_stem="health")

    def test_T15c_max_chars_positive(self):
        for bad in (0, -1):
            with self.subTest(max_chars=bad):
                raw = _valid_raw_dict()
                raw["script"]["max_chars"] = bad
                with self.assertRaises(ChannelSchemaError):
                    validate_and_build(raw, file_stem="health")

    def test_T15d_script_fields_reject_bool(self):
        raw = _valid_raw_dict()
        raw["script"]["min_chars"] = True  # bool は int サブクラスだが拒否
        with self.assertRaises(ChannelSchemaError):
            validate_and_build(raw, file_stem="health")

    def test_T16_missing_required_keys(self):
        for missing in ("schema_version", "id", "paths", "oauth", "script", "tags"):
            with self.subTest(missing=missing):
                raw = _valid_raw_dict()
                del raw[missing]
                with self.assertRaises(ChannelSchemaError):
                    validate_and_build(raw, file_stem="health")

    def test_T16b_missing_nested_keys(self):
        cases = [
            ("paths", "output_subdir"),
            ("paths", "themes_file"),
            ("paths", "lock_file"),
            ("oauth", "credentials"),
            ("oauth", "token"),
            ("script", "min_chars"),
            ("script", "max_chars"),
            ("tags", "default"),
        ]
        for section, key in cases:
            with self.subTest(section=section, key=key):
                raw = _valid_raw_dict()
                del raw[section][key]
                with self.assertRaises(ChannelSchemaError):
                    validate_and_build(raw, file_stem="health")

    def test_T16c_tags_default_empty_rejected(self):
        raw = _valid_raw_dict()
        raw["tags"]["default"] = []
        with self.assertRaises(ChannelSchemaError):
            validate_and_build(raw, file_stem="health")

    def test_T16d_tags_default_non_string_element(self):
        raw = _valid_raw_dict()
        raw["tags"]["default"] = ["ok", 123]
        with self.assertRaises(ChannelSchemaError):
            validate_and_build(raw, file_stem="health")

    def test_T16e_tags_default_empty_string_element(self):
        raw = _valid_raw_dict()
        raw["tags"]["default"] = ["ok", ""]
        with self.assertRaises(ChannelSchemaError):
            validate_and_build(raw, file_stem="health")


# =============================================================================
# T12: path-like field × bad pattern 完全網羅 (5 フィールド × 8 パターン = 40 サブテスト)
# =============================================================================

class TestPathLikeTraversalMatrix(unittest.TestCase):
    """全 path-like フィールド × 全 bad pattern を subTest で網羅.

    Codex v3 H1/H2 対応: PureWindowsPath + PurePosixPath の双方で弾くことを、
    5 フィールド × 8 パターン = 40 ケースで実測する。
    """

    # (section, key) の 5 フィールド
    PATH_FIELDS = [
        ("paths", "output_subdir"),
        ("paths", "themes_file"),
        ("paths", "lock_file"),
        ("oauth", "credentials"),
        ("oauth", "token"),
    ]

    # 8 bad patterns: POSIX absolute / Windows absolute / drive-relative /
    # root-relative backslash / UNC / POSIX traversal / Windows traversal /
    # embedded traversal
    BAD_PATTERNS = [
        "/etc/passwd",          # POSIX absolute
        "C:\\temp\\x.txt",       # Windows absolute
        "C:foo",                # Windows drive-relative
        "\\foo",                 # root-relative (backslash)
        "\\\\server\\share\\x",  # UNC
        "../foo",                # POSIX traversal
        "..\\foo",               # Windows traversal
        "foo/../bar",            # embedded traversal
    ]

    def test_T12_path_like_matrix_rejects_all(self):
        for section, key in self.PATH_FIELDS:
            for bad in self.BAD_PATTERNS:
                with self.subTest(section=section, key=key, pattern=bad):
                    raw = _valid_raw_dict()
                    raw[section][key] = bad
                    with self.assertRaises(ChannelSchemaError):
                        validate_and_build(raw, file_stem="health")

    def test_T12b_path_like_rejects_empty(self):
        for section, key in self.PATH_FIELDS:
            with self.subTest(section=section, key=key):
                raw = _valid_raw_dict()
                raw[section][key] = ""
                with self.assertRaises(ChannelSchemaError):
                    validate_and_build(raw, file_stem="health")

    def test_T12c_path_like_rejects_non_string(self):
        for section, key in self.PATH_FIELDS:
            for bad in (None, 123, [], {}):
                with self.subTest(section=section, key=key, bad=bad):
                    raw = _valid_raw_dict()
                    raw[section][key] = bad
                    with self.assertRaises(ChannelSchemaError):
                        validate_and_build(raw, file_stem="health")


# =============================================================================
# M2: load_channel のエラーパス (ファイル不在 / malformed JSON / top-level 非 dict)
# =============================================================================

class TestLoadChannelErrorPaths(unittest.TestCase):
    """Codex v3 M2 対応: load_channel のファイル層エラーを網羅."""

    def setUp(self):
        # tempdir を CONFIG_DIR に差し替える (monkey patch)
        self._tmpdir = tempfile.TemporaryDirectory(prefix="test_channel_")
        self._tmp = Path(self._tmpdir.name).resolve()
        self._orig = _channel_mod._CONFIG_DIR
        _channel_mod._CONFIG_DIR = self._tmp

    def tearDown(self):
        _channel_mod._CONFIG_DIR = self._orig
        self._tmpdir.cleanup()

    def _write(self, stem: str, content: str) -> None:
        (self._tmp / f"{stem}.json").write_text(content, encoding="utf-8")

    def test_file_missing(self):
        with self.assertRaises(ChannelLoadError) as ctx:
            load_channel("nonexistent")
        self.assertIn("不在", str(ctx.exception))

    def test_malformed_json(self):
        self._write("broken", "{not valid json")
        with self.assertRaises(ChannelLoadError) as ctx:
            load_channel("broken")
        self.assertIn("パース失敗", str(ctx.exception))

    def test_top_level_non_dict(self):
        self._write("asarray", "[1, 2, 3]")
        with self.assertRaises(ChannelLoadError) as ctx:
            load_channel("asarray")
        # schema error は load error で wrap される
        self.assertIn("schema violation", str(ctx.exception))

    def test_top_level_string(self):
        self._write("asstring", '"just a string"')
        with self.assertRaises(ChannelLoadError):
            load_channel("asstring")

    def test_utf8_bom_accepted(self):
        # BOM 付き JSON も正しく読める (utf-8-sig)
        raw = _valid_raw_dict()
        content = "\ufeff" + json.dumps(raw, ensure_ascii=False)
        (self._tmp / "health.json").write_text(content, encoding="utf-8")
        cfg = load_channel("health")
        self.assertEqual(cfg.id, "health")

    def test_id_mismatch_file_stem(self):
        # file stem と id フィールドの不一致
        raw = _valid_raw_dict()
        raw["id"] = "other"
        (self._tmp / "health.json").write_text(
            json.dumps(raw, ensure_ascii=False), encoding="utf-8"
        )
        with self.assertRaises(ChannelLoadError) as ctx:
            load_channel("health")
        self.assertIn("schema violation", str(ctx.exception))


# =============================================================================
# T17: shadow meta-check (本テスト実行時点で stdlib secrets が shadow されていない)
# =============================================================================

class TestShadowMetaCheck(unittest.TestCase):
    """scripts/secrets.py shadowing が発生していないことのメタ検証."""

    def test_stdlib_secrets_usable(self):
        import secrets as stdlib_secrets
        self.assertTrue(hasattr(stdlib_secrets, "token_hex"))
        # 実際に呼べることを確認 (shadow 時は scripts/secrets.py に token_hex が無く AttributeError)
        tok = stdlib_secrets.token_hex(4)
        self.assertEqual(len(tok), 8)

    def test_secrets_not_from_scripts(self):
        import secrets as stdlib_secrets
        mod_file = getattr(stdlib_secrets, "__file__", "(builtin)")
        # scripts/ ディレクトリ配下の secrets.py を指していないこと
        self.assertNotIn(
            "scripts",
            str(mod_file).replace("\\", "/").lower(),
            f"secrets module is shadowed: __file__={mod_file!r}",
        )

    def test_scripts_not_in_sys_path(self):
        scripts_resolved = _SCRIPTS_DIR.resolve()
        for p in sys.path:
            if not p:
                continue
            try:
                if Path(p).resolve() == scripts_resolved:
                    self.fail(f"sys.path に scripts/ が混入: {p}")
            except OSError:
                continue


if __name__ == "__main__":
    unittest.main(verbosity=2)
