"""CLAUDE_PROJECT_CONTEXT.md を元ファイルから自動生成し、変更時のみ Discord 送信

設計（Codex協議済み v1）:
- 入力: CLAUDE.md / .claude/commands/*.md / ~/.claude/projects/.../memory/*.md / tasks/lessons.md
- 出力: CLAUDE_PROJECT_CONTEXT.md（プロジェクトルート）
- 状態: .cache/project_context_state.json に content/last_built/last_enqueued/pending を分離記録
- 排他: .cache/project_context.lock/ を mkdir で取得（stale timeout 10分）
- ハッシュ: sha256(FORMAT_VERSION + PREAMBLE_VERSION + 正規化済み (path, content) 連結)
- 変更検知: content_hash != last_enqueued_hash or pending_delivery 有り → 再生成+送信
- Discord送信: scripts/discord_send.py 経由、Windows パス変換で添付
- 失敗時: pending_delivery にキャッシュ + notifier.notify_report(high) でスマホ通知

run.bat からは wsl.exe 経由で呼ぶ前提（memory パスが WSL 絶対パスのため）。
手動実行時は WSL 上で `python3 scripts/build_project_context.py` で可。

使い方:
  python3 scripts/build_project_context.py              # 通常（変更時のみ送信）
  python3 scripts/build_project_context.py --dry-run    # 生成のみ、送信・state更新スキップ
  python3 scripts/build_project_context.py --force      # hash一致でも強制再送
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

# Note: 標準ライブラリの secrets は scripts/secrets.py にシャドウされるので import しない。
# token_hex 相当は os.urandom(16).hex() で代用する。

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT / "scripts"))
from _atomic import atomic_write_json, atomic_write_text, safe_read_json  # noqa: E402

OUTPUT_FILE = PROJECT_ROOT / "CLAUDE_PROJECT_CONTEXT.md"
CACHE_DIR = PROJECT_ROOT / ".cache"
STATE_FILE = CACHE_DIR / "project_context_state.json"
LOCK_DIR = CACHE_DIR / "project_context.lock"
LOCK_STALE_SEC = 600  # 10分経過した lock は stale とみなす

# 生成ロジック・プリアンブルを変更したら必ずインクリメントする。
# これを digest に混ぜないと、入力同一のまま書式変更しても再生成されない。
FORMAT_VERSION = "1"
PREAMBLE_VERSION = "1"

# メモリディレクトリ（WSL 絶対パス固定）
# Claude Code CLI は WSL 上で動くため、ここは常に /home/aki/... 配下
MEMORY_DIR = Path(
    "/home/aki/.claude/projects/-mnt-c-Users-user-Desktop-youtube-system/memory"
)

STATIC_PREAMBLE = """**注意: このファイルは自動生成です。手編集しないでください。**
**注意: memory配下の内容が含まれます。公開前に機密情報がないか確認してください。**

このファイルは Claudeアプリ（claude.ai）のプロジェクト機能に添付して、本プロジェクト専属の Claude Code エージェント向けの「最適なシステム指示文（instructions）」を別の Claude に生成してもらうためのメタコンテキストです。

プロンプト例:「添付のコンテキストを元に、youtube-system プロジェクトで動く Claude Code エージェント（Opus 4.6、WSL2環境）への最適な system prompt / project instructions を作成してください。Claude Code の Agentic 機能（Read/Edit/Bash/Task/Codex MCP/Discord監視/CronCreate 等）を前提とし、敬語かつ 3歩先チェックを強制する設計で。」
"""


def collect_inputs() -> list[tuple[str, Path]]:
    """入力ファイルを (セクション見出し, パス) のリストで返す。sorted で決定論的"""
    inputs: list[tuple[str, Path]] = []

    claude_md = PROJECT_ROOT / "CLAUDE.md"
    if claude_md.exists():
        inputs.append(("プロジェクト指示 (CLAUDE.md)", claude_md))

    commands_dir = PROJECT_ROOT / ".claude" / "commands"
    if commands_dir.exists():
        for p in sorted(commands_dir.glob("*.md")):
            inputs.append((f"コマンド定義 (.claude/commands/{p.name})", p))

    if MEMORY_DIR.exists():
        memory_md = MEMORY_DIR / "MEMORY.md"
        if memory_md.exists():
            inputs.append(("メモリインデックス (MEMORY.md)", memory_md))
        for prefix in ("user_", "project_", "feedback_", "reference_"):
            for p in sorted(MEMORY_DIR.glob(f"{prefix}*.md")):
                inputs.append((f"メモリ ({p.name})", p))

    lessons = PROJECT_ROOT / "tasks" / "lessons.md"
    if lessons.exists():
        inputs.append(("学習蓄積 (tasks/lessons.md)", lessons))

    return inputs


def normalize_content(text: str) -> str:
    """改行コード・末尾空白を正規化してハッシュ安定化"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.rstrip("\n") + "\n"


