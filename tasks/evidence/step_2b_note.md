# Step 2-β note: code-change-zero resolution of Codex Medium advisory

Date: 2026-04-11
Scope: 実測のみ (コード変更ゼロ)
Outcome: **Codex Medium advisory は本番 sys.path の前提ズレだったため、コード変更不要**

---

## 背景

Step 2-α の Codex adversarial review (Thread ID `019d786c-30eb-7bc2-89b2-150256795d95`) で 1 件の Medium advisory が出ていた:

> `scripts/_channel.py:27` の `from _channel_schema import ...`
> - 本 Step の no-op 性は壊さない
> - 次 Step で generator.py に配線する際、`from scripts._channel import load_channel` 形式では ModuleNotFoundError になる
> - → 次 Step 着手前に import 方式の整理が必要 (本 Step ブロッキングではない)

これを受けて Step 2-β では本来 import 方式修正を予定していたが、実装着手前に **本番 generator.py の実際の sys.path 状態を調査したところ、Codex の前提が本番とズレていることが判明した。**

## 本番 sys.path の実際の状態

**`run.bat:3`** (commit `73bbb51` 時点):
```bat
cd /d C:\Users\user\Desktop\youtube-system\scripts
```
**`run.bat:46`**:
```bat
%PYTHON% -X utf8 -u generator.py --auto --publish-time 18:00 >> %LOG% 2>&1
```

つまり本番 generator.py は:
- **cwd** = `C:\Users\user\Desktop\youtube-system\scripts`
- **sys.path[0]** = `scripts/` (Python が script のあるディレクトリを sys.path[0] に入れる仕様)

## 本番の既存 import 形式

`scripts/generator.py` の先頭 import (`L13-L14`):
```python
from notifier import notify_error, notify_start, notify_success
from skills.self_healing import run_phase_with_healing
```

`scripts/` がパッケージではない (`__init__.py` 不在) にもかかわらず、すべて **トップレベル import** で動いている。これは sys.path[0]==scripts/ が成立しているため。

したがって **本番で generator.py から Step 2-α のコードを呼ぶ正しい形式は**:

```python
from _channel import load_channel   # ← 本番で通る
```

であって、Codex が想定した:

```python
from scripts._channel import load_channel   # ← scripts がパッケージでないため本番で通らない
```

ではない。

## 実測による証明

### probe 仕様

`tasks/evidence/step_2b_prod_import_probe.py` は subprocess で以下を再現する:

1. `cwd = <project>/scripts` (run.bat:3 と等価)
2. `python.exe -X utf8 -c <payload>` (production と等価な起動形式)
3. payload は `from _channel import load_channel` → `load_channel('health')` → happy + error 4 ケース検証

### 実行コマンド

```cmd
cmd.exe /c "cd /d C:\Users\user\Desktop\youtube-system && ^
    set PYTHONIOENCODING=utf-8 && ^
    C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe ^
    tasks\evidence\step_2b_prod_import_probe.py"
```

### 結果 (`tasks/evidence/step_2b_prod_import_probe.log`)

```
cwd=C:\Users\user\Desktop\youtube-system\scripts
sys.path[0]=
python=3.11.9
OK happy: id=health themes=themes.txt lock=logs/last_upload_date.txt
OK happy: schema_version=1 script_min=6000 script_max=7500
OK happy: tags_count=2
OK error: missing_file
OK error: regex_violation_dotdot
OK error: regex_violation_upper
OK error: empty_string
INFO secrets.__file__=C:\Users\user\Desktop\youtube-system\scripts\secrets.py
INFO secrets_is_shadowed_by_scripts=True
OK module: _channel / _channel_schema do not reference stdlib secrets
PROBE_OK
[probe] ---- child exit: 0 ----
[probe] RESULT: OK
```

### `sys.path[0]=""` の解釈

probe の child は `python.exe -c ...` 形式で起動しているため `sys.path[0]` が空文字列になる。これは Python の仕様上「cwd を参照」を意味する。本番 `python.exe generator.py` では `sys.path[0]` が絶対パス `C:\...\scripts` に設定される。

