# スマホ通知モジュール（ntfy.sh）

import os
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
NTFY_URL   = f"https://ntfy.sh/{NTFY_TOPIC}"


def _send(title: str, message: str, priority: str = "default", tags: list[str] = []):
    """ntfy.sh に通知を送る"""
    if not NTFY_TOPIC:
        return
    try:
        requests.post(
            NTFY_URL,
            data=message.encode("utf-8"),
            headers={
                "Title":    title.encode("utf-8"),
                "Priority": priority,
                "Tags":     ",".join(tags),
            },
            timeout=10,
        )
    except Exception:
        pass  # 通知失敗はシステムを止めない


def notify_error(step: str, error: Exception):
    """エラー発生を通知"""
    _send(
        title=f"❌ エラー: {step}",
        message=str(error)[:200],
        priority="high",
        tags=["warning"],
    )


def notify_success(theme: str, url: str = ""):
    """動画アップロード完了を通知"""
    msg = f"テーマ: {theme}"
    if url:
        msg += f"\n{url}"
    _send(
        title="✅ 動画アップロード完了",
        message=msg,
        priority="default",
        tags=["tada"],
    )


def notify_start(theme: str):
    """処理開始を通知"""
    _send(
        title="▶️ 動画生成を開始",
        message=f"テーマ: {theme}",
        priority="low",
        tags=["arrow_forward"],
    )
