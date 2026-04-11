# フェーズ1 調査結果 + 設計提案（実装前レビュー）

生物チャンネル分岐設計 — フェーズ1「調査と設計提案」

作成日: 2026-04-10
ステータス: **実装未着手・ユーザー承認待ち**

---

## 1. 現状の構造調査結果

### 1-1. パイプライン実行フロー

`scripts/generator.py`（オーケストレーター、532行）が以下の順にスキルを直列呼び出し:

```
script_gen → metadata → pronunciation → se_assign → prosody
  → tts → video_build → thumbnail → self_review → upload
```

各スキルは `scripts/skills/skill_*.py`、状態は `output/{run_id}/pipeline.json` で管理。

### 1-2. チャンネル依存箇所（**全てハードコード**）

| # | 箇所 | 依存内容 | 影響度 |
|---|------|----------|-------|
| 1 | `scripts/prompts.py` (1093行) | 5種のナラティブスタイル(ranking/timeline/compare/warning/secret/expose)が**全部健康特化**。笑いの設計プロンプトに「健康ゆっくり解説チャンネル」と明記 | **大** |
| 2 | `themes.txt`（PROJECT_ROOT、121行） | 健康テーマのみ。`generator.py:19 _pick_theme_from_file()` が固定パスで読む | **大** |
| 3 | `scripts/characters.py` | 霊夢=リアクション質問役 / 魔理沙=解説進行役 固定（新チャンネルは役割定義が異なる） | 中 |
| 4 | `scripts/skills/skill_metadata.py:38` | フォールバック説明文に「健康」「医療・健康に関する判断は…」ハードコード、`#ゆっくり解説 #健康` | 中 |
| 5 | `scripts/thumbnail_director.py:43` | `_THEMES = ["food","sleep","exercise","dental","mental","warning","general"]` 健康カテゴリ。`_CANVAS_INFO` に魔理沙/霊夢の配置固定 | 中 |
| 6 | `scripts/image_generator.py:46` | `_build_image_prompt()` が「焼き鮭・味噌汁→朝食」など**健康生活シーン前提**。`IMAGE_PROVIDER` 環境変数切替は既存 | 中 |
| 7 | `scripts/skills/skill_upload.py:29,125` | `_lock_path = logs/last_upload_date.txt` **固定**、`tags=["ゆっくり解説","健康"]` デフォルト | 大 |
| 8 | `scripts/auth_utils.py:17-19` | `credentials.json` / `token.json` が **PROJECT_ROOT に1組固定** = 1 YouTube チャンネルしか認証できない | **最大** |
| 9 | `scripts/generator.py:16,22,105` | `OUTPUT_DIR/output`、`themes.txt`、`logs/last_upload_date.txt` すべて固定 | 大 |
| 10 | `run.bat` | `cd scripts → generator.py --auto --publish-time 18:00`、3回リトライ固定 | 中 |
| 11 | `task_yukkuri_daily_*.xml` | URI `\YukkuriDaily`、毎日 10:00 起動、`run.bat` 実行 | 中 |
| 12 | `scripts/preflight_check.py` | 13:00 実行、単一 run_dir を対象。複数チャンネル前提なし | 中 |

### 1-3. run_dir 構造の課題

- 現状: `output/{YYYYMMDD_HHMMSS}_{safe_theme}/` — **チャンネル識別子なし**
- `_pick_theme_from_file()` はディレクトリ名末尾で使用済みテーマを判定 → チャンネル混在すると誤判定
- `last_upload_date.txt` は `YYYY-MM-DD|video_id` の **単一ファイル** = 1日1本ルールは全チャンネル合算

### 1-4. 共通基盤として再利用可能な箇所

以下はチャンネル非依存で、そのまま 2 チャンネル共通で使えます:

