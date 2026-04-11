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

PROJECT_ROOT = Path(__file__).parent.parent
# Step 3-δ.3: CREDENTIALS_PATH / TOKEN_PATH の module-level 定数は削除.
# get_credentials() 内で channel config から動的に解決する.


def get_credentials(channel_id: str = "health") -> Credentials:
    """OAuth2認証済みのCredentialsオブジェクトを返す.

    Step 3-δ.3: channel_id から config/channels/{channel_id}.json を読み,
    oauth.credentials / oauth.token のパスを解決する. default='health' で
    後方互換 (10時 task の 4 callers は引数なし呼び出しのため bit-identical).

    channel config 読込失敗 / 不正は RuntimeError で fail-closed.
    """
    # import 部と load 部を分離 (generator.py の pattern と同じ).
    # import 部は SyntaxError 等まで含めて Exception で広く捕捉する.
    try:
        from _channel import load_channel, ChannelLoadError
    except Exception as _ce_imp:
        raise RuntimeError(
            f"_channel モジュール import 失敗 (auth, channel={channel_id}): {_ce_imp}"
        ) from _ce_imp

    try:
        _cfg = load_channel(channel_id)
    except ChannelLoadError as _ce_load:
        raise RuntimeError(
            f"チャンネル設定読込失敗 (auth, channel={channel_id}): {_ce_load}"
        ) from _ce_load

    credentials_path = PROJECT_ROOT / _cfg.oauth.credentials
    token_path = PROJECT_ROOT / _cfg.oauth.token

    if not credentials_path.exists():
        raise FileNotFoundError(
            f"credentials.json が見つかりません: {credentials_path}\n"
            "Google Cloud ConsoleからOAuth2認証情報をダウンロードして配置してください。"
        )

    creds = None

    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)

        token_path.write_text(creds.to_json(), encoding="utf-8")

    return creds
