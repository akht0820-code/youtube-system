# AGENTS.md — ゆっくり健康チャンネル自動生成システム

## プロジェクト概要
ゆっくり解説動画を全自動で生成・投稿するシステム。
テーマ選定 → 台本生成(Gemini) → 音声合成(AquesTalk/VOICEVOX) → 動画生成(ffmpeg) → YouTube投稿(API)

## 技術スタック
- Python 3.11（Windows native）
- Gemini API（台本・画像生成）
- AquesTalk / VOICEVOX（音声合成）
- ffmpeg（動画エンコード）
- YouTube Data API v3（投稿）
- Windows 11 + WSL2環境

## 重要な制約
- **cp932エンコーディング**: Windowsコンソール出力はcp932。print()に絵文字禁止
- **ffmpegコマンド長制限**: Windows CreateProcess上限32768文字。380トラック超えで WinError 206
- **パス変換**: WSL(/mnt/c/...)とWindows(C:\...)のパス変換に注意
- **APIキー管理**: `get_secret("KEY_NAME")`経由。直書き禁止
- **字幕テキスト不変**: `line["text"]`は字幕用で変更禁止。TTS用は`line["synthesis_text"]`

## レビュー時の重点確認事項
1. cp932で壊れる文字列がないか
2. ffmpegコマンド長が肥大化しないか
3. WSL/Windowsパス変換の整合性
4. 一時ファイルのロック/解放
5. Gemini APIのレートリミット対策
6. エラー時のリカバリパス
