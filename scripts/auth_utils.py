# 共通OAuth認証ユーティリティ（YouTube + Google Sheets）

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# YouTubeアップロード・管理 + Googleスプレッドシート読み書き
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
    "https://www.googleapis.com/auth/spreadsheets",
]

PROJECT_ROOT     = Path(__file__).parent.parent
CREDENTIALS_PATH = PROJECT_ROOT / "credentials.json"
TOKEN_PATH       = PROJECT_ROOT / "token.json"


def get_credentials() -> Credentials:
    """OAuth2認証済みのCredentialsオブジェクトを返す"""
    if not CREDENTIALS_PATH.exists():
        raise FileNotFoundError(
            f"credentials.json が見つかりません: {CREDENTIALS_PATH}\n"
            "Google Cloud ConsoleからOAuth2認証情報をダウンロードして配置してください。"
        )

    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    return creds