- `scripts/tts.py`, `tts_aquestalk.py`, `aquestalk_synth.ps1`（音声合成）
- `scripts/video_builder.py`（ffmpeg 動画合成・2500行規模・最も複雑で共通化価値が高い）
- `scripts/audio_processor.py`, `font_utils.py`
- `scripts/notifier.py`, `error_logger.py`, `network_check.py`
- `scripts/llm_client.py`, `providers.py`, `model_config.py`（既に多プロバイダ対応）
- `scripts/secrets.py`（keyring 抽象化済み）
- `scripts/skills/` の `skill_tts.py`, `skill_video_build.py`, `skill_pronunciation.py`, `skill_prosody.py`, `skill_se_assign.py`, `skill_cache_cleanup.py`, `skill_self_review.py`（内部で channel 固有要素を参照していない）

---

## 2. 環境制約の確認結果

| 制約 | 現状 | 2 チャンネル並行の可否 |
|------|------|---------|
| メモリ | WSL2 割当 **5.7GB** / 使用中 1.1GB / free 4.5GB + swap 2GB | **並列実行は危険**。video_build が 2〜3GB 食うので2本同時は OOM リスク。**直列必須** |
| ディスク | C: 238GB 中 **123GB 空き**。7日自動削除（既存 cron） | 問題なし。2 本/日 ≒ 年間 700 本 ≒ 600GB、ただし 7 日で削除なら常時使用量は 10〜14GB |
| Gemini API | QUALITY=2.5 Pro（台本）、SIMPLE/STANDARD=2.5 Flash、無料枠内で 1 本運用中 | **2 本/日なら余裕**。Gemini 2.5 Pro の無料 RPM/RPD に収まる。ただし連続実行だとクールダウンが近接するため時差起動推奨 |
| YouTube OAuth | `credentials.json` + `token.json` 1組 | **致命的**: 異なるチャンネル ID への投稿は別の OAuth token が必須。最大の構造変更点 |
| Task Scheduler | `YukkuriDaily` 1本が 10:00 実行 | 新規タスク `CreatureDaily` を別 URI で登録可能（既存を壊さない方式） |

---

## 3. 分岐設計の提案（A〜F）

### A. 環境分離の根本判断 ★最重要★

**結論: パターン3「共通基盤 + チャンネル別設定（ハイブリッド）」を強く推奨します。**

#### 3パターンの評価

| 観点 | P1: 単一コードベース + 分岐 | P2: 完全コピー（別ディレクトリ） | **P3: 共通基盤 + 設定分離** |
|------|------|------|------|
| 波及リスク | **高**: prompts.py/thumbnail_director などを if channel で膨大分岐 → 健康側の既存バグフィックスが生物側を壊す | **低**: 完全独立 | **低**: コアは共通だが動作経路が設定で明示分離 |
| 二重メンテコスト | 低（ただしコードの見通しが壊滅） | **極高**: video_builder.py 2500行級バグを2箇所で直し続ける→必ず乖離する | 低: コア1箇所修正で両方に波及 |
| 30 万人目標への影響 | **健康側の安定稼働を損なうリスク高** | 同じバグを 2 回直す非効率 | **健康側は原則無改修で済む**（アディティブな追加のみ） |
| 3 チャンネル目への拡張性 | if 地獄で崩壊 | 3 倍の保守コスト | **設定ファイル追加だけで済む** |
| 既存スケジューラへの影響 | run.bat の引数追加のみ | 独立タスク | 独立タスク（別 URI） |
| 初期実装コスト | 中 | **低**（cp するだけ） | **中〜高**（抽象化層の設計が必要） |

#### P3 を選ぶ理由

1. **現行システムは既に部分的に P3 の下地がある**:
   - `model_config.py` が LLM_PROVIDER で抽象化済み
   - `image_generator.py` が `IMAGE_PROVIDER` 環境変数で切替済み
   - `secrets.py` が keyring 抽象化済み
   - `skills/_common.py` が共通ヘルパとしてまとまっている

2. **「健康チャンネルの安定稼働を一切損なわない」最優先制約を満たせる**:
   - `--channel health` をデフォルトにすれば既存の `run.bat` は 1 行修正で済む
   - P1 と異なり、健康側のコードパスは**読まれるだけで変わらない**

