"""
resynth_and_build.py — AquesTalk2 で音声を再生成し、動画を再ビルドして YouTube にアップロード。

既存のWAVファイル（VOICEVOX等）を削除してAquesTalk2で再生成する。
いらすとや画像付き動画を生成して予約投稿する。

使い方:
    python scripts/resynth_and_build.py <script_json> <audio_dir> [--publish-at "2026-03-24T18:00:00+09:00"]
"""

import argparse
import json
import os
import sys
import time
import random
from pathlib import Path
from datetime import datetime, timezone, timedelta

SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

# .env を読み込む
from dotenv import load_dotenv
load_dotenv(SCRIPTS_DIR.parent / ".env")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("script_json", help="台本JSONファイルのパス")
    parser.add_argument("audio_dir",   help="WAVファイルの出力先ディレクトリ")
    parser.add_argument("--publish-at", default=None,
                        help="予約公開時刻 ISO8601形式 (例: 2026-03-24T18:00:00+09:00)")
    parser.add_argument("--no-upload", action="store_true", help="アップロードをスキップ")
    parser.add_argument("--keep-wav",  action="store_true", help="既存WAVを削除しない（スキップ）")
    args = parser.parse_args()

    script_path = Path(args.script_json)
    audio_dir   = Path(args.audio_dir)

    if not script_path.exists():
        print(f"エラー: 台本JSONが見つかりません: {script_path}")
        sys.exit(1)

    print(f"[フェーズ0] 台本を読み込んでいます: {script_path}")
    script = json.loads(script_path.read_text(encoding="utf-8"))
    title = script.get("youtube_title") or script.get("title", "")
    if not title or title == "動画" or len(title) < 5:
        print(f"エラー: 台本JSONに有効なタイトルがありません (title={title!r})")
        print("  youtube_title または title フィールドを確認してください")
        sys.exit(1)
    print(f"  タイトル: {title}")

    # 既存WAVを削除（VOICEVOX音声を置き換える）
    if not args.keep_wav and audio_dir.exists():
        wavs = list(audio_dir.glob("*.wav"))
        if wavs:
            print(f"[フェーズ1] 既存WAV {len(wavs)} 件を削除しています...")
            for w in wavs:
                w.unlink()
            print("  削除完了")
        else:
            print("[フェーズ1] 既存WAVなし")
    else:
        print("[フェーズ1] --keep-wav 指定のため既存WAVを保持")

    # AquesTalk2 で音声生成
    print("[フェーズ2] AquesTalk2 で音声を生成しています...")
    os.environ["TTS_PROVIDER"] = "aquestalk"
    from tts import generate_audio_from_script
    audio_dir.mkdir(parents=True, exist_ok=True)
    wav_files = generate_audio_from_script(script, audio_dir)
    print(f"  生成完了: {len(wav_files)} ファイル")

    if not wav_files:
        print("エラー: 音声ファイルが生成されませんでした")
        sys.exit(1)

    # 動画を生成（いらすとや画像付き）
    print("[フェーズ3] 動画を生成しています（いらすとや画像付き）...")
    from video_builder import build_video

    video_path = script_path.with_suffix(".mp4")
    # 背景画像を探す（台本JSONのstemに厳密一致するファイルのみ）
    _script_stem = script_path.stem
    _timestamp_prefix = "_".join(_script_stem.split("_")[:2])
    bg_path = None
    # 1) stem_bg.jpg を最優先（正規パイプラインのファイル名）
    _bg_exact = script_path.with_name(f"{_timestamp_prefix}_{script_path.stem.split('_', 2)[-1]}_bg.jpg")
    if _bg_exact.exists():
        bg_path = _bg_exact
    # 2) timestamp一致で_bg.jpg（1候補のみ許可）
    if not bg_path:
        _bg_candidates = list(script_path.parent.glob(f"{_timestamp_prefix}*_bg.jpg"))
        if len(_bg_candidates) == 1:
            bg_path = _bg_candidates[0]
        elif len(_bg_candidates) > 1:
            print(f"警告: 背景画像候補が複数あります: {[p.name for p in _bg_candidates]}")
    if bg_path:
        print(f"  背景画像: {bg_path.name}")
    else:
        print("  背景画像: なし（デフォルト背景を使用）")

    try:
        build_video(script, audio_dir, video_path, bg_path=bg_path)
        print(f"  動画生成完了: {video_path}")
    except Exception as e:
        print(f"[エラー] 動画生成失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    if args.no_upload:
        print("--no-upload 指定のためアップロードをスキップします")
        return

    # アップロード前待機（ボット判定回避）
    wait_sec = random.randint(30, 90)
    print(f"[フェーズ4] アップロード前に {wait_sec} 秒待機しています...")
    time.sleep(wait_sec)

    # 公開時刻
    publish_at = None
    if args.publish_at:
        # ISO8601 パース（python-dateutil があれば使用、なければ手動パース）
        try:
            from dateutil.parser import isoparse
            publish_at = isoparse(args.publish_at)
        except ImportError:
            # 例: "2026-03-24T18:00:00+09:00" → datetime
            s = args.publish_at.replace("Z", "+00:00")
            publish_at = datetime.fromisoformat(s)
        print(f"  予約公開時刻: {publish_at.strftime('%Y-%m-%d %H:%M:%S %Z')}")

    # アップロード前バリデーション
    description = script.get("description", "")
    tags = script.get("tags", [])
    if not description:
        print("エラー: 台本JSONにdescriptionがありません。アップロードを中止します")
        sys.exit(1)

    # サムネイル画像を特定（stem完全一致のみ）
    thumb_path = script_path.with_name(f"{_script_stem}_thumbnail.png")
    if not thumb_path.exists():
        thumb_path = None
    if thumb_path:
        print(f"  サムネイル: {thumb_path.name}")
    else:
        print("  警告: サムネイル画像が見つかりません")

    # YouTube アップロード
    print("[フェーズ5] YouTube にアップロードしています...")
    from youtube_uploader import upload_video

    try:
        url = upload_video(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            publish_at=publish_at,
        )
        print(f"アップロード完了: {url}")

        # サムネイル設定
        if thumb_path:
            video_id = url.split("=")[-1] if "=" in url else url.split("/")[-1]
            from youtube_uploader import _get_youtube_client
            yt = _get_youtube_client()
            yt.thumbnails().set(
                videoId=video_id,
                media_body=str(thumb_path),
            ).execute()
            print(f"  サムネイル設定完了: {thumb_path.name}")
    except Exception as e:
        print(f"[エラー] アップロード失敗: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
