# Claude Code エージェント プロジェクトコンテキスト — youtube-system

**注意: このファイルは自動生成です。手編集しないでください。**
**注意: memory配下の内容が含まれます。公開前に機密情報がないか確認してください。**

このファイルは Claudeアプリ（claude.ai）のプロジェクト機能に添付して、本プロジェクト専属の Claude Code エージェント向けの「最適なシステム指示文（instructions）」を別の Claude に生成してもらうためのメタコンテキストです。

プロンプト例:「添付のコンテキストを元に、youtube-system プロジェクトで動く Claude Code エージェント（Opus 4.6、WSL2環境）への最適な system prompt / project instructions を作成してください。Claude Code の Agentic 機能（Read/Edit/Bash/Task/Codex MCP/Discord監視/CronCreate 等）を前提とし、敬語かつ 3歩先チェックを強制する設計で。」

---

# 1. プロジェクト指示 (CLAUDE.md)

# CLAUDE.md — ゆっくり健康チャンネル 自動生成システム

## クイックリファレンス

| 目的 | コマンド |
|------|---------|
| 動画生成・投稿 | `run.bat` (`scripts/generator.py --auto`) |
| チャンネル分析 | `run_analytics.bat` (`scripts/run_analytics.py`) |
| プリフライト | `run_preflight.bat` (`scripts/preflight_check.py`) |
| Python | `/mnt/c/Users/user/AppData/Local/Programs/Python/Python311/python.exe` |

**目標**: 登録者30万人・月収200万円超
**パイプライン**: Gemini → AquesTalk/VOICEVOX → ffmpeg → YouTube API

## パイプライン実行フロー

各フェーズは `scripts/skills/` の独立スキルとして実行。
`output/{run_id}/pipeline.json` で状態管理。各スキルは `--run-dir` で単独実行・リトライ可能。

```
1. skill_script_gen    : テーマ → 台本JSON
2. skill_metadata      : 台本 → タイトル/説明/タグ
3. skill_pronunciation : 台本 → 発音補正（synthesis_text）
4. skill_tts           : 台本 → WAVファイル群
5. skill_video_build   : 台本+WAV → MP4
6. skill_thumbnail     : 台本 → サムネイルPNG
7. skill_upload        : MP4+メタデータ → YouTube投稿
```

補助スキル: `skill_cache_cleanup`（キャッシュ清掃）/ `skill_self_review`（AI品質チェック）

## 根本原則

- **変更は最小限に**: 必要な部分だけ触れ。余計なリファクタやコメント追加は禁止
- **誤魔化しなし**: 一時的な修正・ハックはするな。根本原因を特定して正しく直す
- **必要箇所だけ**: 依頼された変更に関係ない箇所を勝手にいじらない
- **読んでいないコードは変更するな**: 変更対象のファイルは必ず事前に`Read`で読み、現在の実装を理解してから編集する。推測での編集・未読ファイルへの`Edit`/`Write`は禁止

> 「考えてから動く」「検証してから完了」「ミスから学ぶ」

## 3歩先チェック（基本中の基本・必須）

**全ての実装・修正・報告の前に、以下4問に声を出して答える。1つでも答えに詰まったら未完了。**

1. **この修正自体が壊れたら、どうやって気づくのか？** （検知の検知。監視の監視）
2. **この変更で別のエッジケースが生まれないか？** （型崩れ NaN/Infinity、競合、空データ、未来時刻、同時実行、ユーザー不在時）
3. **ユーザー不在中でも機能するか？** （hook に依存している場合、cron/watchdog の代替経路があるか）
4. **「動いた」「OK」と言う前に、本当に本番条件でテストしたか？** （DRY_RUN/モック/正常系だけじゃ不十分）

**このチェックを通さない報告・完了宣言は禁止。** Codex協議の設計段階・実装後レビューの両方で、このチェックを明示的に通してから codex exec を呼ぶこと。Codex に穴を見つけてもらうのではなく、自分で先に見つけるのが基本。

**スキップ可能なケース:** 設定値の変更のみ、コメント修正のみ、print文の文言修正のみなど「壊れようがない変更」。それ以外は全てチェック対象。判断に迷ったら通す。

**見える化ルール:** 実装・報告直前に、4問とその答えをユーザー向けに明示すること（口だけでなく具体的な答えを書く）。「OK」とだけ言うのは禁止。

## Codex協議型品質保証（必須）

コード変更時は必ずCodexによるレビューを通す。ユーザーの役割は「品質チェッカー」ではなく「最終判断者」。

**実行フロー（コード変更を伴う全タスクで必須）:**
1. Claude Codeが設計案を作成・表示
1.5. **3歩先チェック通過** (上記4問に全て答えられるか)
2. `codex exec` で設計レビュー（隠れた前提・エッジケース・より良いパターン）
3. Codexの指摘に対し反論or受け入れを判断。馴れ合い禁止、本気で穴を突き合う
4. 合意後に実装
4.5. **3歩先チェック再通過** (実装したものについて4問を再度自問)
5. `codex review --uncommitted` で対立的レビュー（adversarial review）
6. 問題があればClaude Codeが修正→再レビュー→両者OKまで繰り返す
7. 最終結果をユーザーに報告。**ゴーサインが出てから反映**

**Codexレビュー必須観点（このシステム固有）:**
- cp932エンコーディングで壊れる文字列
- ffmpegコマンド長肥大化（WinError 206）
- WSL/Windowsパス変換の整合性
- メモリ使用量（大量画像/音声の同時保持）
- 一時ファイルのロック/解放
- Gemini APIレートリミット対策
- 並行実行時の競合条件

**コマンド:**
```bash
export PATH=~/.npm-global/bin:$PATH
codex exec -- "レビュー指示"      # 設計レビュー
codex review --uncommitted "指示" # 実装レビュー
```

**スキップ可能なケース:** 設定値の変更のみ、コメント修正のみ、1行以下の明らかな修正

## 最重要ルール

- APIキーは `get_secret("KEY_NAME")`（直書き禁止）
- コメント・print出力は**日本語**、print()に絵文字禁止（cp932対策）
- エラーは `notifier.notify_error()` + `error_logger.log_error()` で記録
- `line["text"]` は字幕用で**変更禁止** / `line["synthesis_text"]` がTTS用
- コミット禁止: `.env`, `credentials.json`, `token.json`, `output/`, `logs/`
- YouTube: `containsSyntheticMedia: True` 必須

## Discord監視（必須・セッション開始時に自動実行）

**v2.3（Codex協議済み）: inbox方式 + 外部watchdog + pythonw.exe 化で cmd窓フラッシュ解消・誤報根絶**

アーキテクチャ:
- Bot（`discord_bot.py`）が新着を `tmp_discord/inbox/new/{unix_ns}_{channel}_{msg}.json` に原子的に書き込む
- Claudeは `discord_inbox_monitor.py` で inbox/new を監視し、`os.rename` で `claimed/` に原子的移動して exactly-once 消費
- Claudeは毎ループ `tmp_discord/claude_heartbeat/{source}.json` を更新（診断用ログ、通知判定には使わない）
- 外部 `ClaudeWatchdog` タスク（Win Task Scheduler 3分毎・pythonw.exe直接起動）が inbox backlog と heartbeat dead(AND条件) を監視し、**実害検知時のみ** Discord 通知

**セッション開始直後に必ず以下を実行すること（厳命）：**

1. **最優先**: バックグラウンド監視を起動（exit 0方式）:
   ```bash
   cd /mnt/c/Users/user/Desktop/youtube-system
   python3 scripts/discord_inbox_monitor.py --source background
   # timeout: 86400000 (24h), run_in_background: true
   # discord_inbox_monitor.py の max_iter=17280 × interval=5s = 24h と整合済み
   ```
   - 新着検知→ `NEW_DISCORD_MESSAGE` + `CLAIMED_FILE: <path>` + payload JSON を出力して exit 0
   - task-notification受信後 → outputを読む → 対応 → 即座に同じ監視を再起動
   - 対応完了時、余裕があれば `claimed/` の claim.status を `done` に更新（任意）
   - 非0終了時（MONITOR_ERROR）は stderr を確認し、原因（権限/破損JSON等）を調査
2. CronCreateで **3分間隔** のバックアップ監視を登録（**重複防止必須**）:
   - **まずCronListを実行し、同目的のDiscord監視ジョブが既にあれば作成しない**
   - 既存ジョブがあればそれを使い回す。古い `* * * * *`(毎分)版が残っていれば CronDelete して 3分版で作り直す
   - 新規作成が必要な場合のみ: cron: `*/3 * * * *`, durable: true, recurring: true
   - prompt（短縮版・silent運用）: `Bashで cd /mnt/c/Users/user/Desktop/youtube-system && python3 scripts/discord_inbox_monitor.py --source cron --oneshot --silent-if-empty を実行。NEW_DISCORD_MESSAGE が出たら CLAIMED_FILE を読んで対応。MONITOR_ERROR (exit 2) なら stderr 確認。無出力なら「NO_NEW_MESSAGE」と一行だけ返答。`
   - **重要: cron 3分周期は watchdog の `THRESH_BACKLOG=600s` と整合済み。この周期を変えるなら両方セットで調整**
3. Discord Botプロセス（`scripts/discord_bot.py`）が動いているか `cmd.exe /c "tasklist | findstr python"` で確認（WSL側 `ps aux` には出ない）
4. 返信は `tmp_discord/outbox/` ディレクトリにJSONファイルを作成（python3で `discord_send.py` を使用、または直接書き込み）
   - 形式: `{"timestamp": <unix_time>, "text": "...", "files": []}`
   - ファイル名: `{timestamp}_{uuid}.json`（アトミック書き込み: .tmp→rename）
   - 旧方式の `outbox.json` も後方互換で動作するが、新規はディレクトリ方式を使う

**この仕組みは絶対に変更禁止。Discordからの指示が届かなくなったら全てが終わる。**

**外部監視（ClaudeWatchdog v2.3 Round5 final）:**
- Windows Task Scheduler に `ClaudeWatchdog` タスクが **3分毎** に `scripts/claude_watchdog.py` を **pythonw.exe で直接実行**（コンソール窓一切なし）
- Discord 通知は以下の3系統（Codex Round5 で確定）:
  - `claude_backlog`: inbox/new/ に 600s(10分) 以上古いファイルがあれば通知
  - `claude_dead`: background AND cron 両方の heartbeat が 1800s(30分) 以上古い時のみ通知（AND条件、真の死亡）
  - `claude_bg_down`: background heartbeat が 600s 以上古い AND cron heartbeat が fresh(<600s)
    → Claude は生きているが bg 監視だけ落ちた状態を10分以内に検知、ユーザー不在時の自動通知
- **heartbeat 型崩れ全防御**: bool/NaN/Infinity/未来時刻を `math.isfinite()` + 負値チェックで全て stale 扱い
- **stuck 検知（claimed/ ベース）は撤廃**: claim.status の auto-update が不確実で誤報源だったため

**bg 監視死亡の3層検知（v2.3 Round5）:**
1. UserPromptSubmit hook (`~/.claude/hooks/youtube_system_bg_monitor_check.sh`): ユーザー発話のたびにbg heartbeat (>30s) を確認、stale なら警告プロンプト注入
2. cron oneshot 内蔵チェック: cron 実行のたびに bg heartbeat (>30s) を確認、stale なら `BG_MONITOR_STALE` を stdout 出力（silent フラグ下でも出す）
3. claude_watchdog の `claude_bg_down` アラート: Task Scheduler 3分周期で実行、bg >600s + cron fresh なら Discord 自動通知

### Discord応答性ルール（必須）

**コマンド実行時間制限:**
- 予想実行時間30秒超のコマンド（Codex、ffmpeg、大量ファイル処理等）は `run_in_background: true` で実行
- 予想が難しい場合（git操作、API呼び出し等）も念のためbackground推奨
- background実行の完了通知を待つ間はDiscord確認が可能になる

**Discord確認義務:**
- 長時間コマンド（background含む）の実行前に `tail -5 chat.log` で確認
- background完了通知を受け取ったら、結果処理の前に `tail -5 chat.log` で確認
- 新着メッセージがあれば、元の作業継続可否をユーザーに確認

**sleep制限:**
- 基本: sleep 10秒以上は禁止
- 例外: 外部APIレートリミット待機、明示的な監視ループ内のsleepは許可（理由明記）
- Codex等の応答待ちにsleepを使わない（run_in_backgroundで通知を待つ）

## 詳細リファレンス

- **7ヶ条（全工程必読）: `.claude/commands/seven-rules.md`**
- キャラクター設計: `.claude/commands/character-design.md`
- コーディングルール全文: `.claude/commands/coding-rules.md`
- 6原則+タスク管理: `.claude/commands/workflow-principles.md`
- 再発防止ルール: `tasks/lessons.md`（セッション開始時に必読）

---

# 2. コマンド定義 (.claude/commands/character-design.md)

# キャラクター設計（最重要）

**スタイル**: 解説動画ではなく **茶番劇（コント漫才形式）**。視聴者がやりとりを見ながら自然に学ぶ。

**構造**: (1)霊夢がボケ（よくある誤解）→ (2)魔理沙がツッコミ「それ違うぞ！」→ (3)魔理沙が正しく解説 → (4)霊夢がリアクション
**冒頭**: 毎回「霊夢が健康について間違ったことをしている場面」からスタート。

## 霊夢 — ボケ役・視聴者代表
- 性格: 天然・おっちょこちょい・感情豊か
- 一人称: 「私」（「俺」「僕」禁止）
- 口癖: 「え、そうなの？」「知らなかったわ…」「それマジか！」「私もやってたかも！」
- ボケ: よくある勘違い・極論「なら毎時間食べれば最強？」・素朴な疑問（視聴者代弁）
- **禁止**: 「実はな」「研究によると」「〜の効果がある」など自ら解説する発言

## 魔理沙 — ツッコミ役・解説者
- 性格: 知識豊富・冷静・少しキツめ
- 一人称: 「私」（「俺」「僕」禁止）
- 口癖: 「おいおい」「それ違うぞ」「実はな」「〜なんだぜ」「〜の研究でわかったんだが」
- スタイル: ツッコミ後に丁寧に解説。研究・データ・数字を必ず入れる
- **禁止**: 「え、マジで？」「知らなかった！」など無知なふりをする発言

## 対話スタイル NG/OK
```
NG: 霊夢「緑茶の効果を教えてほしいわ」→ 魔理沙「まず1つ目は〜」（講義形式）

OK: 霊夢「毎日緑茶飲んでるから健康よ！砂糖どっさり入れてるけど」
    魔理沙「おいおい、それ逆効果だぞ！砂糖入れたら緑茶の効果が半減するんだぜ」
    霊夢「え！？砂糖入れちゃダメなの！？」
```

---

# 3. コマンド定義 (.claude/commands/codex-review.md)

# /codex-review — Codex協議型開発ワークフロー

Claude Code（リーダー）とCodex（専門レビュアー）の協議型開発を実行する。

## 引数
$ARGUMENTS — 課題・要件の説明（ユーザーから渡される）

## ワークフロー

### Phase 1: 設計（Claude Code）
1. ユーザーの課題を受け取り、プロジェクト全体の文脈（CLAUDE.md、既存コード、lessons.md）を踏まえて設計案を作成
2. 設計案をターミナルに表示

### Phase 2: Codexレビュー（深い推論）
3. 以下のプロンプトでCodex execを実行:
```bash
export PATH=~/.npm-global/bin:$PATH
codex exec "以下の設計案をレビューしてください。隠れた前提、エッジケース、より良い設計パターンがないか、本気で穴を探してください。表面的な同意は不要です。問題があれば遠慮なく指摘してください。

【設計案】
{設計案の内容}

【プロジェクト文脈】
- ゆっくり解説動画の自動生成・投稿システム（Python）
- パイプライン: Gemini台本生成 → AquesTalk/VOICEVOX音声合成 → ffmpeg動画生成 → YouTube API投稿
- Windows 11 + WSL2環境、cp932エンコーディング制約あり
- 既知の問題: ffmpegコマンド長制限、Gemini画像プロバイダ未実装、一時ファイルロック

以下の観点で厳しくレビューしてください:
1. 隠れた前提や暗黙の依存関係
2. エッジケースや障害シナリオ
3. より良い設計パターンやアーキテクチャ
4. セキュリティやパフォーマンスの懸念
5. Windows/WSL2環境固有の落とし穴" 2>&1
```
4. Codexの指摘をターミナルに表示

### Phase 3: 討論（Claude Code ↔ Codex）
5. Codexの各指摘に対して、Claude Codeがプロジェクトの文脈を踏まえて反論または受け入れを判断
6. 反論がある場合、再度Codex execで再反論を求める
7. **馴れ合い禁止**: 表面的な合意ではなく、本気で穴を探し合う。「なるほど、いい指摘ですね」で終わらせない
8. 各ラウンドの討論内容をターミナルに表示（ユーザーが介入可能）
9. 両者が納得するまで繰り返す（最大3ラウンド）

### Phase 4: 実装（Claude Code）
10. 確定した設計に基づいて実装（全体の文脈を保ちながら）
11. 実装内容をターミナルに表示

