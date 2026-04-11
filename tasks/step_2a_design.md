# Step 2-α 小設計書 (v3) - no-op チャンネル設定の追加

作成日: 2026-04-11
改訂履歴:
- v1 NO-GO (Codex): validation not pure / traversal 無し / nested 無検証 / smoke test / namespace 変更 / WSL python 前提
- v2 NO-GO (Codex): shadowing 回避策が逆 / Windows native Python 手順が Codex 環境で再現不能 / schema_version・id invariant 未テスト / path traversal テスト不足 / 10時成功 acceptance 必須がノイズ
- v3: 上記を全て実測実証後に修正。新方針: テストファイルを `tests/` に配置、`importlib.util.spec_from_file_location` で `_channel.py` を file path 直 load、sys.path を一切触らない

スコープ: Phase 2 の最初の no-op PR 1 本
前提: `tasks/phase1_creatures_scope_reduced.md` の合意 1〜6 がユーザー承認済

---

## 0. Codex v2 指摘 (NO-GO 原因) への対応表

| # | v2 の指摘 | 実測で確認 | v3 の対応 |
|---|---|---|---|
| H1 | WSL から `.exe` 直叩き前提が Codex 環境で `UtilBindVsockAnyPort` 失敗 → acceptance 必須化不可 | Codex 実測済 | acceptance から「WSL→.exe 直叩き」を外す。本番検証は **cmd.exe 経由の Windows 側実行** を正とする。Codex レビューでは「設計整合性」のみ判断対象 |
| H2 | `cd scripts && python _channel_test.py` では sys.path[0]=scripts/ になり shadowing 再発 | Codex 実測 `python3 -c "import secrets"` が `scripts/secrets.py` (dotenv エラー) | shadowing 回避策を **全面変更**: テストファイルを `tests/test_channel.py` に配置し、`importlib.util.spec_from_file_location` で `scripts/_channel.py` を file path 直 load。`sys.path.insert` も `cd scripts` も禁止。**実測証拠**は §11 を参照 |
| M1 | `schema_version==1` / `id==file_stem` invariant がテスト未カバー | - | T13, T14 追加 |
| M2 | path traversal テストが `paths.output_subdir = "/etc/passwd"` の 1 本だけで `paths.*` + `oauth.*` 全フィールド × Windows 系 未網羅 | - | T12 を T12a〜T12f の 6 ケースに分割: `paths.themes_file`, `paths.lock_file`, `oauth.credentials`, `oauth.token` それぞれに `..\\foo`, `C:\\temp\\x`, `/etc/passwd` を適用 |
| L1 | 「翌日 10 時実行成功」を acceptance 必須化は外部要因ノイズ | - | acceptance から外し、§12 の post-merge monitoring に降格 |

---

## 1. 事実確認 (コード実測)

### 1-1. 現行ハードコード値 (本 Step で写す対象)

| 項目 | 現行コード位置 | 値 |
|---|---|---|
| output dir | `scripts/generator.py:16` ほか 12 ファイル | `output` |
| themes file | `scripts/generator.py:22`, `skill_script_gen.py:765` | `themes.txt` |
| lock file | `scripts/skills/skill_upload.py:29`, `generator.py:105`, `preflight_runtime.py:87` | `logs/last_upload_date.txt` |
| credentials | `scripts/auth_utils.py:18` | `credentials.json` |
| token | `scripts/auth_utils.py:19` | `token.json` |
| min script chars | `scripts/skills/skill_script_gen.py:47` | `6000` |
| max script chars | `scripts/skills/skill_script_gen.py:48` | `7500` |
| default tags (fallback) | `scripts/skills/skill_upload.py:125` | `["ゆっくり解説", "健康"]` |

`publish_time` は Python コードではなく `run.bat` の引数 (`--publish-time 18:00`) なので本 Step の schema には含めない (次 Step で run.bat 由来として別途扱う)。

`skill_metadata.py:155` の `["ゆっくり解説", "健康", theme]` は **runtime に theme を付けた生成結果** であり schema には含めない。schema に入れるのは `skill_upload.py:125` の fallback 定数のみ。

### 1-2. `scripts/secrets.py` shadowing 問題の再整理 (v2 訂正)

v2 の「`cd scripts` で回避」は**誤り**。理由:

