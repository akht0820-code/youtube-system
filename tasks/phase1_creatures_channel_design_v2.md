# フェーズ1 設計提案 v2 — Codex 指摘 11 件反映版

生物チャンネル分岐設計

作成日: 2026-04-10
改訂: v1 → v2（Codex adversarial review NO-GO 判定を受け全面改訂）
ステータス: **実装未着手・ユーザー承認待ち**

---

## 0. v2 改訂サマリ（Codex 指摘との対応表）

v1 では 11 件の重大/高リスク指摘を受けた。本 v2 は全件に応答する。

| # | Codex 指摘 | v1 の問題 | v2 の対応 | 対応セクション |
|---|---|---|---|---|
| C1 | 抽象化スコープが狭すぎる | 大規模改修対象を 4 ファイルしか列挙していなかった | §2 に全 7 (token/cred/lock) + 12 (OUTPUT_DIR) ファイルを列挙 | §2 |
| C2 | DRY_RUN ゲートが存在しないフラグ前提 | `generator.py --dry-run` は存在しない (現在は `--no-upload` のみ) | §5 で `--dry-run` 契約を新規定義 | §5 |
| C3 | md5 比較での DRY_RUN 検証は破綻 | LLM 非決定性 + ランダムなナラティブスタイル選択 | §6 で 3 層検証 (fixture / invariant / mock replay) に置換 | §6 |
| C4 | `self_healing.py` を「そのまま利用可能」と断じた誤り | `_fix_delete_token_reauth` 等がグローバル資源に触る | §3 で危険資産として分類、チャンネル所有権を必須化 | §3 |
| C5 | YAML schema が緩すぎて誤設定を起動時に検知できない | 平坦な key/value 列挙 | §4 で nested + version + 起動時 strict validation | §4 |
| C6 | 各スキル間のメディア資産引継ぎ契約が未定義 | script → video_build の間で実体パス渡しの保証なし | §7 で manifest 契約を定義 | §7 |
| C7 | Gemini rate limit の 2 本/日合算での振る舞いが未定義 | 「余裕」と書いたが RPM burst 保証なし | §8 で provider 中央 rate limiter + jitter + 429 cooldown を新規定義 | §8 |
| C8 | Wikimedia ライセンス fail-closed の具体仕様欠落 | 「fail-closed」と書いただけ | §9 で検証項目を列挙 | §9 |
| C9 | cross-platform file lock 方針が曖昧 | thumbnail_history と upload_lock が別機構 | §10 で統一 locking helper 方針 | §10 |
| C10 | OAuth token refresh の race (同時 refresh で片方が破損) | 未検討 | §11 でチャンネル別 token + refresh lock | §11 |
| C11 | preflight_runtime.py / publish_now.py の hardcoded path | v1 D の改修対象から漏れていた | §2 で追加、§12 Phase マップに反映 | §2, §12 |

---

## 1. 基本方針（v1 §3 A から変更なし）

- **パターン3（共通基盤 + チャンネル別設定）を採用** — ユーザー承認済み
- 健康チャンネルの既存稼働を一切損なわない（既存動作の後方互換を絶対条件）
- 生物チャンネル側はアディティブな追加のみ
- 直列実行 + 時差起動（WSL2 メモリ 5.7GB 制約のため並列不可）

以下 §2 以降が v1 からの実質的な改訂部。

---

## 2. 直接参照の完全棚卸し（C1, C11 対応）

v1 では改修対象を 4 ファイルしか列挙していなかった。実際には **「グローバル資源の直接参照」** が 2 群に分かれる。Phase 2 はこの 2 群を全て config 経由に置き換えなければ「チャンネル切替」は成立しない。

### 2-1. token / credentials / 1日1本 lock の直接参照（7 ファイル）