**両者の等価性:**
- 空文字列 `""` は「import 時点の cwd」を指す
- 本番 generator.py は startup の import phase (notifier, skills.self_healing, 将来の _channel) の間 cwd を変更しない
- したがって startup import に関しては両者は **機能的に完全に等価**

もし将来 generator.py が cwd 変更後に import を行うような特殊パターンを導入するなら再検証が必要だが、現状そのような設計予定はない。

## secrets shadowing について

probe の INFO:
```
INFO secrets.__file__=C:\Users\user\Desktop\youtube-system\scripts\secrets.py
INFO secrets_is_shadowed_by_scripts=True
```

**本番では stdlib `secrets` は `scripts/secrets.py` によって既に shadow されている**。これは Step 2-α 以前からの既存状態であり、Step 2-α / 2-β の両方で `_channel` / `_channel_schema` は stdlib `secrets` に依存していない (probe で `hasattr` チェック済み) ため問題にならない。

## 結論

**Step 2-β では以下を行わない:**
- `scripts/_channel.py:27` の import 方式変更 → **不要** (本番で正しく動作する)
- `scripts/__init__.py` 新設 → **不要** (既存 import 全体に波及する変更は過剰)
- 既存テストの修正 → **不要** (test は既に importlib 注入で独立動作している)

**Step 2-β で行ったこと:**
- 本番形態の実測 probe を追加 (`tasks/evidence/step_2b_prod_import_probe.py`)
- 実測ログを evidence として保存 (`tasks/evidence/step_2b_prod_import_probe.log`)
- 本 note で Codex Medium advisory 解消の根拠を記録

**コード変更行数: 0**

**10:00 健康チャンネル定時タスクへの影響: 完全ゼロ** (コード変更ゼロ、read-only 実測のみ)

---

## 自己レビューチェックリスト適用結果 (tasks/self_review_checklist.md)

### §0. 前提確認
- **§0-1 no-op 性**: YES。scripts/_channel*.py および tests/test_channel.py に変更なし。probe と note のみ追加。
  - 根拠: `git status --short` で追加ファイルは `tasks/evidence/step_2b_*` と本 note のみ
- **§0-2 変更ファイル列挙**:
  - 追加: `tasks/evidence/step_2b_prod_import_probe.py`, `tasks/evidence/step_2b_prod_import_probe.log`, `tasks/evidence/step_2b_note.md`
  - 変更: なし
  - 削除: なし

### §1. 網羅性チェック
- **§1-1a 宣言と実体**: N/A (本 Step は新規 test 追加なし、probe の 1 本のみ)
- **§1-1b 代表値/網羅**: probe は「happy 1 + error 4」の代表値テスト。既存 37 tests が網羅を担保しているため重複不要。
- **§1-1c 命名一致**: N/A
- **§1-2a 両 Path モデル**: N/A (本 Step は path 検証ロジックを触らない)
- **§1-2b edge case**: N/A (同上)
- **§1-2c PureWindowsPath**: N/A (同上)
- **§1-3a probe 再現性**: YES。probe は subprocess で cwd=scripts/ を強制再現。本番 `run.bat:3` の `cd /d ...scripts` と同じ状態を作る。
- **§1-3b ダミー注入**: N/A (本番経路をそのまま通すため注入なし)
- **§1-3c 類推で済ませていないか**: NO。実測のみで結論している。

### §2. 契約の完全性
- **§2-1 関数契約**: N/A (関数追加なし)
- **§2-2 失敗経路**: probe で error 4 件実測 (missing / traversal / regex / empty)
- **§2-3 pure 宣言**: N/A
- **§2-4 error path 比率**: happy 1 : error 4 = error 比重高、OK

