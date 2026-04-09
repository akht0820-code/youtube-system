"""Claude Code → Discord 送信ヘルパー

使い方:
  python discord_send.py "メッセージ"
  python discord_send.py "メッセージ" --file path/to/image.png
"""

import json
import sys
import time
from pathlib import Path
from uuid import uuid4

TEMP_DIR = Path(__file__).resolve().parent.parent / "tmp_discord"
OUTBOX_DIR = TEMP_DIR / "outbox"
# 後方互換: 旧方式
OUTBOX_LEGACY = TEMP_DIR / "outbox.json"


def send(text: str, files: list[str] | None = None):
    """outbox/にJSONファイルを作成 → Botが自動で送信（複数メッセージ対応）"""
    OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
    data = {
        "timestamp": time.time(),
        "text": text,
        "files": files or [],
    }
    # ファイル名: タイムスタンプ_UUID（ソートで時系列順を保証）
    fname = f"{time.time():.6f}_{uuid4().hex[:8]}.json"
    tmp = OUTBOX_DIR / (fname + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.rename(OUTBOX_DIR / fname)
    print(f"[Discord送信キュー] {text[:80]}{'...' if len(text) > 80 else ''}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("使い方: python discord_send.py 'メッセージ' [--file path]")
        sys.exit(1)

    msg = sys.argv[1]
    files = []
    i = 2
    while i < len(sys.argv):
        if sys.argv[i] == "--file" and i + 1 < len(sys.argv):
            files.append(sys.argv[i + 1])
            i += 2
        else:
            i += 1

    send(msg, files if files else None)
