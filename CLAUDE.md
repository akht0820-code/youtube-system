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

> 「考えてから動く」「検証してから完了」「ミスから学ぶ」

## Codex協議型品質保証（必須）

コード変更時は必ずCodexによるレビューを通す。ユーザーの役割は「品質チェッカー」ではなく「最終判断者」。

**実行フロー（コード変更を伴う全タスクで必須）:**
1. Claude Codeが設計案を作成・表示
2. `codex exec` で設計レビュー（隠れた前提・エッジケース・より良いパターン）
3. Codexの指摘に対し反論or受け入れを判断。馴れ合い禁止、本気で穴を突き合う
4. 合意後に実装
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

**セッション開始直後に必ず以下を実行すること（厳命）：**

1. **最優先**: バックグラウンド監視を起動（exit 0方式）:
   ```bash
   LOGFILE="/mnt/c/Users/user/Desktop/youtube-system/tmp_discord/chat.log"
   PREV_SIZE=$(wc -c < "$LOGFILE" 2>/dev/null || echo 0)
   while true; do
     CUR_SIZE=$(wc -c < "$LOGFILE" 2>/dev/null || echo 0)
     if [ "$CUR_SIZE" != "$PREV_SIZE" ]; then
       echo "NEW_DISCORD_MESSAGE"
       tail -5 "$LOGFILE"
       exit 0
     fi
     sleep 2
   done
   # timeout: 600000, run_in_background: true
   ```
   - task-notification受信後 → outputを読む → 対応 → 即座に同じ監視を再起動
2. CronCreateで3分間隔のバックアップ監視を登録（**重複防止必須**）:
   - **まずCronListを実行し、同目的のDiscord監視ジョブが既にあれば作成しない**
   - 既存ジョブがあればそれを使い回す。古い重複があれば1つ残して他をCronDeleteする
   - 新規作成が必要な場合のみ: cron: `*/3 * * * *`, durable: true, recurring: true
   - prompt: `Bashツールで tail -5 /mnt/c/Users/user/Desktop/youtube-system/tmp_discord/chat.log を実行し、末尾5行を確認。ユーザーの新しいメッセージに対応が必要であれば対応する。不要なら何もしない。Readツールは使わずBashのtailで読むこと。`
   - **注意: Readツールはキャッシュで変更を見逃すため絶対に使わない**
3. Discord Botプロセス（`scripts/discord_bot.py`）が動いているか `ps aux | grep discord_bot` で確認
4. 返信は `tmp_discord/outbox.json` に `{"timestamp": <unix_time>, "text": "...", "files": []}` 形式で書く（python3で書き込み）

**この仕組みは絶対に変更禁止。Discordからの指示が届かなくなったら全てが終わる。**

## 詳細リファレンス

- **7ヶ条（全工程必読）: `.claude/commands/seven-rules.md`**
- キャラクター設計: `.claude/commands/character-design.md`
- コーディングルール全文: `.claude/commands/coding-rules.md`
- 6原則+タスク管理: `.claude/commands/workflow-principles.md`
- 再発防止ルール: `tasks/lessons.md`（セッション開始時に必読）