- `python _channel_test.py` をスクリプトとして実行すると Python は **スクリプトのディレクトリ** を `sys.path[0]` に prepend する
- `cd scripts && python _channel_test.py` だと `sys.path[0] = scripts/`
- その状態で何かが `import secrets` すると `scripts/secrets.py` が stdlib を shadow する
- Codex が実測で `ModuleNotFoundError: dotenv` を観測したのが証拠 (scripts/secrets.py が読まれたが dotenv が stdlib Python にない)

**v3 の正しい回避策**: テストファイルを `scripts/` **外** (`tests/test_channel.py`) に配置し、その中から `importlib.util.spec_from_file_location("_channel", "<abs path>/scripts/_channel.py")` で直 load する。sys.path は一切触らない。詳細実測証拠は §11。

### 1-3. 既存 `scripts/_atomic.py` (underscore prefix 先例)

`scripts/_atomic.py` と `scripts/skills/_common.py` が既存。本 Step の `_channel.py` / `_channel_schema.py` はこの命名規則に整合する。

---

## 2. 追加ファイル一覧 (4 個)

```
config/
  channels/
    health.json               # 新規: 現行ハードコード値の写し
scripts/
  _channel.py                 # 新規: load_channel() + ChannelConfig dataclass
  _channel_schema.py          # 新規: pure validate_and_build()
tests/
  test_channel.py             # 新規: unittest (__init__.py なし、sys.path 不干渉)
```

**v2 との差分**: テストファイルを `scripts/_channel_test.py` から `tests/test_channel.py` に移動。`tests/__init__.py` は **作らない** (namespace 変更回避)。

---

## 3. Schema 定義

### 3-1. `config/channels/health.json`

```json
{
  "schema_version": 1,
  "id": "health",
  "paths": {
    "output_subdir": "output",
    "themes_file": "themes.txt",
    "lock_file": "logs/last_upload_date.txt"
  },
  "oauth": {
    "credentials": "credentials.json",
    "token": "token.json"
  },
  "script": {
    "min_chars": 6000,
    "max_chars": 7500
  },
  "tags": {
    "default": ["ゆっくり解説", "健康"]
  }
}
```

### 3-2. Strict validation 仕様 (nested 含む)

| object | required keys | 追加許容 | 型 | 相互整合 |
|---|---|---|---|---|
| root | `schema_version`, `id`, `paths`, `oauth`, `script`, `tags` | **なし** | dict | `id == file_stem`, `schema_version == 1` |
| `paths` | `output_subdir`, `themes_file`, `lock_file` | なし | 全て str | - |
| `oauth` | `credentials`, `token` | なし | 全て str | - |
| `script` | `min_chars`, `max_chars` | なし | 全て int | `0 < min_chars <= max_chars` |
| `tags` | `default` | なし | `default` は list[str], 1 個以上 | 全要素が非空 str |

**追加検証 (path-like 全フィールドに適用)**:

対象: `paths.output_subdir`, `paths.themes_file`, `paths.lock_file`, `oauth.credentials`, `oauth.token`

- 絶対パス禁止: `Path(v).is_absolute()` で true なら fail
- drive letter 禁止 (Windows 絶対パス対策): 値が `[A-Za-z]:` で始まったら fail
- traversal 禁止: `Path(v).parts` に `..` が含まれたら fail
- forward slash と backslash 両方を考慮: `v.replace("\\", "/")` で正規化後に parts 検査
- 本 Step では **file 存在確認をしない** (pure validation)
- unknown key は root / 各 nested で個別に検出し fail

### 3-3. `validate_and_build(raw: dict, file_stem: str) -> ChannelConfig` の契約

- **純粋関数**。import しない、file system を触らない、環境変数を読まない
- 入力: parse 済 dict + ファイル名 stem (`id == file_stem` 検証のため)
- 出力: `ChannelConfig` frozen dataclass
- 失敗: 全て `ChannelSchemaError`、サイレント失敗禁止
- `ChannelSchemaError` は `_channel_schema.py` 内で定義する単一例外クラス

---

## 4. `load_channel()` の契約