def compute_content_hash(inputs: list[tuple[str, Path]]) -> str:
    """FORMAT_VERSION + PREAMBLE_VERSION + 正規化済み (path, content) の sha256

    - path は PROJECT_ROOT からの相対（MEMORY_DIR 配下は memory/... 表記で安定化）
    - 入力が追加/削除/並び替えされても sorted により決定論的
    """
    h = hashlib.sha256()
    h.update(f"FORMAT_VERSION={FORMAT_VERSION}\n".encode("utf-8"))
    h.update(f"PREAMBLE_VERSION={PREAMBLE_VERSION}\n".encode("utf-8"))
    # path ソートで安定化
    for _title, path in sorted(inputs, key=lambda x: str(x[1])):
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            # 例外メッセージをハッシュに混ぜるとハッシュが不安定になる
            # （errno 文字列・ロケール差・パス差で揺れる）ので固定 sentinel
            content = "[READ_ERROR]\n"
            # debuggability のため stderr にどのファイルが読めなかったか記録
            print(
                f"[build_project_context] read failed: {path} "
                f"({type(e).__name__})",
                file=sys.stderr,
            )
        content = normalize_content(content)
        # 安定した識別子: 相対化できなければ絶対パス
        try:
            rel = str(path.relative_to(PROJECT_ROOT))
        except ValueError:
            if MEMORY_DIR in path.parents or path == MEMORY_DIR:
                rel = f"memory/{path.name}"
            else:
                rel = str(path)
        h.update(f"--- FILE: {rel} ---\n".encode("utf-8"))
        h.update(content.encode("utf-8"))
    return h.hexdigest()


def build_context(inputs: list[tuple[str, Path]], content_hash: str) -> str:
    """統合ドキュメントを組み立てる"""
    parts: list[str] = []
    parts.append("# Claude Code エージェント プロジェクトコンテキスト — youtube-system")
    parts.append("")
    parts.append(STATIC_PREAMBLE.rstrip())
    parts.append("")
    parts.append("---")
    parts.append("")

    for i, (title, path) in enumerate(inputs, 1):
        parts.append(f"# {i}. {title}")
        parts.append("")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
            content = normalize_content(content)
        except OSError as e:
            # ハッシュ計算と同じく固定 sentinel（例外メッセージは含めない）
            content = "[ファイル読み込み失敗]\n"
            print(
                f"[build_project_context] read failed (build): {path} "
                f"({type(e).__name__})",
                file=sys.stderr,
            )
        parts.append(content.rstrip())
        parts.append("")
        parts.append("---")
        parts.append("")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    parts.append("")
    parts.append(f"_生成日時: {now}_")
    parts.append(
        f"_FORMAT_VERSION: {FORMAT_VERSION} / PREAMBLE_VERSION: {PREAMBLE_VERSION}_"
    )
    parts.append(f"_入力ハッシュ: {content_hash[:16]}..._")
    parts.append("")

    return "\n".join(parts)


def wsl_to_windows_path(p: Path) -> str:
    """WSL パス (/mnt/c/Users/...) を Windows パス (C:\\Users\\...) に変換

    Discord Bot は Windows 側で動作するため、添付ファイルのパスは Windows 表記である必要がある。
    WSL パスを渡すと Bot 側 Path.exists() が False になり無言で添付落ちする。
    """
    s = str(p)
    if s.startswith("/mnt/") and len(s) >= 7 and s[6] == "/":
        drive = s[5].upper()
        rest = s[7:].replace("/", "\\")
        return f"{drive}:\\{rest}"
    return s