3. **video_builder.py を共有できる**: 2500行級の最も複雑な資産を 1 箇所で維持できる。P2 だと数週間で乖離する

4. **Codex 協議フロー（必須）との相性**: 共通コア + 薄い設定層なら Codex レビュー対象が明確で、審査が現実的

#### P3 の主なリスクとその緩和

| リスク | 緩和策 |
|------|------|
| 抽象化の設計を誤ると両方が同時に壊れる | Phase 2 Step 1 を「抽象化リファクタ + 健康側で同じ挙動を再現」に絞り、生物側の実装着手前に Codex adversarial review を必ず通す |
| 認証情報の取り違え（健康の動画を生物チャンネルに投稿） | `channel_id` を metadata に記録 + upload 前に `youtube.channels().list(mine=True)` でチャンネルタイトル検証、不一致なら fail-closed |

---

### B. チャンネル識別の設計

#### 提案: チャンネル設定ファイル + `--channel` CLI 引数

```
config/channels/
  health.yaml          # 既存の健康チャンネル（デフォルト）
  creatures.yaml       # 新設の生き物チャンネル
```

`config/channels/health.yaml`（例）:
```yaml
id: health
display_name: ゆっくり健康ラボ
themes_file: themes/health.txt
prompts_module: prompts.health            # scripts/prompts/health.py
output_subdir: output                     # 既存互換: output/ 直下
lock_file: logs/last_upload_date.txt      # 既存互換
oauth:
  credentials: credentials.json           # 既存互換
  token: token.json                       # 既存互換
youtube:
  expected_channel_id: UCxxxxxxxx         # 認証時に検証
  publish_time: "18:00"
characters:
  reimu_role: リアクション・質問役
  marisa_role: 解説・進行役
image_provider: gemini
thumbnail_theme_categories: [food, sleep, exercise, dental, mental, warning, general]
min_script_chars: 6000
max_script_chars: 7500
default_tags: [ゆっくり解説, 健康]
```

`config/channels/creatures.yaml`（例）:
```yaml
id: creatures
display_name: ゆっくり生き物劇場
themes_file: themes/creatures.txt
prompts_module: prompts.creatures
output_subdir: output_creatures           # ディレクトリ完全分離
lock_file: logs/last_upload_date_creatures.txt
oauth:
  credentials: credentials_creatures.json
  token: token_creatures.json
youtube:
  expected_channel_id: UCyyyyyyyy
  publish_time: "19:30"
characters:
  reimu_role: 感情担当・視聴者代弁
  marisa_role: 語り部・解説者
image_provider: wikimedia_commons         # 新設プロバイダ
thumbnail_theme_categories: [survival, beloved, breeding, ability, travel]
min_script_chars: 8000                    # 5幕17分台本のため増やす
max_script_chars: 10000
default_tags: [ゆっくり解説, 生き物, 動物]
rotation_state_file: state/creatures_rotation.json  # 冒頭/結末/カテゴリのローテーション
narrative_structure: five_act             # 新規5幕構造識別子
```

#### 実装の最小変更方針

- `scripts/_channel.py`（新設・80〜120行程度）: `load_channel(name) -> ChannelConfig` のみ提供
- `generator.py` に `--channel` 引数追加（デフォルト `health`）
- 各スキルは `channel: ChannelConfig` を引数で受け取る（環境変数汚染を避ける）
- **既存の健康チャンネルは `--channel` 未指定でも動作することを保証**（後方互換）

---

### C. パイプライン実行の設計

**結論: 直列実行 + 時差起動。理由は WSL2 メモリ 5.7GB 制約。**

#### 推奨スケジュール

| 時刻 | タスク | 備考 |
|------|------|------|
| 10:00 | 健康チャンネル パイプライン (`run.bat` = `--channel health`) | 既存維持 |
| 12:00 | 生物チャンネル パイプライン (`run_creatures.bat` = `--channel creatures`) | 健康の3回リトライと衝突しないよう 11:30→12:00 に変更推奨 |
| 13:00 | プリフライト（両チャンネル両方チェック） | 既存拡張 |
| 18:00 | 健康チャンネル公開（予約投稿） | 既存 |
| 19:30 | 生物チャンネル公開（予約投稿） | 新設 |