```python
# scripts/_channel.py (擬似コード)

import json
import re
from pathlib import Path

from _channel_schema import ChannelConfig, ChannelSchemaError, validate_and_build

_CHANNEL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = (PROJECT_ROOT / "config" / "channels").resolve()


def load_channel(channel_id: str) -> ChannelConfig:
    # (1) 入口 sanitize: 型 + 正規表現検証
    if not isinstance(channel_id, str):
        raise ChannelSchemaError(f"channel_id は str 必須: {type(channel_id).__name__}")
    if not _CHANNEL_ID_PATTERN.match(channel_id):
        raise ChannelSchemaError(f"channel_id 形式不正: {channel_id!r}")

    # (2) path 構築 + containment 検証
    path = (CONFIG_DIR / f"{channel_id}.json").resolve()
    try:
        path.relative_to(CONFIG_DIR)
    except ValueError:
        raise ChannelSchemaError(f"channel_id が CONFIG_DIR 外を指す: {channel_id!r}")

    # (3) file read (BOM 吸収)
    if not path.is_file():
        raise ChannelSchemaError(f"チャンネル設定が見つかりません: {path}")
    raw_text = path.read_text(encoding="utf-8-sig")
    try:
        raw = json.loads(raw_text)
    except json.JSONDecodeError as e:
        raise ChannelSchemaError(f"JSON parse 失敗: {path}: {e}")

    if not isinstance(raw, dict):
        raise ChannelSchemaError(f"トップレベル dict 必須: {path}")

    # (4) pure validation + build
    return validate_and_build(raw, file_stem=channel_id)
```

**ポイント**:
- 入口で正規表現 + containment の **二重検証**。regex だけでも traversal は防げるが、念のため resolve() 後の prefix 検証を併用
- `PROJECT_ROOT` の解決は `Path(__file__).resolve().parent.parent` のみ。環境変数未使用
- `_channel.py` 自身は `_channel_schema` を `from _channel_schema import ...` する。`_channel.py` が `importlib.util.spec_from_file_location` で load される場合でもこの import が通るよう、load 時に同時に `_channel_schema.py` も spec で load する必要あり (詳細は §5-3)

---

## 5. Unit test 設計 (invariant ベース 19 ケース)

`tests/test_channel.py` 単一ファイル。`tests/__init__.py` は作らない。`scripts/_channel.py` と `scripts/_channel_schema.py` を `importlib.util.spec_from_file_location` で load する。

### 5-1. テストケース一覧

| # | テスト名 | 守る invariant |
|---|---|---|
| T01 | `test_load_returns_channel_config` | load 成功時の返却型が ChannelConfig |
| T02 | `test_health_id_matches` | `id == "health"` |
| T03 | `test_paths_output_subdir_matches_hardcoded` | `paths.output_subdir == "output"` |
| T04 | `test_paths_themes_file_matches_hardcoded` | `paths.themes_file == "themes.txt"` |
| T05 | `test_paths_lock_file_matches_hardcoded` | `paths.lock_file == "logs/last_upload_date.txt"` |
| T06 | `test_oauth_credentials_matches_hardcoded` | `oauth.credentials == "credentials.json"` |
| T07 | `test_oauth_token_matches_hardcoded` | `oauth.token == "token.json"` |
| T08 | `test_script_chars_match_hardcoded` | `min_chars=6000`, `max_chars=7500` |
| T09 | `test_default_tags_match_hardcoded` | `tags.default == ["ゆっくり解説", "健康"]` |
| T10 | `test_channel_id_regex_rejects_traversal` | `../foo`, `..`, `./foo`, 空文字, `Foo`, `foo/bar`, `foo-bar` 全て fail |
| T11 | `test_unknown_top_level_key_raises` | root に `extra: 1` を加えた設定で fail |
| T12a | `test_paths_output_subdir_traversal_dotdot_raises` | `paths.output_subdir = "../foo"` で fail |
| T12b | `test_paths_themes_file_windows_absolute_raises` | `paths.themes_file = "C:\\temp\\x"` で fail |
| T12c | `test_paths_lock_file_backslash_traversal_raises` | `paths.lock_file = "..\\bar"` で fail |
| T12d | `test_oauth_credentials_absolute_posix_raises` | `oauth.credentials = "/etc/passwd"` で fail |
| T12e | `test_oauth_token_traversal_raises` | `oauth.token = "../token.json"` で fail |
| T12f | `test_unknown_nested_key_raises` | `paths` に `extra: "x"` を加えた設定で fail |
| T13 | `test_schema_version_invalid_raises` | `schema_version = 2` で fail (integer 1 以外) |
| T14 | `test_id_mismatch_file_stem_raises` | `id = "creatures"` で `file_stem = "health"` なら fail |
| T15 | `test_min_gt_max_chars_raises` | `min_chars=10000, max_chars=5000` で fail |
| T16 | `test_missing_required_key_raises` | `paths.output_subdir` 欠落で fail |
| T17 | `test_stdlib_secrets_not_shadowed_during_test` | テスト中に `import secrets; secrets.token_hex(4)` が成功する (shadow 防御の meta-check) |

