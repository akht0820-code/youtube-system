# フェーズ1 スコープ縮小案 — Phase 2 着手前の最小前提のみ

作成日: 2026-04-10
背景: v1/v2 がいずれも Codex adversarial review で NO-GO (Critical 4 件含む)。完全設計書を書く前に、まず **動かぬ事実** と **Phase 2 開始に必要な最小合意** だけを確定する。

**本ドキュメントは設計書ではない。** これは「Phase 2 を始めてよいか」の判断に必要な最小限の事実と合意事項リストである。壮大な設計は Phase 2 の第1ステップで得た知見をもとに逐次書く方式に切り替える。

---

## 1. 調査でわかった動かぬ事実（rg で実測）

v1/v2 の見積もりはいずれも不足していた。以下が 2026-04-10 時点の実測値。

### 1-1. get_credentials() 呼び出し元（4 ファイル）

```
scripts/auth_utils.py:22           # 定義側
scripts/analytics_collector.py:94  # 呼び出し
scripts/youtube_uploader.py:21     # 呼び出し
scripts/run_monitor.py:193         # 呼び出し (★動画を非公開化する破壊的経路)
scripts/sheets_writer.py:31        # 呼び出し
```

`get_credentials()` は **引数なし** で `PROJECT_ROOT / "token.json"` を読む。これを channel 対応にするには呼び出し元 4 ファイル全てに手を入れる必要がある。v2 で列挙漏れしていた `run_monitor.py` / `analytics_collector.py` / `sheets_writer.py` が含まれる。

### 1-2. token.json / credentials.json の直接パス参照（6 ファイル）

```
scripts/auth_utils.py:18-19              # CREDENTIALS_PATH / TOKEN_PATH
scripts/preflight_runtime.py:40,67       # token_path / cred_path
scripts/publish_now.py:17                # token_path
scripts/skills/self_healing.py:160       # token_path を unlink する
(scripts/youtube_uploader.py:305         # print 文内の参照のみ、実害なし)
```

### 1-3. last_upload_date.txt の直接パス参照（3 ファイル）

```
scripts/generator.py:105
scripts/skills/skill_upload.py:29
scripts/preflight_runtime.py:87
```

### 1-4. `output/` ディレクトリ直接参照（12 ファイル）

```
scripts/generator.py:16
scripts/analyzer.py:13
scripts/run_monitor.py:21
scripts/preflight_check.py:23
scripts/image_generator.py:716   # thumbnail_history.json の親
scripts/discord_bot.py:45
scripts/skills/_common.py:366
scripts/skills/skill_video_build.py:23
scripts/skills/skill_script_gen.py:36
scripts/skills/skill_upload.py:28
scripts/skills/skill_cache_cleanup.py:24
scripts/skills/skill_metadata.py:32
```

### 1-5. themes.txt の直接パス参照（2 ファイル）

```
scripts/generator.py:22            # _pick_theme_from_file
scripts/skills/skill_script_gen.py:765  # _pick_theme_from_file (重複定義)
```

**発見**: `_pick_theme_from_file` は generator.py と skill_script_gen.py の **両方** に定義されている。どちらがどこから呼ばれるかを Phase 2 前に確定する必要がある（コードの単一責任が壊れている）。

### 1-6. preflight_runtime.py の実態（v2 の前提誤り確認）

```python
# scripts/preflight_runtime.py:38
def _check_token_json():
    """token.jsonの存在と有効期限をファイルベースで確認（API呼び出しなし）"""
```

v2 は「09:55 preflight が refresh 済みなら 10:00 は不要」と書いたが **誤り**。preflight_runtime は **refresh も API 実検証もしていない**。ファイルの expiry 文字列を読むだけ。失効 token は 09:55 で検知できない。

---

## 2. Layer 3 replay 前提の破綻（非決定性の全棚卸し）

v2 の「プロンプトは決定的」は誤り。以下が本番パイプラインに効く乱択呼び出しの実測。

### 2-1. 台本生成の非決定要素（最重要）

```
scripts/prompts.py:90          _NARRATIVE_STYLES から random.choice
scripts/generator.py:41        テーマ選択 (残候補から random.choice)
scripts/skills/skill_script_gen.py:786   同上（重複定義）
```

**影響**: 同一テーマ入力でも `random.choice` の結果が毎回異なるため、プロンプト自体が byte 単位で変わる。Layer 3 の「LLM 入力プロンプト byte 一致」は現行コードのまま成立しない。

### 2-2. その他の非決定要素（動画合成・サムネ・SE など）

