"""Discord inbox monitor - Claude側の消費ループ + heartbeat 書き込み

設計方針（Codex協議済み v2.3）:
- CLAUDE.md の chat.log 監視ループを置き換える次世代モニタ
- 毎ループ claude_heartbeat/{source}.json に ts を書き込み（外部watchdogが読む）
- inbox/new/ にJSONが現れたら原子的に claimed/ へ移動し、ペイロードをstdoutへ出す
- exit 0 で Claude のBackgroundタスクに通知が飛ぶ → 会話ループが再開
- claim メタ: {pid, ts_claimed, status:"processing"}
  - status は会話が終わる時に "waiting_user" または "done" に更新して良い
- exactly-once: os.rename が原子的なので重複消費なし

エラー方針（v2.2 Codex修正）:
- FileNotFoundError は「他プロセスに取られた」競合として None 返却
- それ以外の OSError (EACCES, EXDEV 等) は MonitorError として非0終了
- 壊れたJSONを発見した場合は中身を一切上書きせず claimed/ に退避し、
  INVALID_JSON を出して非0終了する（証拠保全）
- heartbeat はエラー発生時には更新しない → 連続失敗すれば watchdog が検知する

cron 運用前提（v2.3 Codex協議で周期緩和）:
- --oneshot は CronCreate の cron="*/3 * * * *" (3分毎) 前提で動く
- claude_watchdog.py の THRESH_CRON=600s と整合 (cron 3分 + ジッタ・リカバリ = 最悪240s < 600s)
- cron 周期を 3分より長くすると watchdog 閾値も上げる必要あり

--silent-if-empty (v2.3 新規):
  新着無しの時は stdout を一切出さない (NO_NEW_MESSAGE も出力しない)。
  Claude Code の会話コンテキスト圧迫対策。heartbeat 書き込みは従来通り。

使い方:
  # Claude Code の background 監視ループとして
  python3 scripts/discord_inbox_monitor.py --source background

  # CronCreate のバックアップ監視として (1回だけ確認して終わる)
  python3 scripts/discord_inbox_monitor.py --source cron --oneshot --silent-if-empty
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = PROJECT_ROOT / "tmp_discord"
INBOX_NEW = TMP_DIR / "inbox" / "new"
INBOX_CLAIMED = TMP_DIR / "inbox" / "claimed"
HEARTBEAT_DIR = TMP_DIR / "claude_heartbeat"

# NOTE: claude_watchdog.py の THRESH_CRON=600s と整合。3分 (180s) 以下の呼び出し周期推奨。
CRON_EXPECTED_INTERVAL_SEC = 180

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _atomic import atomic_write_json  # noqa: E402


class MonitorError(Exception):
    """致命的なI/O失敗。watchdogが検知できるよう非0終了に寄せる"""


def _write_heartbeat(source: str) -> None:
    """heartbeat JSONを原子的に書く。失敗したら MonitorError"""
    try:
        HEARTBEAT_DIR.mkdir(parents=True, exist_ok=True)
        atomic_write_json(
            HEARTBEAT_DIR / f"{source}.json",
            {
                "ts": time.time(),
                "source": source,
                "pid": os.getpid(),
            },
        )
    except OSError as e:
        raise MonitorError(f"heartbeat write failed: {e}") from e


def _oldest_new_file() -> Path | None:
    """inbox/new/ の最古のJSON（ファイル名順＝unix_ns順）を返す"""
    if not INBOX_NEW.exists():
        return None
    try:
        files = sorted(p for p in INBOX_NEW.iterdir() if p.suffix == ".json")
    except FileNotFoundError:
        return None  # dir が途中で消えた競合
    except OSError as e:
        raise MonitorError(f"new/ unreadable: {e}") from e
    return files[0] if files else None


def _claim(src: Path) -> tuple[str, Path | None]:
    """原子的に new → claimed へ移動し、claim メタを追記

    戻り値:
        ("ok", dst)           - 成功: claimed/ にペイロード付き
        ("invalid_json", dst) - claimed/ に退避成功だが中身がJSONとして壊れている
        ("race", None)        - 他プロセスに先に取られた

    例外:
        MonitorError - 致命的なI/O失敗（EXDEV, EACCES 等）
    """
    try:
        INBOX_CLAIMED.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise MonitorError(f"claimed/ mkdir failed: {e}") from e

    dst = INBOX_CLAIMED / src.name
    try:
        os.rename(src, dst)
    except FileNotFoundError:
        return ("race", None)
    except OSError as e:
        # EXDEV (cross-filesystem), EACCES 等は致命的
        raise MonitorError(f"claim rename failed ({src.name}): {e}") from e

    # ここからは dst を所有している。以下失敗しても dst は claimed/ に残る
    try:
        raw = dst.read_text(encoding="utf-8")
    except OSError as e:
        raise MonitorError(f"claim read failed ({dst.name}): {e}") from e

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        # 壊れたJSON: 中身を一切上書きせず証拠保全
        return ("invalid_json", dst)

    if not isinstance(data, dict):
        return ("invalid_json", dst)

    # claim メタを追記
    data["claim"] = {
        "pid": os.getpid(),
        "ts_claimed": time.time(),
        "status": "processing",
    }
    try:
        atomic_write_json(dst, data)
    except OSError as e:
        raise MonitorError(f"claim meta write failed ({dst.name}): {e}") from e
    return ("ok", dst)


def _emit_claimed(claimed_path: Path) -> None:
    """Claude向けにstdoutへペイロードを出す"""
    try:
        data = json.loads(claimed_path.read_text(encoding="utf-8"))
    except Exception as e:
        raise MonitorError(f"emit read failed ({claimed_path.name}): {e}") from e
    print("NEW_DISCORD_MESSAGE")
    print(f"CLAIMED_FILE: {claimed_path}")
    print(json.dumps(data, ensure_ascii=False, indent=2))


def _check_once(source: str) -> bool:
    """1回だけ inbox/new/ をチェック

    戻り値: True = 新着を claim して出力した, False = 新着なし/競合
    例外: MonitorError = 壊れたJSON or 致命的I/O失敗
    """
    f = _oldest_new_file()
    if f is None:
        return False
    status, claimed = _claim(f)
    if status == "race":
        return False
    if status == "invalid_json":
        assert claimed is not None
        print(f"INVALID_JSON: {claimed}")
        raise MonitorError(
            f"invalid JSON quarantined to claimed/: {claimed.name}"
        )
    # ok
    assert claimed is not None
    _emit_claimed(claimed)
    return True


def _read_other_heartbeat_age(source: str) -> float:
    """別sourceのheartbeat経過秒を返す。無ければ inf

    Codex Round5: NaN/Infinity/未来時刻/負値は全て「壊れた heartbeat」扱いで inf。
    json.loads は NaN/Infinity を float として通すので isinstance だけでは不十分。
    math.isfinite() で有限実数のみ許可し、さらに未来時刻(age<0) も異常値として弾く。
    """
    p = HEARTBEAT_DIR / f"{source}.json"
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return float("inf")
    if not isinstance(data, dict):
        return float("inf")
    ts = data.get("ts")
    # bool は int の派生クラスなので除外、NaN/Infinity は isfinite で除外
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        return float("inf")
    if not math.isfinite(float(ts)):
        return float("inf")
    try:
        age = time.time() - float(ts)
    except (TypeError, ValueError):
        return float("inf")
    if not math.isfinite(age):
        return float("inf")
    if age < 0:
        # 未来時刻 = 時計ずれ or 壊れた値。安全側で stale 扱い
        return float("inf")
    return age


# background が生きていれば 5s 間隔でheartbeat更新される。
# 30s は「ほぼ確実に落ちている」閾値 (正常系は 5-10s)。
BG_STALE_THRESHOLD_SEC = 30


def _run(args: argparse.Namespace) -> int:
    if args.oneshot:
        # エラー時に heartbeat を更新しないため、成功後に書く
        try:
            found = _check_once(args.source)
        except MonitorError:
            # heartbeat は意図的に更新しない
            raise
        _write_heartbeat(args.source)
        if not found and not args.silent_if_empty:
            print("NO_NEW_MESSAGE")
        # v2.3 Round5: cron からは background 監視の生存も監視する。
        # bg が落ちていると Discord リアルタイム応答(5秒周期)が死ぬので、
        # silent_if_empty であっても警告だけは出す → Claude が気づいて再起動する。
        if args.source == "cron":
            bg_age = _read_other_heartbeat_age("background")
            if bg_age > BG_STALE_THRESHOLD_SEC:
                if bg_age == float("inf"):
                    print(
                        "BG_MONITOR_STALE: background heartbeat not found "
                        "— `python3 scripts/discord_inbox_monitor.py --source background` "
                        "を run_in_background で起動してください"
                    )
                else:
                    print(
                        f"BG_MONITOR_STALE: background heartbeat age={bg_age:.0f}s "
                        f"(閾値 {BG_STALE_THRESHOLD_SEC}s) "
                        "— `python3 scripts/discord_inbox_monitor.py --source background` "
                        "を run_in_background で再起動してください"
                    )
        return 0

    # background ループ: 初回 heartbeat は session 開始シグナルとして書く
    _write_heartbeat(args.source)
    for _ in range(args.max_iter):
        if _check_once(args.source):
            _write_heartbeat(args.source)
            return 0
        _write_heartbeat(args.source)
        time.sleep(args.interval)

    print("MONITOR_TIMEOUT")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--source",
        default="background",
        choices=["background", "cron", "hook"],
        help="heartbeat source名",
    )
    ap.add_argument(
        "--interval",
        type=float,
        default=5.0,
        help="ループ間隔秒 (default: 5.0)",
    )
    ap.add_argument(
        "--max-iter",
        type=int,
        default=17280,
        help=(
            "最大ループ回数 (interval*max_iter = 最大実行時間、"
            "default 17280 × 5秒 = 24時間)。"
            "呼び出し側の timeout も同程度にする必要がある"
        ),
    )
    ap.add_argument(
        "--oneshot",
        action="store_true",
        help="1回チェックしてheartbeat更新のみで終わる (cron用、3分周期前提)",
    )
    ap.add_argument(
        "--silent-if-empty",
        action="store_true",
        dest="silent_if_empty",
        help="新着が無い時は stdout を一切出さない (NO_NEW_MESSAGE も抑制)",
    )
    args = ap.parse_args()

    try:
        return _run(args)
    except MonitorError as e:
        print(f"MONITOR_ERROR: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