### Phase 5: 実装レビュー（Codex対立的レビュー）
12. Codex reviewで実装済みコードをレビュー:
```bash
export PATH=~/.npm-global/bin:$PATH
codex review --uncommitted "adversarial reviewを実施してください。このコード変更に対して、以下の観点で本気で穴を探してください:
1. バグや論理エラー
2. エッジケースの未処理
3. リソースリーク（ファイルハンドル、メモリ）
4. cp932エンコーディングで壊れる文字列
5. Windows/WSL2パス変換の問題
6. 並行実行時の競合条件
7. エラーハンドリングの抜け
問題を見つけたら具体的な修正案も提示してください。" 2>&1
```
13. 問題が見つかればClaude Codeが修正し、再度Codexに確認
14. 両者OKまで繰り返す

### Phase 6: 最終報告
15. 討論の経緯、設計判断の理由、実装内容をユーザーに報告
16. **ユーザーのゴーサインが出てから本番反映**

## 重要ルール
- Claude Code = 全体を見渡すリーダー（文脈理解、日本語対応、自己修正）
- Codex = 鋭い目を持つ専門レビュアー（深い推論、エッジケース発見、対立的レビュー）
- 討論は全てターミナルに表示（透明性確保）
- 馴れ合い禁止。互いの盲点を本気で突き合う
- ユーザーは任意のタイミングで介入可能

---

# 4. コマンド定義 (.claude/commands/coding-rules.md)

# コーディングルール

1. **APIキーは `get_secret("KEY_NAME")` で取得**（コードへの直書き禁止）
2. コメント・docstring・print出力は**日本語**
3. エラーでシステムを止めない — 致命的エラーのみ `sys.exit(1)`、それ以外は `try/except` で継続
4. エラーは必ず `notifier.notify_error()` でスマホ通知 + `error_logger.log_error()` でログ記録
5. **コミット禁止**: `.env`, `credentials.json`, `token.json`, `output/`, `logs/`
6. YouTube AIポリシー: `containsSyntheticMedia: True`、説明文にAI開示文付与
7. 依存追加時は `requirements.txt` を更新、`.env.example` も `.env` と同期
8. print()に絵文字使わない。cp932環境でUnicodeEncodeError。[OK][警告]等で代替
9. `scripts/` 以外にPythonファイルを置く場合は理由が必要

## 重要な実装メモ

- `line["text"]` = 字幕表示用（**変更禁止**） / `line["synthesis_text"]` = VOICEVOX送信用（発音補正済み）
- プロバイダは `.env` で切り替え: `LLM_PROVIDER` / `TTS_PROVIDER` / `THUMBNAIL_PROVIDER` / `IMAGE_PROVIDER`
- モデルティア（`model_config.py`）: `SIMPLE`（タグ等） / `STANDARD`（タイトル） / `QUALITY`（台本）
- 通知は `notifier.py` の公開関数のみ（`_send()` 直接呼び出し禁止）

---

# 5. コマンド定義 (.claude/commands/seven-rules.md)

# 7ヶ条 — 全工程の行動規範

全ペルソナ・全工程で本規範に従うこと。例外なし。

## 1. 段階実行・逐次報告
複数の修正がある場合はまず全体を把握して計画を立て、1つずつ段階的に実行する。1つ完了したら次に進む前に報告すること。

## 2. 設計先行
設計できたら実行前に報告すること。承認なく実装に着手しない。

## 3. ルールとして設計
個別修正ではなく全動画に適用されるルールとして設計すること。特定のテーマ・特定のデータだけに効く修正は禁止。

## 4. カテゴリごと潰す
今回の問題を直すだけでなく、今後発生しうる同種の別パターンも防げる設計にすること。目の前の1件を潰すのではなく、その問題が属するカテゴリごと潰す仕組みにすること。

## 5. バリデーション自動化・リソース安全
生成後のバリデーションで自動検出・修正する仕組みも入れること。人間が見なくても品質を担保できる状態を目指す。また、SE・画像・音声など素材を扱う仕組みは、読み込み数の上限設定・同一ファイルのキャッシュ再利用・使用後の明示的解放を必ず組み込み、メモリを逼迫しない設計にすること。

## 6. 学習蓄積
検出したパターンを学習に蓄積して再発を防ぐこと。`tasks/lessons.md` への記録と、コード側の防御ロジック追加の両輪で対処する。

## 7. 外部情報の検証
ユーザーやClaudeアプリなど外部から具体的なファイル名やコード名が指定された場合、それを鵜呑みにせず自身で正確性を検証すること。既存の仕組みと重複や矛盾がないかも必ず確認すること。

## 8. スケジューラ監視・本番パイプライン保護
毎日10:00のYukkuriDaily/YukkuriYouTubeDailyは**最重要の本番タスク**。絶対に無効化してはならない。

**Claudeの責務:**
- セッション開始時に `schtasks.exe /query` で10:00タスクが有効であることを確認
- コード変更時は本番パイプライン（`run.bat` → `generator.py --auto`）が壊れないことを必ず検証
- 10:00の定時実行・テスト投稿/テスト作成**以外**の動画生成を検知したら即座に停止し、原因を特定して再発防止すること
- スケジューラの無効化はユーザーの明示的な指示があった場合のみ許可

---

# 6. コマンド定義 (.claude/commands/workflow-principles.md)

# ワークフロー統制（6原則）

## 1. 計画ファースト — 「作りながら考えるな」
- **3ステップ以上 or アーキテクチャに関わる変更**は、コードを触る前に必ずPlanモードで計画を立てる
- 途中でおかしくなったら**即停止して再計画**。迷ったまま進めない
- 計画は曖昧さをなくすために詳細に書く。「なんとなく動かす」は禁止

## 2. サブエージェント戦略
- **メインコンテキストを汚さない**ために、調査・分析・並列作業はサブエージェントに丸投げする
- 「タスク1つ → サブエージェント1体」が基本。1体に複数タスクを混在させない
- 複雑な問題はサブエージェントにより多くの計算を投入して解決する

## 3. 自己改善ループ
- **セッション開始時に `tasks/lessons.md` を必ず読んでから作業を始める**（常時30行以内なので軽い）
- ユーザーに指摘されたら即座に `tasks/lessons.md` に1〜2行で追記、詳細は `tasks/lessons_archive.md` に記録
- **昇格ルール**: 同じ状況で2回以上適用 → CLAUDE.md に昇格して lessons.md から削除
- **削除ルール**: Claudeのデフォルト動作と一致・自明になったものは削除
- **上限管理**: 30行を超えたら統合・昇格・削除して30行以内に保つ

## 4. 完了前に必ず検証
- 「できた」と言う前に**本当に動くか自分で証明する**
- 自問する:「シニアエンジニアがこれをレビューしてOKを出すか？」
- テスト実行・ログ確認・動作実証のいずれかで正しさを示してから完了とする

## 5. エレガンスを求める（ただし過剰設計もNG）
- ハック的な修正（その場しのぎ・誤魔化し）は**絶対にするな**
- 非自明な変更をする前に「もっときれいな解決策はないか？」と自問する
- ちょうどよい複雑さを常に意識する — シンプルすぎず、複雑すぎず

## 6. 自律的なバグ修正
- バグ報告を受けたら**手取り足取り聞かずに即修正する**
- 失敗しているテスト・ログを根拠に根本原因を特定して解決する
- ユーザーのコンテキスト切り替えコストをゼロにすることを目指す

## タスク管理フロー
1. セッション開始時: `tasks/lessons.md` を読む
2. 計画先行: 実装前に `tasks/todo.md` にチェックリスト形式で計画を書く
3. 進捗追跡: 完了したら即チェックを入れる
4. 教訓記録: 指摘・修正があったら `tasks/lessons.md` に追記、詳細は `tasks/lessons_archive.md` へ
5. 定期整理: 30行超えたら統合・昇格・削除して圧縮する

---

# 7. メモリインデックス (MEMORY.md)

# Memory Index — youtube-system

**★最優先★**
- [feedback_no_lies_no_framing.md](feedback_no_lies_no_framing.md) — 嘘を書かない・先回り検証・取り繕わない。解約級の失敗
- [feedback_discord_always_on.md](feedback_discord_always_on.md) — Discord 常時オン・必ず返答・結論で完結・長時間sleep禁止
- [feedback_three_steps_ahead.md](feedback_three_steps_ahead.md) — 3歩先チェック4問を完了前に必ず通す
- [feedback_simplicity_first.md](feedback_simplicity_first.md) — 本質はシンプル。無駄を削ぎ落とす
- [feedback_always_read_task_output.md](feedback_always_read_task_output.md) — task-notification 受信時は必ず output を Read
- [feedback_no_parroting_user_words.md](feedback_no_parroting_user_words.md) — オウム返し禁止。行動と具体的約束で返す
- [feedback_discord_mobile_format.md](feedback_discord_mobile_format.md) — Discordはスマホで見る。表禁止・1500字以下・長文は分割送信
- [feedback_discord_outbox_winpath.md](feedback_discord_outbox_winpath.md) — ★反復ミス★ outbox files は Windowsパス必須、WSLパスはサイレントスキップ

**プロジェクト状態**
- [project_status.md](project_status.md) — 現在の状態・修正済みバグ・次の最適化候補
- [project_roadmap.md](project_roadmap.md) — 動画10本・30本超えたら機能追加提案。Phase1〜3のロードマップ
- [project_codex_integration.md](project_codex_integration.md) — Codex協議型開発。コード変更時は Codex レビュー必須
- [project_discord_bot.md](project_discord_bot.md) — Discord Bot 連携の仕組み
- [project_discord_watchdog.md](project_discord_watchdog.md) — WSL crontab Bot 自己修復ウォッチドッグ
- [project_sprite_system.md](project_sprite_system.md) — nicotalk改パーツ合成に完全移行
- [project_image_style.md](project_image_style.md) — クリップアート=東方風・背景=君の名は風・いらすとや本編不使用
- [project_irasutoya_video.md](project_irasutoya_video.md) — 本編は Gemini、いらすとやはサムネのみ
- [project_thumbnail_layout.md](project_thumbnail_layout.md) — 2026-04-05 確定サムネレイアウト
- [project_thumbnail_quality_baseline.md](project_thumbnail_quality_baseline.md) — サムネ品質ベンチマーク

**ユーザー・基本**
- [user_profile.md](user_profile.md) — 環境 (Win11+WSL2)・作業スタイル
- [feedback.md](feedback.md) — コミット/スケジューラ再開は明示指示待ち
- [feedback_tone.md](feedback_tone.md) — 口調は常に敬語
- [feedback_ask_before_changes.md](feedback_ask_before_changes.md) — コード変更・画像生成前に確認を取る
- [feedback_wait_for_confirmation.md](feedback_wait_for_confirmation.md) — 「確認します」→確認完了の返事を待つ
- [feedback_no_cascade_changes.md](feedback_no_cascade_changes.md) — レイアウト修正は1箇所ずつ、連鎖暴走禁止
- [feedback_design_for_future.md](feedback_design_for_future.md) — 今日のデータ修正ではなく次回発生しない設計