合計 19 ケース (T01-T17, T12a-f)。

### 5-2. テスト実行コマンド

**Windows native Python (正 / acceptance で使う)**:

```cmd
cd /d C:\Users\user\Desktop\youtube-system
set PYTHONIOENCODING=utf-8
C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe tests\test_channel.py -v
```

または PowerShell / bash から cmd.exe 経由:

```bash
cmd.exe /c "cd /d C:\Users\user\Desktop\youtube-system && set PYTHONIOENCODING=utf-8 && C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe tests\test_channel.py -v"
```

**重要**: `tests/test_channel.py` を実行すると `sys.path[0] = tests/` になる。`tests/` は `scripts/` ではないので shadowing は発生しない。

### 5-3. テスト内での `_channel.py` load 方式

```python
# tests/test_channel.py (先頭)
import sys
import unittest
import importlib.util
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"

def _load_module(name: str, file_path: Path):
    spec = importlib.util.spec_from_file_location(name, str(file_path))
    mod = importlib.util.module_from_spec(spec)
    # _channel.py が _channel_schema を from import するため、先に schema を
    # sys.modules に登録しておく必要がある
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

# _channel_schema を先に load (_channel.py が from import するため)
_channel_schema = _load_module("_channel_schema", SCRIPTS_DIR / "_channel_schema.py")
_channel = _load_module("_channel", SCRIPTS_DIR / "_channel.py")

load_channel = _channel.load_channel
validate_and_build = _channel_schema.validate_and_build
ChannelConfig = _channel_schema.ChannelConfig
ChannelSchemaError = _channel_schema.ChannelSchemaError
```

**重要**:
- `sys.path` を一切触らない
- `sys.modules[name] = mod` は `_channel.py` の `from _channel_schema import ...` を通すために必要
- これは `scripts/` を sys.path に入れる操作ではなく、特定モジュール名を module 参照に紐付ける操作。`import secrets` は依然 stdlib を拾う

### 5-4. 検知の検知 (テスト自体の健全性確認)

開発手順として (**invariant ではない**):

1. `_channel_schema.py` の validation を **空実装** にしてテストを走らせる
2. T10〜T16 が fail することを確認 (validation が効いていないことを示す)
3. その後 validation を実装して全 19 ケース pass を確認

この手順は設計書に記録するが、恒久的な invariant としては扱わない。

---

## 6. 既存コードへの影響範囲

| 影響観点 | 本 PR での実態 |
|---|---|
| 既存 import 解決への影響 | `scripts/_channel.py` / `_channel_schema.py` が `scripts/` namespace に追加される。全て underscore prefix + 既存名と衝突なし (grep 確認済) |
| 本番 10:00 実行 | `generator.py` / `run.bat` / 既存 skill 群から新ファイルを呼ばない → 実行経路は 1 行も変わらない |
| 依存追加 | なし (json, re, dataclasses, pathlib, unittest, importlib.util 全て stdlib) |
| pickle キャッシュ | 既存 module 構造を変えない |
| Discord Bot | `discord_bot.py` は新ファイルを import しない |
| ClaudeWatchdog | 同上 |
| Task Scheduler | xml を変更しない |
| `tests/` ディレクトリ | 新規作成だが `__init__.py` なし → namespace 変更なし |
| `scripts/secrets.py` shadowing | `tests/test_channel.py` は sys.path[0]=tests/ で起動するため shadowing 発生経路なし。§11 実測で確認済 |
| ffmpeg コマンド長 | 本 PR では ffmpeg を呼ばない |
| cp932 | 本 PR のコードに日本語 print 文を入れない。JSON/Python ソースは UTF-8 で読み書き。テスト実行時は `PYTHONIOENCODING=utf-8` を設定 |
| Windows/WSL パス | JSON 内は全て PROJECT_ROOT 相対 + forward slash |

**残存リスク (正直な列挙)**:

1. `scripts/_channel.py` に文法エラーがあると、将来の Step で import する側が壊れる (本 Step の本番への影響はなし)
2. `config/channels/health.json` に誤記があっても、現行コードは読まないため本番には影響しない。ただし次 Step で参照され始めた瞬間に表面化する
3. `tests/` を新規作成することで pytest discovery が将来混入した場合に影響を受ける可能性あり (今はない)