#### なぜ並列ではないか

- `skill_video_build` が ffmpeg エンコード中に 2〜3GB 使う → 2本並列で OOM 確定
- Gemini 2.5 Pro の同時呼び出しで RPM 逼迫の可能性
- 失敗時のログ追跡が困難になる

#### 健康側の生物側への連動失敗ガード

- `run_creatures.bat` 冒頭で「健康側 run_dir が当日作成済みかつ status=completed」を確認する軽いチェックを入れる
- 生物側が失敗しても健康側の完了には影響しない設計（独立 lock file / 独立 run_dir）

---

### D. 変更が必要な箇所の一覧

| 規模 | 対象 | 変更内容 |
|------|------|---------|
| **大** | `scripts/prompts.py` | `scripts/prompts/` パッケージ化。`prompts/health.py` (既存移植) + `prompts/creatures.py` (新設) + `prompts/__init__.py` で `get_prompts_module(channel)` 提供 |
| 大 | `scripts/generator.py` | `--channel` 引数、`_pick_theme_from_file()`・`_create_run_dir()`・`_find_resumable_run()`・1日1本ロックを channel-aware に |
| 大 | `scripts/auth_utils.py` | `get_credentials(channel_config)` に変更。credentials/token パスを config から |
| 大 | `scripts/skills/skill_upload.py` | lock_path、default tags、YouTube channel ID 検証を channel_config から |
| 大 | `scripts/skills/skill_script_gen.py` | `_MIN_SCRIPT_CHARS` / `_MAX_SCRIPT_CHARS` を channel config から。prompts モジュールを動的 import |
| 中 | `scripts/skills/skill_metadata.py` | フォールバック説明文・タグ・AI 開示文を channel config から |
| 中 | `scripts/thumbnail_director.py` | `_THEMES` を channel config から |
| 中 | `scripts/image_generator.py` | `_build_image_prompt()` のシーン例を channel 別に分岐、または prompts モジュールから取得 |
| 中 | `scripts/preflight_check.py` | 両チャンネルをループで検査 |
| 中 | `scripts/run_monitor.py` | 両チャンネルの post-run 監視 |
| 中 | `run.bat` | `generator.py --auto --channel health --publish-time 18:00` に変更 |
| 中 | `task_yukkuri_daily_*.xml` | そのまま維持（健康のまま）|
| 小 | `scripts/characters.py` | `get_character_roles(channel)` 関数を追加。既存 `get_character_names()` は維持 |
| 小 | `scripts/notifier.py` | 通知文にチャンネル名プレフィックス |
| 小 | `scripts/claude_watchdog.py` | 両チャンネルの死活チェックを追加 |

### E. 変更が不要な箇所（そのまま共通利用）

- `scripts/tts.py`, `tts_aquestalk.py`, `tts_client.py`
- `scripts/aquestalk_synth.ps1`
- `scripts/video_builder.py`（**最大資産、そのまま流用**）
- `scripts/audio_processor.py`, `scripts/font_utils.py`
- `scripts/llm_client.py`, `providers.py`, `model_config.py`
- `scripts/secrets.py`, `error_logger.py`, `network_check.py`
- `scripts/skills/skill_tts.py`, `skill_video_build.py`, `skill_pronunciation.py`, `skill_prosody.py`, `skill_se_assign.py`, `skill_cache_cleanup.py`, `skill_self_review.py`
- `scripts/skills/self_healing.py`

### F. 新チャンネル固有で新設が必要なもの