| # | ファイル | 現行コード | 参照内容 | 対応 |
|---|---|---|---|---|
| 1 | `scripts/auth_utils.py:17-19` | `CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"` / `TOKEN_PATH = PROJECT_ROOT / "token.json"` | OAuth 認証の起点 | `get_credentials(channel_cfg)` に変更、cfg から path 解決 |
| 2 | `scripts/youtube_uploader.py:305` | `token_path = PROJECT_ROOT / "token.json"` | アップロード時の token ロード | 引数で `channel_cfg` 受け取る |
| 3 | `scripts/preflight_runtime.py:40,67,87` | `token_path = PROJECT_ROOT / "token.json"` / `cred_path = PROJECT_ROOT / "credentials.json"` / `lock_file = LOGS_DIR / "last_upload_date.txt"` | 09:55 プリフライトの 3 種 path | 両チャンネルをループ、各 channel_cfg から解決 |
| 4 | `scripts/publish_now.py:17` | `token_path = Path(__file__).parent.parent / "token.json"` | 手動公開ツール | `publish_now(video_id, channel="health")` に拡張 |
| 5 | `scripts/generator.py:105` | `_lock_path = LOGS_DIR / "last_upload_date.txt"` | 1日1本ロック | channel_cfg.lock_file から解決 |
| 6 | `scripts/skills/skill_upload.py:29` | `_lock_path = LOGS_DIR / "last_upload_date.txt"` | 同上（upload 側） | 同上 |
| 7 | `scripts/skills/self_healing.py:159-166` | `token_path = PROJECT_ROOT / "token.json"` を `unlink()` する `_fix_delete_token_reauth` | **危険**: 片方のチャンネルのエラーで両方の token を削除する | §3 で別途扱う |

### 2-2. `output/` ディレクトリの直接参照（12 ファイル）

| # | ファイル | 現行コード | 役割 | 対応 |
|---|---|---|---|---|
| 1 | `scripts/generator.py:16` | `OUTPUT_DIR = PROJECT_ROOT / "output"` | run_dir 作成の基点 | channel_cfg.output_subdir |
| 2 | `scripts/analyzer.py:13` | `OUTPUT_DIR = PROJECT_ROOT / "output"` | テーマ分析 | channel 別ループ |
| 3 | `scripts/run_monitor.py:21` | `OUTPUT_DIR = ...` | post-run 監視 | 両チャンネル対象 |
| 4 | `scripts/preflight_check.py:23` | `OUTPUT_DIR = ...` | 13:00 プリフライト | 両チャンネルループ |
| 5 | `scripts/discord_bot.py:45` | `OUTPUT_DIR = ...` | 操作対象 | channel 指定引数 |
| 6 | `scripts/image_generator.py:716` | `THUMB_HISTORY_FILE` | サムネ重複回避履歴 | channel 別 history file (§10) |
| 7 | `scripts/skills/_common.py:366` | `output_dir = PROJECT_ROOT / "output"` | 共有ヘルパ | channel_cfg 経由 |
| 8 | `scripts/skills/skill_cache_cleanup.py:24` | `OUTPUT_DIR = ...` | キャッシュ清掃 | 両チャンネル対象ループ |
| 9 | `scripts/skills/skill_metadata.py:32` | `OUTPUT_DIR = ...` | メタデータ生成 | channel_cfg から |
| 10 | `scripts/skills/skill_script_gen.py:36` | `OUTPUT_DIR = ...` | 台本生成 | 同上 |
| 11 | `scripts/skills/skill_upload.py:28` | `OUTPUT_DIR = ...` | アップロード | 同上 |
| 12 | `scripts/skills/skill_video_build.py:23` | `OUTPUT_DIR = ...` | 動画合成 | 同上 |

### 2-3. Phase 2 最小 PR 粒度の再定義

v1 の「Step 2-1 〜 2-5」は抽象度が荒く、Codex から「1 ステップの変更範囲が広すぎ、DRY_RUN 検証の粒度も合わない」と指摘された。v2 では §2-1 と §2-2 のファイル群を **1 ステップ 3〜4 ファイルの独立 PR** に割り直す（§12 Phase マップ参照）。

---

## 3. self_healing.py を「危険資産」として再分類（C4 対応）

v1 では「そのまま利用可能」と断じたが誤り。以下 3 関数が **グローバル資源** に触れるため、チャンネル分岐以前に単独で問題を起こし得る。

### 3-1. 危険箇所の棚卸し

| 関数 | 動作 | 危険性 |
|---|---|---|
| `_fix_delete_token_reauth` (line 158-166) | `PROJECT_ROOT / "token.json"` を `unlink()` | **片方のチャンネルで OAUTH_EXPIRED が出ると両方の token が消える**。`_ESCALATION` の `OAUTH_EXPIRED` 経路で自動発火する |
| `_fix_kill_orphan_processes` → `_common.force_kill_pipeline_processes` | `tasklist.exe` で python.exe/ffmpeg を列挙し `os.getpid()`/`os.getppid()` 以外を全 kill | **健康側の実行中プロセスを生物側の修復で殺す** |
| `_fix_delete_temp_files` (line 111) | `Path(run_dir).parent` = `output/` 配下を GC | run_dir の親ディレクトリ前提 → 生物側 run_dir から呼ぶと `output_creatures/` を GC するのは正しいが、両チャンネル共通の tmp を触る可能性を監査要 |
| `_fix_memory_deep_cleanup` | 上記 kill + GC + video_builder キャッシュクリア | 同上の合算 |