### §3. 既存システム制約
- **§3-1 cp932**: probe の出力は ASCII のみ。日本語混入なし。
- **§3-2 ffmpeg**: N/A
- **§3-3 WSL/Windows path**: Windows native Python で実行。probe 内でパス変換なし。
- **§3-4 Gemini**: N/A
- **§3-5 一時ファイルロック**: N/A
- **§3-6 scripts/secrets.py shadowing**: YES 考慮済み。probe で本番 shadow 状態を観察し、`_channel` / `_channel_schema` が stdlib secrets に依存しないことを確認。
- **§3-7 Task Scheduler 連動**: YES。`run.bat` / `generator.py` / `skill_*.py` を **1 文字も変更していない**。
- **§3-8 self_healing**: N/A
- **§3-9 pickle / module cache**: YES。既存モジュール名・階層・`__init__.py` を変更していない。

### §4. 実行環境の実測裏付け
- **§4-1 Windows native**: YES。`C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe` で実行。
- **§4-2 cmd.exe 形式**: YES。`cmd.exe /c "cd /d C:\... && set PYTHONIOENCODING=utf-8 && python.exe ..."` 形式。
- **§4-3 cp932 エラー**: 出ていない。PROBE_OK まで完走。
- **§4-4 全文保存**: YES。`tasks/evidence/step_2b_prod_import_probe.log` にフル保存。
- **§4-5 実測環境**: YES。probe output に `cwd`, `sys.path[0]`, `python version`, `secrets.__file__` を記録。

### §5. 3 歩先チェック 4 問
- **§5-1 Q1 検知**: probe 自体は CI/定期実行に組み込まれていない。ただしコード変更ゼロのため壊れる余地がない。将来 `_channel.py` の import を変更したら本 probe を再実行する運用。
- **§5-2 Q2 エッジケース**: probe で 4 種類の error path を実測済。sys.path[0]=="" vs 絶対パスの差は note で明示的に分析済。
- **§5-3 Q3 ユーザー不在**: YES。probe は read-only で 10:00 タスクに完全非依存。ユーザー不在中に probe を動かす必要がそもそもない。
- **§5-4 Q4 本番条件**: YES。Windows native Python + cp932 locale + 実ファイル (`config/channels/health.json`) を使用。DRY_RUN / モックなし。

### §6. 実装詳細
- **§6-1 事前 Read**: YES。`scripts/_channel.py`, `scripts/_channel_schema.py`, `scripts/generator.py` 先頭 130 行, `run.bat`, 既存 Codex review note を読んでいる。
- **§6-2 最小変更**: YES。コード変更ゼロ。
- **§6-3 get_secret**: N/A
- **§6-4 notifier / error_logger**: N/A
- **§6-5 line["text"]**: N/A
- **§6-6 禁止ファイル stage**: NO (stage していない)
- **§6-7 containsSyntheticMedia**: N/A

### §7. 宣言と実装の対応
- **§7-1 宣言と実装**: 本 Step の宣言「コード変更ゼロで Codex Medium advisory を解消する」と実装 (コード変更 0、probe 追加) が一致。
- **§7-2 テスト件数一致**: N/A
- **§7-3 取りこぼし検証**: probe の `PROBE_OK` assertion で取りこぼしゼロを確認。
- **§7-4 no-op 証明**: YES。`grep -r "from _channel import\|import _channel" scripts/` で Step 2-α 自身以外に呼び出し元なし。
- **§7-5 adversarial 自己読み**: YES。sys.path[0]=="" vs 絶対パス差分に自分で突っ込みを入れて note に明示記述。

### §8. Codex 運用ルール
- **§8-1 実装 PR か**: NO。本 Step は設計ドキュメント + 実測 evidence のみで、コード変更ゼロ。
  - `self_review_checklist.md §8-1` に従い **本リストのみで自己完結させ、Codex は呼ばない**。
- **§8-2 Critical/High only**: N/A (Codex 呼ばない)
- **§8-3 NO-GO 覚悟**: N/A
- **§8-4 高リスク領域**: 触れていない (probe のみ)
- **§8-5 全項目通過**: YES

**NG だった項目と対処**: なし
**Codex に送るかどうか**: 送らない (理由: コード変更ゼロ、§8-1 適用)
