"""run.bat用ネットワーク接続チェック

socket接続でDNS+TCP到達性を確認する。
HTTP応答コード（4xx/5xx）に左右されない設計。

使い方:
  python network_check.py
  終了コード 0=OK, 1=NG
"""

import socket
import sys

TARGETS = [
    ("generativelanguage.googleapis.com", 443, "Gemini"),
    ("www.googleapis.com", 443, "Google API"),
]

TIMEOUT = 10


def check() -> bool:
    """全ターゲットにsocket接続を試行。1つでも成功すればTrue"""
    ok_count = 0
    for host, port, label in TARGETS:
        try:
            sock = socket.create_connection((host, port), timeout=TIMEOUT)
            sock.close()
            print(f"  [OK] {label} ({host}:{port})")
            ok_count += 1
        except OSError as e:
            print(f"  [NG] {label} ({host}:{port}): {e}")
    return ok_count > 0


if __name__ == "__main__":
    if check():
        print("Network OK")
        sys.exit(0)
    else:
        print("Network FAILED")
        sys.exit(1)