### 3-2. v2 での扱い

- `self_healing` は **Phase 2 の「危険資産」扱い** とし、チャンネル分岐の完全完了までこの経路は抑制する
- 具体策:
  - Phase 2 の期間中、`_ESCALATION["OAUTH_EXPIRED"]` から `_fix_delete_token_reauth` を一時的に除外（通知のみに降格）
  - `force_kill_pipeline_processes` に `allow_pids: set[int]` 引数を追加し、両チャンネルの稼働中 pid を除外
  - `_fix_delete_temp_files` は `channel_cfg.output_subdir` を受け取り、そのサブツリーのみを GC
- これらは **Phase 2 Step 2-D（危険資産のチャンネル化）** として独立 PR 化する
- Codex レビューは `self_healing.py` 変更 PR のみ単独で受ける（他のリファクタと混ぜない）

### 3-3. 3歩先チェック Q1（検知の検知）

- `_fix_delete_token_reauth` を抑制した状態で、テスト的に `raise OAUTH_EXPIRED` を発生させ **通知のみが飛ぶ** ことを確認
- 抑制解除忘れ対策: `self_healing.py` 冒頭に「Phase 2 完了フラグ」を置き、Phase 2 終了時にのみ False → True に切り替える
- フラグの逆戻り防止: `config/channels/_phase2_done.flag` を別ファイルにし、Git log で切替履歴が残る形にする

---

## 4. YAML schema の strict 化 + version field（C5 対応）

v1 の yaml 例は key の階層が浅く、起動時に誤設定を検出できない。v2 では **nested schema + version field + 起動時 strict validation** を必須にする。

### 4-1. schema（`scripts/_channel_schema.py` で dataclass 定義）

```yaml
# config/channels/health.yaml
version: 1                                # 必須。schema バージョン不一致は起動時 fail
id: health                                # [a-z_]+ のみ、パス要素に使う
display_name: ゆっくり健康ラボ

paths:                                    # 全て PROJECT_ROOT 相対、Path.resolve() 必須
  output_subdir: output
  themes_file: themes/health.txt
  lock_file: logs/last_upload_date.txt
  rotation_state_file: null               # 健康は未使用

oauth:
  credentials: credentials.json
  token: token.json
  refresh_lock: logs/token_refresh_health.lock   # §11 で追加

youtube:
  expected_channel_id: UCxxxxxxxx         # 必須、fail-closed 検証に使う
  publish_time: "18:00"                   # HH:MM 形式、正規表現で検証

script:
  min_chars: 6000
  max_chars: 7500
  narrative_structure: healthcare_essay   # enum: healthcare_essay / five_act / ...
  prompts_module: prompts.health          # dotted path、起動時 importlib で実体確認

thumbnail:
  theme_categories: [food, sleep, exercise, dental, mental, warning, general]
  history_file: output/.thumbnail_history.json   # §10 で channel 別に

images:
  provider: gemini                        # enum: gemini / wikimedia_commons / ...
  fallback_provider: null
  scene_prompt_style: healthcare_lifestyle

runtime:
  gemini_rate_limit_key: health           # §8 で central rate limiter のキー
  daily_upload_max: 1
  preflight_enabled: true

tags:
  default: [ゆっくり解説, 健康]
  ai_disclosure: "この動画はAIにより生成された合成音声を使用しています"
```

### 4-2. 起動時 validation（`load_channel()` の責務）

1. `version` が未知なら即 `ChannelSchemaError` で fail-closed
2. `id` が `^[a-z][a-z0-9_]*$` に一致しない場合 fail
3. `paths.*` を全て `Path(PROJECT_ROOT / v).resolve()` し、PROJECT_ROOT 配下から脱出していたら fail（path traversal 防止）
4. `oauth.credentials` と `oauth.token` のファイル存在確認（token は未存在許容、credentials は必須）
5. `youtube.expected_channel_id` 未設定時は fail（誤投稿を防ぐため必須化）
6. `script.prompts_module` を `importlib.import_module()` で即時ロード、失敗なら fail
7. `images.provider` が enum 外なら fail
8. 全 path が **両チャンネル間で一意** であることを全チャンネル load 後に交差チェック（`token.json` を両方が参照していたら fail）