1. **`config/channels/health.yaml`** + **`config/channels/creatures.yaml`**
2. **`themes/creatures.txt`** — 5カテゴリ × 30 = 150 テーマ（カテゴリごとのマーカー付き: `[A] カモノハシ…` のように）
3. **`scripts/prompts/creatures.py`** — 5幕構成プロンプト / 冒頭6パターン / 結末5パターン / キャラクター役割（語り部・感情担当）
4. **`state/creatures_rotation.json`** — 冒頭・結末・カテゴリのローテーションキュー状態
5. **`scripts/hybrid_selector.py`** — ローテーション+テーマ相性スコアのハイブリッド選択ロジック（冒頭/結末/カテゴリ共通）
6. **`scripts/wikimedia_fetcher.py`** — Wikimedia Commons API クライアント（学名検索 + CC BY-SA ライセンス情報取得）
7. **`scripts/skills/skill_creature_images.py`** — 生物画像取得スキル（Wikimedia メイン、Pixabay/Pexels 補助）
8. **`scripts/skills/skill_credits.py`** — エンドクレジット画面生成（画像の著作者・ライセンスを動画末尾にまとめて表示）
9. **`credentials_creatures.json`** + **`token_creatures.json`** — 新チャンネル用 OAuth（手動登録）
10. **`run_creatures.bat`** — 生物チャンネル用バッチファイル
11. **`task_creatures_daily.xml`** — 12:00 起動の新規 Task Scheduler タスク
12. **`logs/last_upload_date_creatures.txt`** — 独立 1日1本ロック
13. **`output_creatures/`** — 独立 run_dir 階層

---

## 4. 懸念点・リスク

| # | 懸念 | 対応 |
|---|------|------|
| 1 | **認証情報の取り違え（誤チャンネル投稿）** 最重要 | `skill_upload.py` 冒頭で `youtube.channels().list(mine=True)` を呼び、`channel_config.youtube.expected_channel_id` と一致しなければ **fail-closed**。metadata.json にも channel_id を記録して二重防御 |
| 2 | Phase 2 実装中に健康チャンネルの既存稼働が壊れる | Step 1 の抽象化リファクタで「健康側 DRY_RUN / 実投稿の両方で既存挙動と完全一致」を Codex adversarial review で確認してから次へ。既存 output/ との互換性テスト |
| 3 | prompts.py の分割時にナラティブスタイル文言が破損 | 既存 `prompts.py` → `prompts/health.py` は**コピーのみ**、文言変更ゼロ。`from prompts.health import *` で健康側の import を維持 |
| 4 | 生物チャンネルの台本が 5 幕 17 分になり、既存 `_MIN_SCRIPT_CHARS=6000` と不整合 | channel config で文字数閾値を上書き可能にする。`skill_script_gen.py` が閾値を config から読む |
| 5 | Wikimedia Commons ライセンス遵守の自動検証 | `skill_credits.py` がライセンス情報を必須フィールド化、欠損時は fail-closed で該当画像を破棄。CC BY-SA 以外（CC0, public domain）もライセンス名記録 |
| 6 | 11:30 起動の生物側が、健康側の失敗リトライ（60+60+60=30分）と重なる | 健康側 3回目失敗は 10:00 + 45分 + 10分 + 45分 + 10分 = **11:50 頃まで続く可能性** → 生物側は **12:00 起動**に変更を推奨 |
| 7 | 1日1本ルールの合算誤動作 | lock_file を channel 別にする（設計済み）。ただし `_check_duplicate_on_youtube()` は `forMine=True` で認証チャンネルのみ対象なので自動で分離される |
| 8 | preflight_check.py の 13:00 実行時に両チャンネルが未完了の場合、片方だけ修復するか | 両チャンネル独立に修復し、修復結果を通知文で個別に報告。どちらか失敗しても他方のアップロードはブロックしない |
| 9 | claude_watchdog / Discord 通知のチャンネル識別 | 通知文先頭に `[health]` / `[creatures]` プレフィックスを必須化 |
| 10 | 3 チャンネル以上への拡張時のテスト負担 | 設定ファイルが正しく読めて最低限のフェーズが走ることを CI 的に確認する smoke test を Phase 2 で新設 |

### 3歩先チェック4問 (Phase2 抽象化リファクタに対する明示回答)

**Q1: この修正自体が壊れたら、どうやって気づくのか？(検知の検知)**