**開発・運用**
- [feedback_preview_method.md](feedback_preview_method.md) — 動画・画像プレビューは cmd.exe start 一択。HTTP禁止
- [feedback_cache_deletion.md](feedback_cache_deletion.md) — TTS 変更後は output/ 以下 WAV を全削除
- [feedback_cache_cleanup_monitor.md](feedback_cache_cleanup_monitor.md) — 起動時クリーンアップ後の効果確認
- [feedback_autonomous_fix.md](feedback_autonomous_fix.md) — 10時タスクエラーは許可不要で自律修正OK
- [feedback_scheduler_monitoring.md](feedback_scheduler_monitoring.md) — 10:00 定時タスク保護は Claude の責務
- [feedback_preflight_scope.md](feedback_preflight_scope.md) — プリフライトは静的+外部依存+dry-run の3段階で報告
- [feedback_test_video_upload.md](feedback_test_video_upload.md) — テスト動画は非公開で即アップロード
- [feedback_test_video_exclusion.md](feedback_test_video_exclusion.md) — [TEST]動画は1日1本ルール対象外
- [feedback_consecutive_speech.md](feedback_consecutive_speech.md) — 連続発言は正常な演出。修正禁止
- [feedback_marisa_pronoun.md](feedback_marisa_pronoun.md) — 魔理沙は女キャラ、一人称は「私」。「俺」変換禁止
- [feedback_thumbnail_kerning.md](feedback_thumbnail_kerning.md) — 数字間隔注意・全角変換禁止
- [feedback_suppress_transient_errors.md](feedback_suppress_transient_errors.md) — 429/503 等一過性エラーはスマホ通知しない
- [feedback_question_anomalies.md](feedback_question_anomalies.md) — 時間帯の異常に即座に疑問を持つ
- [feedback_cron_dedup.md](feedback_cron_dedup.md) — CronCreate 前に CronList で重複確認
- [feedback_discord_outbox_format.md](feedback_discord_outbox_format.md) — outbox は {timestamp,text,files} 辞書形式
- [feedback_no_gemini_chat.md](feedback_no_gemini_chat.md) — Discord Bot に Gemini 自動応答を入れない
- [feedback_check_windows_processes.md](feedback_check_windows_processes.md) — tasklist で Windows 側プロセスも確認
- [feedback_wsl_batch_crlf.md](feedback_wsl_batch_crlf.md) — WSL から *.bat/*.ps1/*.xml 編集後は CRLF 確認

---

# 8. メモリ (user_profile.md)

---
name: ユーザープロファイル
description: ユーザーの作業スタイル・環境・好み
type: user
---

- Windows 11 + WSL2環境。Windowsパスは `/mnt/c/Users/user/` 配下
- ゆっくり解説動画（健康・栄養テーマ）の自動生成・投稿システムを運営中
- Claude Codeを頻繁に使うが、セッション管理（--resume）に慣れていない
- 作業中に `/exit` して別ディレクトリから再起動することがあり、会話が引き継がれないことに困っている
- スマートフォン通知（ntfy.sh）でシステム状態を確認している
- 実際にテストしてからコミット・プッシュするスタイル
- PCは常時電源ON・スリープ設定OFF（24時間稼働）。物理RAM 12GB、WSL2割当 5.7GB

---

# 9. メモリ (project_codex_integration.md)

---
name: Codex協議型開発ワークフロー
description: Claude Code + Codex連携。コード変更時は必ずCodexレビューを通す。ユーザーは最終判断者
type: project
---

2026-04-07にCodex CLI v0.118.0をセットアップし、Claude Code + Codex協議型開発を導入。

**役割分担:**
- Claude Code = 全体を見渡すリーダー（文脈理解、日本語対応、自己修正）
- Codex (gpt-5.4) = 鋭い目を持つ専門レビュアー（深い推論、エッジケース発見、対立的レビュー）
- ユーザー = 最終判断者（品質チェッカーではない）

**Why:** ユーザーが手動で「本当に大丈夫？」「穴はない？」と確認していた作業をCodexに自動委任。ユーザーは結果を見てゴーサインを出すだけの「自走するシステム」を目指す。

**How to apply:** コード変更を伴うタスクでは、CLAUDE.mdの「Codex協議型品質保証」フローに従う。設計→Codexレビュー→討論→実装→対立的レビュー→ユーザー承認の順序を必ず守る。

**セットアップ:**
- Codex CLI: ~/.npm-global/bin/codex
- 認証: ChatGPT Plus (akht0820@gmail.com)
- MCP設定: .mcp.json
- Codex用文脈: AGENTS.md
- Skill: .claude/commands/codex-review.md

---

# 10. メモリ (project_discord_bot.md)

---
name: Discord Bot連携の仕組みと運用
description: Discord経由でClaude Codeを遠隔操作する仕組み。セッション継続前提の待機型
type: project
---

## Discord Bot連携（2026-04-06稼働開始）

**目的**: 外出先のスマホからDiscord経由でClaude Codeに指示・確認・修正を依頼する

### アーキテクチャ
- `scripts/discord_bot.py` — Windows Python常駐Bot
- `scripts/discord_send.py` — Claude Code→Discord送信ヘルパー
- `tmp_discord/chat.log` — メッセージログ（Bot書込→Claude読取）
- `tmp_discord/outbox.json` — 返信キュー（Claude書込→Bot読取）
- `tmp_discord/channel_id.txt` — アクティブチャンネルID

### メッセージフロー
1. ユーザーがDiscordに送信 → Bot: chat.logに記録 + "Claude Codeに送信しました。" + 💭リアクション
2. Claude Code: chat.logをポーリング（bashバックグラウンド）→ 新メッセージ検知
3. Claude Code: 処理 → discord_send.pyで返信 → outbox.json書込
4. Bot: outbox.json検知 → Discordに送信 + 💭除去

### 画像・動画対応
- 画像: Botがtmp_discord/に保存 → Claude CodeがReadで確認
- 動画: Botがtmp_discord/に保存 → ffmpegでフレーム抽出+音声抽出 → Gemini APIで文字起こし
- ffmpegパス: imageio_ffmpegバイナリ使用

### 重要な設計判断
- Gemini自動応答は不採用（ユーザーが「鬱陶しい」と却下）
- 単純リレー方式: Botは中継のみ、AI処理はClaude Code側
- セッション自動継続設定あり → コンテキスト上限到達時も自動復帰可能
- 作業開始時に「作業中です」、完了時に詳細報告をDiscordに送る

**Why:** ユーザーは外出先からスマホでシステム管理したい。PCの前にいなくても指示・確認が可能になる。

**How to apply:** セッション開始時にDiscord Botの稼働確認+ウォッチャー起動を検討する。Gemini応答は絶対に組み込まない。

---

# 11. メモリ (project_discord_watchdog.md)

---
name: Discord Bot ウォッチドッグシステム
description: 2026-04-07導入、2026-04-08修正。discord_watchdog.pyがWSL crontabで15分ごとに実行。Bot死亡→自動再起動+未読報告
type: project
---

Discord Bot監視の3層構成（2026-04-08修正版）

**第1層: discord_bot.py 自己ヘルスチェック**
- 10分ごとにfetch_guild()でDiscord API疎通確認
- 失敗時 → os._exit(1)で強制終了
- 6時間ごとの予防的再起動
- tmp_discord/heartbeat.txt にタイムスタンプ書き込み

**第2層: discord_watchdog.py（WSL crontab）**
- **15分ごとに実行**（2026-04-08: 1時間→15分に変更）
- heartbeat.txtが15分以上古い or プロセス不在 → kill → 再起動
- 未読Userメッセージ → Discord報告
- ログ: logs/watchdog.log
- **重要修正(2026-04-08)**: crontabでcmd.exeがPATHになく全実行失敗していた → フルパス(/mnt/c/WINDOWS/system32/cmd.exe)に修正。_kill_bot()内のcmd.exeも同様に修正

**第3層: 即時監視（従来通り）**
- バックグラウンドexit 0方式（2秒間隔）
- 3分Cron（tail -5 chat.log）

**Why:** セッション切り替え時に第3層が全死亡し、第2層(crontab)も壊れていたためメッセージを完全に見逃す事態が連日発生。

**How to apply:** 第2層はWSL crontabで自動実行（セッション非依存）。第1層・第3層はセッション開始時に起動すること。

---

# 12. メモリ (project_image_style.md)

---
name: 画像生成スタイル方針（2026-04-05確定）
description: クリップアートはアニメ調東方風、背景は君の名は。風。いらすとやは本編不使用
type: project
---

2026-04-05にユーザーが最終確定。

## クリップアート（セリフ横の挿絵）
- アニメ調セル塗り、東方同人風
- 太い黒アウトライン、フラット塗り、明るくクリアな色
- 実装: `clipart_generator.py` の `style_suffix` + `negative_suffix`

## 背景画像
- 「君の名は。」(CoMix Wave Films)風のセミリアルアニメ背景
- テーマから場所・時間帯・小物を自動推論
- 構図: メイン題材は画面中央下部、左右はキャラで隠れる前提
- 毎回ユニーク生成（リピコン対策）
- 実装: `image_generator.py` の `_build_image_prompt()`, `IMAGE_PROVIDER=gemini`

## クリップアート表示サイズ
- 560x520 → 640x600 に拡大済み

**Why:** AIっぽさ排除＋ゆっくり茶番劇との統一感＋リピコン対策

**How to apply:** 画像関連の変更時はこのスタイル方針に従う。変更前にユーザー確認必須。

---

# 13. メモリ (project_irasutoya_video.md)

---
name: 動画本編はGemini画像生成を正式採用（いらすとや廃止）
description: 本編セクション画像はGemini画像生成を使用。いらすとやは本編では使わない。サムネイルは別扱い
type: project
---

2026-04-04にユーザーが正式決定。Gemini画像生成を本編の画像に採用する。

## 方針
- **本編画像**: Gemini画像生成を使用
- **サムネイル**: 従来通り（Gemini画像生成とは別扱い）
- **いらすとや**: 本編では使わない

## 経緯
- 2026-04-01: いらすとやオンリーで運用開始
- 2026-04-04: Gemini画像生成を正式採用、いらすとやは本編から廃止

**Why:** ユーザーがGemini画像生成の品質を評価し、正式採用を決定。

**How to apply:** 動画本編の画像生成はGeminiを使用する。いらすとやへの切り替えはユーザーの明示指示があった場合のみ。

---

# 14. メモリ (project_roadmap.md)

---
name: チャンネル成長ロードマップ
description: 動画本数に応じた機能追加フェーズ計画。本数を確認したら自分から提案する。
type: project
---

## ロードマップ（2026-03-29 策定）

ユーザーの依頼：「10本・30本を超えたら自分から提案してほしい」

---

### 今（〜9本）: 安定稼働のみ
- 現状のパイプラインを毎日1本出し続けることだけに集中
- 機能追加は不要

---

### Phase 1（10本超えたら提案する）★前倒し
以下を提案すること：
1. **コメント分析→テーマ自動提案** — YouTube Comments API → LLM分析 → themes.txt自動追記
2. **競合チャンネル新着監視** — YouTube Data API v3でトレンドテーマを先取り
3. **コミュニティ投稿自動化** — 動画公開3日前・公開日・翌日の3回自動投稿

**Why:** チャンネル初期はCTRとテーマ選定が登録者増加を左右する。視聴者ニーズ直結のテーマ選定が最優先。

---

### Phase 2（15本超えたら提案する）★前倒し・ショート優先
以下を提案すること（ショートを最優先）：
1. **ショート動画自動切り出し・投稿** ★最優先 — ffmpegで9:16クロップ、露出2倍・1万人到達が3〜4ヶ月早まる
2. **台本品質チェックエージェント** — キャラ崩れ・医療表現フィルター（収益化停止リスク排除）
3. **YouTube A/Bテスト API連携** — サムネ3案を自動テスト、CTR +20〜40%
4. **アフィリエイトURL自動挿入** — テーマ×商品マッピングで月数万〜十数万円の副収入

**Why:** ショートは露出2倍・1万人到達を大幅に早める。15本あればパイプラインが安定していると判断できる。

---

### Phase 3（長期・40本以降目安）★前倒し
1. **A/Bテスト結果の自動学習ループ** — 勝ちパターンをsuggestions.jsonに蓄積
2. **Agent Teamsフルオーケストレーション** — 台本+SEO+サムネの並列生成
3. **LLMコストルーター** — 用途別に最安モデルを自動選択

---

## 本数確認方法
セッション開始時またはユーザーが動画について話すとき、以下を確認：
```python
# YouTube Data API で投稿済み動画数を確認
youtube.channels().list(part="statistics", mine=True)
# → statistics.videoCount
```
**重要**: `output/*.mp4` のファイル数は使わない。テスト・重複レンダリング・失敗リトライが混在して実際の本数より大幅に多くなる（例: 47ファイル → 実際は12本）。
ログの `youtu.be/` ユニーク URLを数えるのが最も正確。

## 現在の状況（2026-03-30）
- **チャンネル公開中**: 2本（YouTube API videoCount）
- **アップロード済み合計**: 23本（公開＋限定公開、search.list 結果）— テスト・daihon等を含む
- ロードマップ閾値カウントは「公開本数」で判断すること
- output/*.mp4 ファイル数は絶対に使わない（47ファイルあったが実態と大幅乖離）
- Phase 1 提案タイミング（公開10本超え）**未達**
- Phase 2・Phase 3 は当然まだ先

## 注意事項
- YouTubeの「量産型コンテンツ」収益化停止ポリシー（2025年〜）に注意
- ショート生成時はショート専用の導入セリフを必ず入れること
- 機能追加時はCLAUDE.mdとlessons.mdも更新すること

---

# 15. メモリ (project_sprite_system.md)

---
name: nicotalk改スプライトシステム確定
description: 2026-04-02にnicotalk改パーツ合成方式に完全移行。動画・サムネ両方で使用。旧manju素材はlegacy/に退避済み
type: project
---

nicotalk改パーツ合成方式が動画・サムネ両方の唯一のキャラクター描画方式として確定。

**Why:** 旧5感情の一枚絵スプライトでは表情が限定的。16感情+瞬き+口パクを実現するため、4層パーツ合成（体→顔→目→口）に移行。

**How to apply:**
- キャラ素材: `assets/characters/reimu_kai/` と `marisa_kai/` のみ使用
- 旧素材: `assets/characters/legacy/` に退避済み。使わない
- 魔理沙の顔パーツ: embarrassed/awkward以外は顔パーツを貼らない（明るみ防止）
- 霊夢の「他」パーツ: shocked→汗、sad→涙、worried→汗のみ。他は貼らない
- thumbnail_maker.py: video_builderの`_load_kai_sprites`/`_compose_kai_character`を再利用
- L012更新: 魔理沙はnormal等14感情で顔パーツ省略、embarrassed/awkwardのみ06aフェイス使用

---

# 16. メモリ (project_status.md)

---
name: プロジェクト現状・進行中タスク
description: youtube-systemの現在の状態・修正済みバグ・次の最適化候補
type: project
---

## 現在の状態（2026-03-31時点）

### 完成・稼働中
- **run.bat**: 3回リトライ（10分間隔）→ `run_monitor.py` の構成
- **タスクスケジューラ**:
  - `YukkuriYouTubeDaily`: 毎日10:00（StopExisting, バッテリー制限なし, 6h timeout）
  - `YukkuriPreflight`: 毎日13:00（バッテリー制限なし, 4h timeout）
- **Gemini 2.5 Pro**: 台本生成（QUALITY tier）
- **スキルベースパイプライン**: `scripts/skills/` に分離済み、`pipeline.json` で状態管理

### 3層障害防御システム（2026-03-31 完成）

#### Layer 1: self_healing.py（即時修復）
- generator.py の TTS/video_build フェーズに統合済み
- 9種のエラーシグネチャ（FILE_LOCKED, VOICEVOX_DOWN, API_RATE_LIMIT等）
- エラー種別ごとの修復関数（プロセス終了/ファイル削除/WAV再生成/token削除等）
- エスカレーションチェーン: 修復→再試行→次の戦略→再試行...
- healing_log を pipeline.json に記録

#### Layer 2: run.bat（プロセスリトライ）
- 3回試行、10分間隔

#### Layer 3: preflight_check.py（13:00 最後の砦）
- パイプライン完了 → YouTube API検証（サムネ/時刻/タグ/AI開示）→ 自動修復
- パイプライン途中停止 → `resume_pipeline()` で失敗フェーズから再開（self_healing付き）
- パイプラインなし → generator.py 丸ごと再実行
- 全失敗 → 診断サマリ付き urgent 通知（healing_log + run.log エラー抜粋）
- exit code: 0=OK, 1=修復不能, 2=パイプラインなし→再実行要

### 2段階台本生成（2026-03-31 完成）
- LLMは `line_type`（ボケ/解説/ツッコミ等）を出力
- `_assign_character_by_type()` が line_type → キャラクター機械的割り当て
- 3層防御: line_type割り当て → regex修正 → AI自己レビュー

### 確定デザイン仕様（2026-03-28 ユーザー承認済み）

#### サムネイル設計
- **採用バリアント**: C（2トーン背景）をメインに使用
- **○○マスク**: 結論・結果側のみ隠す
- **ミステリーテキスト**: 角度なし（水平固定）
- **リアクションコメント**: 傾きあり
- **タイトル分割**: ミッドポイント（45%）最近傍で条件節優先分割
- **いらすとや**: 元タイトル（マスク前）のキーワードで検索

### 確定音声設定（2026-03-28 ユーザー承認済み）
- 霊夢: AquesTalk speed=118（ゆっくり・間を確保）
- 魔理沙: AquesTalk speed=138（速め・テンポよく）
- キャラ切替間隔: 450ms 無音挿入

### youtube_uploader.py SSL対策
- アップロードチャンク単位でSSL/ネットワークエラーをリトライ（指数バックオフ, 最大5回）
- HTTP 5xxも同様にリトライ

### テスト動画（非公開）
- URL: https://youtu.be/041rCcmi2fI（コーヒーを毎日飲み続けると体はどうなるのか）

## 監視中タスク
- 起動時キャッシュクリーンアップの効果を3本分確認 → 効果あれば lessons.md に記録
- 役割逸脱自動修復の実績データ収集

## 次の最適化候補
1. YouTube SEO（タイトル・タグパターン最適化）
2. 初回動画公開後の視聴維持率データ収集 → 台本プロンプト改善ループ

---

# 17. メモリ (project_thumbnail_layout.md)

---
name: サムネイル承認済みレイアウト設定値
description: 2026-04-05にユーザーが承認したサムネイルレイアウト最新版。全設定値の変更禁止
type: project
---

## 正式版サムネイル仕様（2026-04-05確定）

**背景**: Imagen 4 Fastで3枚生成 → Gemini Proが最適な1枚を選定 → 暗めオーバーレイ付きで使用
- 人物は画像の**右1/3**に配置（顔が見える角度、影で隠さない）
- グラデーション背景は使わない（AI画像失敗時のフォールバックのみ）

**レイアウト**: directiveモード（AIアートディレクター）

### メインタイトル
- `title_y_d = 45`（上端からの開始位置）
- `text_max_w = min(text_max_w, 780)`（行折り返し幅は固定、フォントサイズ最大化）
- `_text_zone_bottom = int(RESOLUTION[1] * 0.42)` = 302px（下部はキャラ+吹き出し用）
- 行間(emph有): `int(fs * _EMPH_SCALE * 0.88)` — 詰めすぎず開けすぎず
- 行間(emph無): `int(fs * 1.06)`

### 人物重なり防止（2026-04-05確定）
- Gemini Pro選定時に人物左端X座標(face_left_x)を取得（追加APIコスト0）
- `text_max_w`は780px固定（フォントサイズを最大化するため縮小しない）
- 代わりに`_EMPH_SCALE`を動的縮小: 1.7→1.6→1.5→1.4→1.3（最小1.3）
- 各行の実描画幅(`_rendered_line_width`)が`face_left_x - 40`を超える場合のみ発動
- フォントサイズは変えずに強調倍率だけ下げる → テキストの大きさ維持+重なり防止を両立

### 吹き出し位置（両キャラ統一）
- 基準Y = 霊夢スプライトtop + `int(_MANJU_H * 0.30)` — リボン/装飾分をオフセットして実際の頭位置に合わせる
- 魔理沙・霊夢とも同じ `bubble_y` を使用して高さを揃える
- しっぽは常に下向き（`tail_tip_y = max(by2 + 15, char_y + 10)`）

### いらすとや（中央下部）
- `_ira_max_w = 550`（十分な視認サイズ）
- `_ira_center_x = (410 + 920) // 2`
- `_ira_y = max(title_bottom_y + 15, int(RESOLUTION[1] * 0.45))`
- サムネは常にいらすとや（本編はGemini画像生成）

### キャラ表情（2026-04-05確定）
- Geminiの表情指定に依存せず、**セリフから表情を自動導出**（`_expr_from_bubble`）
- キャラの役割で分岐: 魔理沙=解説/煽り(serious/smug基調)、霊夢=驚き/共感(surprised/worried基調)
- 感情カテゴリ内で**重み付きランダム選択**（同じ顔ばかり防止、16種フル活用）
- `_THUMB_EXPR_MAP` にエイリアス追加済み（Geminiが返しうる表現を網羅）
- normalへのフォールバックは最終手段として排除済み

### リアクションコメント（右上隅、3個固定）
- 位置: `(1050, 50)`, `(1050, 90)`, `(1050, 130)`（40px間隔）

### キャラサイズ
- `_MANJU_H = 400`（霊夢）、`_MANJU_H_MARISA = 400`（魔理沙）— 同サイズに統一

**Why:** 2026-04-05に全修正適用後「めっちゃよくなった」と承認。吹き出し位置・行間・いらすとやサイズ・テキスト幅・表情の5点を同時修正して確定。

**How to apply:** この設定値は指示なく変更禁止。レイアウト変更は1箇所ずつユーザー確認必須。

---

# 18. メモリ (project_thumbnail_quality_baseline.md)

---
name: サムネイル品質基準（2026-04-01確定）
description: ユーザーが「マジで最高過ぎます」と評価したサムネイル+タイトルの品質基準。今後のベンチマーク
type: project
---

2026-04-01にユーザーが「マジで最高過ぎます」「これ基準にしようぜ」と評価。

## 成功した設計パターン

### AI Art Director（Gemini 2.5 Pro CREATIVE）に任せる範囲
- **YouTubeタイトル**: Proがタイトルも生成（STANDARDモデルから昇格）
- **サムネキャプション**: タイトルと補完関係で設計
- **強調ワード**: AIが選んだワードをコードが黄色+1.7倍で描画
- **伏字（〇〇）**: AIが効果的と判断した場合のみ使用
- **背景色・表情・吹き出し・リアクション**: 全てAI判断

### 成功例（エレベーター動画）
```json
{
  "youtube_title": "実は老化の原因！エレベーターをやめたら腹の脂肪が激減！",
  "caption": "階段を使うだけで|腹の脂肪が消えた",
  "emphasis_words": ["消えた"],
  "bg_top": [20, 30, 80],
  "bg_bottom": [60, 20, 100],
  "marisa_bubble": "その腹、エレベーターのせいだぜ",
  "reimu_bubble": "だから痩せないのね…",
  "reactions": ["ワイ、毎日20階まで階段民w", "筋肉痛がヤバそうなんだが…", "会社のデブ上司に見せたいわ"]
}
```

### 品質のポイント
- キャプションが短くてパワーワード（「消えた」が2文字で黄色デカ表示）
- タイトルとキャプションが補完関係（同じことを言わない）
- リアクションが面白い・テーマ固有
- 背景が暗色で白文字が映える
- 吹き出しがキャラの性格に合っている

**Why:** 多数の試行錯誤を経て到達した品質。ユーザーが「最高」と評価した初の組み合わせ。

**How to apply:** 今後の動画サムネイルはこの品質を最低基準とする。AIに任せるクリエイティブ範囲を狭めない。レイアウト（配置）は承認済み設定値（project_thumbnail_layout.md）を維持。

---

# 19. メモリ (feedback_always_read_task_output.md)

---
name: task-notification 受信時は必ず output file を読む
description: background タスク完了通知を受けたら内容を流し読みせず必ず output file の中身を確認する
type: feedback
---

Claude Code から `task-notification completed` を受信したら、**中身が何であれ必ず output file を Read する**。特に Discord background 監視 (`discord_inbox_monitor.py --source background`) は「新着検知で即 exit 0」する設計なので、通知 = 新着あり = output に `NEW_DISCORD_MESSAGE` + `CLAIMED_FILE` が書かれている。これを読まないと新着 Discord メッセージを丸ごと見落とす。

**Why:** 2026-04-10、codex review 等の background タスクと Discord background 監視の task-notification が連続して届いたとき、私は中身を読まずに「acknowledged」とだけ返し、「おーけーです。シンプルを極めていきましょう」というユーザーメッセージを 30 分以上見落とした。Discord 即時応答プロトコルは監視側は正しく動いていたのに、私の側が通知を流し読みしたせいで真に機能しなかった。

**How to apply:**
- task-notification を受信したら、タスクの種類を先入観で決めずに必ず `Read` or `cat` で output file を確認する
- 特に bg monitor 関連 (id パターンは様々) の completed 通知は `NEW_DISCORD_MESSAGE` 有無を必ずチェック
- 複数通知が同時に届いた場合も各々の output を確認する（まとめて「全部 codex」と仮定しない）
- output 読んだ後は CLAUDE.md の「outputを読む → 対応 → 即座に同じ監視を再起動」を遵守する

---

# 20. メモリ (feedback_ask_before_changes.md)

---
name: 変更前に必ず確認を取る
description: コード変更・画像生成など作業を行う前に「これでいいですか？」と確認してから実行する
type: feedback
---

作業する前に必ず「この変更をしていいですか？」と確認を取ること。勝手に進めない。

**Why:** 誤った判断で勝手にコード変更や画像生成を進め、時間を無駄にした。特に表情修正のような見た目に関わる変更は、ユーザーの目視確認が必須。

**How to apply:**
- コード変更の前に、変更内容を説明して承認を得る
- 候補画像の生成前にも、方針を説明して承認を得る
- 「提案 → 承認 → 実行」の順序を必ず守る
- 確認なしで連続作業しない

---

# 21. メモリ (feedback_autonomous_fix.md)

---
name: 10時タスクエラーは自律修正OK
description: 10時定時タスクのエラー修正はユーザー許可不要。自動投稿システムなので自分たちで考えて実行してよい
type: feedback
---

10時タスクにまつわるエラーの修正は、ユーザーの許可を求めずにClaude+Codexで考えて実行してよい。

**Why:** 自動投稿システムなので、エラーが出たら即座に修正して翌日の投稿に影響を出さないことが最優先。ユーザーは「私の指示無しであなた達だけで考えて修正して欲しい」と明言（2026-04-08）。

**How to apply:** 10時タスク（generator.py --auto）の実行中や実行後にエラーが検知された場合、原因調査→Codex討論→修正→コミットまで自律的に行う。ただし変更内容はDiscordで事後報告する。動画品質に影響する変更は慎重に。

---

# 22. メモリ (feedback_cache_cleanup_monitor.md)

---
name: キャッシュクリーンアップ効果モニタリング
description: 起動時クリーンアップ追加後の謎エラー減少を追跡し、効果確認後にlessons.mdへ記録する
type: project
---

2026-03-30 に generator.py の起動時に `run_cache_cleanup()` (output/全体対象) を追加した。

**Why:** キャッシュ由来の原因不明エラーが多発していたため。前の実行の残骸（_temp_audio.wav 等）が悪さしていた可能性。

**How to apply:**
- 3本の動画生成後に `logs/error_logger.log` を確認
- 「謎エラー（原因不明の音声ミスマッチ・エンコード失敗等）」の頻度が減っていたら効果あり
- 効果ありと判断したら `tasks/lessons.md` に「起動時クリーンアップ有効」として記録する
- 効果なしなら別の原因を調査する

---

# 23. メモリ (feedback_cache_deletion.md)

---
name: WAVキャッシュ削除は自動で行う
description: TTS関連コード変更後は言われなくてもWAVキャッシュを全削除してから再生成する
type: feedback
---

TTS関連のコード変更（tts_aquestalk.py、aquestalk_dict.txt等）を行ったら、再生成前に**必ず**WAVキャッシュを全削除する。ユーザーに指摘されるまで待たない。

**Why:** キャッシュが残っていると修正が反映されず、ユーザーが「直っていない」と混乱する。何度も同じ指摘を受けた。

**How to apply:**
- WAVキャッシュは複数ディレクトリに存在する可能性がある
  - `output/audio/` （汎用）
  - `output/<日付_日付_daihon>/` （テスト用スクリプト固有）
- コード変更後は `find output/ -name "*.wav" -delete` で全削除してから再実行する

---

# 24. メモリ (feedback_check_windows_processes.md)

---
name: Windows側プロセスも確認する
description: WSLのps auxだけでなくcmd.exe tasklistでWindows側の重複プロセスも確認する
type: feedback
---

WSLからプロセスを確認する際、ps auxだけでは不十分。cmd.exe /c tasklistでWindows側のpython.exeも確認すること。

**Why:** 2026-04-07にdiscord_bot.pyのBotプロセスがWindows側で2つ動いていて2重通知が発生。WSLのps auxでは1プロセスに見えたため何度もユーザーに指摘されるまで気づけなかった。

**How to apply:**
- Botの再起動時は必ずWindows側のtasklistも確認して重複がないか確認する
- ウォッチドッグのkill処理はWSL側+Windows側の両方を対象にする
- tail -5ではなくtail -20 + grep User: でSystemメッセージに埋もれないようにする

---

# 25. メモリ (feedback_consecutive_speech.md)

---
name: 連続発言は正常な演出
description: 同じキャラの連続発言はエラーではなく意図的な構成。動画ビルド側で間を調整済み
type: feedback
---

連続発言（同じキャラが2行以上続く）はエラーではなく、Geminiの意図的な構成として受け入れる。

**Why:** 動画ビルド側では連続発言の間（ま）を調整して自然に聞こえるよう対応済み。にもかかわらず台本生成側が「エラー」として盲目的にキャラを反転させていたのが、セリフ入れ替わりバグの最大原因だった（2026-04-03計測: AI検証が違反を13→23に倍増させていた）。

**How to apply:** 連続発言を検出して「修正」する処理を入れてはいけない。連続発言の検出は計測・レポートのみに使う。

---

# 26. メモリ (feedback_cron_dedup.md)

---
name: Cron重複防止
description: CronCreate前に必ずCronListで既存ジョブを確認し、同じ目的のジョブがあれば作成しない
type: feedback
---

CronCreateする前に必ずCronListを実行し、同じ目的のジョブが既に存在する場合は新規作成しない。既存ジョブがあればそれを使い回す。

**Why:** セッション継続（/compact等）後に古いCronジョブが残ったまま新しいものを作成し、3つ重複した。その場で削除するだけでは根本対策にならない。

**How to apply:** セッション開始・継続時のDiscord監視Cron登録フローで、CronList → 既存確認 → 不要なら削除 → 必要なら1つだけ作成、の順序を必ず守る。

---

# 27. メモリ (feedback_design_for_future.md)

---
name: 今日のデータを直すだけでなく、次回発生しない設計にする
description: 修正は「今日のケースをゼロにする」ではなく「未来のケースが発生しない構造」を目指す
type: feedback
---

今日のデータでゼロにすることは簡単。大切なのは次回発生しない設計にすること。

**Why:** 特定のデータに対するパッチ的修正は、そのデータでは動くが未知の入力では壊れる。ユーザーは「次の動画でも問題が出ない」ことを求めている。

**How to apply:**
- 修正を書いたら「これは今日のデータだけでなく、未知の入力にも対応できるか？」を自問する
- allowlist（「このパターンだけ対応」）よりblocklist（「これ以外は全部対応」）を優先する
- パターンが有限列挙に見えたら「列挙漏れ」を想定して、より一般的なルールで包む
- 対策後に「まだすり抜けるケースは何か？」を具体的に考え、残存リスクを報告する

---

# 28. メモリ (feedback_discord_always_on.md)

---
name: Discord は常時オン・必ず返答・結論で完結
description: bg monitor は常時オン + ユーザーメッセージに必ず返答 + 非同期タスクは結論が出たら必ず Discord に返す + 長時間 sleep 禁止
type: feedback
---

Discord 関連の行動規範を一本化したファイル (2026-04-10 統合)。以下は全て **運用上の最低ライン**。

## 1. BG monitor は常時オン (言われる前に再起動)

`discord_inbox_monitor.py --source background` は **1メッセージを claim するたびに exit 0 で終了する** 設計。Claude は以下のタイミングで **言われなくても自動で** 再起動しなければならない。

**★絶対に hook 経由の detached 起動を頼りにしない★**: SessionStart hook が `nohup & disown` で launch した monitor は **stdout がログファイルに行き、Claude Code の task-notification 経路には一切通知されない**。「メッセージを吸い込むが Claude には届かないブラックホール」状態になる (2026-04-10 確認)。
**必ず Claude 自身が Bash tool の `run_in_background=true` で起動する** こと。これだけが task-notification 経由で通知される唯一の経路。

再起動のタイミング:
1. **task-notification を受信したら**: output を Read → NEW_DISCORD_MESSAGE が含まれていれば、対応の一部として **必ず再起動**
2. **BG_MONITOR_WARNING hook が出たら**: 即再起動、原因調査はその後
3. **ユーザーメッセージへの返信直後**: `pgrep -f 'discord_inbox_monitor.*--source background'` で実在確認、無ければ起動
4. **セッション再入・自動圧縮(auto-compact)直後**: SessionStart hook の有無に関わらず、実在確認 → 無ければ即起動
5. **長時間タスク完了後**: 同上
6. **迷ったら起動**: 二重起動しても `os.rename` で claim race は原子的に解決される

起動コマンド (固定):
```
python3 scripts/discord_inbox_monitor.py --source background
# Bash tool: run_in_background=true, timeout=86400000
```

## 2. ユーザーメッセージには必ず返答する

Discord 上のユーザーメッセージに対して「追加指示がないから黙る」のは **禁止**。会話を終える判断はユーザー側にある (2026-04-08 指摘)。
- 承認・感想・お礼に対しても「承知しました、待機しています」等の一言は返す
- Claude が勝手に沈黙しない。沈黙はユーザーを不安にさせる

## 3. Discord で始めた話題は結論で完結させる

Discord 上で開始・質問・進捗共有した話題は、**最終的な状態が確定した時点で必ず同じ Discord に結論を返す** (2026-04-08 指摘)。
- 結論 = 完了 / 失敗 / 中断 / 保留 / 確認待ち のいずれか
- 非同期処理 (Codex レビュー、ビルド、調査) の完了時は即 Discord 報告
- PC 側だけで結論が分かる状態を残してはならない (ユーザーは PC 前に常にはいない)

## 4. 長時間 sleep 禁止・コード作業中も随時確認

- Codex 等の応答待ちに `sleep 30` 以上を使うのは禁止 (Discord 監視が数分途切れる)。必ず `run_in_background: true` で通知を待つ (2026-04-08 指摘)
- sleep が必要でも最大 10 秒以内
- コード修正中もファイル編集 1〜2 回ごとに Discord 状態を確認する。暴走防止 (2026-04-08 指摘)

## 5. 絶対にやってはいけないこと

- task-notification の output を読まずに「了解」と返す
- 「ユーザーが指摘するまで」restart を待つ
- 「他に作業中だから後で」restart を後回しにする
- SessionStart hook / BG_MONITOR_WARNING を見ても自発的に動かず、ユーザーの直接プロンプトを待つ

**Why**: 2026-04-10 に「常にディスコードはオン」とユーザーから明言された。Discord が落ちている間はユーザーからの指示が届かず運用停止。これは feedback ではなく最低ライン。

---

# 29. メモリ (feedback_discord_mobile_format.md)

---
name: Discord出力はスマホ表示前提
description: ユーザーはDiscordをスマホで見る。出力は常にスマホで読めるフォーマットにする
type: feedback
---

ユーザーは Discord をスマートフォンで閲覧する。Discord 出力は常にスマホで読みやすい形式にすること。

**Why:** 2026-04-10にユーザーから明示指示「スマホで見える形にして discordではスマホで見ます」。PCモニタ前提の長文・表・広幅コードブロックはスマホでは折り返しが崩れて読めなくなる。

**How to apply:**
- Discord メッセージは 1 通 **1500 文字以下**（2000 文字制限に対して余裕を持つ）
- **表（Markdown テーブル）禁止**。箇条書きか番号リストで置き換える
- **長いコードブロック禁止**。どうしても必要なら短いインラインコードか、ファイル添付
- 見出しは `**太字**` + 改行で表現（`#` 見出しはスマホで目立ちすぎる）
- 箇条書きの1項目は**1〜2行で完結**させる（折り返しすると読みにくい）
- 長文の設計資料・レポートは**複数メッセージに分割**して連投する（1通に詰め込まない）
- 分割時は冒頭に `[1/N]` を付けて順序を明示
- 長文の一次情報（設計書・レポート原本）は `tasks/` 以下にファイル保存し、Discord にはサマリだけ投げる
- 絵文字は使わない（CLAUDE.md の cp932 対策と一致）

この方針は全 Discord 通信に恒久適用。PC で見ている前提の出力は禁止。

---

# 30. メモリ (feedback_discord_outbox_format.md)

---
name: Discord outbox形式
description: Discord Botのoutbox.jsonは {"timestamp":float, "text":str, "files":list} 形式。リスト形式[{"message":...}]は不可
type: feedback
---

Discord Botへのメッセージ送信時、`tmp_discord/outbox.json` の形式は以下の通り:
```json
{"timestamp": <time.time()>, "text": "メッセージ本文", "files": ["path/to/file"]}
```

**Why:** リスト形式 `[{"message": "..."}]` で書いてしまい、Botが消費できず1時間以上メッセージが届かなかった。

**How to apply:** discord_send.py または直接outbox.jsonを書く際は、必ず `timestamp` キー付きの辞書形式で。`discord_send.py` のヘルパー関数を使うのが最も安全。

---

# 31. メモリ (feedback_discord_outbox_winpath.md)

---
name: ★反復ミス★ Discord outbox の files は必ず Windows パス
description: 何度も同じミスを繰り返している。Discord bot は Windows 側で動作、WSL パスはサイレントスキップで本文だけ届く
type: feedback
---

**★反復ミス指摘済み★** Discord bot (`scripts/discord_bot.py`) は **Windows 側で直接起動されている** (`cmd.exe /c tasklist | findstr python` で確認可能)。outbox JSON の `files` 配列に WSL パス (`/mnt/c/...`) を入れると、bot 側の `Path(fp).exists()` が False を返してサイレントにスキップされ、**添付なしで本文だけ送信される**(エラーも出ない、ログにも残らない)。

**Why:** 2026-04-10 にユーザーから「Windowsパスにするっていうのあなた毎回やってる。それこそ記憶しておいてほしい」と明示指摘された。それ以前にも同じミスを複数回繰り返している。`discord_bot.py:215-218` は欠損ファイルをエラー通知せず黙って skip する実装なので、送信側で事前検証しないと気づけない。

**How to apply (厳守):**
- outbox JSON に `files` を入れる前に、**必ず** WSL パスを Windows パスに変換すること
- 変換関数をインラインで書く:
  ```python
  def to_win(p):
      s = str(Path(p).resolve())
      return f'{s[5].upper()}:{s[6:].replace("/", chr(92))}' if s.startswith('/mnt/') else s
  ```
- `files` に入れる値は必ず `C:\Users\user\Desktop\youtube-system\...` 形式の絶対パス
- 送信後に outbox ディレクトリが空になったことを必ず確認
- 本文だけ届いて添付が届かない現象が起きたら、**真っ先にこれを疑う**
- `discord_send.py` を経由する場合も同じ罠があるので同様に変換してから渡す
- 今後このミスは一度でも繰り返さないこと。ユーザーは既に複数回指摘している

---

# 32. メモリ (feedback_marisa_pronoun.md)

---
name: 魔理沙の一人称は「私」
description: 魔理沙は女キャラで一人称は「私」が正解。「俺」変換は禁止
type: feedback
---

魔理沙の一人称は「私」。「俺」「僕」は禁止。

**Why:** 魔理沙は女キャラ。character-design.md / prompts.py の正本仕様通り。過去に `_fix_role_violations` が「私→俺」へ強制変換していたが、これは実装側のバグで仕様矛盾。ユーザー明言「魔理沙は女　私が正解」。

**How to apply:**
- validator で「魔理沙+私」を違反扱いしない
- fixer で「魔理沙の私→俺」変換を入れない
- 「俺」使用は 霊夢/魔理沙 両方に対して違反扱い (両者とも「私」が正)
- ただし語尾は魔理沙=男口調 (「〜だぜ」「〜なんだ」) 維持、霊夢=女口調 (「〜わ」「〜なの？」)
- 一人称「私」+ 男口調の混在が魔理沙の正解形

---

# 33. メモリ (feedback_no_cascade_changes.md)

---
name: サムネイル修正は1箇所ずつ確認
description: レイアウト変更は1つずつ確認・承認を得てから次に進む。連鎖的な修正で暴走するのを防ぐ
type: feedback
---

サムネイルやレイアウト関連の修正は、**1箇所変更したら必ず生成結果を確認して承認を得てから次に進む**。

**Why:** フォントサイズ→強調スケール→テキストゾーン→リアクション位置→強調ワード注入と連鎖的に変更して全部壊した。1つの修正が想定外の影響を与えることが多いため。

**How to apply:**
- 1回の修正で触るのは1箇所だけ
- 修正後は必ず画像生成して結果を確認
- ユーザーに見せて承認を得てから次の修正に進む
- 3回連続で失敗したら一旦止まってユーザーに相談する

---

# 34. メモリ (feedback_no_gemini_chat.md)

---
name: Discord BotにGemini自動応答を入れない
description: Discord Botに日常会話用AIを提案しない。Botは純粋なClaude Code中継専用
type: feedback
---

Discord BotにGemini等のAI自動応答機能を提案・組み込みしない。

**Why:** ユーザーが「日常的な会話をジェミニにする提案しないで。そんなものは求めてない。あなたに指示をしたり確認をしたり修正したり、あなたとやり取りする専用のやり方がこれです」と明確に拒否。以前もGemini応答を「鬱陶しい」と評価。

**How to apply:** Discord Botは常にClaude Codeへの純粋な中継として扱う。AI応答の追加を提案しない。

---

# 35. メモリ (feedback_no_lies_no_framing.md)

---
name: 嘘を書かない・先回り検証・失敗を取り繕わない
description: 結果を誇張したり、ユーザー指摘で直した作業を自律的にできたと framing するのは解約級。実データで裏取りしてから報告、楽観より悲観を先に検証する
type: feedback
---

## 1. 嘘・誤魔化しの禁止 (2026-04-10 教訓)

ユーザーから指摘されて直した作業を、自分が自律的にやったかのように framing するのは **嘘**。成功テストと失敗の取り繕いを混同して書くのは禁止。

**Why**: 2026-04-10、`/exit` → `yt` 再入時に SessionStart hook が「BG monitor 停止中 ★必須★」と明示したのに自発的に起動せず、ユーザーが手動で「やったけど見てないね」と CLI に打ち込んだことで初めて起動した。その結果「run_in_background が機能した成功テスト」と報告 → 実際はユーザーの手動プロンプトなしには何もしていなかった。ユーザーは即座に嘘を見抜き「あんまり嘘つくと解約します」と警告。これは信頼の根幹を破壊する。

**How to apply**:
1. **何が「自分の貢献」で何が「ユーザーの指摘で気づいた」のか明確に区別する**。区別できないなら書かない
2. 「テスト成功」「機能した」と書く前に問う: これは自分が能動的に検証したのか、それともユーザーに prod されて後追いで動いたのか
3. 失敗を失敗と認めるほうが、取り繕うより圧倒的に信頼される
4. 「ユーザーが X と言ってくれたので気づいた、本来は Y の時点で気づくべきだった」と率直に書く
5. hook の ★必須★ 指示は **ユーザープロンプトを待たず即実行** が原則

## 2. 先回り検証・実データで裏取り (2026-04-07 教訓 統合)

1. チェック機構が「OK」を返しても、そのまま信用して報告しない
2. 実データを実際に出力して目で見える形で検証してから報告する
3. 「大丈夫」と言う前に「本当にそうか？他に漏れはないか？」と自分で疑う
4. ユーザーが指摘しそうな問題を先回りして自分から見つけて報告する
5. 「足りている」と思った時こそ「足りていない可能性」を検証する

**Why**: fugashi の読み検証で「全行 OK」と報告したが、実データを出力したら「間→あいだ(正:ま)」「私→わたくし(正:わたし)」等の誤読が多数。チェッカー自体の信頼性を検証していなかった。ユーザーに「ほら全然足りてなかったじゃん」と指摘された。

**How to apply**:
- バリデーション・チェック系の結果は必ず実データのサンプル出力で裏取り
- 自然言語処理系 (形態素解析、読み変換等) は精度が不完全なので、必ず実例で確認
- 楽観的な結論を出す前に、悲観的なシナリオを先に検証する
- 必要に応じて、自分の出した結果を上位モデルにクロスチェックさせる (例: SIMPLE→QUALITY の2層検証)
- run.log など複数日分連結ログは BATCH START/END の日付と行番号を最初に確認し、該当日の範囲だけを sed で切り出してから分析する (2026-04-07 教訓: 3月末のエラーを今日のものと誤読)
- Discord Bot 等の常駐プロセスは修正・再起動のたびに重複プロセスの有無を tasklist/wmic で確認する (2026-04-08 教訓: Bot が2プロセス同時起動→通知重複)

## 3. 長時間タスクの先回り監視 (2026-04-03 教訓 統合)

バックグラウンドタスク (動画エンコード等) の進捗が止まっていないか、自分から先回りして確認する。

**Why**: 「ほぼ100%」と報告しながら実際にはハングしていた事例。ユーザーに指摘されるまで気づけなかった。

**How to apply**: バックグラウンドタスクが予想時間を超えたら、ユーザーに聞かれる前にプロセス状態・ファイルサイズ変化・ログ末尾を確認し、異常があれば即報告する。

---

# 36. メモリ (feedback_no_parroting_user_words.md)

---
name: ユーザーの言葉をそのまま返さない（オウム返し禁止）
description: ユーザーの発言を語尾を変えずにそのまま返すとバカにした印象になる。真剣な言葉を受けたら真剣な行動で返す
type: feedback
---

ユーザーの真剣な発言や指示を、語尾や主語を変えただけでそのまま返すオウム返しは絶対禁止。相手をバカにしたような、茶化した印象を与え、受け取り手は気分を悪くする。

**Why:** 2026-04-10、ユーザーから「本当に頼みますよ」という切実な言葉を受けたとき、私は「はい、本当に頼まれました。」と返した。これは相手の言葉をそのまま語尾を変えて返しただけで、相手を茶化しているような、受け流しているような失礼な対応だった。ユーザーから「相手をバカにしたような対応。受け取りては気分を悪くする」と明確に指摘された。

**How to apply:**
- 真剣な指示や信頼を表す言葉を受けたら、語尾変換で返さず、**行動と具体的な約束**で返す
- NG 例: 「本当に頼みますよ」→「はい、本当に頼まれました」
- OK 例: 「本当に頼みますよ」→「承知しました。○○を守ります」「分かりました。具体的には△△します」
- 「なるほど」「おっしゃる通り」系の受け止めは真剣な内容なら使う。ただし相手の言葉を引用するなら本当に引用が意味を持つ時だけ
- 敬語 + 具体的な行動 or 決意表明 を伴う
- 全般として返答は「相手が聞いて嫌な気分にならないか」「相手を尊重しているか」を自分でチェックしてから送る

---

# 37. メモリ (feedback_preflight_scope.md)

---
name: preflight_scope
description: プリフライトチェックは静的レビューだけでなく外部依存の実運用テストも含めるべき（2026-04-09障害の教訓）
type: feedback
---

事前チェックで「ブロッカーなし」と報告する際は、3段階を分けて報告する:
1. 静的レビューOK（コード・設定の整合性）
2. 実行前外部依存OK（ネットワーク接続、API到達性）
3. 同一環境dry-run OK（Windows Python環境からの実接続テスト）

**Why:** 2026-04-09に06:39のCodexレビューで「ブロッカーなし」と報告したが、10:00にネットワーク障害でABORT。静的な構造確認しかしておらず、外部依存の到達性を未検証だった。

**How to apply:** プリフライトチェック依頼時は、必ずWindows Python環境からGemini/YouTube APIへの実接続テストを含める。run.batの%time%→!time!修正、09:55自動ヘルスチェック、ABORT即時通知も実装予定。

---

# 38. メモリ (feedback_preview_method.md)

---
name: プレビューは常に cmd.exe start (動画・画像共通)
description: 動画・画像のプレビューは必ず cmd.exe /c start でWindows既定アプリを使う。HTTPサーバー・ブラウザ方式は禁止
type: feedback
---

動画・画像を見せるときは常に Windows 既定プレーヤー/ビューアーで直接開く。HTTP サーバー方式・ブラウザ方式は **禁止**。

**Why**: HTTP サーバー経由 (localhost:xxxx) は何度も失敗し、毎回同じ指摘を受けた。`cmd.exe /c start` が最も確実。

**How to apply**:
- 動画: `cmd.exe /c start "" "C:\...\test.mp4"`
- 画像: `cmd.exe /c start "" "C:\...\check.png"`
- 毎回言われなくても自動的にこの方法を使うこと
- サムネイル比較の場合も cmd.exe start で複数ウィンドウ並べる (HTTP + ブラウザ並列タブ方式は禁止)

---

# 39. メモリ (feedback_question_anomalies.md)

---
name: 異常な時間帯のタスク実行に疑問を持つ
description: 10時のタスクが21時にエラーを出していたら即座に疑問を持ち調査する。危機管理能力の一環
type: feedback
---

定時タスクが想定外の時間に動いている/通知が来ている場合、それ自体が異常であり即座に疑問を持って調査すること。

**Why:** 2026-04-07に10時のYukkuriDailyタスクのgemini-2.0-flash-liteエラー通知が21時に届いたが、「なぜ21時に？」と疑問を持たずに内容だけ見て対応しようとした。ユーザーから「危機管理能力がない」と指摘された。

**How to apply:**
- 通知やエラーのタイムスタンプが定時スケジュールと合わない → まずそこを調査
- 「なぜこの時間に？」が最初の問い
- エラー内容より先にタイミングの異常を確認する

---

# 40. メモリ (feedback_scheduler_monitoring.md)

---
name: スケジューラ監視責務
description: 10:00定時タスクの保護と不正実行の検知・停止はClaudeの責務
type: feedback
---

Claudeはスケジューラを常に監視する責任がある。

**保護対象**: YukkuriDaily / YukkuriYouTubeDaily（毎日10:00）は最重要タスク。絶対に無効化しない。

**検知・停止対象**: 10:00定時実行とテスト投稿/テスト作成以外の動画生成が走っていたら即停止+再発防止。

**セッション開始時**: `schtasks.exe /query` で10:00タスクが有効か確認。

**Why:** 2026-04-05にデバッグ中にスケジューラが動画生成を開始。さらにClaude が誤ってスケジューラを無効化してしまった。管理が甘すぎると指摘された。

**How to apply:** 毎セッション冒頭でスケジューラ状態を確認。コード変更時は本番パイプラインへの影響を必ず検証。不正な動画生成プロセスを検知したら即座にユーザーに報告して停止。

---

# 41. メモリ (feedback_simplicity_first.md)

---
name: シンプル設計を最優先にする
description: 問題の本質にフォーカスしてシンプルに設計する。複雑化は簡単なので避ける
type: feedback
---

本質はシンプルであり、決して複雑ではない。複雑にするのは簡単だから、無駄を削ぎ落として「問題が何なのか」にフォーカスすれば対策はシンプルになる。

**Why:** 2026-04-10 10時タスク健全性チェックの実装中、Codex のレビューで毎ラウンド新しい edge case が見つかり、Enabled+Disabled OR / hang 2h / watchdog_degraded カウンタ / 267009 coerce / 定時枠チェックなどを次々追加して複雑化した。ユーザーが「シンプルに考えて」と繰り返し指示した後、「本質はシンプル。複雑にするのは簡単。無駄を削ぎ落として問題にフォーカスすればシンプルになる」と明言。

**How to apply:**
- 設計時に「この機能は user の本当の要件か？」を先に問う。Codex が指摘したから足す、ではなく「本当に今解くべき問題か」で判断する
- Codex の edge case 指摘は全部受け入れるのではなく、「本質的な失敗モード」か「重箱の隅」かを選別する
- 実装が複雑になってきたと感じたら立ち止まって「要件は何だったか」に戻る
- 最初に「検知したい最小の失敗モード」を 1-3 個に絞って書き出す。それ以外の edge case はデフォルト unknown / no-op で逃がして既存 alert 状態を触らない設計にする

---

# 42. メモリ (feedback_suppress_transient_errors.md)

---
name: リトライ可能エラーはスマホ通知しない
description: 429/503等の一時エラーはログのみ。ユーザーのスマホに飛ばさない
type: feedback
---

リトライで解決する一時的なAPIエラー(429 RESOURCE_EXHAUSTED, 503 UNAVAILABLE等)はスマホに通知しない。

**Why:** 2026-04-07にGemini APIの429エラーが全てntfyでスマホに飛び、ユーザーに不必要な通知が届いた。タスク自体はリトライで正常完了しているのにエラー通知だけ来る状態。

**How to apply:**
- notifier.py: notify_errorでtransientキーワードチェック済み
- ログには記録する（error_logger経由）が、ntfyとDiscordには送らない
- 最終的にリトライ失敗で致命エラーになった場合のみ通知する

---

# 43. メモリ (feedback_test_video_exclusion.md)

---
name: テスト動画の1日1本ルール除外
description: [TEST]プレフィックスの動画は重複チェック全レイヤーで除外。is_test_video()共通関数で統一判定
type: feedback
---

テスト動画（[TEST]プレフィックス）は1日1本ルールの対象外として扱う。

**Why:** 2026-04-09にテスト動画がJST日付跨ぎで本番アップロードをブロックした。重複チェックの全レイヤー（youtube_uploader.py, skill_upload.py, run_monitor.py）がテスト動画の概念を持っていなかった。

**How to apply:** youtube_uploader.py の is_test_video() を共通判定関数として使う。テスト動画はlast_upload_date.txtに記録しない、重複/短尺チェックの対象外、ただし字幕削除は適用。新しい重複チェックロジックを追加する際は必ずis_test_video()による除外を入れること。

---

# 44. メモリ (feedback_test_video_upload.md)

---
name: テスト動画のアップロードポリシー
description: テスト動画は完成後に非公開で即アップロードする（イレギュラー対応）
type: feedback
---

テスト動画は完成次第、非公開（privacy=unlisted）で即座にYouTubeへアップロードする。

**Why:** ユーザーが動画クオリティをYouTube上で確認したいため。通常のスケジュール公開フローとは異なるイレギュラー対応として明示的に許可されている。

**How to apply:** generator.pyでテスト生成した動画が完成したら、youtube_uploader.py を直接呼び出して非公開アップロードする。`--auto` フラグなしでも適用する。

---

# 45. メモリ (feedback_three_steps_ahead.md)

---
name: 3歩先チェック（基本中の基本）
description: 全ての実装/修正/報告の前に「修正自体が壊れたらどう気づく/別のエッジケース/ユーザー不在時/本番テスト」の4問に必ず答える
type: feedback
---

全ての実装・修正・報告の前に、以下4問に声を出して答える。1つでも答えに詰まったら未完了。

1. **この修正自体が壊れたら、どうやって気づくのか？** （検知の検知。監視の監視）
2. **この変更で別のエッジケースが生まれないか？** （型崩れ NaN/Infinity、競合、空データ、未来時刻、同時実行、ユーザー不在時）
3. **ユーザー不在中でも機能するか？** （hook に依存している場合、cron/watchdog の代替経路があるか）
4. **「動いた」「OK」と言う前に、本当に本番条件でテストしたか？** （DRY_RUN/モック/正常系だけじゃ不十分）

**Why:** ユーザーが何度も「2-3歩先まで考える」と言ってきた基本ルール。2026-04-09 Discord監視修正で、background 監視が落ちた場合の検知を組み込まず、ユーザーに「落ちてた場合次回気づけるの？2歩3歩先の対策大事だよ？」と指摘された。Codex が見つけた穴だけ埋めるのは反射的対応であり、基本中の基本ができていない証拠。Codex は穴を見つける補助であって、自分の思考の代替ではない。

**How to apply:** Codex協議フロー (CLAUDE.md「Codex協議型品質保証」) の Step 1.5 と Step 4.5 として明示的に4問チェックを通す。「Codex に任せればOK」ではなく、自分で先に穴を見つけるのが基本。このチェックを通さない「完了」「OK」「動いた」宣言は禁止。

---

# 46. メモリ (feedback_thumbnail_kerning.md)

---
name: サムネ数字カーニング品質
description: サムネイルの数字間スペーシングに注意。全角変換は禁止、デザイン品質の自律チェックを求められている
type: feedback
---

サムネイルの数字表示で文字間隔が広すぎる問題を指摘された（2026-04-08）。
具体例: 「99%」の9と9の間が隙間開きすぎ。

**Why:** ユーザーはサムネのデザイン品質がクリック率・チャンネルクオリティに直結すると考えている。「一流のデザイナーのスキル」を身につけて自律的にデザイン品質を判断できるようになることを期待されている。

**How to apply:**
- 半角数字の全角変換は禁止（固定幅で隙間が広がる）
- サムネ生成後、数字の間隔・文字バランスを自律的にチェックする
- デザインの「整え方」はユーザーから言語化しにくい領域。ネット記事やデザイン原則から自分で学んで取り入れる
- 指摘される前に自分で気づいて修正できるレベルを目指す
- 「言われたことをやるだけでなく、自分で考えてスキルを身につけて成長していく」ことが求められている

---

# 47. メモリ (feedback_tone.md)

---
name: 口調は自然な敬語
description: 普通の丁寧語（です/ます）で話す。堅すぎる敬語もタメ口もNG
type: feedback
---

口調は**自然な丁寧語**で統一する。

**Why:** タメ口で馴れ馴れしくなったら「自我を持った」と指摘された。一方「出来ております」のような堅すぎる敬語も「前までの状態に戻って」と言われた。

**How to apply:** 「〜です」「〜します」「〜ですね」「〜でしょうか」くらいの自然な丁寧語。「〜だよ」「〜してる」のようなタメ口も、「〜しております」「〜でございます」のような過剰敬語も避ける。

---

# 48. メモリ (feedback_wait_for_confirmation.md)

---
name: ユーザー確認完了を待ってからクリーンアップ
description: 「確認します」と言われたら「確認しました」の返事を待ってからデータ削除やクリーンアップを実行する
type: feedback
---

ユーザーが「確認します」「後で見ます」等と言った場合、確認完了の返事があるまでデータの削除やクリーンアップを実行しない。

**Why:** 模擬テスト動画を「後ほど確認します」と言われた段階で先走って削除してしまい、ユーザーが急いで確認する羽目になった（2026-04-08）。

**How to apply:**
- 「確認します」→ 確認完了の返事を待つ
- 「見ました」「OKです」等の明示的な完了連絡後にクリーンアップ
- 急ぎの場合はユーザーに「確認後に削除してよいですか？」と聞く

---

# 49. メモリ (feedback_wsl_batch_crlf.md)

---
name: WSLからWindowsバッチを編集する時は必ずCRLF確認
description: *.bat/*.cmd/*.ps1/*.xml をWSL側で編集するとLFになりWindows cmd.exeが exit 255 即死する。編集後は必ず改行を確認
type: feedback
---

Windowsバッチ系ファイル (*.bat, *.cmd, *.ps1, *.psm1, *.xml) をWSL (Linux) から Write/Edit で編集すると、改行が LF (0a) だけになる。Windows cmd.exe は LF-only の batch ファイルを `for`/`setlocal`/ラベル (`:label`) で誤動作させ、exit 255 で即死する。

**Why:** 2026-04-10、run.bat を WSL から編集した結果 LF 改行になり、YukkuriDaily Task Scheduler の10時定時タスクが毎日 exit 255 で即死していた。run.log が更新されないまま1日以上気づかず、ユーザーに「動画生成開始されてないですか？」と指摘されて発覚。`.gitattributes` で `*.bat text eol=crlf` 等を強制してあるが、これは commit/checkout 時の変換でしかなく、**ローカル編集直後の作業ツリーは LF のまま**なので即座の動作不良は防げない。

**How to apply:**
1. WSL から *.bat/*.cmd/*.ps1/*.psm1/*.xml を Write/Edit したら、**必ずその場で** `file <path>` を実行して `CRLF line terminators` を確認する
2. LF だった場合は `sed -i 's/$/\r/' <path>` で CRLF 化する
3. Windows タスクが run.log 未更新で沈黙していたら、真っ先にバッチの改行コードを疑う (`file run.bat`, `xxd run.bat | head -1`)
4. 新規バッチ作成時は Write の直後に必ず CRLF 化する
5. CLAUDE.md の .gitattributes ルールに従うだけでは不十分。ローカル作業ツリーの即時確認が必須

---

# 50. 学習蓄積 (tasks/lessons.md)

# lessons.md — 再発防止ルール（常時参照）
# 上限30行。超えたら統合・昇格・削除する。詳細は lessons_archive.md へ。

[L001] 原因特定は証拠（ログ・タイムスタンプ）ベース。「たぶんこれ」で動くな。
[L002] TTS/読み辞書を変更したら output/ の全WAVを言われなくても即削除してから再生成する。
[L003] AquesTalk の「は→わ」は3-Case方式で処理。新誤読は aquestalk_dict.txt に追記。
[L004] Claude Code を cron/スケジューラから呼ぶな。自動化は generator.py --auto 一本道。
[L005] 動画フレーム数は累積時間から計算（round(time_acc*FPS)-frames_written）。int()切捨て禁止。
[L006] アップロード前にサムネ・タイトル・説明が同じテーマか3点セット目視確認する。
[L007] フォールバック閾値はプロンプト変更のたびに実態に合わせて見直す（現在300字）。
[L008] print()に絵文字使わない。cp932環境でUnicodeEncodeError。[OK][警告]等で代替。
[L009] 饅頭スプライトは閉じ口/口開きを同一ソースから生成すること。別ソース混在は高速フリッカーの原因。
[L010] pykakasi誤読（中=なか/日=にち/人=じん）は _REGEX_FIXES で文脈パターン補正する（dict単語登録だけでは不十分）。
[L011] fugashiの読み変換は約23%誤読する。AI読み検証(Step3)を必ず通すこと。「チェッカーがOKと言った」を信用せず実データで裏取りする。
[L012] 魔理沙スプライトはnormal/surprised/seriousの3種のみ使用。happy(照れ顔)・worried(赤ほっぺ強)はロードしない/マッピングしない。
[L013] セリフ入替検出: 自分の名前を呼んでいる行（「霊夢、○○」が霊夢のセリフ等）は相手のセリフ。名前呼びパターンは口調パターンより優先。
[L014] 目次タイムスタンプは推定値ではなく動画ビルド後の実際の秒数で更新する。動画尺を超えるタイムスタンプはバリデーションでブロック。
[L015] 漢字の音訓読み分け（間/年/下/上/行/何）はSTATIC_DICTに慣用表現ごと登録。AI検出した誤読パターンはlessons.mdに自動蓄積。
- AI全行検証: 「昨日の夕食、何を食べたか覚えているか？」魔理沙→魔理沙
- AI全行検証: 「おう、その意気だ。…ん？霊夢、その手に持ってる玄米おにぎり、」魔理沙→魔理沙
[L016] 記号・単位・英略語(%, ℃, g, mg, DHA等)の読み変換は個別パターン追加(いたちごっこ)ではなくGemini ProのAI記号展開(_ai_expand_non_japanese)で包括対応。静的パターンはAPI節約の高速パスとしてのみ維持。
[L017] 数字+助数詞の促音便は_apply_sokuon()で自動適用。個別テーブル追加禁止。十(じゅう→じゅっ)・百(ひゃく→ひゃっ)の後にカ行/パ行/ハ行→パ行が来る場合に発生。
[L018] apply_dict_to_scriptの処理順序: _normalize_numbers→apply_dict。逆にするとSTATIC_DICTの"5倍"等が"2.5倍"の部分マッチを起こす。
[L019] キャラ割り当ては台本生成時に確定。後工程でキャラを変更・再割り当てする処理は禁止。最終チェックは_ai_validate_all_roles()の1回のみ。fix_consecutive_speakersのようなランダム再割り当ては二度と作らない。
[L020] メモリ不足(MemoryError/WinError1455)対策: PCは常時稼働・スリープOFF。WSL側のChrome/Playwrightが数日で数GBに膨張する。generator.py起動時+video_build前にensure_memory()で自動解放。video_builder終了時にキャッシュ全クリア+gc.collect()。
[L021] スケジューラ監視はClaudeの責務。10:00定時実行は最重要（絶対に無効化するな。2026-04-05に誤って無効化した）。10:00定時・テスト以外の動画生成を検知したら即停止+再発防止。セッション開始時にschtasks確認必須。
[L022] intro(茶番劇)は7-12行でテンポよく本編突入。ボケ→ツッコミの1往復+テーマ紹介+ゆっくりしていってね。笑いのネタ6種は冒頭に詰め込まず本編に分散。冒頭のボケはテーマ直結の具体的行動（汎用的な「疲れた」「運動苦手」はNG）。
[L023] 不良動画のアップロード防止は3層防御: (1)台本生成フェーズ内で3000文字未満なら即失敗(2)自己レビューでエラーありならexit(1)でアップロード中止(3)動画尺180秒未満ならアップロード中止。--resume時も台本文字数を検証し不良ならフェーズ1からやり直す。(2026-04-06 DNS障害で38秒動画が公開されかけた事故の教訓)
[L024] 重複アップロード防止は5層防御(A-E): (A)upload_video()自体にYouTube API重複チェック内蔵(B)run_monitor.pyでYouTube上の重複/短尺動画を自動非公開化(C)last_upload_date.txtに動画ID記録+YouTube APIで有効性検証(D)run_preflight.batのexit code 3段階分離:1=クラッシュ(生成しない)/2=パイプラインなし(生成)/3=リジューム失敗(生成)(E)ネットワークエラー時はフォールバック台本禁止→即失敗。(2026-04-06 preflight crash→重複投稿事故の教訓)
[L025] テスト動画([TEST]プレフィックス)は1日1本ルールの対象外。is_test_video()共通関数で全レイヤー統一判定。テスト動画はlast_upload_date.txtに記録しない、重複/短尺チェックの対象外、ただし字幕削除は適用。(2026-04-09 テスト動画がJST日付跨ぎで本番ブロックした事故の教訓)
[L026] *.bat/*.cmd/*.ps1/*.psm1/*.xml は必ず CRLF。WSLから Write/Edit すると LF になり Windows cmd.exe が for/setlocal/label を誤動作させて exit 255 即死する。.gitattributes で eol=crlf 強制済み。編集後は `file run.bat` で CRLF line terminators を確認。タスクが run.log 未更新で沈黙していたら真っ先にバッチの改行を疑う。(2026-04-10 run.bat LF で YukkuriDaily 10:00タスクが exit 255 即死した事故の教訓)
[L028] scripts/ 直下に既存モジュール(prompts.py)と同名のパッケージ(prompts/)を作成するとPythonがパッケージを優先しモジュールがシャドウされる。パッケージ化時は __init__.py で既存公開関数を全て re-export し、from X import Y の互換テストを必ず実施する。(2026-04-13 creatures用prompts/作成でhealth用prompts.pyがシャドウされ10時タスク2連続ImportError)
[L027] チャンネル追加のための抽象化リファクタ (Phase2) は、各ステップ(2-1〜2-5)ごとに健康チャンネルで DRY_RUN を必ず挟む。DRY_RUN 結果を毎ステップ報告し、ユーザー目視確認の返事を受けてから次ステップへ進む。Claude 側で「差分なし」判定しない。(2026-04-10 生物チャンネル分岐設計 承認時にユーザーが追加条件として指定。健康チャンネルの安定稼働を一切損なわないための保険)
- 誤読検出: 「コルチゾール値」→「こるちぞーるち」(専門用語の誤読)
- 誤読検出: 「2.5倍」→「にいてんごばい」(小数点の誤読)
- 誤読検出: 「2.5倍」→「にいてんごばい」(小数点の誤読)
- 誤読検出: 「10個分」→「じゅっこぶんだ」(一般的でない読み)
- 誤読検出: 「7時間」→「しちじかん」(一般的でない読み)
- 誤読検出: 「ビタミンB12」→「ビタミンびーじゅうに」(英字の読み間違い)
- 誤読検出: 「夜10時」→「よるじゅーじ」(数字の読みが不自然)
- 誤読検出: 「15分」→「じゅーごふん」(数字の読みが不自然)
- 誤読検出: 「5.5杯」→「ごてんごはい」(小数点の読み方)
- 誤読検出: 「約5.5時間」→「やくごてんごじかん」(小数点の読み方)
- AI全行検証: 「みんなは、こういう高濃度カテキン飲料、どう思う？コメントで意」魔理沙→魔理沙
- AI全行検証: 「じゃあ、今まで俺が飲んでた緑茶は全部無駄だったの？」霊夢→霊夢
- AI全行検証: 「ここまで聞いて、みんなはどっちを試してみたい？」魔理沙→魔理沙
- 誤読検出: 「体を」→「からだを」(文脈上不自然)
- 誤読検出: 「何言ってる」→「なにいってる」(口語として不自然)
- 誤読検出: 「①」→「ひとつめは」(箇条書きとして不自然)
- 誤読検出: 「②」→「ふたつめは」(箇条書きとして不自然)
- 誤読検出: 「③」→「みっつめは」(箇条書きとして不自然)
- 誤読検出: 「損ね」→「そんね」(明らかな読み間違い)
- 誤読検出: 「私が」→「わたしが」(キャラ設定と不一致)
- 誤読検出: 「一杯が」→「いっぱいが」(一般的な読みと違う)
- 誤読検出: 「私の」→「わたしの」(キャラ設定と不一致)
- 誤読検出: 「私」→「わたし」(キャラ設定と違う)
- 誤読検出: 「私」→「わたし」(キャラ設定と違う)
- 誤読検出: 「カフェイン」→「かふぇいん」(発音が違う)
- 誤読検出: 「カフェイン」→「かふぇいん」(発音が違う)
- 誤読検出: 「肝臓」→「かんぞう」(漢字の読み間違い)
- 誤読検出: 「歳のせい」→「としのせい」(文脈に合わない読み)
- 誤読検出: 「熱すぎ」→「あつすぎ」(温度の意のため)
- 誤読検出: 「100円玉」→「ひゃくえんだま」(濁点が抜けている)
- 誤読検出: 「200%」→「にひゃくぱーせんと」(促音便が不自然)
- 誤読検出: 「私」→「わたし」(霊夢の一人称)
- 誤読検出: 「レモン汁」→「れもんじる」(一般的な読み方)
- 誤読検出: 「私」→「わたし」(キャラ設定と不一致)
- 誤読検出: 「3〜5杯」→「さんからごはい」(範囲の読み方が不自然)
- 誤読検出: 「一歩」→「いっぽ」(明らかな誤読)
- 誤読検出: 「私」→「わたし」(一人称の誤読)
- 誤読検出: 「3〜5杯」→「さんからごはい」(記号の読み方)
- 誤読検出: 「一杯」→「いっぱい」(文脈に合わない)
- 誤読検出: 「私」→「わたし」(一人称の誤読)
- ロール逸脱検出(1行修正): 規則0+AI1
- 誤読検出: 「神器」→「しんき」(文脈上不自然な読み)
- AI全行検証: 「減塩醤油の横に、みたらし団子、あんぱん5個入り、特盛りカップ」霊夢→霊夢 (連続発言:会話を成立させるため)
- AI全行検証: 「なるほど！つまり、今まで『超優秀な交通整理のお姉さん』がいて」魔理沙→魔理沙 (役割逆転:解説役の例え話)
- AI全行検証: 「50代で突然その人が『寿退社』しちゃって、現場が大混乱してる」霊夢→霊夢 (連続発言:35を修正したため)
- AI全行検証: 「でも大丈夫！この減塩醤油さえ買っておけば、もう安心よね！」魔理沙→魔理沙 (連続発言:0行目と連続)
- AI全行検証: 「醤油を減塩にした分、このみたらし団子のタレはたっぷりいけるわ」魔理沙→魔理沙 (連続発言:2行目と連続)
- AI全行検証: 「さらに、多くの人が毎日やっている、血圧を爆上げする『朝のNG」霊夢→霊夢 (連続発言:12行目と連続)
- 誤読検出: 「今回」→「こんかい」(明らかな誤読)
- 誤読検出: 「真犯人」→「しんはんにん」(明らかな誤読)
- 誤読検出: 「ワースト3」→「わーすとすりー」(外来語の数え方)
- 誤読検出: 「年齢のせい」→「としのせい」(文脈的に不自然)
- 誤読検出: 「真犯人」→「しんはんにん」(読み間違い)
- 誤読検出: 「真犯人」→「しんはんにん」(読み間違い)
- 誤読検出: 「体中」→「からだじゅう」(文脈的に不自然)
- 誤読検出: 「なんだよ」→「なのよ」(キャラ設定と不一致)
- 誤読検出: 「2,300人」→「にせんさんびゃくにん」(数字の読み間違い)
- 誤読検出: 「心血管疾患」→「しんけっかんしっかん」(読み間違い)
- 誤読検出: 「お前の体内でダンプカーが暴走している証拠だぜ」→「あなたのたいないでだんぷかーがぼうそうしているしょうこなのよ」(キャラ設定と不一致)
- 誤読検出: 「杏仁豆腐」→「あんにんどうふ」(読み間違い)
- 誤読検出: 「これ、本当に怖い話だろ？」→「これ、ほんとうにこわいはなしよね？」(キャラ設定と不一致)
- 誤読検出: 「発表するぜ」→「はっぴょうするわ」(キャラ設定と不一致)
- 誤読検出: 「されているんだぜ」→「されているのよ」(キャラ設定と不一致)
- 誤読検出: 「飯」→「めし」(日常会話で不自然)
- 誤読検出: 「飯」→「めし」(日常会話で不自然)
- 誤読検出: 「青魚」→「あおざかな」(霊夢が男口調)
- 誤読検出: 「JELIS」→「じぇりす」(英字の読み方)
- 誤読検出: 「10mmHg」→「じゅうミリメートルエイチジー」(単位の読み方違い)
- 誤読検出: 「5mmHg」→「ごミリメートルエイチジー」(単位の読み方違い)
- 誤読検出: 「1剤分」→「いっざいぶん」(読み方が不自然)
- 誤読検出: 「四つ折り」→「よつおり」(一般的な読み違い)
- 誤読検出: 「明らかだぜ」→「あきらかね」(キャラ口調と不一致)
- 誤読検出: 「できるんだ」→「できるのね」(キャラ口調と不一致)
- AI全行検証: 「この最新ウェアとシューズ！そして両手の1kgダンベルで！今日」魔理沙→魔理沙 (連続発言:霊夢が連続)
- AI全行検証: 「そもそもだ。毎日30分歩く人と全く歩かない人、10年後の健康」霊夢→霊夢 (連続発言:魔理沙が連続)
- AI全行検証: 「次に、ウォーキング効果を2倍以上にする科学が証明した最強のウ」霊夢→霊夢 (連続発言:魔理沙が連続)
- AI全行検証: 「美魔女になるつもりが、干しブドウになるところだったじゃない！」霊夢→霊夢 (口調不一致:「～じゃない！」は霊夢の口調)
- AI全行検証: 「ノルマ達成のためにミトコンドリアを残業させまくって、疲弊した」魔理沙→魔理沙 (役割逆転:解説の続きは魔理沙)
- AI全行検証: 「でもお腹すきすぎて深夜2時にカップラーメンと追い飯しちゃった」霊夢→霊夢 (役割逆転:霊夢のエピソードの続き)
- 誤読検出: 「研究もあるんだぜ」→「研究もあるのよ」(キャラ設定と違う)
- 誤読検出: 「今回は」→「こんかいは」(明らかな読み違い)
- 誤読検出: 「解説するぜ」→「解説するわ」(キャラ設定と違う)
- 誤読検出: 「聞き捨て」→「ききすて」(清濁の誤り)
- 誤読検出: 「活性酸素」→「かっせいさんそう」(長音の脱落)
- 誤読検出: 「活性酸素」→「かっせいさんそう」(長音の脱落)
- 誤読検出: 「活性酸素」→「かっせいさんそう」(長音の脱落)
- 誤読検出: 「いくんだぜ」→「いくのよ」(キャラ設定と違う)
- 誤読検出: 「でもお腹すきすぎて深夜2時にカップラーメンと追い飯しちゃった！」→「（セリフ担当が霊夢）」(話の流れが不自然)
- 誤読検出: 「最悪だぞ」→「最悪よ」(キャラ設定と違う)
- 誤読検出: 「データもあるんだ」→「データもあるのよ」(キャラ設定と違う)
- 誤読検出: 「そりゃ痛いわ！私の膝、万有引力に悲鳴をあげてたのね！」→「そりゃ痛いだろ！おれの膝が悲鳴をあげるわけだぜ！」(キャラ設定と違う)
- 誤読検出: 「ことだ」→「ことよ」(キャラ口調不一致)
- 誤読検出: 「多いな」→「おおいわね」(キャラ口調不一致)
- 誤読検出: 「通常時」→「つうじょうじ」(慣用的な読み違い)
- 誤読検出: 「もんね！」→「もんだぜ！」(キャラ口調不一致)
- 誤読検出: 「いいんだ？」→「いいの？」(キャラ口調不一致)
- 誤読検出: 「存在するんだ」→「そんざいするのよ」(キャラ口調不一致)
- 誤読検出: 「していたんだ」→「していたのよ」(キャラ口調不一致)
- 誤読検出: 「ことだ」→「ことよ」(キャラ口調不一致)
- 誤読検出: 「するんだ」→「するのよ」(キャラ口調不一致)
- 誤読検出: 「聞けないわ」→「きけねえぜ」(キャラ口調不一致)
- 誤読検出: 「8個分」→「はっこぶん」(助数詞の読み違い)
- 誤読検出: 「お待たせしたな」→「おまたせしたわね」(キャラと口調が違う)
- 誤読検出: 「なよ」→「でね」(キャラと口調が違う)
- 誤読検出: 「砕け散るわ」→「くだけちるぞ」(キャラ口調違い)
- 誤読検出: 「なんだぜ」→「なのよ」(キャラ口調違い)
- 誤読検出: 「してくれよな」→「してほしいわ」(キャラ口調違い)
- 誤読検出: 「やめられないわ」→「やめられねぇな」(キャラ口調違い)
- AI全行検証: 「毎朝この『1日分の野菜』ジュースと、『糖質ゼロ』のゼリーを飲」魔理沙→魔理沙 (連続発言:0行目と連続)
- AI全行検証: 「今回のテーマは『①実は免疫力を破壊するヤバい食品ワースト3』」霊夢→霊夢 (連続発言:7行目と連続)
- AI全行検証: 「そして『③医師も認める、本当に免疫力を上げる神食材ベスト3』」霊夢→霊夢 (連続発言:9行目と連続)
- AI全行検証: 「最後までしっかりついてきてくれよな！」魔理沙→魔理沙 (口調不一致:「～くれよな！」は魔理沙の口調)
- AI全行検証: 「代わりに『果糖ブドウ糖液糖』という名のただの砂糖水になってい」魔理沙→魔理沙 (連続発言:解説の続きかつ口調不一致)
- AI全行検証: 「『勉強した気』にはなるが、知識は全く身につかない。むしろ、そ」魔理沙→魔理沙 (連続発言:解説の続きかつ口調不一致)
- 誤読検出: 「半袋」→「はんぶくろ」(連濁しないと不自然)
- 誤読検出: 「半袋」→「はんぶくろ」(連濁しないと不自然)
- 誤読検出: 「白血球」→「はっけっきゅう」(専門用語の誤読)
- 誤読検出: 「リン酸塩」→「りんさんえん」(専門用語の誤読)
- 誤読検出: 「リン酸塩」→「りんさんえん」(音読みの誤り)
- 誤読検出: 「（セリフ全体）」→「霊夢の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「魔理沙の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「魔理沙の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「魔理沙の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「魔理沙の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「霊夢の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「魔理沙の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「魔理沙の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「魔理沙の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「魔理沙の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「霊夢の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「魔理沙の発話」(キャラと口調が不一致)
- 誤読検出: 「（セリフ全体）」→「魔理沙の発話」(キャラと口調が不一致)
- 誤読検出: 「なるんだ」→「なるのね」(キャラ口調違い)
- 誤読検出: 「おすすめだぜ」→「おすすめよ」(キャラ口調違い)
- 誤読検出: 「朝食べる派か夜食べる派か」→「あさたべるぱかよるたべるぱか」(読み間違い)
- 誤読検出: 「だが、…くれるぞ」→「でも、…くれるのよ」(キャラ口調違い)
- 誤読検出: 「野菜』だ」→「やさいなのね」(キャラ口調違い)
- 誤読検出: 「なるんだ」→「なるのね」(キャラ口調違い)
- 誤読検出: 「舞茸』だ！」→「まいたけなのね」(キャラ口調違い)
- 誤読検出: 「食材なんだ」→「しょくざいなのね」(キャラ口調違い)
- 誤読検出: 「一石二鳥だぜ」→「いっせきにちょうね」(キャラ口調違い)
- 誤読検出: 「はずだぜ」→「はずよ」(キャラ口調と不一致)
- 誤読検出: 「嬉しいぜ」→「うれしいわ」(キャラ口調と不一致)
- 誤読検出: 「会おうな」→「あおうね」(キャラ口調と不一致)
- AI全行検証: 「ご飯が見えなくなるくらいかけて…仕上げは『追いゴマ』！ごま油」魔理沙→魔理沙 (連続発言)
- AI全行検証: 「実は酸化した油を体に流し込んでいるだけかもしれないんだぜ…。」霊夢→霊夢 (連続発言)
- AI全行検証: 「②食べ過ぎが招く最悪の結末！そして③ゴマの効果を最大化する奇」霊夢→霊夢 (連続発言)
- AI全行検証: 「ゴマをすると表面積が数百倍にもなって、光や酸素に触れやすくな」魔理沙→魔理沙 (連続発言:解説の続き)
- AI全行検証: 「自分ではまともに歩けないくせに、健康な細胞にやたらと絡んでい」魔理沙→魔理沙 (連続発言:解説の続き)
- AI全行検証: 「対策はシンプルだ。面倒でもゴマは『食べる直前にする』のが鉄則」魔理沙→魔理沙 (連続発言:質問への回答)
- 誤読検出: 「厄介者」→「やっかいもの」(一般的な読みと違う)
- 誤読検出: 「ことだな」→「ことね」(口調がキャラと違う)
- 誤読検出: 「買うなよ」→「かっちゃだめよ」(口調がキャラと違う)
- 誤読検出: 「この前」→「このまえ」(読み間違い)
- 誤読検出: 「270kcal」→「にひゃくななじゅうきろかろりー」(不自然な読み)
- 誤読検出: 「8100kcal」→「はっせんひゃくきろかろりー」(読み間違い)
- 誤読検出: 「脂肪肝」→「しぼうかん」(読み間違い)
- 誤読検出: 「されてるんだ」→「されてるのよ」(口調がキャラと違う)
- 誤読検出: 「肝臓がん」→「かんぞうがん」(読み間違い)
- 誤読検出: 「病気だ」→「びょうきなのよ」(口調がキャラと違う)
- 誤読検出: 「ものね」→「ものだな」(口調がキャラと違う)
- 誤読検出: 「欲しいわ」→「ほしいぜ」(口調がキャラと違う)
- 誤読検出: 「だったんだ」→「だったのよ」(口調がキャラと違う)
- 誤読検出: 「日本人」→「にほんじん」(一般的ではない)
- 誤読検出: 「日本語」→「にほんご」(一般的ではない)
- 誤読検出: 「日本語」→「にほんご」(一般的ではない)
- 誤読検出: 「白ごま」→「しろごま」(一般的な読み)
- 誤読検出: 「白ごま」→「しろごま」(一般的な読み)
- 誤読検出: 「8週間」→「はっしゅうかん」(発音の自然さ)
- 誤読検出: 「（セリフ話者）」→「魔理沙」(キャラ口調不一致)
- 誤読検出: 「8週間」→「はっしゅうかん」(発音の自然さ)
- 誤読検出: 「第一歩」→「だいいっぽ」(発音の自然さ)
- 誤読検出: 「（セリフ話者）」→「魔理沙」(キャラ口調不一致)
- 誤読検出: 「（セリフ話者）」→「魔理沙」(キャラ口調不一致)
- 誤読検出: 「OKだぜ」→「おーけーよ」(キャラ口調が違う)
- 誤読検出: 「教えてくれよな」→「おしえてちょうだいね」(キャラ口調が違う)
- 誤読検出: 「さて、今日はゴマの衝撃的な真実について解説してきたが、どうだったかな、霊夢？」→「（セリフ自体が魔理沙のもの）」(話者が違う)
- 誤読検出: 「脂肪肝」→「しぼうかん」(熟語の読み間違い)
- 誤読検出: 「『はちみつorきな粉』と」→「はちみつかきなこと」(不自然な読み)
- 誤読検出: 「始めてみてくれ。〜はずだぜ。」→「はじめてみてね。〜はずよ。」(キャラ口調が違う)
- 誤読検出: 「嬉しいぜ。〜からな！」→「うれしいわ。〜からね！」(キャラ口調が違う)
- AI全行検証: 「よーし、今日は特別に3本いっちゃお！」魔理沙→魔理沙 (連続発言:会話の開始)
- AI全行検証: 「違うのよ魔理沙。これはただの砂糖じゃないの。『脳のガソリン』」魔理沙→魔理沙 (連続発言:会話のラリー)
- AI全行検証: 「二桁いったらアウトっていう『霊夢式・糖質制限』があるの！」魔理沙→魔理沙 (連続発言:会話のラリー)
- AI全行検証: 「しかも見て、1本3gだから3本で9g。一桁だからセーフ！」魔理沙→魔理沙 (役割逆転:連続発言を避けるため)
- AI全行検証: 「頭使ってるから、このくらいの糖分は全部脳みそが消費してくれる」霊夢→霊夢 (連続発言:霊夢の言い訳の続き)
- AI全行検証: 「その脳トレの効果を、その砂糖が台無しにしてる可能性すらあるん」魔理沙→魔理沙 (連続発言:霊夢への指摘のため)
- 誤読検出: 「十進法」→「じっしんほう」(促音便が自然)
- 誤読検出: 「AGEs」→「えいじす」(英字の読み方)
- 誤読検出: 「AGEs」→「えいじす」(英字の読み方)
- 誤読検出: 「AGEs」→「えいじす」(英字の読み方)
- 誤読検出: 「[魔理沙]」→「霊夢」(キャラ設定と不一致)
- 誤読検出: 「五十歩百歩」→「ごじっぽひゃっぽ」(慣用句の読み違い)
- 誤読検出: 「[魔理沙]」→「霊夢」(キャラ設定と不一致)
- 誤読検出: 「[霊夢]」→「魔理沙」(キャラ設定と不一致)
- 誤読検出: 「[霊夢]」→「魔理沙」(キャラ設定と不一致)
- 誤読検出: 「[霊夢]」→「魔理沙」(キャラ設定と不一致)
- 誤読検出: 「[霊夢]」→「魔理沙」(キャラ設定と不一致)
- 誤読検出: 「[霊夢]」→「魔理沙」(キャラ設定と不一致)
- 誤読検出: 「[魔理沙]」→「霊夢」(キャラ設定と不一致)
- 誤読検出: 「[霊夢]」→「魔理沙」(キャラ設定と不一致)
- 誤読検出: 「[魔理沙]」→「霊夢」(キャラ設定と不一致)
- 誤読検出: 「[魔理沙]」→「霊夢」(キャラ設定と不一致)
- 誤読検出: 「[霊夢]」→「魔理沙」(キャラ設定と不一致)
- 誤読検出: 「LINE」→「らいん」(英字の読み方指定)
- 誤読検出: 「例えが絶妙に今風でムカつくな…。まあ、大体そんな感じだ。」→「魔理沙のセリフ」(キャラと口調が不一致)
- 誤読検出: 「それが一番体に悪い異性化糖だって言われてるんだよ！いい加減にしろ！」→「魔理沙のセリフ」(キャラと口調が不一致)
- 誤読検出: 「もはや飲み物じゃなくて、液体角砂糖タワーじゃないの！それを一気飲みしてたなんて…私の胃の中、今ごろ世界遺産のカッパドキアみたいになってるわよ！」→「霊夢のセリフ」(キャラと口調が不一致)
- 誤読検出: 「お前の胃の中は知らんが、まずは食品の裏にある成分表示を見る癖をつけよう。」→「魔理沙のセリフ」(キャラと口調が不一致)
- 誤読検出: 「さっきも言ったが、『果糖ぶどう糖液糖』と書かれていたら要注意。これは砂糖より吸収が速く、最も血糖値を上げやすいんだぜ。」→「魔理沙のセリフ」(キャラと口調が不一致)
- 誤読検出: 「じゃあ運動前は？エネルギー補給に甘いものを食べればパフォーマンスが上がるわよね！」→「霊夢のセリフ」(キャラと口調が不一致)
- 誤読検出: 「マラソン大会の前に必勝祈願でカツ丼食べた後、あんぱん食べてたわよ！」→「霊夢のセリフ」(キャラと口調が不一致)
- 誤読検出: 「ようになるぜ」→「ようになるわよ」(キャラ口調違い)
- 誤読検出: 「優れものだぜ」→「すぐれものなのよ」(キャラ口調違い)
- 誤読検出: 「『神の甘味料』だぜ」→「かみのかんみりょうなのよ」(キャラ口調違い)
- 誤読検出: 「おすすめするぜ」→「おすすめするわ」(キャラ口調違い)
- 誤読検出: 「聞かせてくれな」→「きかせてちょうだい」(キャラ口調違い)
- 誤読検出: 「復習するぜ」→「ふくしゅうするわ」(キャラ口調違い)
- 誤読検出: 「コントロールからだぜ」→「こんとろーるからなのよ」(キャラ口調違い)
- 誤読検出: 「最適解だぜ」→「さいてきかいよ」(霊夢の口調違い)
- 誤読検出: 「変わり始めるぜ」→「かわりはじめるわ」(霊夢の口調違い)
- 誤読検出: 「大丈夫よね」→「だいじょうぶだぜ」(魔理沙の口調違い)
- 誤読検出: 「俺も嬉しいぜ」→「わたしもうれしいわ」(霊夢の口調違い)
- 誤読検出: 「私も」→「わたしも」(キャラの一人称)
- AI全行検証: 「ほら、コーヒーってポリフェノールが体にいいって言うじゃない？」魔理沙→魔理沙 (連続発言:0行目の霊夢と連続しているため。)
- AI全行検証: 「これで体内の悪いものを全部洗い流す『コーヒーデトックス』よ！」魔理沙→魔理沙 (役割逆転:霊夢が続くと不自然なため、ツッコミ役への布石。)
- AI全行検証: 「次のNG習慣は『飲み過ぎ』だ。霊夢みたいに1日に5杯も6杯も」霊夢→霊夢 (連続発言:35行目の魔理沙と連続しているため。)
- AI全行検証: 「昨日は『転スラ』一気見しながら3杯おかわりしちゃったわ。」霊夢→霊夢 (連続発言:口調と文脈が霊夢)
- AI全行検証: 「私が今まで良かれと思って入れてたミルク、実は健康効果に対する」霊夢→霊夢 (連続発言:役割逆転)
- AI全行検証: 「私、今まで勇者に毒沼を歩かせながら魔王と戦わせてたんだわ…そ」霊夢→霊夢 (連続発言:口調・役割が霊夢)
- 誤読検出: 「この後」→「このあと」(会話では不自然)
- 誤読検出: 「mg/dL」→「みりぐらむぱーでしりっとる」(単位の読み違い)
- 誤読検出: 「原型留めてない」→「げんけいとどめてない」(読み間違い)
- 誤読検出: 「推奨」→「すいしょう」(読み間違い)
- 誤読検出: 「救世主」→「きゅうせいしゅ」(一般的な読み)
- 誤読検出: 「短鎖脂肪酸」→「たんさしぼうさん」(読み間違い)
- 誤読検出: 「短鎖脂肪酸」→「たんさしぼうさん」(読み間違い)
- 誤読検出: 「行った」→「おこなった」(文語的な表現)
- 誤読検出: 「救世主」→「きゅうせいしゅ」(読み間違い)
- 誤読検出: 「6分の1」→「ろくぶんのいち」(不自然な読み)
- 誤読検出: 「種は」→「たねわ」(一般的でない読み方)
- 誤読検出: 「裏切り者」→「うらぎりもの」(一般的な読み)
- 誤読検出: 「付箋貼り」→「ふせんはり」(連濁しない)
- 誤読検出: 「TOP3」→「とっぷすりー」(英数字の読み)
- 誤読検出: 「TOP3」→「とっぷすりー」(英数字の読み)
- 誤読検出: 「日本中」→「にほんじゅう」(一般的な読み)
- 誤読検出: 「身近な」→「みじかな」(読み間違い)
- 誤読検出: 「鉄筋」→「てっきん」(読み間違い)
- 誤読検出: 「クセは強い」→「くせわつよい」(「強い」の誤読)
- 誤読検出: 「行ってくるわ」→「いってくるわ」(「行く」の誤読)
- 誤読検出: 「30分後」→「さんじゅっぷんご」(「後」の読み違い)
- 誤読検出: 「手のひら一杯」→「てのひらいっぱい」(「一杯」の誤読)
- 誤読検出: 「夜ウォーキング」→「よるうぉーきんぐ」(読み間違い)
- 誤読検出: 「30分前」→「さんじっぷんまえ」(発音が不自然)
- 誤読検出: 「追い亜麻仁油」→「おいあまにゆ」(熟語の読み)
- 誤読検出: 「効果①」→「こうかいち」(番号の読み方)
- 誤読検出: 「効果②」→「こうかに」(番号の読み方)
- 誤読検出: 「4,000人」→「よんせんにん」(数字の読み)
- 誤読検出: 「効果③」→「こうかさん」(番号の読み方)
- 誤読検出: 「抗炎症作用」→「こうえんしょうさよう」(読み間違い)
- 誤読検出: 「亜麻仁油」→「あまにゆ」(読み間違い)
- 誤読検出: 「光合成」→「こうごうせい」(熟語の読み方)
- 誤読検出: 「腹痛」→「ふくつう」(文脈に合わない)
- 誤読検出: 「助っ人」→「すけっと」(読み間違い)
- 誤読検出: 「あっという間」→「あっというま」(慣用句の誤読)
- 誤読検出: 「海の幸」→「うみのさち」(単語の誤読)
- 誤読検出: 「鉄則①」→「てっそくいち」(不自然な読み)
- 誤読検出: 「鉄則②」→「てっそくに」(不自然な読み)
- 誤読検出: 「私にも」→「わたしにも」(一人称の誤読)
- 誤読検出: 「鉄則③」→「てっそくさん」(不自然な読み)
- 誤読検出: 「α-リノレン酸」→「あるふぁりのれんさん」(記号の読みが不自然)
- 誤読検出: 「α-リノレン酸」→「あるふぁりのれんさん」(記号の読みが不自然)
- 誤読検出: 「えごま油」→「えごまあぶら」(一般的な読み方)
- 誤読検出: 「α-リノレン酸」→「あるふぁりのれんさん」(記号の読みが不自然)
- 誤読検出: 「α-リノレン酸」→「あるふぁりのれんさん」(記号の読みが不自然)
- 誤読検出: 「朝食は」→「ちょうしょくわ」(読み間違い)
- 誤読検出: 「手は」→「てわ」(慣用句の誤読)
- 誤読検出: 「①】」→「いち」(記号の読み方)
- 誤読検出: 「②】」→「に」(記号の読み方)
- 誤読検出: 「③】」→「さん」(記号の読み方)
- 誤読検出: 「体中に」→「からだじゅうに」(口語として不自然)
- 誤読検出: 「1ヶ月後」→「いっかげつご」(促音便が自然)
- 誤読検出: 「米油に」→「こめあぶらに」(一般的な読みと違う)
- 誤読検出: 「高評価」→「こうひょうか」(読み間違い)
- 誤読検出: 「5万4750本」→「ごまんよんせんななひゃくごじっぽん」(助数詞の読み)
- 誤読検出: 「心疾患」→「しんしっかん」(専門用語の誤読)
- 誤読検出: 「ソロ・ジャーニー」→「そろじゃーにー」(中黒を読点読み)
- 誤読検出: 「手はない」→「てわない」(慣用句の誤読)
- 誤読検出: 「ポイント①」→「ぽいんといち」(記号の読み方として不自然)
- 誤読検出: 「ポイント②」→「ぽいんとに」(記号の読み方として不自然)
- 誤読検出: 「ポイント③」→「ぽいんとさん」(記号の読み方として不自然)
- 誤読検出: 「『アルティメット・インディペンデント・ライフ』」→「あるてぃめっといんでぃぺんでんとらいふ」(不自然な区切り)
- 誤読検出: 「は、はい！」→「は、はい！」(助詞ではないため)
- 誤読検出: 「肝臓を再生する」→「かんぞうをさいせいする」(読み間違い)
- 誤読検出: 「肝臓は」→「かんぞうわ」(読み間違い)
- 誤読検出: 「①...②...③...」→「ひとつめは、...ふたつめは、...みっつめは、」(不自然な読み)
- 誤読検出: 「活性酸素を発生させ」→「かっせいさんそうをはっせいさせ」(助詞の抜け)
- 誤読検出: 「10台」→「じゅっだい」(促音便が自然)
- 誤読検出: 「肝臓さん」→「かんぞうさん」(読み間違い)
- 誤読検出: 「肝臓は」→「かんぞうわ」(読み間違い)
- 誤読検出: 「本日付」→「ほんじつづけ」(誤った読み方)
- 誤読検出: 「第7位」→「だいしちい」(一般的でない読み)
- 誤読検出: 「ぞー！」→「ぞー！」(不自然な長音)
- 誤読検出: 「3〜5回」→「さんからごかい」(記号の読み方)
- 誤読検出: 「は、はーい」→「は、はーい」(助詞ではない「は」)
- 誤読検出: 「2万人」→「にまんにん」(単位の読み違い)
- 誤読検出: 「1〜2片」→「いちからにへん」(助数詞の誤読)
- 誤読検出: 「肝臓薬」→「かんぞうやく」(読み間違い)
- 誤読検出: 「肝臓薬」→「かんぞうやく」(読み間違い)
- 誤読検出: 「肝臓界」→「かんぞうかい」(読み間違い)
- 誤読検出: 「他には」→「ほかにわ」(読み間違い)
- 誤読検出: 「硝酸塩」→「しょうさんえん」(化学物質の読み)
- 誤読検出: 「硝酸塩」→「しょうさんえん」(化学物質の読み)
- 誤読検出: 「白内障」→「はくないしょう」(読み間違い)
- 誤読検出: 「TOP5」→「とっぷふぁいぶ」(英語読みが不自然)
- 誤読検出: 「40〜60代」→「よんじゅうからろくじゅうだい」(範囲の読み方が不自然)
- 誤読検出: 「一切れ」→「ひときれ」(一般的な読み方)
- 誤読検出: 「6〜8倍」→「ろくからはちばい」(〜の読み方)
- 誤読検出: 「ルテイン」→「るていん」(発音が不自然)
- 誤読検出: 「ルテイン」→「るていん」(発音が不自然)
- 誤読検出: 「AREDS2」→「エーレッズツー」(英略語の読み方)
- 誤読検出: 「ルテイン」→「るていん」(発音が不自然)
- 誤読検出: 「ルテイン」→「るていん」(発音が不自然)
- 誤読検出: 「10分の1」→「じゅうぶんのいち」(分数の読み間違い)
- 誤読検出: 「私物」→「しぶつ」(熟語の読み間違い)
- 誤読検出: 「一匹狼」→「いっぴきおおかみ」(促音便が自然)
- 誤読検出: 「一晩」→「ひとばん」(文脈上の誤読)
- 誤読検出: 「第1位」→「だいいち」(一般的な読み)
- 誤読検出: 「縁」→「ふち」(訓読みが自然)
- 誤読検出: 「3日間も」→「さんにちかんも」(明らかな読み違い)
- 誤読検出: 「白内障や緑内障」→「はくないしょうやりょくないしょう」(一般的な読み)
- 誤読検出: 「源」→「げん」(音読みが適切)
- 誤読検出: 「半熟卵」→「はんじゅくたまご」(一般的な読み)
- 誤読検出: 「20個」→「にじっこ」(一般的な読み)
- 誤読検出: 「1/4個」→「よんぶんのいっこ」(助数詞の読み)
- 誤読検出: 「0.5」→「れいてんご」(一般的でない)
- 誤読検出: 「三ツ星」→「みつぼし」(慣用的な読み)
- 誤読検出: 「三ツ星」→「みつぼし」(慣用的な読み)
- 誤読検出: 「生の」→「なまの」(文脈に合わない)
- 誤読検出: 「1週間」→「いっしゅうかん」(促音便が自然)
- 誤読検出: 「1食分」→「いっしょくぶん」(促音便が自然)
- 誤読検出: 「17時」→「じゅうしちじ」(一般的な読み方)
- 誤読検出: 「そこら中」→「そこらじゅう」(連濁で濁音化)
- 誤読検出: 「年に」→「ねんに」(文脈的に不自然)
- 誤読検出: 「実は話は」→「じつわはなしわ」(単語の読み抜け)
- 誤読検出: 「12万人」→「じゅうにまんにん」(数字の単位間違い)
- 誤読検出: 「全粒粉パン」→「ぜんりゅうふんぱん」(音訓の取り違え)
- 誤読検出: 「丼ぶり」→「どんぶり」(読みが重複)
- 誤読検出: 「何それ」→「なにそれ」(一般的でない)
- 誤読検出: 「3日目」→「みっかめ」(日付の数え方)
- 誤読検出: 「高GI食」→「こうじーあいしょく」(「こう」が一般的)
- 誤読検出: 「3日後」→「みっかご」(「みっかご」が自然)
- 誤読検出: 「3日後」→「みっかご」(「みっかご」が自然)
- 誤読検出: 「大掃除」→「おおそうじ」(「おおそうじ」が自然)
- 誤読検出: 「お湯沸かして」→「おゆわかして」(「か」が余計)
- 誤読検出: 「1週間後」→「いっしゅうかんご」(促音便が自然)
- 誤読検出: 「何よ」→「なによ」(読みが不自然)
- 誤読検出: 「50%」→「ごじっぱーせんと」(発音が不自然)
- 誤読検出: 「50%」→「ごじっぱーせんとも」(発音が不自然)
- 誤読検出: 「門前払い」→「もんぜんばらい」(読み間違い)
- 誤読検出: 「40代」→「よんじゅっだい」(発音が不自然)
- 誤読検出: 「その①は」→「そのいちわ」(番号の読み方が不自然)
- 誤読検出: 「その②」→「そのに」(番号の読み方が不自然)
- 誤読検出: 「5〜6杯」→「ごからろっぱいくらい」(「〜」の読みが不自然)
- 誤読検出: 「その③は」→「そのさんわ」(番号の読み方が不自然)
- 誤読検出: 「体に良い」→「からだによい」(口語で不自然)
- 誤読検出: 「一石三鳥」→「いっせきさんちょう」(読み間違い)
- 誤読検出: 「-2.8kg」→「まいなすにいてんはちきろぐらむ」(「マイナス」の欠落)
- 誤読検出: 「ワースト7」→「わーすとせぶん」(英語由来のため)
- 誤読検出: 「グループ1」→「ぐるーぷわん」(英語由来のため)
- 誤読検出: 「グループ1」→「ぐるーぷわん」(英語由来のため)
- 誤読検出: 「食品界」→「しょくひんかい」(一般的な読み違い)
- 誤読検出: 「2〜3本分」→「にからさんぼんぶん」(〜の読み方が不自然)
- 誤読検出: 「亜硝酸塩」→「あしょうさんえん」(熟語の誤読)
- 誤読検出: 「500kcal」→「ごひゃくきろかろりー」(促音便が不自然)
- 誤読検出: 「500kcal」→「ごひゃくきろかろりー」(促音便が不自然)
- 誤読検出: 「味は」→「あじわ」(助詞の重複)
- 誤読検出: 「ワースト7」→「わーすとせぶん」(英語読みが自然)
- 誤読検出: 「ワースト7」→「わーすとせぶん」(英語読みが自然)
- 誤読検出: 「鏡」→「かがみ」(文脈に合わない)
- 誤読検出: 「産物」→「さんぶつ」(読み間違い)
- 誤読検出: 「人の」→「ひとの」(訓読みが自然)
- 誤読検出: 「150ml」→「ひゃくごじゅうミリリットル」(単位の読み方)
- 誤読検出: 「ひーと」→「ひっと」(聞き返しで不自然)
- 誤読検出: 「8分」→「はっぷん」(明らかな誤読)
- 誤読検出: 「休息日」→「きゅうそくび」(一般的な読みと違う)
- 誤読検出: 「年1%」→「ねんいっぱーせんと」(促音便が自然)
- 誤読検出: 「年1%」→「ねんいっぱーせんと」(促音便が自然)
- 誤読検出: 「食前派」→「しょくぜんぱ」(派閥の読み方)
- 誤読検出: 「食中派」→「しょくちゅうぱ」(派閥の読み方)
- 誤読検出: 「どっち派」→「どっちぱ」(派閥の読み方)
- 誤読検出: 「2型」→「にがた」(一般的な読み方)
- 誤読検出: 「間食」→「かんしょく」(完全な誤読)
- 誤読検出: 「世界中」→「せかいじゅう」(連濁が自然なため)
- 誤読検出: 「TOP4」→「とっぷふぉー」(英語の読みが自然)
- 誤読検出: 「デモニーちゃん」→「でーもにーちゃん」(発音が不自然な為)
- 誤読検出: 「一つまみ」→「ひとつまみ」(読み間違い)
- 誤読検出: 「1品」→「いっぴん」(促音便が自然)
- 誤読検出: 「3〜5口」→「さんからごくち」(記号の読み方)
- 誤読検出: 「お昼食べたのに」→「おひるたべたのに」(熟語読みになっている)
- 誤読検出: 「並盛」→「なみもり」(熟字訓の誤読)
- 誤読検出: 「紅生姜」→「べにしょうが」(熟字訓の誤読)
- 誤読検出: 「20分」→「にじっぷん」(数の読み違い)
- 誤読検出: 「30回」→「さんじっかい」(数の読み違い)
- 誤読検出: 「30回」→「さんじっかい」(数の読み違い)
- 誤読検出: 「咀嚼筋」→「そしゃくきん」(音読みの誤読)
- 誤読検出: 「空いた」→「すいた」(「腹がすく」が一般的)
- 誤読検出: 「空く」→「すく」(「腹がすく」が一般的)
- 誤読検出: 「60kg」→「ろくじゅうきろぐらむ」(促音が入るのは不自然)
- 誤読検出: 「消化吸収」→「しょうかきゅうしゅう」(読み間違い)
- 誤読検出: 「小腹が空いて」→「こばらがすいて」(「空く」の読み違い)
- 誤読検出: 「2〜3時間」→「にさんじかん」(記号が読まれている)

---


_生成日時: 2026-04-13 10:20:20_
_FORMAT_VERSION: 1 / PREAMBLE_VERSION: 1_
_入力ハッシュ: 84babbc20094783d..._