### 4-3. 3歩先チェック Q2（エッジケース）

- yaml 編集ミス: 未知 key はログ WARN で報告（fail ではない。将来の schema 追加許容）
- BOM 問題: `yaml.safe_load(open(p, encoding="utf-8-sig"))` で吸収
- 改行コード: `.gitattributes` で `*.yaml text eol=lf`
- 型崩れ: dataclass field に型 annotation、`dataclasses.asdict` でチェック

---

## 5. DRY_RUN 契約の新規定義（C2 対応）

v1 は存在しない `--dry-run` を前提にしていた。v2 では新規導入する。

### 5-1. フラグと契約

```
python scripts/generator.py --auto --channel health --dry-run
```

- `--dry-run` は `--no-upload` の **上位互換** + 以下を追加する:
  1. **upload phase skip**: `pipeline.json` の `upload` を `skipped(dry_run)` でマーク
  2. **YouTube API 抑止**: `youtube_uploader` の client 作成前に `DRY_RUN=1` なら raise
  3. **外部 API コスト抑止**:
     - Gemini: quality=simple を強制し、max_tokens を通常の 1/4 に
     - 画像生成: 既存 `output/` 内の最新画像を cp してきて使い回す（`image_generator.dry_run_mode`）
  4. **state update 無効化**: `last_upload_date.txt` を touch しない、`thumbnail_history.json` も append しない
  5. **Discord 通知抑止**: notifier 側で `DRY_RUN=1` なら「[DRY_RUN]」プレフィックス付きで1通だけ
- `DRY_RUN=1` は環境変数でも有効（スキル単独実行時の一貫性）

### 5-2. `--dry-run` 実装箇所（新規コード）

| ファイル | 変更 |
|---|---|
| `scripts/generator.py` | argparse に `--dry-run` 追加、環境変数に伝播 |
| `scripts/skills/_common.py` | `is_dry_run() -> bool` ヘルパ追加 |
| `scripts/skills/skill_upload.py` | `is_dry_run()` なら phase を `skipped(dry_run)` にして即 return |
| `scripts/youtube_uploader.py` | `is_dry_run()` なら client 作成前に raise（fail-fast） |
| `scripts/skills/skill_script_gen.py` | `is_dry_run()` なら `quality=simple` |
| `scripts/image_generator.py` | `is_dry_run()` なら最新画像を cp して使い回す |
| `scripts/notifier.py` | `is_dry_run()` なら Discord 通知を 1通だけ、prefix `[DRY_RUN]` |

### 5-3. 3歩先チェック Q3（ユーザー不在時）

- DRY_RUN 忘れ暴走防止: `--dry-run` 指定時は `notifier` が「[DRY_RUN] 開始」通知を冒頭で飛ばす。通知が飛ばない場合は実投稿モードと判定可能
- `DRY_RUN=1` 環境変数のリーク防止: `run.bat` で `set DRY_RUN=` を冒頭に入れ、親プロセスからの伝染を遮断

---

## 6. 検証の 3 層化（C3 対応）

v1 の「md5 比較」は非決定的な LLM 出力と相性が悪く破綻する。v2 では 3 層に分離する。

### 6-1. Layer 1: Fixture snapshot（決定的な config/schema 側）

- 対象: channel_cfg の load 結果、prompts モジュールの定数、schema 制約
- 方法: `tests/fixtures/health_channel_v1.json` を用意し、`load_channel("health")` の `asdict` を `json.dumps(sort_keys=True)` して byte-level 一致を確認
- 期待: 完全一致（不一致 = リファクタ漏れ）

### 6-2. Layer 2: Structural invariant（決定的構造の確認）

- 対象: pipeline.json の schema、run_dir の必須ファイル集合、metadata の key 集合、動画尺の許容範囲
- 方法: 毎回 run を実行し、以下の invariant を検証:
  - `pipeline.json.phases` の key 集合が既知セットと一致
  - `run_dir/` 直下の `script.json`, `metadata.json`, `video.mp4` (dry_run 時はダミー), `thumbnail.png` が存在
  - `metadata.json.title` が str、長さ 15〜100
  - `metadata.json.tags` が list[str]、1〜30 個
  - 動画尺が 900〜1200 秒（健康チャンネルの定常範囲）
