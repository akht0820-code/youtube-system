"""Claude Watchdog - Claude Code側の死活/backlogを外部から監視

設計方針（Codex協議済み v2.3）:
- Windows Task Scheduler から3分毎に実行される外部独立監視 (pythonw.exe 直接起動)
- Claude が死んでる/監視が止まってることを検知 → Discord通知
- Bot側監視は discord_watchdog.py に分離（責務分離、両者独立動作）
- heartbeat は source 別ファイル: tmp_discord/claude_heartbeat/{background,cron,hook}.json
- alert 状態は tmp_discord/alerts/*.json に保存（1ファイル1key、競合ゼロ）
- 通知は outbox 経由（Bot生きてる前提）+ claude_watchdog.log 追記（監査証跡）

実行パス:
  Windows側: C:\\Users\\user\\Desktop\\youtube-system\\scripts\\claude_watchdog.py
  pythonw.exe 直接起動 (コンソール窓なし)

判定ロジック（v2.3 Codex Round5 final）:
  Backlog   = inbox/new/ に 600秒以上古いファイルあり (cron 3分周期と整合)
              → Discord に警告通知

  Dead      = background AND cron の両方の heartbeat が 1800秒(30分) 以上古い
              → Discord に警告通知 (真の Claude 死亡)
              両方揃った時のみ発火。30分なら動画生成(15分)も飲み込める。

  BG Down   = background heartbeat が 600秒以上古い AND cron heartbeat が fresh
              → Discord に警告通知 (Claudeは生きてるが bg 監視だけ落ちた)
              ユーザー不在中の bg 死亡を即検知するため。
              cron が fresh = Claude セッションは生きている証拠。
              bg だけ落ちている = Discord リアルタイム応答不能。

  Stuck 検知（claimed/ ベース）は廃止（Round3 指摘）:
    claim.status の auto-update が信頼できず、"processing" のまま放置されて
    毎回誤報になる。真の死亡は上記 Dead 条件で捕捉する。

Alert state machine:
  OK → down 検知: 即1回通知、state=down
  down 継続: 1800秒(30分)ごとに再通知
  down → ok 復帰: 1回復旧通知

pythonw.exe 対応:
  - _log() は print() を使わない (stdout が None の可能性)
  - sys.stderr を claude_watchdog_stderr.log にリダイレクト
  - sys.excepthook で未捕捉例外を _log() に書く
  - run_state.json で前回 run の ended_cleanly を追跡（ハング証跡、ログのみ）

Dry-run mode:
  環境変数 CLAUDE_WATCHDOG_DRY_RUN=1 ならログのみ、Discord通知しない
"""

from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from uuid import uuid4

# プロジェクトルート (Windows絶対パス or /mnt/c パス、どちらでも動く)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
TMP_DIR = PROJECT_ROOT / "tmp_discord"
HEARTBEAT_DIR = TMP_DIR / "claude_heartbeat"
ALERTS_DIR = TMP_DIR / "alerts"
INBOX_NEW = TMP_DIR / "inbox" / "new"
INBOX_CLAIMED = TMP_DIR / "inbox" / "claimed"
OUTBOX_DIR = TMP_DIR / "outbox"
LOGS_DIR = PROJECT_ROOT / "logs"
WATCHDOG_LOG = LOGS_DIR / "claude_watchdog.log"
WATCHDOG_STDERR_LOG = LOGS_DIR / "claude_watchdog_stderr.log"
RUN_STATE_FILE = LOGS_DIR / "claude_watchdog_run_state.json"

# 閾値（秒） v2.3 Codex Round5 final
# NOTE: 閾値は discord_inbox_monitor.py の運用周期と整合させる必要がある
#   background: 5秒間隔ループ → 通常 1-10s
#   cron     : 3分周期 (CronCreate "*/3 * * * *") → 通常 180s
#   backlog  : 600秒 = cron最悪遅延(240秒) + マージン
#   dead     : 1800秒 = 30分 (動画生成15分+マージン)、AND条件で発火
#   bg_down  : 600秒 = 10分 (bg正常は5s、10分沈黙は確実に死亡), AND cron_fresh
THRESH_DEAD = 1800         # bg/cron両方が1800s以上古い時のみ Claude dead と判定
THRESH_BACKLOG = 600       # new/ 内のファイルが 600秒以上古いと backlog (通知対象)
THRESH_BG_DOWN = 600       # bg heartbeat が 600s 以上古い + cron fresh で bg_down
THRESH_CRON_FRESH = 600    # cron が 600s 未満なら fresh (bg_down 判定の前提条件)
ALERT_REPEAT_SEC = 1800    # 障害継続中の再通知間隔 (30分)

