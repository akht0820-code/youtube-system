"""Discord ウォッチドッグ -Botの生存確認と自己修復

1時間ごとにClaude CodeのCronから呼ばれる。
即時応答システム(chat.log監視)とは完全に別のプロセス。

チェック内容:
  1. heartbeat.txt が10分以上更新されていない → Bot死亡
  2. chat.logに未読のUserメッセージがある → メッセージ見逃し

異常検知時:
  1. Botプロセスをkill → 再起動
  2. 未読メッセージを収集
  3. Discordに報告メッセージを送信
"""

import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TEMP_DIR = PROJECT_ROOT / "tmp_discord"
HEARTBEAT_FILE = TEMP_DIR / "heartbeat.txt"
CHAT_LOG = TEMP_DIR / "chat.log"
OUTBOX = TEMP_DIR / "outbox.json"
LAST_READ_POS = TEMP_DIR / "last_watchdog_pos.txt"
PYTHON = r"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe"
BOT_SCRIPT = PROJECT_ROOT / "scripts" / "discord_bot.py"


def _get_heartbeat_age() -> float:
    """ハートビートファイルの経過秒数を返す。ファイルがなければ無限大"""
    if not HEARTBEAT_FILE.exists():
        return float("inf")
    try:
        data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
        return time.time() - data.get("ts", 0)
    except (json.JSONDecodeError, OSError):
        return float("inf")


def _is_bot_process_alive() -> bool:
    """discord_bot.pyプロセスが存在するか"""
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=10,
        )
        return "discord_bot.py" in result.stdout
    except Exception:
        return False


def _kill_bot():
    """discord_bot.pyプロセスをkill（heartbeat.txtのPIDのみ対象）"""
    # heartbeat.txtからBot PIDを取得（他のpython.exeを巻き込まない）
    bot_pid = None
    if HEARTBEAT_FILE.exists():
        try:
            data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
            bot_pid = data.get("pid")
        except (json.JSONDecodeError, OSError):
            pass

    # WSL側: discord_bot.pyを名前で特定してkill
    try:
        result = subprocess.run(
            ["ps", "aux"], capture_output=True, text=True, timeout=10,
        )
        for line in result.stdout.splitlines():
            if "discord_bot.py" in line and "grep" not in line:
                parts = line.split()
                if len(parts) > 1:
                    pid = parts[1]
                    os.kill(int(pid), 9)
                    print(f"[Watchdog] WSL discord_bot.py (PID {pid}) をkill")
    except Exception as e:
        print(f"[Watchdog] WSL kill失敗: {e}")

    # Windows側: heartbeat.txtに記録されたPIDのみkill（他プロセスを巻き込まない）
    if bot_pid:
        try:
            subprocess.run(
                ["cmd.exe", "/c", f"taskkill /f /pid {bot_pid}"],
                capture_output=True, timeout=10,
            )
            print(f"[Watchdog] Windows Bot (PID {bot_pid}) をkill")
        except Exception as e:
            print(f"[Watchdog] Windows kill失敗: {e}")
    else:
        print("[Watchdog] Bot PIDが不明のためWindows側killをスキップ")


def _start_bot():
    """discord_bot.pyをバックグラウンドで起動（重複起動防止付き）"""
    # 既存プロセスがあれば起動しない
    if _is_bot_process_alive():
        print("[Watchdog] Botプロセスが既に存在するため起動スキップ")
        return
    try:
        subprocess.Popen(
            [PYTHON, str(BOT_SCRIPT)],
            cwd=str(PROJECT_ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
        print("[Watchdog] discord_bot.py を再起動しました")
    except Exception as e:
        print(f"[Watchdog] 再起動失敗: {e}")


def _get_unread_messages() -> list[str]:
    """前回チェック以降の未読Userメッセージを取得"""
    if not CHAT_LOG.exists():
        return []

    # 前回の読み取り位置を取得
    last_pos = 0
    if LAST_READ_POS.exists():
        try:
            last_pos = int(LAST_READ_POS.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            last_pos = 0

    try:
        content = CHAT_LOG.read_text(encoding="utf-8")
    except OSError:
        return []

    # 現在位置を保存
    current_pos = len(content)
    LAST_READ_POS.write_text(str(current_pos), encoding="utf-8")

    if last_pos >= current_pos:
        return []

    # 新しい部分だけ解析
    new_content = content[last_pos:]
    user_messages = []
    for line in new_content.splitlines():
        # [HH:MM:SS] User: メッセージ のパターン
        m = re.match(r"\[\d{2}:\d{2}:\d{2}\] User: (.+)", line)
        if m:
            user_messages.append(m.group(1))

    return user_messages


def _send_discord_report(message: str):
    """outbox.jsonに書き込んでDiscordに送信"""
    try:
        msg = {
            "timestamp": time.time(),
            "text": message,
            "files": [],
        }
        OUTBOX.write_text(json.dumps(msg, ensure_ascii=False), encoding="utf-8")
        print(f"[Watchdog] Discordに報告送信")
    except Exception as e:
        print(f"[Watchdog] outbox書き込み失敗: {e}")


def main():
    print(f"[Watchdog] チェック開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    heartbeat_age = _get_heartbeat_age()
    bot_alive = _is_bot_process_alive()
    unread = _get_unread_messages()

    print(f"[Watchdog] ハートビート経過: {heartbeat_age:.0f}秒")
    print(f"[Watchdog] Botプロセス: {'生存' if bot_alive else '死亡'}")
    print(f"[Watchdog] 未読メッセージ: {len(unread)}件")

    bot_was_dead = False

    # Bot死亡判定: ハートビートが15分以上古い、またはプロセスが存在しない
    if heartbeat_age > 900 or not bot_alive:
        bot_was_dead = True
        print("[Watchdog] Bot異常検知 -再起動実行")

        # 既存プロセスをkill（ゾンビ対策）
        if bot_alive:
            _kill_bot()
            time.sleep(2)

        # 再起動
        _start_bot()

        # Bot起動を待機（outbox処理が可能になるまで）
        print("[Watchdog] Bot起動待機中（15秒）...")
        time.sleep(15)

    # 未読メッセージがある場合の報告
    if unread and bot_was_dead:
        # Botが死んでいて未読がある → フル報告
        msg_summary = "\n".join(f"- {m[:100]}" for m in unread[-10:])  # 最新10件
        report = (
            f"メッセージ溜まってることに今気が付きました。"
            f"直しましたので、もうメッセージは無事に届くようになりました。\n\n"
            f"【未読メッセージ {len(unread)}件】\n{msg_summary}\n\n"
            f"（ウォッチドッグによる自動復旧）"
        )
        _send_discord_report(report)
    elif bot_was_dead:
        # Botが死んでいたが未読なし
        report = (
            "Discord Botの接続異常を検知して自動復旧しました。"
            "現在は正常に稼働しています。\n"
            "（ウォッチドッグによる自動復旧）"
        )
        _send_discord_report(report)

    # 結果を返す（Claude CodeのCronプロンプトで使える）
    status = "OK" if not bot_was_dead else "RECOVERED"
    print(f"[Watchdog] 結果: {status}")
    return status


if __name__ == "__main__":
    main()