- 期待: 全 invariant 成立（内容の byte 一致は見ない）

### 6-3. Layer 3: Mock provider replay（決定的実行の再現）

- 対象: LLM / image provider の呼び出し前後で pipeline の挙動が等価か
- 方法:
  - `providers.py` に `ReplayProvider` を新設
  - Phase 2 Step 2-A 着手前に、既存コードで 1 本 health を実行し、LLM レスポンス・画像レスポンスを `tests/replay/YYYYMMDD/*.json` に保存
  - 抽象化後のコードを同じ replay データで走らせ、step-by-step に出力を比較
- 期待: 全ステップで構造一致（Layer 2）と、LLM 入力プロンプトの byte 一致
- 重要: **プロンプトは決定的** のはず（入力テーマが同じなら）なので prompt の byte 一致は成立する。出力の byte 一致は求めない

### 6-4. どの Layer を Phase 2 のどのステップで使うか

| Step | Layer 1 | Layer 2 | Layer 3 |
|---|---|---|---|
| 2-A: config/YAML + `_channel.py` | **必須** | - | - |
| 2-B: prompts パッケージ化 | 必須 | - | **必須**（prompt byte 一致） |
| 2-C: generator.py `--channel` | 必須 | **必須** | - |
| 2-D: self_healing 抑制 | - | **必須** | - |
| 2-E: upload/auth の channel 化 | 必須 | 必須 | **必須** |
| 2-F: output_dir 系 12 ファイルの channel 化 | 必須 | 必須 | 必須 |
| 2-G: 本番 1 本投入 | - | **必須** | - |

### 6-5. 3歩先チェック Q4（本番テスト）

- Layer 1-3 全通過 → Step 2-G で **本番投稿** を 1 本実施（DRY_RUN ではなく本番）
- 本番投稿後に run_monitor.py で自動チェック: 過去 10 本の動画と title 長さ / tag 数 / 説明文長さ / サムネ解像度 / 動画尺 を比較し逸脱なしを確認
- 逸脱あり → 即 git revert → ユーザー通知

---

## 7. Media asset manifest 契約（C6 対応）

v1 ではスキル間のメディア受渡しが「`run_dir/` 内の実体ファイル」という暗黙契約だった。チャンネル分岐後は generation path が分岐するため **manifest JSON で明示契約** する。

### 7-1. `run_dir/manifest.json`（新設）

```json
{
  "version": 1,
  "channel_id": "health",
  "run_id": "20260410_100000_foo",
  "created_at": "2026-04-10T10:00:01+09:00",
  "script": {
    "path": "script.json",
    "checksum_sha256": "...",
    "source": "llm:gemini-2.5-pro",
    "min_chars": 6000,
    "max_chars": 7500,
    "actual_chars": 6840
  },
  "metadata": {
    "path": "metadata.json",
    "checksum_sha256": "...",
    "title_length": 38,
    "tag_count": 12
  },
  "tts": {
    "wav_dir": "wav/",
    "file_count": 87,
    "total_duration_sec": 1021.3,
    "provider": "aquestalk_v2"
  },
  "video_build": {
    "path": "video.mp4",
    "checksum_sha256": "...",
    "duration_sec": 1021.3,
    "resolution": "1920x1080",
    "codec": "libx264"
  },
  "thumbnail": {
    "path": "thumbnail.png",
    "checksum_sha256": "...",
    "resolution": "1280x720",
    "history_reserved_at": "2026-04-10T10:03:15+09:00"
  },
  "upload": {
    "youtube_video_id": null,
    "published_at": null,
    "channel_id_actual": null,
    "dry_run": true
  },
  "media_licenses": [
    {
      "file": "images/creature_01.jpg",
      "source": "wikimedia_commons",
      "license": "CC-BY-SA-4.0",
      "author": "Foo Bar",
      "url": "https://..."
    }
  ]
}
```

### 7-2. 契約ルール

- 各スキルは開始時に manifest を load、終了時に自スキル section を update して atomic write
- 後段スキルは前段 section の `checksum_sha256` を検証してから処理開始
- 不一致 = 前段の出力が壊れている / 改変されている → fail-closed
- `channel_id` は全段で固定検証（途中で channel が変わるバグを検出）

### 7-3. atomic write