---

## 7. 3歩先チェック 4 問

### Q1: この修正自体が壊れたら、どうやって気づくのか？

- Windows native Python で 19 unittest 実行 → 全 pass
- 既存コードから呼ばれない → 10:00 実行が壊れる経路は存在しない
- `_channel.py` が load 可能であることを `tests/test_channel.py` の T01 で確認
- 検知の検知: §5-4 で validation 空実装時に T10〜T16 が fail することを手順として実施

### Q2: この変更で別のエッジケースが生まれないか？

- **cp932**: print 文を入れない、notifier を呼ばない、JSON は `encoding="utf-8-sig"` で read、`ensure_ascii=False` で write、テスト実行時は `PYTHONIOENCODING=utf-8`
- **Windows native Python**: acceptance は cmd.exe 側からの実行を正とする。WSL→.exe 直叩きは補助手段 (動く環境では使える) だが acceptance 必須ではない
- **WSL/Windows パス**: Schema 内は全て forward slash + PROJECT_ROOT 相対
- **Task Scheduler**: 新タスク登録は本 Step では行わない。既存タスクは新ファイルを import しない
- **Discord/ClaudeWatchdog の import 連鎖**: 両者は `_channel` を import しない
- **ffmpeg コマンド長**: 本 Step では ffmpeg を呼ばない
- **`scripts/secrets.py` shadowing**: 実測証拠 §11 により、`tests/` 起動 + `spec_from_file_location` 方式で完全回避
- **channel_id traversal**: 正規表現 + containment の二重検証
- **JSON BOM**: `encoding="utf-8-sig"` で吸収
- **tests/ 新設**: `__init__.py` なし、pytest discovery 未導入のため namespace 変更は発生しない

### Q3: ユーザー不在中でも機能するか？

- 実装・マージは日中のみ、10:00 タスクには一切触れない
- 10:00 実行への影響ゼロなので、マージ後ユーザー不在時に何も起きない
- ClaudeWatchdog / Discord Bot / cron heartbeat に影響なし

### Q4: 「動いた」「OK」と言う前に、本当に本番条件でテストしたか？

- 本 Step の acceptance は以下 **2 点全て** を満たすこと:
  1. **Windows native Python (`C:\...\python.exe`) で 19 unittest 全 pass**
  2. **手動 load 確認**: 同じ Python から `import importlib.util; spec = importlib.util.spec_from_file_location("_channel", r"C:\...\scripts\_channel.py"); ...; load_channel("health")` が例外なく ChannelConfig を返す
- 「翌日 10:00 実行成功」は acceptance ではなく **post-merge monitoring** (§12) として別枠で確認
- unittest pass だけで「OK」と言わない: (2) の手動 load が本番 Python での真の import 可能性を担保する

---

## 8. テスト実行の Windows native Python 検証手順

```bash
# 1. unittest 実行 (Windows native Python、cmd.exe 経由)
cmd.exe /c "cd /d C:\Users\user\Desktop\youtube-system && set PYTHONIOENCODING=utf-8 && C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe tests\test_channel.py -v"

# 2. 手動 load 確認 (cmd.exe 経由、WSL→.exe 直叩きは非依存)
cmd.exe /c "cd /d C:\Users\user\Desktop\youtube-system && set PYTHONIOENCODING=utf-8 && C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe -c \"import importlib.util; spec = importlib.util.spec_from_file_location('_channel_schema', r'C:\Users\user\Desktop\youtube-system\scripts\_channel_schema.py'); import sys; m1 = importlib.util.module_from_spec(spec); sys.modules['_channel_schema']=m1; spec.loader.exec_module(m1); spec2 = importlib.util.spec_from_file_location('_channel', r'C:\Users\user\Desktop\youtube-system\scripts\_channel.py'); m2 = importlib.util.module_from_spec(spec2); sys.modules['_channel']=m2; spec2.loader.exec_module(m2); print(m2.load_channel('health'))\""

# 3. traversal 攻撃ペイロード確認 (例外が出ることを確認)
# (上記 -c 内の load_channel('health') を load_channel('../etc/passwd') に置換して実行し ChannelSchemaError が出ることを確認)
```

**Codex レビュー環境での再現不要**: Codex sandbox は Windows .exe を実行できないため、Codex は **設計整合性のみ判断**。本 acceptance は実装者 (Claude) が Windows 側で実行して検証し、ログを `tasks/evidence/` に残す。

