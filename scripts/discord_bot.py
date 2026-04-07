"""Discord Bot -ゆっくり管理Bot（Claude Code中継モード）

双方向リアルタイム同期:
  Discord → chat.log → Claude Code（バックグラウンド監視）
  outbox.json → Discord

コマンド:
  !status   -パイプラインの状態確認
  !log      -最新の生成ログ（末尾20行）
  !thumb    -最新サムネイルを送信
  !runs     -直近の生成一覧
  !gen      -動画生成を開始
  !stop     -実行中のgenerator.pyを停止
  !reset    -チャット履歴をリセット
  !help     -コマンド一覧

!で始まらないメッセージ → chat.logに記録 + ntfyでClaude Codeに通知
"""

import sys
from pathlib import Path

# scripts/secrets.pyが標準secretsを隠す問題を回避
_scripts_dir = str(Path(__file__).resolve().parent)
if _scripts_dir in sys.path:
    sys.path.remove(_scripts_dir)

import asyncio
import json
import os
import subprocess
import time
from datetime import datetime

import keyring

TOKEN = keyring.get_password("youtube-system", "DISCORD_BOT_TOKEN")

import discord
from discord import Intents

# プロジェクトルート
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
OUTPUT_DIR = PROJECT_ROOT / "output"
LOGS_DIR = PROJECT_ROOT / "logs"
PYTHON = r"C:\Users\user\AppData\Local\Programs\Python\Python311\python.exe"
TEMP_DIR = PROJECT_ROOT / "tmp_discord"
CHAT_LOG = TEMP_DIR / "chat.log"
OUTBOX = TEMP_DIR / "outbox.json"
ERROR_FEED = TEMP_DIR / "error_feed.json"
CHANNEL_FILE = TEMP_DIR / "channel_id.txt"
HEARTBEAT_FILE = TEMP_DIR / "heartbeat.txt"
LAST_MSG_FILE = TEMP_DIR / "last_discord_recv.txt"

if not TOKEN:
    print("[!] DISCORD_BOT_TOKEN が見つかりません")
    sys.exit(1)

# Bot初期化
intents = Intents.default()
intents.message_content = True
bot_client = discord.Client(intents=intents)

_OWNER_FILE = TEMP_DIR / "owner_id.txt"
OWNER_ID: int | None = None
_last_user_message_id: int | None = None
_processed_message_ids: set[int] = set()  # 重複イベント防止用

# OWNER_IDをファイルから復元
if _OWNER_FILE.exists():
    try:
        OWNER_ID = int(_OWNER_FILE.read_text().strip())
    except (ValueError, OSError):
        pass