- 各ステップ完了時に DRY_RUN diff スクリプトを走らせ、抽象化前の最新 health run_dir と md5/内容比較
- diff スクリプト自体の健全性を先に担保: **抽象化着手前** に「同一コードの2回実行」で diff がゼロになることを確認 (ベースライン確立)。タイムスタンプ等の不可避差分は除外リストに明示
- 新規ファイル (yaml / _channel.py) はユニットテストで既存ハードコード値と1対1一致を確認
- Step 2-5 では **翌朝の 10:00 定時実行 1 本** を実投稿まで通してリグレッション確認 (DRY_RUN では upload コードパスが動かないため)
- リグレッション検知時: 即座に該当ステップを git revert し、ユーザーに通知

**Q2: この変更で別のエッジケースが生まれないか？**

- `prompts.py → prompts/ パッケージ化`: 既存 `from prompts import X` の全箇所を事前に grep で列挙し、`__init__.py` の re-export で完全カバー。漏れは import 時点で ModuleNotFoundError に早期失敗
- `generator.py --channel` 引数追加: 既存の argparse 定義に `default="health"` で追加し、`run.bat` の既存引数との衝突を事前確認 (`--auto`, `--publish-time`, `--resume` と衝突しない)
- config yaml: UTF-8 BOM なしで明示保存、`yaml.safe_load` で読む。`display_name` に日本語が入るため。`.gitattributes` で yaml を `text eol=lf` 固定 (Windows の CRLF 化で pyyaml が稀に誤動作するのを防ぐ)
- lock_file の相対パス問題: config の `lock_file` は PROJECT_ROOT からの相対として解決し、`Path(PROJECT_ROOT / cfg.lock_file).resolve()` で絶対パス化
- OAuth token refresh: 現行 `Credentials.from_authorized_user_file` + `creds.refresh` が同じパスに書き戻すことを事前確認 (`auth_utils.py` に save 処理があるか)
- pickle キャッシュの古い module path 問題: prompts.py 分割時は `skill_cache_cleanup` を先に一度走らせる
- `--channel` 未指定時のデフォルト: `health`。既存 `run.bat` が引数なしで既存挙動を保つことを DRY_RUN で確認

**Q3: ユーザー不在中でも機能するか？**

- Phase2 実装は日中に限定 (ユーザーが Discord で確認できる時間)
- 各ステップは **アトミックに完了** させる。中途半端な状態でセッション終了しない
- 10:00 定時実行の健康チャンネルは Phase2 実装中も毎日動き続けなければならない → 各ステップの作業開始前に「今日の 10:00 タスクは完了しているか」を確認し、未完了なら Phase2 作業を延期
- `ClaudeWatchdog` は Phase2 実装中も稼働継続。DRY_RUN 失敗時も Discord に通知が飛ぶ
- ユーザー承認待ちの待機中はコードに一切触らない (各ステップごとにゲート)

**Q4: 「動いた」「OK」と言う前に、本当に本番条件でテストしたか？**

- DRY_RUN は upload コードパスを通らない → 不十分
- **Step 2-5 で翌朝 10:00 の定時実行をそのまま本番リグレッションテストに使う**: 通常の健康チャンネル動画を1本生成→投稿まで通し、前日までの過去 10 本と比較 (尺・文字数・メタデータ構造・サムネ座標)
- 比較失敗時: 該当ステップを即 revert、翌日の 10:00 は revert 後の状態で走る
- ユーザー主観チェック: 投稿直後の動画を cmd.exe start で再生確認依頼
- **3歩先チェック4問を通したこと自体をユーザーに毎ステップ報告する** (口だけで「OK」と言わない)

---

### 7ヶ条 #5 の自動検出項目

- **チャンネル識別誤りの検知**: メトリクス用に `output_{channel}/{run_dir}/manifest.json` に `channel_id` を記録 → `run_monitor.py` がチャンネル ID 不一致を検知
- **prompts モジュール not found**: `load_channel()` 時点で prompts モジュール import を検証、失敗なら fail-closed
- **config 読み込み失敗**: yaml parse エラーは起動時即死、サイレントフォールバック禁止
- **time collision**: 11:30 と 12:00 の両方で健康パイプラインが動いている場合（リトライ中）の検知を claude_watchdog に追加