`_common.py` に `atomic_write_json(path, data)` を追加:
```python
def atomic_write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)  # POSIX atomic rename
```

---

## 8. Gemini rate limiter 中央化（C7 対応）

v1 は「無料枠内に収まる」としか書いていない。2 本/日でも同一分に burst があると 429 で両方失敗し得る。

### 8-1. 設計

- `scripts/providers.py` に `GeminiRateLimiter` クラスを新設
- プロセス内 singleton + ファイルロックで **両チャンネル同時起動時も調停**
- ロックファイル: `logs/gemini_rate_limit.state.json`（msvcrt / fcntl で保護）
- state schema:
  ```json
  {
    "version": 1,
    "daily": {"date": "2026-04-10", "count": {"health": 42, "creatures": 31}},
    "recent_calls": [
      {"ts": 1775832065.123, "channel": "health", "model": "gemini-2.5-pro"}
    ]
  }
  ```

### 8-2. Throttle policy

- Gemini 2.5 Pro RPM: 2 calls/min に制限（通常 5 だが安全率）
- Gemini 2.5 Flash RPM: 10 calls/min
- 日次 RPD: pro 50 / flash 200（無料枠より低く設定、クッション）
- burst 超過時: `time.sleep(60 - elapsed)` で次分まで待機、ただし上限 90 秒で abort
- 429 受信時: exponential backoff (2, 4, 8s) + 最終失敗で fail、notifier に通知
- jitter: 各 sleep に `random.uniform(0, 2)` 秒を加算（両チャンネル同時起動時の衝突回避）

### 8-3. 起動時差の再検討

- v1 は「11:30 → 12:00」推奨だったが、実際には Gemini rate limit の daily cooldown は 24h 単位 → 時差起動だけでは不十分
- v2: **健康 10:00 / 生物 12:00 を維持** + rate limiter が burst を調停
- 万が一の同時起動事故時も rate limiter で片方が順延する

---

## 9. Wikimedia ライセンス fail-closed 具体仕様（C8 対応）

v1 は 1 行だけだった。v2 では検証項目を列挙する。

### 9-1. 必須フィールド

- `license`: enum 照合 (`CC-BY-4.0`, `CC-BY-SA-3.0`, `CC-BY-SA-4.0`, `CC0-1.0`, `public domain`)
- `author`: 空文字列 NG
- `source_url`: `https://commons.wikimedia.org/` から始まること
- `uploaded_by`: optional だが記録

### 9-2. Fail-closed 条件

1. 単一画像でライセンス取得失敗 → 該当画像を破棄、代替を 3 回まで再試行
2. 1 本の動画で **全画像が破棄** → `skill_creature_images` を fail、pipeline を error 終了
3. 1 本の動画で **50% 以上の画像が破棄** → WARN 通知 + 手動確認 prompt、ただし pipeline は継続
4. `license` enum 外 → 即破棄（上記 1 扱い）

### 9-3. エンドクレジット画面（`skill_credits`）

- manifest.media_licenses を読み取り、動画末尾 20 秒に表示
- 1 画面あたり 5 件、複数ページなら 4 秒/ページ
- ライセンス URL も QR コードで併記（fair use の確実性向上）

---

## 10. File locking の統一（C9 対応）

現行は `thumbnail_history` と `upload_lock` が別実装。v2 では統一する。

### 10-1. 共通 helper: `scripts/_file_lock.py`（新設）

```python
@contextmanager
def cross_platform_lock(lock_path: Path, timeout_sec: float = 30.0):
    """msvcrt (Win) / fcntl (Unix) を吸収する排他ロック。
    timeout 超過で TimeoutError を raise。
    lock ファイルは呼び出し側が後片付け不要（with 退出で release）。
    """
```

- Windows: `msvcrt.locking(fd, LK_NBLCK, 1)` を retry with backoff
- Unix: `fcntl.flock(fd, LOCK_EX | LOCK_NB)` を retry
- retry interval: 50ms, max 600 回 = 30s（既存 thumbnail_history と同等）

### 10-2. 既存機構の移行

| 対象 | 現行 | 移行後 |
|---|---|---|
| `image_generator._HistoryLock` | 独自実装 | `cross_platform_lock()` に委譲 |
| `skill_upload` の lock | 独自 msvcrt + fd 手管理 | `cross_platform_lock()` |
| 新設: token refresh lock (§11) | - | `cross_platform_lock()` |
| 新設: gemini rate limiter state (§8) | - | `cross_platform_lock()` |