def _log_chat(sender: str, text: str, attachments: list[str] | None = None):
    """chat.logに追記（ターミナル側で tail -f で表示）"""
    TEMP_DIR.mkdir(exist_ok=True)
    # ローテーション: 1000行超えたら古い行を切り捨て
    try:
        if CHAT_LOG.exists() and CHAT_LOG.stat().st_size > 200_000:
            existing = CHAT_LOG.read_text(encoding="utf-8").splitlines()
            if len(existing) > 1000:
                CHAT_LOG.write_text("\n".join(existing[-500:]) + "\n", encoding="utf-8")
    except Exception:
        pass
    ts = datetime.now().strftime("%H:%M:%S")
    lines = [f"[{ts}] {sender}: {text}"]
    if attachments:
        for a in attachments:
            lines.append(f"  [添付] {a}")
    with open(CHAT_LOG, "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def _latest_run_dir() -> Path | None:
    if not OUTPUT_DIR.exists():
        return None
    dirs = sorted(
        [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name[:8].isdigit()],
        key=lambda d: d.name, reverse=True,
    )
    return dirs[0] if dirs else None


def _latest_log() -> Path | None:
    if not LOGS_DIR.exists():
        return None
    logs = sorted(LOGS_DIR.glob("*.log"), key=lambda f: f.stat().st_mtime, reverse=True)
    return logs[0] if logs else None


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv", ".webm"}


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


# --- ヘルスチェック + ハートビート ---

async def _health_check_loop():
    """10分ごとに自己ヘルスチェック。接続が死んでいたら強制終了して外部で再起動させる"""
    await asyncio.sleep(60)  # 起動直後は待機
    while True:
        try:
            # ハートビート書き込み（生存証明）
            HEARTBEAT_FILE.write_text(
                json.dumps({"ts": time.time(), "pid": os.getpid()}, ensure_ascii=False),
                encoding="utf-8",
            )
            # ギルド情報を取得してDiscord接続が生きているか確認
            if bot_client.guilds:
                guild = bot_client.guilds[0]
                # fetch_guildでAPI呼び出し -接続が死んでいたら例外
                await bot_client.fetch_guild(guild.id)
                print(f"[Bot] ヘルスチェックOK: {datetime.now().strftime('%H:%M:%S')}")
            else:
                print("[Bot] ヘルスチェック: ギルドなし -強制終了")
                os._exit(1)
        except Exception as e:
            print(f"[Bot] ヘルスチェック失敗: {e} -強制終了して再起動を待つ")
            os._exit(1)
        await asyncio.sleep(600)  # 10分間隔


async def _preventive_reconnect():
    """24時間ごとにGateway再接続（ゾンビ化防止、プロセスは維持）"""
    while True:
        await asyncio.sleep(24 * 3600)
        print("[Bot] 予防的再接続: 24時間経過")
        try:
            await bot_client.close()
        except Exception:
            pass


# --- outbox監視（Claude Code → Discord）---

async def _outbox_watcher():
    """outbox.jsonを監視して、内容があればDiscordに送信"""
    last_ts = 0.0
    while True:
        await asyncio.sleep(1)
        try:
            if not OUTBOX.exists():
                continue
            try:
                data = json.loads(OUTBOX.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                # 書き込み途中の可能性 → 次のサイクルでリトライ
                continue
            ts = data.get("timestamp", 0)
            if ts <= last_ts:
                continue

            text = data.get("text", "")
            files_to_send = data.get("files", [])
            if not text and not files_to_send:
                continue

            # チャンネルID取得
            if not CHANNEL_FILE.exists():
                continue
            channel_id = int(CHANNEL_FILE.read_text().strip())
            channel = bot_client.get_channel(channel_id)
            if channel is None:
                continue

            # ファイル添付
            discord_files = []
            for fp in files_to_send:
                p = Path(fp)
                if p.exists():
                    discord_files.append(discord.File(str(p), filename=p.name))

            # 送信（2000文字分割）
            while text:
                if len(text) <= 1900:
                    chunk = text
                    text = ""
                else:
                    split_at = text.rfind("\n", 0, 1900)
                    if split_at == -1:
                        split_at = 1900
                    chunk = text[:split_at]
                    text = text[split_at:].lstrip("\n")

                kwargs = {"content": chunk}
                if not text and discord_files:
                    kwargs["files"] = discord_files
                await channel.send(**kwargs)

            # 💭リアクション除去（最新ユーザーメッセージから）
            if _last_user_message_id and channel_id:
                try:
                    msg = await channel.fetch_message(_last_user_message_id)
                    await msg.remove_reaction("\U0001F4AD", bot_client.user)
                except Exception:
                    pass

            # 送信成功 → タイムスタンプを更新して再送防止
            last_ts = ts
            # 送信済み削除
            OUTBOX.unlink(missing_ok=True)
        except Exception as e:
            print(f"[Bot] outbox送信エラー: {e}")


# --- error_feed監視（システム通知 → Discord）---

async def _error_feed_watcher():
    """error_feed.jsonを監視して、エラー通知をDiscordに送信しchat.logにも記録"""
    _processed_count = 0
    while True:
        await asyncio.sleep(2)
        try:
            if not ERROR_FEED.exists():
                _processed_count = 0
                continue
            feed = json.loads(ERROR_FEED.read_text(encoding="utf-8"))
            if not isinstance(feed, list):
                continue
            # 未処理のエントリのみ送信
            new_entries = feed[_processed_count:]
            if not new_entries:
                continue

            # チャンネルID取得
            if not CHANNEL_FILE.exists():
                continue
            channel_id = int(CHANNEL_FILE.read_text().strip())
            channel = bot_client.get_channel(channel_id)
            if channel is None:
                continue

            for entry in new_entries:
                title = entry.get("title", "")
                message = entry.get("message", "")
                text = f"**{title}**\n```\n{message[:1500]}\n```"
                # Discord送信
                await channel.send(text[:1900])
                # chat.logにも記録（Claude Codeが検知できるように）
                _log_chat("System", f"{title}\n{message[:500]}")

            _processed_count = len(feed)

            # 全件処理済みならファイル削除
            ERROR_FEED.unlink(missing_ok=True)
            _processed_count = 0
        except Exception as e:
            print(f"[Bot] error_feed送信エラー: {e}")


# --- コマンドハンドラ ---

async def _cmd_status(message: discord.Message):
    run_dir = _latest_run_dir()
    if not run_dir:
        await message.reply("生成履歴がありません。")
        return
    pipeline_json = run_dir / "pipeline.json"
    if pipeline_json.exists():
        data = json.loads(pipeline_json.read_text(encoding="utf-8"))
        status = data.get("status", "不明")
        theme = data.get("theme", "不明")
        lines = [
            f"**最新run**: `{run_dir.name}`",
            f"**テーマ**: {theme}",
            f"**状態**: {status}",
        ]
        skills = data.get("skills", {})
        if skills:
            lines.append("**スキル状態**:")
            for skill_name, skill_data in skills.items():
                s = skill_data.get("status", "?")
                icon = {"done": "[OK]", "running": "[...]", "error": "[NG]"}.get(s, f"[{s}]")
                lines.append(f"  {icon} {skill_name}")
        await message.reply("\n".join(lines))
    else:
        await message.reply(f"最新run: `{run_dir.name}`\npipeline.json が見つかりません。")


async def _cmd_log(message: discord.Message):
    log = _latest_log()
    if not log:
        await message.reply("ログファイルがありません。")
        return
    text = log.read_text(encoding="utf-8", errors="replace")
    tail = "\n".join(text.splitlines()[-20:])
    if len(tail) > 1900:
        tail = tail[-1900:]
    await message.reply(f"**{log.name}** (末尾20行)\n```\n{tail}\n```")


async def _cmd_thumb(message: discord.Message):
    run_dir = _latest_run_dir()
    if not run_dir:
        await message.reply("生成履歴がありません。")
        return
    thumbs = list(run_dir.glob("*thumbnail*")) + list(run_dir.glob("*thumb*.jpg")) + list(run_dir.glob("*thumb*.png"))
    if not thumbs:
        await message.reply(f"`{run_dir.name}` にサムネイルが見つかりません。")
        return
    latest = max(thumbs, key=lambda f: f.stat().st_mtime)
    await message.reply(
        f"**{run_dir.name}**",
        file=discord.File(str(latest), filename=latest.name),
    )


async def _cmd_runs(message: discord.Message):
    if not OUTPUT_DIR.exists():
        await message.reply("output/ が見つかりません。")
        return
    dirs = sorted(
        [d for d in OUTPUT_DIR.iterdir() if d.is_dir() and d.name[:8].isdigit()],
        key=lambda d: d.name, reverse=True,
    )[:5]
    if not dirs:
        await message.reply("生成履歴がありません。")
        return
    lines = ["**直近5件の生成**:"]
    for d in dirs:
        pj = d / "pipeline.json"
        status = ""
        if pj.exists():
            data = json.loads(pj.read_text(encoding="utf-8"))
            status = f" -{data.get('status', '?')}"
        lines.append(f"  `{d.name}`{status}")
    await message.reply("\n".join(lines))


async def _cmd_gen(message: discord.Message):
    await message.reply("動画生成を開始します...")
    try:
        proc = await asyncio.create_subprocess_exec(
            PYTHON, str(SCRIPTS_DIR / "generator.py"), "--auto",
            cwd=str(PROJECT_ROOT),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await message.reply(f"generator.py を起動しました (PID: {proc.pid})")
    except Exception as e:
        await message.reply(f"起動失敗: {e}")


async def _cmd_stop(message: discord.Message):
    try:
        result = subprocess.run(
            ["taskkill.exe", "/f", "/im", "python.exe", "/fi", "WINDOWTITLE eq generator*"],
            capture_output=True, text=True,
        )
        await message.reply(f"停止コマンドを実行しました。\n```\n{result.stdout or result.stderr}\n```")
    except Exception as e:
        await message.reply(f"停止失敗: {e}")


HELP_TEXT = """**ゆっくり管理Bot コマンド一覧**

**パイプライン操作:**
`!status` -パイプラインの状態確認
`!log` -最新の生成ログ（末尾20行）
`!thumb` -最新サムネイルを送信
`!runs` -直近の生成一覧
`!gen` -動画生成を開始
`!stop` -実行中の生成を停止

**Claude Code連携:**
`!`なしでメッセージ送信 -Claude Codeに転送
画像・動画も添付可能

`!help` -このヘルプ
"""


@bot_client.event
async def on_ready():
    print(f"[Bot] ログイン完了: {bot_client.user}")
    print(f"[Bot] サーバー: {[g.name for g in bot_client.guilds]}")
    # outbox監視タスク開始
    bot_client.loop.create_task(_outbox_watcher())
    # エラーフィード監視タスク開始
    bot_client.loop.create_task(_error_feed_watcher())
    # ヘルスチェック開始
    bot_client.loop.create_task(_health_check_loop())
    # 予防的再接続タイマー開始
    bot_client.loop.create_task(_preventive_reconnect())


@bot_client.event
async def on_disconnect():
    print(f"[Bot] Discord接続切断: {datetime.now().strftime('%H:%M:%S')}")


@bot_client.event
async def on_resumed():
    print(f"[Bot] Discord接続再開: {datetime.now().strftime('%H:%M:%S')}")


@bot_client.event
async def on_message(message: discord.Message):
    global OWNER_ID, _last_user_message_id
    if message.author == bot_client.user:
        return

    # 重複イベント防止（同じメッセージIDは1回だけ処理）
    if message.id in _processed_message_ids:
        return
    _processed_message_ids.add(message.id)
    # メモリ節約: 古いIDを削除（最新100件のみ保持）
    if len(_processed_message_ids) > 100:
        _processed_message_ids.clear()
        _processed_message_ids.add(message.id)

    content = message.content.strip()
    if not content and not message.attachments:
        return

    if OWNER_ID is None:
        OWNER_ID = message.author.id
        _OWNER_FILE.write_text(str(OWNER_ID))
        print(f"[Bot] オーナー登録: {message.author} (ID: {OWNER_ID})")

    if message.author.id != OWNER_ID:
        if content.startswith("!"):
            await message.reply("このBotはオーナー専用です。")
        return

    # チャンネルIDを保存（discord_send.py用）
    TEMP_DIR.mkdir(exist_ok=True)
    CHANNEL_FILE.write_text(str(message.channel.id))

    # 最終受信時刻を記録（ウォッチドッグ用）
    LAST_MSG_FILE.write_text(
        json.dumps({"ts": time.time(), "user": content[:100]}, ensure_ascii=False),
        encoding="utf-8",
    )

    # chat.logに記録（ターミナル側にリアルタイム表示）
    att_names = [a.filename for a in message.attachments]
    _log_chat("User", content, att_names if att_names else None)

    # ntfy経由でClaude Codeに即時通知（本文は送らずpingのみ）
    try:
        import urllib.request
        _req = urllib.request.Request(
            "https://ntfy.sh/yukkuri-health-discord-relay",
            data=b"ping",
            headers={"Title": "new_message", "Priority": "high"},
        )
        urllib.request.urlopen(_req, timeout=3)
    except Exception:
        pass  # 通知失敗でもメッセージ処理は続行

    # コマンド処理
    if content.startswith("!"):
        if content == "!status":
            await _cmd_status(message)
        elif content == "!log":
            await _cmd_log(message)
        elif content == "!thumb":
            await _cmd_thumb(message)
        elif content == "!runs":
            await _cmd_runs(message)
        elif content == "!gen":
            await _cmd_gen(message)
        elif content == "!stop":
            await _cmd_stop(message)
        elif content == "!reset":
            await message.reply("チャット履歴をリセットしました。")
        elif content == "!help":
            await message.reply(HELP_TEXT)
        else:
            await message.reply(f"不明なコマンド: `{content}`\n`!help` でコマンド一覧を表示")
        return

    # --- Claude Code中継 ---
    _last_user_message_id = message.id

    # 💭リアクション（考え中マーク）
    await message.add_reaction("\U0001F4AD")

    # 添付ファイルをダウンロード（ファイル名をサニタイズ）
    for att in message.attachments:
        safe_name = att.filename.replace("/", "_").replace("\\", "_").replace("..", "_")
        dest = TEMP_DIR / safe_name
        await att.save(dest)

    await message.reply("Claude Codeに送信しました。")

    # 💭タイムアウト: 5分以内に応答がなければ自動除去＋警告
    async def _reaction_timeout(msg_ref, msg_id):
        await asyncio.sleep(300)
        try:
            ch = msg_ref.channel
            m = await ch.fetch_message(msg_id)
            for r in m.reactions:
                if str(r.emoji) == "\U0001F4AD":
                    await m.remove_reaction("\U0001F4AD", bot_client.user)
                    await ch.send("Claude Codeからの応答がありません（5分タイムアウト）。セッションを確認してください。")
                    break
        except Exception:
            pass
    asyncio.create_task(_reaction_timeout(message, message.id))


if __name__ == "__main__":
    print("[Bot] 起動中...")
    # 自動再接続ループ: 切断・例外時にbackoff付きで再試行
    _backoff = 5
    _MAX_BACKOFF = 300
    while True:
        try:
            bot_client.run(TOKEN)
        except Exception as e:
            print(f"[Bot] 異常終了: {e}")
        print(f"[Bot] {_backoff}秒後に再接続します...")
        time.sleep(_backoff)
        _backoff = min(_backoff * 2, _MAX_BACKOFF)
        # Clientを再生成（discord.pyはrun()後に再利用不可）
        bot_client = discord.Client(intents=intents)
        # イベントハンドラを再登録
        bot_client.event(on_ready)
        bot_client.event(on_disconnect)
        bot_client.event(on_resumed)
        bot_client.event(on_message)