---

## 5. フェーズ2 以降の実装計画（概要レベル）

> **このフェーズでは実装しません。** 以下はユーザー承認後の作業順序の提案です。

### Phase 2: 抽象化リファクタ（健康チャンネルのみで完全後方互換）

**★ユーザー追加条件 (2026-04-10)★**: 各ステップ(2-1〜2-5) 完了時に健康チャンネルで **DRY_RUN** を必ず実施し、結果を毎回ユーザーに報告、目視確認の返事を受けてから次ステップへ進む。Claude 側で「差分なし」判定は禁止。

| Step | 内容 | DRY_RUN 検証 + 報告内容 | ユーザー確認ゲート |
|------|------|---------|---------|
| 2-1 | `config/channels/health.yaml` + `scripts/_channel.py` 新設 | `load_channel("health")` のユニット出力を diff で既存ハードコード値と突合。`python scripts/generator.py --dry-run --channel health` で起動オプション認識のみ確認 | 2-1 結果を報告 → ユーザー OK → 2-2 |
| 2-2 | `prompts.py` → `scripts/prompts/health.py` にファイル移動、`scripts/prompts/__init__.py` で互換 re-export | `from prompts import build_script_prompt` など **全既存 import を grep で列挙し再現実行**。dry-run で台本プロンプト文字列の完全一致確認 (md5 比較) | 2-2 結果を報告 → ユーザー OK → 2-3 |
| 2-3 | `generator.py` に `--channel` 引数追加（デフォルト `health`） | `run.bat` 引数なし起動と `--channel health` 起動の両方で pipeline.json が同一になることを確認 | 2-3 結果を報告 → ユーザー OK → 2-4 |
| 2-4 | `auth_utils.py`, `skill_upload.py`, `skill_script_gen.py`, `skill_metadata.py` を channel-aware に | 健康チャンネルで **DRY_RUN パイプライン 1本**を通し、既存 output の metadata.json / 台本 / サムネ設計ディレクティブが抽象化前と一致することを md5/diff で確認 | 2-4 結果を報告 → ユーザー目視確認 → 2-5 |
| 2-5 | **Codex adversarial review 通過** | Codex に「抽象化漏れ・既存バグ回帰」を指摘させる。合意後に健康チャンネルの **本番投稿を1本**実施してリグレッションを確認 | 2-5 本番確認 → ユーザー OK → Phase 3 へ |

**DRY_RUN の定義**: `--dry-run` フラグで generator.py を起動し、upload 手前まで全フェーズを実行。出力 run_dir の artifacts を既存の最新 health run_dir と比較。差分があった場合はステップを巻き戻す。

### Phase 3: 生物チャンネル固有要素の実装

| Step | 内容 |
|------|------|
| 3-1 | `scripts/prompts/creatures.py` 作成（5幕プロンプト・冒頭6パターン・結末5パターン） |
| 3-2 | `scripts/hybrid_selector.py` 作成（ローテーション + テーマ相性スコア） |
| 3-3 | `themes/creatures.txt` 作成(150テーマ、カテゴリマーカー付き) |
| 3-4 | `scripts/wikimedia_fetcher.py` 作成（学名検索、ライセンス抽出） |
| 3-5 | `scripts/skills/skill_creature_images.py` 作成 |
| 3-6 | `scripts/skills/skill_credits.py` 作成（エンドクレジット画面） |
| 3-7 | `config/channels/creatures.yaml` 作成 |

### Phase 4: インフラ統合

| Step | 内容 |
|------|------|
| 4-1 | `run_creatures.bat` 作成 |
| 4-2 | `task_creatures_daily.xml` 作成（12:00 起動、既存 `YukkuriDaily` には触らない） |
| 4-3 | `preflight_check.py` を両チャンネル対応に |
| 4-4 | `claude_watchdog.py` を両チャンネル対応に |
| 4-5 | Discord 通知のチャンネルプレフィックス追加 |

