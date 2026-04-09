"""
rebuild_video.py — 既存のWAVファイルから動画を再ビルドしてYouTubeにアップロードする。
音声合成は済んでいるが動画生成が失敗した場合のリカバリ用スクリプト。

使い方:
    python scripts/rebuild_video.py <script_json> <audio_dir> [--publish-hours N]
"""

import argparse
import json
import sys
import time
import random
from pathlib import Path
from datetime import datetime, timezone, timedelta

# youtube-system の scripts/ をパスに追加
SCRIPTS_DIR = Path(__file__).parent
sys.path.insert(0, str(SCRIPTS_DIR))

from video_builder import build_video
from youtube_uploader import upload_video
from notifier import notify_start, notify_error


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("script_json", help="台本JSONファイルのパス")
    parser.add_argument("audio_dir", help="WAVファイルが入っているディレクトリ")
    parser.add_argument("--publish-hours", type=int, default=0, help="何時間後に公開するか（0=即時公開）")
    parser.add_argument("--no-upload", action="store_true", help="アップロードをスキップ（動画生成のみ）")
    args = parser.parse_args()

    script_json_path = Path(args.script_json)
    audio_dir = Path(args.audio_dir)

    if not script_json_path.exists():
        print(f"エラー: 台本JSONが見つかりません: {script_json_path}")
        sys.exit(1)
    if not audio_dir.exists():
        print(f"エラー: 音声ディレクトリが見つかりません: {audio_dir}")
        sys.exit(1)

    print(f"台本JSON: {script_json_path}")
    print(f"音声ディレクトリ: {audio_dir}")

    # 台本JSONを読み込む
    with open(script_json_path, encoding="utf-8") as f:
        script = json.load(f)

    title = script.get("youtube_title") or script.get("title", "")
    if not title or title == "動画" or len(title) < 5:
        print(f"エラー: 台本JSONに有効なタイトルがありません (title={title!r})")
        sys.exit(1)
    print(f"タイトル: {title}")

    # 動画出力パス（script_jsonと同じ場所に .mp4 で出力）
    video_path = script_json_path.with_suffix(".mp4")

    # 背景画像（台本JSONのタイムスタンプに厳密一致するファイルのみ）
    _stem = script_json_path.stem
    _ts_prefix = "_".join(_stem.split("_")[:2])
    bg_path = None
    _bg_candidates = list(script_json_path.parent.glob(f"{_ts_prefix}*_bg.jpg"))
    if len(_bg_candidates) == 1:
        bg_path = _bg_candidates[0]
    elif len(_bg_candidates) > 1:
        print(f"警告: 背景画像候補が複数: {[p.name for p in _bg_candidates]}")
    if bg_path:
        print(f"背景画像: {bg_path}")

    print("\n動画を生成しています...")
    try:
        build_video(script, audio_dir, video_path, bg_path=bg_path)
        print(f"動画生成完了: {video_path}")
    except Exception as e:
        print(f"[エラー] 動画生成失敗: {e}")
        sys.exit(1)

    if args.no_upload:
        print("--no-upload が指定されたためアップロードをスキップします")
        return

    # アップロード前のランダム待機（ボット判定回避）
    wait_sec = random.randint(30, 120)
    print(f"アップロード前に {wait_sec} 秒待機しています...")
    time.sleep(wait_sec)

    # 公開時刻の計算
    publish_at = None
    if args.publish_hours > 0:
        publish_at = datetime.now(timezone(timedelta(hours=9))) + timedelta(hours=args.publish_hours)
        print(f"予約公開時刻: {publish_at.strftime('%Y-%m-%d %H:%M:%S JST')}")

    # YouTubeアップロード
    print("YouTubeにアップロードしています...")
    description = script.get("description", "")
    tags = script.get("tags", [])

    try:
        url = upload_video(
            video_path=video_path,
            title=title,
            description=description,
            tags=tags,
            publish_at=publish_at,
        )
        print(f"アップロード完了: {url}")
    except Exception as e:
        notify_error("YouTubeアップロード", e)
        print(f"[エラー] アップロード失敗: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