### 10-3. channel 別 lock file path（既に §4 yaml で反映済）

- `thumbnail_history`: `output_{channel}/.thumbnail_history.json`
- `upload_lock`: `logs/last_upload_date_{channel}.txt` → `.lock` 同階層
- `token refresh lock`: `logs/token_refresh_{channel}.lock`

---

## 11. OAuth token refresh の race condition 対策（C10 対応）

v1 は token パスの分離しか考えていなかった。実際には **refresh 処理の race** がある。

### 11-1. 問題

- `google-auth` ライブラリの `Credentials.refresh()` は token の再書き込みを行うが、同一 token.json への並列 refresh は後勝ちで一方が破損する
- 健康と生物が別 token ファイルを持っていても、同一プロセス内で両方同時に refresh すると同じく race
- preflight_runtime が 09:55 に refresh し、10:00 の本チャンネルも refresh しようとすると衝突

### 11-2. 対策

1. **channel 別 token ファイル**（既に §2, §4 で反映）
2. **refresh 時にファイルロック取得**: `_file_lock.cross_platform_lock(cfg.oauth.refresh_lock)` で保護
3. **refresh 後 fsync**: `os.fsync(fd)` で書込み確定
4. **auth_utils の refresh wrapper**:
   ```python
   def get_credentials(channel_cfg: ChannelConfig) -> Credentials:
       with cross_platform_lock(channel_cfg.oauth.refresh_lock, timeout=60):
           creds = Credentials.from_authorized_user_file(...)
           if not creds.valid:
               creds.refresh(Request())
               atomic_write_json(channel_cfg.oauth.token, json.loads(creds.to_json()))
           return creds
   ```
5. **channel ID 検証**: refresh 後に `youtube.channels().list(mine=True)` を呼び、`expected_channel_id` と不一致なら fail-closed（token の取り違え検知）

### 11-3. preflight_runtime との協調

- 09:55 preflight が refresh 済みなら 10:00 の本チャンネルは refresh 不要
- 逆に preflight をスキップした場合でも本チャンネル側で refresh lock が有効に働く
- lock timeout: 60s（refresh 自体は 2〜3s で完了する想定、余裕を取る）

---

## 12. Phase マップ（v2 改訂版）

v1 の Phase 2 は Step 5 構成だったが粒度が荒く 1 ステップで触るファイルが 10+ になっていた。v2 では **1 ステップ 3〜4 ファイル** の独立 PR に割り直す。

### Phase 2: 健康チャンネルのみで完全後方互換の抽象化（★実装期間はコード変更禁止のまま待機）

| Step | 内容 | 触るファイル | 検証 Layer | DRY_RUN ゲート | ユーザー確認ゲート |
|---|---|---|---|---|---|
| 2-A | `config/channels/health.yaml` + `scripts/_channel.py` + `scripts/_channel_schema.py` 新設 | 新規 3 ファイル + `scripts/_file_lock.py` | L1 | load_channel 単体 | 2-A 結果報告 → OK → 2-B |
| 2-B | prompts.py → prompts/ パッケージ化 | `prompts.py` → `prompts/__init__.py`, `prompts/health.py` | L1 + L3 | prompt byte 一致 | 2-B 報告 → OK → 2-C |
| 2-C | generator.py `--channel` + `--dry-run` 引数 | `generator.py`, `skills/_common.py`, `notifier.py` | L1 + L2 | DRY_RUN 1本通過 | 2-C 報告 → OK → 2-D |
| 2-D | self_healing の危険資産抑制 | `skills/self_healing.py`, `skills/_common.py:force_kill_*` | L2 | 人為 error 注入で通知のみ確認 | 2-D 報告 → OK → 2-E |
| 2-E | auth/upload/youtube_uploader の channel 化 | `auth_utils.py`, `youtube_uploader.py`, `skills/skill_upload.py`, `preflight_runtime.py`, `publish_now.py` | L1 + L2 + L3 | DRY_RUN 1本通過 | 2-E 報告 → OK → 2-F |
| 2-F | `output/` 系 12 ファイルの channel 化 | §2-2 の 12 ファイル | L1 + L2 + L3 | DRY_RUN 1本通過 | 2-F 報告 → OK → 2-G |
| 2-G | Gemini rate limiter + file_lock 統一 + manifest 契約 | `providers.py`, `image_generator.py`, `skill_upload.py`, `_common.py` | L2 + L3 | DRY_RUN 1本通過 | 2-G 報告 → OK → 2-H |
| 2-H | **本番 1 本投入** + run_monitor 逸脱チェック | 変更なし（稼働確認のみ） | L2 + 主観確認 | - | 本番 1 本 OK → Phase 3 |