---

## 9. 本 Step で扱わないもの (明示的保留)

- `--channel` CLI 引数
- generator.py / skill_*.py の channel 化
- auth_utils.py の channel_cfg 対応
- `display_name` / `publish_time` / `expected_channel_id` / `prompts_module` の schema 追加
- DRY_RUN フラグ
- manifest.json 契約
- Gemini rate limiter
- cross_platform_lock 統一
- self_healing 改修
- 生物チャンネル固有実装

---

## 10. 承認いただきたい点 (v3)

以下 5 点に Yes/No で返答ください:

1. **テストファイル配置を `tests/test_channel.py` に変更**、`tests/__init__.py` は作らず `importlib.util.spec_from_file_location` で `scripts/_channel.py` と `scripts/_channel_schema.py` を file path 直 load する方針に同意するか (shadowing 回避の実測証拠は §11)
2. **schema を §3-1 の最小構成** (`schema_version` / `id` / `paths` / `oauth` / `script` / `tags`) に絞ることに同意するか
3. **テスト 19 ケース** (T01-T17, T12a-f 含む nested traversal 全フィールド) の網羅範囲に同意するか
4. **acceptance を「Windows native Python で 19 unittest 全 pass + 手動 load 確認」の 2 点のみ** とし、「翌日 10:00 実行成功」は post-merge monitoring (§12) に落とすことに同意するか
5. **Codex レビューは設計整合性のみ判断**、Windows native Python での実測は Claude が cmd.exe 経由で行い `tasks/evidence/` にログ保存する方針に同意するか

全 5 点 Yes なら Codex 再々レビューにかけ、GO なら実装 PR に進みます。

---

## 11. Shadow 回避の実測証拠 (v3 新規)

### 11-1. 実測スクリプト

`tasks/evidence/shadow_probe.py` に read-only 実測スクリプトを配置済 (2026-04-11 実行)。

### 11-2. 実測環境と結果

| 環境 | Python | 結果 |
|---|---|---|
| WSL2 Ubuntu | python3 3.12.3 (`/usr/bin/python3`) | **8/8 PASS** |
| Windows native | python.exe 3.11.9 (`C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe`) | **8/8 PASS** |

両環境で全 8 ケース PASS。完全ログ: `tasks/evidence/shadow_probe_win_python.log`

### 11-3. 実証した命題

**命題 A (positive)**: テストスクリプトを `scripts/` 外 (例: `/tmp/`, `C:\...\Temp\`) から起動し、`importlib.util.spec_from_file_location("_probed_atomic", "<abs>/scripts/_atomic.py")` で scripts/ 配下のファイルを load しても:
- `sys.path` に scripts/ は追加されない (load 前後で確認)
- stdlib `secrets` は shadow されない (`secrets.__file__` が stdlib を指したまま、`token_hex(4)` 呼出成功)
- 対象ファイル (`scripts/_atomic.py`) は正常 load される

**命題 B (negative)**: `sys.path.insert(0, "<abs>/scripts")` した瞬間、`import secrets` は `scripts/secrets.py` を拾う (shadow 発生):
- WSL 環境: `ModuleNotFoundError: No module named 'dotenv'` (scripts/secrets.py 経由で dotenv を求めた証拠)
- Windows 環境: `secrets.__file__ == 'C:\\Users\\user\\Desktop\\youtube-system\\scripts\\secrets.py'` (直接 shadow 確認)

両命題が両環境で成立することから、v3 の設計 (`tests/test_channel.py` + `spec_from_file_location`) は shadowing を確実に回避する。

### 11-4. 証拠ファイル一覧

```
tasks/evidence/
  shadow_probe.py              # 実測スクリプト本体
  shadow_probe_win_python.log  # Windows 3.11.9 + WSL 3.12.3 両方の実行ログ
```

---

## 12. Post-merge monitoring (acceptance 外の確認)

acceptance (§7-Q4) から外した「翌日 10:00 実行成功」は以下の監視タスクとして扱う:

- マージ翌日 10:00 の定時実行完了を ClaudeWatchdog / Discord Bot の既存通知で確認
- 3 日間連続で 10:00 実行成功を観測してから次 Step (2-β) の設計に進む
- 1 日でも失敗したら PR を revert + 原因調査
- 本件は「GO 判定の条件」ではなく「次 Step 着手の条件」
