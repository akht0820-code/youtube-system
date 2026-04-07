# 予約投稿済みの動画を即時公開に変更するスクリプト
# 使い方: python publish_now.py <動画ID>
# 例:    python publish_now.py xp-X-mwtYNE

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from secrets import get_secret
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json


def publish_now(video_id: str) -> None:
    token_path = Path(__file__).parent.parent / "token.json"
    creds = Credentials.from_authorized_user_file(str(token_path), [
        "https://www.googleapis.com/auth/youtube"
    ])
    youtube = build("youtube", "v3", credentials=creds)

    youtube.videos().update(
        part="status",
        body={
            "id": video_id,
            "status": {
                "privacyStatus": "public",
                "selfDeclaredMadeForKids": False,
            }
        }
    ).execute()

    print(f"[OK] 即時公開に変更しました: https://youtu.be/{video_id}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python publish_now.py <動画ID>")
        sys.exit(1)
    publish_now(sys.argv[1])