### Phase 3: 生物チャンネル固有実装（v1 と同じ、割愛）

### Phase 4: インフラ統合（v1 と同じ、割愛）

### Phase 5: 本番投入前の最終検証（v1 と同じ、割愛）

---

## 13. 3歩先チェック 4問（v2 全体に対する再回答）

### Q1: この修正自体が壊れたら、どうやって気づくのか？

- Layer 1 (fixture) で config load 段階の破損を検知
- Layer 2 (invariant) で pipeline 構造の破損を検知
- Layer 3 (replay) で LLM 呼び出しプロンプトの byte 一致検証
- 各 Step 完了時に **3 Layer の結果** + **Discord 通知** + **ユーザー目視** の三重ゲート
- self_healing の危険資産は Phase 2 期間中抑制 → 検知漏れが存在しない

### Q2: この変更で別のエッジケースが生まれないか？

- `--dry-run` 環境変数のリーク → `run.bat` で明示 unset
- YAML schema version 不整合 → 起動時 fail
- token refresh race → channel 別 lock + fsync
- Gemini burst → central rate limiter + jitter
- Wikimedia ライセンス欠損 → fail-closed 3 段階
- channel ID 取り違え → refresh 後の `channels().list(mine=True)` 検証
- output dir traversal → load_channel の path resolve で検証
- manifest 改竄 → 各段で checksum 検証

### Q3: ユーザー不在中でも機能するか？

- Phase 2 実装は日中のみ、1 Step を必ず報告してユーザー承認を取る
- Step 2-H の本番投入は **翌朝 10:00 の通常実行** に乗せる（DRY_RUN 後にユーザー承認を取ってから）
- self_healing の危険資産抑制期間中も notifier は稼働 → 異常は通知される
- ClaudeWatchdog (3 分毎) と cron (3 分毎) は継続稼働

### Q4: 「動いた」「OK」と言う前に、本当に本番条件でテストしたか？

- DRY_RUN だけで完了宣言しない
- Step 2-H で **本番投稿 1 本** を通し、run_monitor.py が過去 10 本との逸脱チェックで異常なしを確認してから Phase 3 へ
- 逸脱時は即 git revert、翌朝の 10:00 定時は revert 後の状態で走る
- 各 Step 完了時に 3歩先チェック 4 問の **具体的回答** をユーザーに提示する

---

## 14. v1 からの非変更箇所

以下は v1 から変更なし（参照は v1 §X を参照）:

- §3 A 環境分離判断（パターン3 採用、ユーザー承認済）
- §3 B チャンネル識別の基本アイデア（v1 §3 B、ただし YAML schema は §4 で strict 化）
- §3 C 直列実行 + 時差起動（v1 §3 C）
- §3 E 変更不要箇所（ただし self_healing は §3 で除外）
- §3 F 新設物（ただし §10 file_lock, §4 channel_schema.py を追加）
- Phase 3/4/5 の大枠（v1 §5 Phase 3-5）

---

## 15. 実装着手前に承認いただきたい点（v2 追加分のみ）

v1 の 6 項目は既に承認済。v2 で新たに承認が必要なもの:

1. **self_healing の危険資産抑制を Phase 2 期間中だけ実施することに同意** — Phase 2 完了時に抑制解除する旨を含む
2. **`--dry-run` フラグ新設に同意** — `--no-upload` は存続、`--dry-run` はそれを包含する
3. **3 層検証の採用に同意** — md5 byte 一致は Layer 1 / Layer 3 prompts のみで、LLM 出力は Layer 2 invariant のみ
4. **Gemini rate limiter 中央化** + **file_lock 統一** + **manifest 契約** の追加導入
5. **Phase 2 を Step 2-A 〜 2-H の 8 ステップに細分化** に同意
6. **Step 2-H の本番 1 本投入** が Phase 2 の卒業条件であることに同意

---

**実装には着手していません。** 本 v2 の §0 対応表 + §15 の 6 点について承認または修正指示をください。次は Codex adversarial review v2 にかけます。