- `scripts/video_builder.py`: 瞬き (238, 242, 246)、表情中途切替 (331-338)、BGM 選択 (1074)、字幕バー色 (1088)、挨拶感情 (1867) — **6 箇所**
- `scripts/thumbnail_maker.py`: キャラ配置、リアクション選択、吹き出し、センター霊夢パターン等 — **30 箇所以上**
- `scripts/image_generator.py`: seed 生成 (410)、画像選択 (482)、重み付き選択 (895, 907, 912)
- `scripts/skills/skill_se_assign.py:58`: SE 選択
- `scripts/skills/skill_upload.py:282`, `scripts/generator.py:473`, `scripts/preflight_check.py:195`, `scripts/rebuild_video.py:85`, `scripts/resynth_and_build.py:118`: リトライ wait jitter

**結論**: 現行コードのまま DRY_RUN を 2 回実行して diff を取ると、少なくとも台本・動画・サムネ・SE が全て異なる。md5 比較はもちろん、byte 一致系の検証は **どの Layer でも成立しない**。

### 2-3. Layer 3 の再設計方針（Phase 2 着手前に要合意）

- 案 X: 非決定要素を全て「シード注入可能」に改修してから Phase 2 に入る → 30+ 箇所の事前改修
- 案 Y: LLM 呼び出しと画像プロバイダ呼び出しの **入出力ペア** を replay、その間のランダム要素は「許容差分」として無視
- 案 Z: Layer 3 を諦め、Layer 2 (structural invariant) のみで検証

**推奨は案 Z** (Layer 2 のみ)。Layer 3 の再設計は Phase 2 の途中で必要になったら別途やる。

---

## 3. Phase 2 着手前の最小合意事項（ユーザー承認が欲しい項目）

以下 **6 項目のみ** を Phase 2 開始の前提とする。各項目は単一の Yes/No で答えられる粒度にした。

### 合意 1: 検証は Layer 2 (structural invariant) のみに一本化する

- Layer 1 (fixture) と Layer 3 (replay) は Phase 2 の範囲から外す
- 検証は「pipeline.json の phase 集合・run_dir の必須ファイル集合・metadata の key 集合・動画尺の許容範囲・title/tag 長」の invariant 検証のみ
- 非決定要素はそのまま放置（シード固定化は Phase 2 で扱わない）

**理由**: v2 Layer 3 は現行コードの乱択構造と噛み合っていない。完璧な再現性を求めると 30+ 箇所の事前改修が必要になり、健康チャンネルのコード全体をいじることになる＝後方互換の保証が困難になる。

### 合意 2: Phase 2 の最初の PR は「no-op リファクタ」に限定する

以下のみを含む単一 PR:

- `config/channels/health.yaml` 新設（中身は現行ハードコード値の写し）
- `scripts/_channel.py` 新設（`load_channel()` のみ、dataclass 返却）
- `scripts/_channel_schema.py` 新設（dataclass 定義、validation ロジック）
- **既存のどのスキル・generator からも呼ばない**。ファイルを追加するだけ
- 健康チャンネルの本番実行フローは **1 行も変わらない**

**検証**: ユニットテストで `load_channel("health")` が既知の dict を返すことのみ確認。本番の 10:00 実行には一切影響しない。

### 合意 3: Step 2-α の後、Codex レビュー通過まで次 Step には進まない

- 最初の no-op PR を Codex adversarial review にかけ、GO 判定が出るまで次 Step の設計は書かない
- NO-GO が出たら PR を revert するか、Codex の指摘を踏まえて PR を書き直す
- **設計を先にまとめて書くアプローチ（v1/v2 が失敗した方法）を再使用しない**

### 合意 4: self_healing の危険経路は現状維持

- v2 で提案した「OAUTH_EXPIRED 自動回復を Phase 2 期間中抑制」は **撤回**
- 理由: preflight_runtime が実は refresh していないため、抑制すると 10:00 本番で失効 token が回復できずサイレント失敗する
- 代わりに: `_fix_delete_token_reauth` / `_fix_kill_orphan_processes` / `_fix_delete_temp_files` の変更は **Phase 2 スコープから完全に除外**。これらは Phase 3 以降で別扱い

### 合意 5: `--dry-run` フラグの新設は Phase 2 スコープから外す

- v2 で提案した `--dry-run` は既存の `--no-upload` と機能重複が大きい
- 代わりに: **Phase 2 Step 2-α の検証には DRY_RUN を一切使わない**。ユニットテスト（ファイル追加のみ）で完結させる
- Phase 2 の後半 Step で必要になったら、そのタイミングで DRY_RUN 契約を別途議論する

