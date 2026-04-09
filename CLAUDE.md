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