def _pid_is_alive(pid: int | None) -> bool:
    """PID が生存しているかチェック。None/0/負値/不正は False"""
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # 存在するが権限がない（別ユーザーのプロセス）
        return True
    except OSError:
        return False
    return True


def _read_lock_owner() -> tuple[str | None, int | None]:
    """lock の owner token と pid を読む。読めなければ (None, None)"""
    owner_file = LOCK_DIR / "owner.json"
    if not owner_file.exists():
        return None, None
    try:
        data = json.loads(owner_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    if not isinstance(data, dict):
        return None, None
    token = data.get("token")
    pid = data.get("pid")
    if not isinstance(token, str) or not isinstance(pid, int):
        return None, None
    return token, pid


def acquire_lock() -> str | None:
    """lockdir + owner token 方式で排他制御

    Returns:
        取得成功時は owner token (str)、失敗時は None

    stale 判定:
      - age > LOCK_STALE_SEC かつ owner PID が死んでいる → 剥がして再取得
      - どちらか一方のみでは剥がさない（誤 reclaim 防止）
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    owner_token = os.urandom(16).hex()
    owner_data = json.dumps(
        {"token": owner_token, "pid": os.getpid()},
        ensure_ascii=False,
    )

    # 最大2回試行: 初回 + stale reclaim 後
    for _ in range(2):
        try:
            LOCK_DIR.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            try:
                age = time.time() - LOCK_DIR.stat().st_mtime
            except OSError:
                return None
            _existing_token, owner_pid = _read_lock_owner()
            owner_alive = _pid_is_alive(owner_pid)
            # 生存中の所有者がいれば絶対に剥がさない
            if owner_alive:
                return None
            # owner 情報が読めない場合は stale timeout だけで判断
            # owner PID 情報があれば「死んでいる AND age > threshold」の AND 条件
            if age <= LOCK_STALE_SEC:
                return None
            print(
                f"[build_project_context] stale lock を剥がします "
                f"(age={age:.0f}s, owner_pid={owner_pid}, alive={owner_alive})"
            )
            try:
                for child in LOCK_DIR.iterdir():
                    try:
                        child.unlink()
                    except OSError:
                        pass
                LOCK_DIR.rmdir()
            except OSError:
                return None
            continue  # 再試行
        # 取得成功 → owner 情報を原子的に書き込む
        # tmp 経由 + os.replace で書き込み失敗時に中途半端な owner.json が残らないよう保証
        owner_file = LOCK_DIR / "owner.json"
        owner_tmp = LOCK_DIR / "owner.json.tmp"
        try:
            owner_tmp.write_text(owner_data, encoding="utf-8")
            os.replace(owner_tmp, owner_file)
        except OSError:
            # owner 書き込み失敗 → 残骸を全部掃除してから lockdir を解放
            for candidate in (owner_tmp, owner_file):
                try:
                    candidate.unlink()
                except OSError:
                    pass
            try:
                LOCK_DIR.rmdir()
            except OSError:
                pass
            return None
        return owner_token
    return None


def release_lock(owner_token: str) -> None:
    """自分の owner token と一致する場合のみ lock を解放

    stale reclaim で他プロセスが lock を取り直していた場合、
    token が一致しないので何もしない（他人の lock を誤削除しない）。
    """
    current_token, _ = _read_lock_owner()
    if current_token != owner_token:
        print("[build_project_context] lock owner 不一致、release をスキップします")
        return
    try:
        owner_file = LOCK_DIR / "owner.json"
        owner_file.unlink(missing_ok=True)
        LOCK_DIR.rmdir()
    except OSError:
        pass


def send_discord(output_path: Path, msg: str) -> tuple[bool, str]:
    """Discord に添付付きで enqueue。(成功, エラーメッセージ)"""
    win_path = wsl_to_windows_path(output_path)
    send_script = PROJECT_ROOT / "scripts" / "discord_send.py"
    try:
        result = subprocess.run(
            [sys.executable, str(send_script), msg, "--file", win_path],
            capture_output=True,
            text=True,
            timeout=30,
            encoding="utf-8",
        )
        if result.returncode == 0:
            return True, ""
        return False, f"exit={result.returncode} stderr={result.stderr[:500]}"
    except subprocess.TimeoutExpired:
        return False, "discord_send.py が 30秒以内に完了しませんでした"
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def notify_failure(reason: str) -> None:
    """enqueue 失敗時のスマホ通知（notifier が死んでも例外を出さない）"""
    try:
        from notifier import notify_report

        notify_report(
            "[build_project_context] Discord enqueue 失敗",
            reason,
            priority="high",
        )
    except Exception as e:
        print(f"[build_project_context] notify_report 失敗: {e}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "CLAUDE_PROJECT_CONTEXT.md は書き換えるが、state 更新と Discord 送信はスキップ。"
            "--force と併用するとファイル再生成は強制されるが state は一切更新しない"
        ),
    )
    ap.add_argument(
        "--force",
        action="store_true",
        help="hash 一致でも強制再生成・再送信",
    )
    args = ap.parse_args()

    print(
        f"[build_project_context] 開始 "
        f"({datetime.now().strftime('%Y-%m-%d %H:%M:%S')})"
    )

    owner_token = acquire_lock()
    if not owner_token:
        print("[build_project_context] 他プロセスが実行中のためスキップします")
        return 0

    try:
        inputs = collect_inputs()
        if not inputs:
            print("[build_project_context] 入力ファイルが見つかりません")
            return 0
        print(f"[build_project_context] 入力ファイル {len(inputs)} 件")

        content_hash = compute_content_hash(inputs)
        print(f"[build_project_context] content_hash={content_hash[:16]}...")

        state = safe_read_json(STATE_FILE, default={}) or {}
        last_built = state.get("last_built_hash")
        last_enqueued = state.get("last_enqueued_hash")
        pending = state.get("pending_delivery")

        # 変更検知: 配達済 hash と一致 かつ pending 無し → 何もしない
        if (
            not args.force
            and content_hash == last_enqueued
            and not pending
            and OUTPUT_FILE.exists()
        ):
            print("[build_project_context] 変更なし、スキップします")
            return 0

        # ファイル生成（last_built と一致 かつ ファイル存在 なら再利用）
        regenerated = False
        if content_hash != last_built or not OUTPUT_FILE.exists() or args.force:
            print("[build_project_context] 再生成します")
            doc = build_context(inputs, content_hash)
            atomic_write_text(OUTPUT_FILE, doc)
            regenerated = True
            print(f"[build_project_context] 書き込み完了: {OUTPUT_FILE}")
        else:
            print("[build_project_context] 既存ファイルを再利用")

        if args.dry_run:
            # dry-run では state を一切更新しない（契約）
            print("[build_project_context] dry-run のため送信・state更新をスキップ")
            return 0

        # dry-run でない場合のみ last_built_hash / content_hash を更新
        if regenerated:
            state["last_built_hash"] = content_hash
            state["content_hash"] = content_hash
            atomic_write_json(STATE_FILE, state)

        # Discord enqueue
        short_hash = content_hash[:8]
        msg = (
            f"CLAUDE_PROJECT_CONTEXT.md を更新しました (hash={short_hash})\n"
            f"Claudeアプリのプロジェクトに再アップロードしてください。"
        )

        ok, err = send_discord(OUTPUT_FILE, msg)
        if ok:
            print("[build_project_context] Discord enqueue 成功")
            state["last_enqueued_hash"] = content_hash
            state["pending_delivery"] = None
            state["last_enqueued_at"] = datetime.now().isoformat(timespec="seconds")
            atomic_write_json(STATE_FILE, state)
            return 0
        else:
            print(f"[build_project_context] Discord enqueue 失敗: {err}")
            state["pending_delivery"] = content_hash
            state["last_error"] = err[:500]
            atomic_write_json(STATE_FILE, state)
            notify_failure(
                f"CLAUDE_PROJECT_CONTEXT.md を Discord に送れませんでした "
                f"(hash={short_hash}): {err}"
            )
            # Python 内部のハンドル済み失敗は exit 0 で返す。
            # notify_failure() で既にスマホ通知済みなので、呼び出し側の
            # run.bat errorlevel ハンドラで二重通知させないため。
            # infrastructure 失敗（wsl.exe 起動不能等）だけを bat 側で拾わせる。
            return 0
    finally:
        release_lock(owner_token)


if __name__ == "__main__":
    sys.exit(main())
