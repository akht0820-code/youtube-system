# YouTube自動アップロードモジュール

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from auth_utils import get_credentials


# ── 認証 ─────────────────────────────────────────────────

def _get_youtube_client():
    """OAuth2認証を行いYouTube APIクライアントを返す"""
    return build("youtube", "v3", credentials=get_credentials())


# ── アップロード ──────────────────────────────────────────

def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    thumbnail_path: Path | None = None,
    publish_at: datetime | None = None,
) -> str:
    """
    動画をYouTubeにアップロードする

    Args:
        video_path:      動画ファイルのパス
        title:           動画タイトル
        description:     動画説明文
        tags:            タグのリスト
        thumbnail_path:  サムネイル画像のパス（省略可）
        publish_at:      予約投稿の日時（Noneなら即公開）

    Returns:
        アップロードされた動画のID
    """
    if not video_path.exists():
        raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")

    youtube = _get_youtube_client()

    # 予約投稿の場合はprivateで、指定時刻に自動公開
    privacy_status = "private" if publish_at else "public"

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "27",          # 教育カテゴリ
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    if publish_at:
        # YouTube APIはUTC・ISO 8601形式で受け付ける
        if publish_at.tzinfo is None:
            # タイムゾーン未指定ならJSTとして扱いUTCに変換
            from datetime import timedelta
            publish_at = publish_at.replace(tzinfo=timezone(timedelta(hours=9)))
        body["status"]["publishAt"] = publish_at.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )

    # 動画ファイルをチャンク分割でアップロード（大容量対応）
    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=10 * 1024 * 1024,  # 10MB単位
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    print("YouTubeにアップロードしています...")
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            pct = int(status.progress() * 100)
            print(f"  アップロード中... {pct}%", end="\r")

    video_id = response["id"]
    print(f"  アップロード完了！ 動画ID: {video_id}")

    # サムネイルを設定
    if thumbnail_path and thumbnail_path.exists():
        print("  サムネイルを設定しています...")
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path)),
        ).execute()
        print("  サムネイル設定完了")

    return video_id


def get_video_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"


# ── CLI ──────────────────────────────────────────────────

def _parse_publish_at(text: str) -> datetime | None:
    """
    「2026/03/25 18:00」などの入力をdatetimeに変換する
    空文字またはスキップなら None を返す
    """
    text = text.strip()
    if not text or text.lower() in ("skip", "s", "スキップ", ""):
        return None
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"日時の形式が認識できません: {text}\n例: 2026/03/25 18:00")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--auth" in args:
        # 認証だけ行う
        print("YouTube APIの認証を開始します...")
        _get_youtube_client()
        print("認証完了！token.json に保存されました。")

    elif "--upload" in args:
        # 手動アップロード: python youtube_uploader.py --upload <動画> <タイトル>
        if len(args) < 3:
            print("使い方: python youtube_uploader.py --upload <動画パス> <タイトル>")
            sys.exit(1)
        video  = Path(args[1])
        title  = args[2]
        vid_id = upload_video(video, title, "", [])
        print(f"URL: {get_video_url(vid_id)}")

    else:
        print("使い方:")
        print("  python youtube_uploader.py --auth          認証（初回のみ）")
        print("  python youtube_uploader.py --upload <動画> <タイトル>  手動アップロード")