# 原子的書き込みヘルパ
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from _atomic import atomic_write_json, safe_read_json
except ImportError:
    # Windows側で scripts/ が PATH に無い場合の fallback
    def atomic_write_json(path, obj):  # type: ignore
        p = Path(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)

    def safe_read_json(path, default=None):  # type: ignore
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return default


# --- ログ ---
# pythonw.exe 下では sys.stdout が None の可能性があるため print() は使わない。
# 書き込みは WATCHDOG_LOG のみ。失敗しても静かに諦める (watchdog自体が落ちない)。

def _log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}\n"
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        # 1MB超でローテ
        if WATCHDOG_LOG.exists() and WATCHDOG_LOG.stat().st_size > 1_000_000:
            for i in range(4, 0, -1):
                old = WATCHDOG_LOG.with_suffix(f".log.{i}")
                new = WATCHDOG_LOG.with_suffix(f".log.{i+1}")
                if old.exists():
                    old.rename(new)
            WATCHDOG_LOG.rename(WATCHDOG_LOG.with_suffix(".log.1"))
        with open(WATCHDOG_LOG, "a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


# --- pythonw.exe 下での死に方を見える化 ---

def _setup_pythonw_fallbacks() -> None:
    """pythonw.exe 下では stdout/stderr が None になりうる。早期に差し替えておく。

    やること:
    - sys.stderr を WATCHDOG_STDERR_LOG に append リダイレクト
    - sys.stdout は None のままだと print() が落ちるので、/dev/null 相当に差し替え
    - sys.excepthook を差し替え、未捕捉例外を _log() へ書く
    """
    import traceback as _tb
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass

    # stderr を永続ログに
    try:
        if sys.stderr is None:
            sys.stderr = open(WATCHDOG_STDERR_LOG, "a", encoding="utf-8", buffering=1)
        else:
            # pythonw の場合 sys.stderr は None だが、cmd 経由の場合は開いているので
            # そちらは壊さず、NoneだけファイルにリダイレクトするためのガードでOK
            pass
    except Exception:
        pass

    # stdout も None の可能性があるので、念のため黙らせる
    try:
        if sys.stdout is None:
            sys.stdout = open(os.devnull, "w", encoding="utf-8")
    except Exception:
        pass

    # 未捕捉例外は _log() に書く
    def _excepthook(exc_type, exc_value, exc_tb):
        try:
            lines = _tb.format_exception(exc_type, exc_value, exc_tb)
            _log("[FATAL] uncaught exception:\n" + "".join(lines))
        except Exception:
            pass

    try:
        sys.excepthook = _excepthook
    except Exception:
        pass


# import 段階で即実行: _begin_run() や _log() より前の import エラーも拾えるよう、
# モジュールロード直後に stdout/stderr/excepthook を差し替える。
# （v2.3 Codex協議: main() 内で呼ぶと import 段階の例外が闇に消える）
_setup_pythonw_fallbacks()


# --- run_state: 前回 run の清潔な終了を追跡 ---

def _load_run_state() -> dict:
    return safe_read_json(RUN_STATE_FILE, default={}) or {}


def _begin_run() -> str:
    """前回 run の ended_cleanly をチェックし、START を書く。
    前回が ended_cleanly=False or 欠落なら WARN ログに残す（Discord通知はしない）。

    v2.3 Codex協議:
    - 並行起動 (schtasks + 手動実行など) で前回 run が "まだ走ってるだけ" のケースがあり、
      毎回 WARN を吐くと誤報になる。
    - ExecutionTimeLimit=PT3M=180s を超えたら初めて "ハングの可能性あり" と判定。
      それ以下は単なる並行実行とみなして何も言わない。
    """
    TASK_EXEC_LIMIT_SEC = 180  # claude_watchdog_task.xml の ExecutionTimeLimit=PT3M
    HANG_GRACE_SEC = 60        # さらに余裕マージン（Task Schedulerのkill遅延吸収）
    prev = _load_run_state()
    if prev and not prev.get("ended_cleanly", False):
        prev_start = prev.get("start_ts", 0)
        try:
            age = max(0.0, time.time() - float(prev_start)) if prev_start else 0.0
        except (TypeError, ValueError):
            age = 0.0
        if age > (TASK_EXEC_LIMIT_SEC + HANG_GRACE_SEC):
            _log(
                f"[WARN] previous run did not end cleanly "
                f"(run_id={prev.get('run_id','?')}, start_age={age:.0f}s "
                f"> {TASK_EXEC_LIMIT_SEC + HANG_GRACE_SEC}s) "
                f"— possible hang, crash, or hard terminate"
            )
        # age が short なら並行起動の可能性大、黙る
    run_id = uuid4().hex[:12]
    new_state = {
        "run_id": run_id,
        "start_ts": time.time(),
        "pid": os.getpid(),
        "ended_cleanly": False,
    }
    try:
        atomic_write_json(RUN_STATE_FILE, new_state)
    except Exception as e:
        _log(f"[WARN] run_state write failed on start: {e}")
    return run_id


def _end_run(run_id: str) -> None:
    """正常終了を記録"""
    try:
        state = _load_run_state()
        if state.get("run_id") != run_id:
            # 同時実行されている場合は自分の run_id が上書きされているので触らない
            return
        state["ended_cleanly"] = True
        state["end_ts"] = time.time()
        atomic_write_json(RUN_STATE_FILE, state)
    except Exception as e:
        _log(f"[WARN] run_state write failed on end: {e}")


# --- heartbeat 読み取り ---

def _read_heartbeat_age(source: str) -> float:
    """source別heartbeatの経過秒を返す。無ければ inf

    v2.3 Codex協議:
    - safe_read_json は JSON構文エラーしか拾わない
    - {"ts": ""} のような型崩れだと float() が ValueError で watchdog 自滅
    - isinstance チェック + try/except で防御、崩れていれば inf 扱い（stale判定）
    """
    p = HEARTBEAT_DIR / f"{source}.json"
    data = safe_read_json(p)
    if not isinstance(data, dict):
        return float("inf")
    ts = data.get("ts")
    # NOTE: bool は int の派生クラスなので isinstance(ts, int) で通ってしまう。
    #       {"ts": true} → time.time()-1 扱いで「壊れた heartbeat を正常と誤判定」する
    #       Codex Round4 指摘。明示的に bool を弾く。
    if isinstance(ts, bool) or not isinstance(ts, (int, float)):
        _log(f"[WARN] heartbeat {source}: ts type invalid ({type(ts).__name__})")
        return float("inf")
    # Codex Round5: NaN/Infinity も json.loads は通すので math.isfinite で除外。
    # 未来時刻 (age<0) も壊れたクロック扱いで stale 判定する。
    if not math.isfinite(float(ts)):
        _log(f"[WARN] heartbeat {source}: ts non-finite ({ts})")
        return float("inf")
    try:
        age = time.time() - float(ts)
    except (TypeError, ValueError) as e:
        _log(f"[WARN] heartbeat {source}: ts value invalid: {e}")
        return float("inf")
    if not math.isfinite(age) or age < 0:
        _log(f"[WARN] heartbeat {source}: age invalid ({age})")
        return float("inf")
    return age


def _check_claude_dead() -> tuple[bool, dict]:
    """Claude が死亡しているか判定。bg AND cron 両方が stale の時のみ True。

    v2.3 Codex Round4:
    - OR 条件 (片方生きていればOK) → ほぼ誤報源なし。しかし「claimed/ に取った直後に
      Claude 死亡」ケースで何も飛ばない問題があった。
    - AND 条件で両方 1800s (30分) 以上古い場合のみ「真の死亡」と判定し通知。
    - 30分は動画生成 (15分程度) を飲み込める安全閾値。
    """
    bg_age = _read_heartbeat_age("background")
    cron_age = _read_heartbeat_age("cron")
    hook_age = _read_heartbeat_age("hook")
    # AND 条件: 両方が閾値超え
    dead = (bg_age > THRESH_DEAD) and (cron_age > THRESH_DEAD)
    return dead, {
        "background_age": bg_age,
        "cron_age": cron_age,
        "hook_age": hook_age,
    }


# --- inbox backlog ---

def _scan_inbox_backlog() -> tuple[int, list[str]]:
    """未処理 backlog を数える。返り値 (backlog_count, sample_names)

    v2.3 Codex協議 Round3:
    - stuck (claimed/ が古い) 判定は撤廃。claim.status の auto-update が不確実で
      毎回誤報になるため。
    - new/ だけを p.stat().st_mtime で判定 (外部Botが書いたタイミング)
    """
    now = time.time()
    samples: list[str] = []
    backlog = 0
    if INBOX_NEW.exists():
        for p in INBOX_NEW.iterdir():
            if p.suffix != ".json":
                continue
            try:
                age = now - p.stat().st_mtime
            except OSError:
                continue
            if age > THRESH_BACKLOG:
                backlog += 1
                if len(samples) < 3:
                    samples.append(p.name)
    return backlog, samples


# --- alert state machine ---

def _alert_file(key: str) -> Path:
    return ALERTS_DIR / f"{key}.json"


def _load_alert_state(key: str) -> dict:
    data = safe_read_json(_alert_file(key), default={})
    if not data:
        return {"state": "ok", "down_since": 0, "last_alert_ts": 0, "alert_count": 0}
    return data


def _save_alert_state(key: str, state: dict) -> None:
    atomic_write_json(_alert_file(key), state)


def _should_notify(key: str, is_down: bool) -> tuple[bool, str, dict]:
    """通知すべきか判定。戻り値 (should_notify, reason, new_state)"""
    now = time.time()
    cur = _load_alert_state(key)
    cur_state = cur.get("state", "ok")

    if is_down:
        if cur_state == "ok":
            # 初回検知
            new = {
                "state": "down",
                "down_since": now,
                "last_alert_ts": now,
                "alert_count": 1,
            }
            return True, "initial_down", new
        else:
            # 継続中
            elapsed = now - cur.get("last_alert_ts", 0)
            if elapsed >= ALERT_REPEAT_SEC:
                new = dict(cur)
                new["last_alert_ts"] = now
                new["alert_count"] = cur.get("alert_count", 0) + 1
                return True, "continue_down", new
            else:
                return False, "suppressed", cur
    else:
        # alive
        if cur_state == "down":
            # 復旧通知
            new = {
                "state": "ok",
                "down_since": 0,
                "last_alert_ts": now,
                "alert_count": 0,
            }
            return True, "recovered", new
        else:
            return False, "still_ok", cur


# --- 通知 (outbox経由) ---

def _send_outbox_alert(text: str) -> bool:
    """outbox/ にJSONを書き込み、Botに転送してもらう"""
    dry_run = os.environ.get("CLAUDE_WATCHDOG_DRY_RUN", "") == "1"
    if dry_run:
        _log(f"[DRY_RUN] would send: {text[:100]}")
        return True
    try:
        OUTBOX_DIR.mkdir(parents=True, exist_ok=True)
        ts = time.time()
        fname = f"{ts:.6f}_{uuid4().hex[:8]}.json"
        payload = {"timestamp": ts, "text": text, "files": []}
        atomic_write_json(OUTBOX_DIR / fname, payload)
        return True
    except Exception as e:
        _log(f"[ERROR] outbox write failed: {e}")
        return False


# --- main ---

def main() -> int:
    run_id = _begin_run()

    _log(f"=== check start (run_id={run_id}) ===")
    dead, hb = _check_claude_dead()
    _log(
        f"heartbeat: bg={hb['background_age']:.0f}s cron={hb['cron_age']:.0f}s "
        f"hook={hb['hook_age']:.0f}s dead={dead}"
    )

    # Dead 通知 (bg AND cron 両方 stale の時のみ)
    should, reason, new_state = _should_notify("claude_dead", dead)
    _save_alert_state("claude_dead", new_state)
    if should:
        if reason == "recovered":
            msg = "[復旧] Claudeセッションが復帰しました。"
        else:
            msg = (
                f"[警告] Claudeセッションが停止している可能性があります。"
                f"background heartbeat: {hb['background_age']:.0f}s / "
                f"cron heartbeat: {hb['cron_age']:.0f}s "
                f"（両方 {THRESH_DEAD}秒以上古い）。"
            )
        _send_outbox_alert(msg)
        _log(f"claude_dead notified: {reason}")

    # BG Down 通知 (Claude 生きてるが bg 監視だけ死んでいる)
    # Dead と違って AND 条件が「bg stale AND cron fresh」
    bg_age = hb["background_age"]
    cron_age = hb["cron_age"]
    bg_down = (bg_age > THRESH_BG_DOWN) and (cron_age < THRESH_CRON_FRESH)
    should, reason, new_state = _should_notify("claude_bg_down", bg_down)
    _save_alert_state("claude_bg_down", new_state)
    if should:
        if reason == "recovered":
            msg = "[復旧] Discord background 監視が復帰しました。"
        else:
            msg = (
                f"[警告] Discord background 監視が落ちています "
                f"(bg heartbeat age={bg_age:.0f}s > {THRESH_BG_DOWN}s、cron は fresh)。"
                f"Claude セッションは生きていますが Discord リアルタイム応答ができません。"
                f"PCで `python3 scripts/discord_inbox_monitor.py --source background` "
                f"を再起動してください。"
            )
        _send_outbox_alert(msg)
        _log(f"claude_bg_down notified: {reason} bg_age={bg_age:.0f}")

    backlog, samples = _scan_inbox_backlog()
    _log(f"inbox: backlog={backlog} samples={samples}")

    # Backlog 通知
    should, reason, new_state = _should_notify("claude_backlog", backlog > 0)
    _save_alert_state("claude_backlog", new_state)
    if should:
        if reason == "recovered":
            msg = "[復旧] Discord未処理メッセージが解消しました。"
        else:
            msg = (
                f"[警告] Discord未処理メッセージが {backlog} 件あります"
                f"（{THRESH_BACKLOG}秒以上未消費）。Claude側の受信処理を確認してください。"
            )
        _send_outbox_alert(msg)
        _log(f"claude_backlog notified: {reason} count={backlog}")

    _log("=== check end ===")
    _end_run(run_id)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        # sys.excepthook は main() 内で設定されるが、その前に落ちた場合の保険
        import traceback
        try:
            _log("[FATAL] top-level exception:\n" + traceback.format_exc())
        except Exception:
            pass
        sys.exit(1)