### Phase 5: 本番投入前の最終検証

| Step | 内容 |
|------|------|
| 5-1 | 新 YouTube チャンネル作成・`credentials_creatures.json` 登録 |
| 5-2 | 生物チャンネルで DRY_RUN + `[TEST]` プレフィックス動画を非公開で1本作成 |
| 5-3 | Codex adversarial review 通過 |
| 5-4 | ユーザー承認後に本番投入、最初の 3 日は健康/生物両方を毎朝手動確認 |

---

## 6. 既存仕組みとの矛盾・整合性確認

| 項目 | 確認結果 |
|------|------|
| スケジューラ | OK 既存 `YukkuriDaily` は触らず新規 `CreatureDaily` を追加。別 URI で衝突なし |
| 1日1本ルール | OK channel 別 lock file で独立。YouTube API 側も `forMine=True` で認証チャンネル限定 |
| プリフライトチェック | 要改修 `preflight_check.py` の `OUTPUT_DIR = BASE_DIR/output` 固定を両チャンネル対応に拡張必要（Phase 4-3） |
| 自己修復 (`self_healing`) | OK 既存のまま利用可能（run_dir 単位で動作） |
| キャッシュ清掃 (`skill_cache_cleanup`) | 要改修 `output/` 全体対象 → `output_creatures/` も対象にする小改修必要 |
| Codex 協議フロー | OK Phase 2-5 と Phase 5-3 で adversarial review を必須化 |
| 3歩先チェック | OK 本設計案に「(1)検知の検知=manifest channel_id 記録、(2)エッジケース=OAuth 取り違え、(3)ユーザー不在時=独立 watchdog、(4)本番テスト=Phase 5-2 の [TEST] 動画」を含めた |

---

## 7. lessons.md 記録候補（調査で発見した既存制約）

1. `credentials.json` / `token.json` が PROJECT_ROOT 固定 = マルチチャンネル前提で書かれていない
2. `logs/last_upload_date.txt` が単一ファイル = 1日1本ロックは全チャンネル合算
3. `output/{run_id}_{theme}/` にチャンネル識別子がない = 複数チャンネル時の used_themes 判定が破綻
4. `prompts.py` 1093行が全面健康特化 = 分割にはパッケージ化が必須
5. `thumbnail_director.py` のキャンバス情報にキャラクター位置が固定 = 新チャンネルで位置を変えるなら director も差し替え必要
6. `image_generator.py` の `_build_image_prompt()` は健康生活シーン前提 = 生物チャンネルでは背景画像用途自体を見直す必要（屋外・水中・ジャングル）
7. `generator.py:16` の `OUTPUT_DIR = .../output` 固定が多数のスキルに波及 = channel_config 受け渡しの主経路になる

---

## 最終確認事項（実装前に承認いただきたい点）

1. **パターン3 採用の同意** — 特に「既存健康チャンネルの後方互換を最優先、生物側はアディティブ追加」方針で進めて良いか
2. **12:00 起動への同意** — 健康側の3回リトライを考慮すると 11:30 では健康側と衝突の可能性あり。12:00 起動を推奨
3. **config 形式は YAML で良いか** — JSON でも可。YAML はコメントが書けるので運用しやすい
4. **`output_creatures/` としてディレクトリを完全分離** — 健康は `output/` のまま、生物は `output_creatures/`。Phase 2 で両方 `output_{channel}/` に統一する案もあるが、健康側の既存 run_dir を触ると自己修復・プリフライトが影響するので**健康側はそのまま `output/`** を推奨
5. **Wikimedia Commons ライセンス自動検証の fail-closed 動作** — ライセンス取得失敗時は該当画像を破棄 + 1本の動画で全画像が破棄されたら fail-closed で台本中断、でよいか
6. **Phase 2 Step 2-4 の後に一度止まってユーザー承認を取る** — 健康側の既存動作が壊れていないことの目視確認をしていただく

---

**実装には着手していません。** 上記の設計案について、A の環境分離判断と最終確認事項 6 点について、承認 / 修正指示 / 追加調査要望をください。
