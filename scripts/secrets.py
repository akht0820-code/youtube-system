# 秘密情報の読み込みモジュール
#
# 優先順位:
#   1. Windows Credential Manager（keyring）
#   2. 環境変数 / .env ファイル（開発時フォールバック）
#
# 秘密情報は setup_secrets.py で Credential Manager に登録する。
# .env には非機密の設定値（トピック名・スプレッドシートID等）だけ置く。

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

_KEYRING_SERVICE = "youtube-system"

# Credential Manager に保管すべきキーの一覧
SECRET_KEYS = [
    "GEMINI_API_KEY",
]


def get_secret(key: str) -> str:
    """
    キーに対応する秘密情報を返す。

    1. Windows Credential Manager から取得を試みる
    2. 見つからなければ環境変数（.env 含む）から取得
    3. どちらにも無ければ RuntimeError を送出
    """
    # ── 1. Credential Manager ──────────────────────────────
    try:
        import keyring
        value = keyring.get_password(_KEYRING_SERVICE, key)
        if value:
            return value
    except Exception:
        pass  # keyring が使えない環境では次へ

    # ── 2. 環境変数 / .env ─────────────────────────────────
    value = os.getenv(key, "")
    if value:
        return value

    raise RuntimeError(
        f"秘密情報 {key!r} が見つかりません。\n"
        "setup_secrets.py を実行して Credential Manager に登録してください。"
    )