### 合意 6: 完全設計書を書くアプローチを放棄する

- v1/v2 のように「Phase 1〜5 を全て設計書にまとめる」方式は NO-GO を出し続ける
- 代わりに: **各 Step の着手前に、その Step 単独の小さな設計書（1〜2 ページ）を書き、Codex レビューを通してから着手する**
- 利点: 1 Step で実コードを読み直す → 前提誤りを早期発見できる
- 欠点: 全体像がユーザーから見えにくい → 補うため、各 Step 完了時にユーザーに 1 分で読める要約を提示する

---

## 4. 本ドキュメントで明示的に保留するもの

以下は Phase 2 開始前には決めない。Step 2-α 完了後に別途議論する。

- §2 v2 で書いた全ファイル一覧からどれを channel 化するかの順序
- prompts.py → prompts/ パッケージ化の具体手順
- generator.py に `--channel` 引数を追加するタイミング
- output_dir の 12 ファイル channel 化の順序と PR 分割
- Gemini rate limiter の実装
- manifest.json 契約
- cross_platform_lock の既存実装からの移行
- OAuth token refresh race 対策
- 生物チャンネル固有の実装（Phase 3 以降）
- Wikimedia Commons 連携
- 新 YouTube チャンネル作成

---

## 5. 3歩先チェック（本縮小案に対する回答）

### Q1: この修正自体が壊れたら、どうやって気づくのか？

- Step 2-α は「ファイル 3 個を追加するだけ」の no-op PR。既存コードパスを 1 行も変えない
- 万が一 import エラーや文法エラーがあっても、本番 10:00 実行は新ファイルを import しないので影響なし
- 検知: `pytest scripts/_channel_test.py` で `load_channel("health")` が期待 dict を返すことを確認
- 検知の検知: テスト自体が空振りしないよう、**わざと間違った値を返すケースも書き、テストが落ちることを確認** してから正しい値に戻す

### Q2: この変更で別のエッジケースが生まれないか？

- ファイル追加のみ → 既存 import の解決に影響しない
- yaml 形式のみ追加 → `yaml` モジュールは既存 requirements にある（`pip show pyyaml` で確認要）
- BOM: `yaml.safe_load(open(p, encoding="utf-8-sig"))` で吸収
- cp932: yaml ファイルに日本語は入るが、UTF-8 で保存する旨を schema 内にコメント記載
- Windows/WSL パス変換: yaml 内のパスは全て PROJECT_ROOT 相対の **forward slash** で書く
- ffmpeg コマンド長: 本 Step では ffmpeg を一切呼ばない

### Q3: ユーザー不在中でも機能するか？

- Step 2-α は本番 10:00 実行に影響しないため、ユーザー不在時でも健康チャンネルは通常通り動く
- PR 着手は日中のみ、完了後に Discord で報告してユーザー承認を取ってから次 Step へ

### Q4: 「動いた」「OK」と言う前に、本当に本番条件でテストしたか？

- Step 2-α 完了時点では **本番テストは不要**（no-op なので）
- ただし Step 2-α 完了の翌朝 10:00 実行が通常通り完了することを確認してから次 Step 設計に進む
- 翌朝 10:00 が失敗したら、Step 2-α の PR を revert して原因を調査する

---

## 6. 承認いただきたい点

本ドキュメントは設計書ではなく **「Phase 2 の開始条件合意書」** です。以下 6 点について Yes/No で指示をください。

1. **合意 1**: Layer 2 のみで検証する方針に同意するか
2. **合意 2**: 最初の PR を no-op ファイル追加のみに絞ることに同意するか
3. **合意 3**: 完全設計書アプローチを放棄し、Step ごとに小設計書 + Codex レビューを通す方式に切り替えることに同意するか
4. **合意 4**: self_healing の危険経路は Phase 2 スコープから完全除外することに同意するか
5. **合意 5**: `--dry-run` フラグ新設を Phase 2 スコープから外すことに同意するか
6. **合意 6**: 本ドキュメントの §4「保留するもの」リストを Phase 2 開始前には決めないことに同意するか

全 6 点 Yes なら Step 2-α の単独設計書（1〜2 ページ）に進みます。1 つでも No があれば、その項目について追加議論します。

---

**補足**: 本縮小案自体が間違っている可能性もあります。ユーザー側で「これは前提として甘い」「ここは逆に厳しすぎる」があれば教えてください。取り繕いではなく、次の最小一歩を確実に踏むための合意です。
