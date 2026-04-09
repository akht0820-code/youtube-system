"""UserPromptSubmit hook 用: claimed/processing の高齢未処理メッセージを検出

設計（Codex協議 v1 2026-04-10）:
- inbox/claimed/*.json を走査
- 条件:
  1. claim.status が done/waiting_user 以外（= processing/未定義）
  2. ts_claimed age > STALE_THRESHOLD_SEC (default 600s)
  3. sidecar tmp_discord/alerts/claimed_notified/<basename>.json が未作成
- 検出したら stdout に注入用テキストを出し、sidecar を作成
- sidecar は 1 ファイル 1 メッセージで competing writers 同士が衝突しない
- claim 本体は一切触らない（実処理側との read-modify-write 競合回避）

なぜ sidecar 方式か:
- Codex 指摘: claim.status を hook と本体が同時に書くと compare-and-swap 無しで競合
- claim 本体を変更すると実処理側の done マーキングと race する
- sidecar は 1 ファイル 1 キー、hook だけが書く領域なので競合しない

なぜ Python helper に切り出したか:
- hook 内で shell + python2spawn は可読性/保守性が低い
- 1 箇所にロジックを集約して単体で動作確認できる

使い方:
    python3 scripts/discord_hook_check_claimed.py
    # 何もなければ無出力 exit 0
    # 高齢未処理があれば UNPROCESSED_DISCORD_MESSAGE セクションを出力 exit 0
"""

from __future__ import annotations

import heapq
import json
import math
import os
import sys
import time
from pathlib import Path

# cp932 防御（Codex Round 3 指摘）:
# Windows コンソール (cp932) から呼ばれても絶対に UnicodeEncodeError で落ちないよう、
# stdout/stderr を backslashreplace に切り替える。WSL の UTF-8 環境では副作用なし。
# reconfigure は Python 3.7+ で常に使える。失敗しても起動は続行。
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(errors="backslashreplace")  # type: ignore[attr-defined]
        except Exception:
            pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
CLAIMED_DIR = PROJECT_ROOT / "tmp_discord" / "inbox" / "claimed"
SIDECAR_DIR = PROJECT_ROOT / "tmp_discord" / "alerts" / "claimed_notified"

# watchdog の THRESH_BACKLOG=600s と揃えて誤報を減らす
STALE_THRESHOLD_SEC = 600
# 1 メッセージあたり注入する text の最大長
MAX_TEXT_LEN = 200
# 1 回の hook 発火で注入する最大メッセージ数（ログ肥大化防止）
MAX_MESSAGES_PER_CALL = 5
# 除外する終端 status
TERMINAL_STATUSES = {"done", "waiting_user"}


def _mtime_age(p: Path, now: float) -> float | None:
    """p の mtime から経過秒を返す。取得失敗 or 非有限/負値なら None"""
    try:
        mt = p.stat().st_mtime
    except OSError:
        return None
    if not math.isfinite(mt):
        return None
    age = now - float(mt)
    if not math.isfinite(age) or age < 0:
        return None
    return age


def _sidecar_exists(claimed_basename: str) -> bool:
    return (SIDECAR_DIR / f"{claimed_basename}.json").exists()


# sidecar 作成系の失敗を main() 側で集計して stdout に surfacing するためのバッファ
# （hook stderr は /dev/null 行きなので stdout に寄せないと Claude が気づけない）
_SIDECAR_FAILURES: list[str] = []


def _create_sidecar(claimed_basename: str, reason: str) -> bool:
    """sidecar を原子的に作成。成否を返す。

    Codex Round N+1 指摘対応:
    - O_CREAT|O_EXCL で exactly-once を保証（TOCTOU race 防止）
    - hook と cron が同時に同一ファイルを走査しても、sidecar 作成に成功した
      プロセスだけが「通知権」を持ち、もう片方は FileExistsError で False 返却

    Codex Round 3 残留リスク対応:
    - mkdir/open/write 失敗は stderr + _SIDECAR_FAILURES に記録、main() で stdout surfacing
    - hook stderr は /dev/null に行くので stderr だけでは観測不能だった

    仕様メモ (Codex Round 3):
    - sidecar の basename は claim ファイル名と 1:1 なので、同一 claim に対する
      stale 通知と broken 通知は同一 sidecar で抑制される。つまり「broken で先に
      通知→手修復で stale に変わる」シナリオでは再通知されない。claim を修復した
      オペレータは sidecar を手動削除するか、claim.status を done にして廃棄する運用。
    """
    try:
        SIDECAR_DIR.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        msg = f"sidecar dir mkdir failed: {e}"
        print(f"[discord_hook_check_claimed] {msg}", file=sys.stderr)
        _SIDECAR_FAILURES.append(msg)
        return False

    target = SIDECAR_DIR / f"{claimed_basename}.json"
    payload = json.dumps(
        {
            "ts_notified": time.time(),
            "source": "hook_check_claimed",
            "reason": reason,
        },
        ensure_ascii=False,
    ).encode("utf-8")
    try:
        fd = os.open(
            str(target),
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o644,
        )
    except FileExistsError:
        # 他プロセスが先に取った。exactly-once を保つため False（失敗記録しない）
        return False
    except OSError as e:
        msg = f"sidecar open failed ({target.name}): {e}"
        print(f"[discord_hook_check_claimed] {msg}", file=sys.stderr)
        _SIDECAR_FAILURES.append(msg)
        return False
    try:
        try:
            os.write(fd, payload)
        finally:
            os.close(fd)
    except OSError as e:
        # 中身書き込み失敗: 残骸を消して次回リトライ可能にする
        msg = f"sidecar write failed ({target.name}): {e}"
        print(f"[discord_hook_check_claimed] {msg}", file=sys.stderr)
        _SIDECAR_FAILURES.append(msg)
        try:
            target.unlink()
        except OSError:
            pass
        return False
    return True


def _classify(p: Path, now: float) -> tuple[dict, float, str] | None:
    """1 件の claim ファイルを分類して (data, age, kind) を返す

    kind:
      "stale"  - 正常な claim だが age > STALE_THRESHOLD_SEC
      "broken" - JSON 破損・非dict・claim 欠損・ts_claimed 異常の stale (mtime 基準)
      None     - 健全 or 検知閾値未満 or 読み取り消滅（race）

    broken の発生源（全て stdout 経由で Claude に surfacing する対象）:
    - read error (権限/破損)
    - invalid JSON
    - 非 dict ペイロード
    - claim メタ欠損 / 非 dict
    - ts_claimed の型異常（bool/非数値）or 非有限値
    """
    try:
        raw = p.read_text(encoding="utf-8")
    except FileNotFoundError:
        # claimed/ から消えた: 別プロセスが手動で片付けた等、sane な race。無視
        return None
    except OSError as e:
        age = _mtime_age(p, now)
        if age is None or age < STALE_THRESHOLD_SEC:
            return None
        return ({"user": "?", "text": f"<READ_ERROR: {e}>"}, age, "broken")

    try:
        data = json.loads(raw)
    except (json.JSONDecodeError, ValueError) as e:
        age = _mtime_age(p, now)
        if age is None or age < STALE_THRESHOLD_SEC:
            return None
        return ({"user": "?", "text": f"<INVALID_JSON: {e}>"}, age, "broken")

    if not isinstance(data, dict):
        age = _mtime_age(p, now)
        if age is None or age < STALE_THRESHOLD_SEC:
            return None
        return ({"user": "?", "text": "<NOT_A_DICT>"}, age, "broken")

    claim = data.get("claim")
    if not isinstance(claim, dict):
        # claim メタ欠損: 書きかけ or 壊れ。mtime で stale 判定
        age = _mtime_age(p, now)
        if age is None or age < STALE_THRESHOLD_SEC:
            return None
        return (data, age, "broken")

    status = claim.get("status")
    if status in TERMINAL_STATUSES:
        return None

    ts_claimed = claim.get("ts_claimed")
    # bool は int 派生なので先に除外、NaN/Infinity は isfinite で除外
    ts_bad = (
        isinstance(ts_claimed, bool)
        or not isinstance(ts_claimed, (int, float))
        or not math.isfinite(float(ts_claimed))
    )
    if ts_bad:
        age = _mtime_age(p, now)
        if age is None or age < STALE_THRESHOLD_SEC:
            return None
        return (data, age, "broken")

    age = now - float(ts_claimed)
    if not math.isfinite(age):
        return None
    if age < 0:
        # 未来時刻 = 時計ずれ、安全側で無視
        return None
    if age < STALE_THRESHOLD_SEC:
        return None
    return (data, age, "stale")


def _collect_stale(limit: int) -> list[tuple[Path, dict, float, str]]:
    """高齢未処理/壊れた claim を limit 件まで収集して早期 return

    Codex Round 2 指摘対応:
    - sorted() で全件ソート(O(N log N)) ではなく heapq で O(N + k log N)
      ※ heapify は O(N)、heappop×k は O(k log N)。k=limit=5 で実質線形。
    - 壊れた claim を silent skip せず "broken" として stdout surfacing 対象にする
      （検知の検知: 壊れた inbox が検知できないのは不可視化と同じ）

    scandir 失敗時の扱い（Codex Round 3 指摘対応）:
    - OSError (permission/I/O) は監視機能そのものの異常なので stdout に警告を出す
    - 毎回騒がしくなるのは妥協。claimed/ が読めない状態は stale 以上の緊急事態
    - hook stderr は /dev/null に行くので、stderr だけでは検知不可
    """
    if not CLAIMED_DIR.exists():
        return []
    now = time.time()
    try:
        # scandir + 名前フィルタ。os.scandir は Path.iterdir より軽い
        names = [
            e.name
            for e in os.scandir(CLAIMED_DIR)
            if e.is_file() and e.name.endswith(".json")
        ]
    except FileNotFoundError:
        return []
    except OSError as e:
        # stdout に出して Claude に surfacing (stderr だと hook 経由で消える)
        print(
            f"[HOOK_SCAN_FAILED] claimed/ を読めません: {e}. "
            f"path={CLAIMED_DIR}. Discord stale 検知が停止しています。"
            "権限や fs の状態を確認してください。"
        )
        return []

    # unix_ns プレフィックス固定幅 → lex 順 == 時系列順（最古 = min）。
    # heapify は O(N)、heappop は O(log N)。k 件取り出す間だけ回す。
    heapq.heapify(names)
    results: list[tuple[Path, dict, float, str]] = []
    while names and len(results) < limit:
        name = heapq.heappop(names)
        if _sidecar_exists(name):
            continue
        p = CLAIMED_DIR / name
        classified = _classify(p, now)
        if classified is None:
            continue
        data, age, kind = classified
        results.append((p, data, age, kind))
    return results


def _emit_message(path: Path, data: dict, age: float, kind: str) -> None:
    user = str(data.get("user", "?"))[:80]
    text = str(data.get("text", "?")).replace("\n", " ")[:MAX_TEXT_LEN]
    tag = (
        "[UNPROCESSED_DISCORD_MESSAGE]"
        if kind == "stale"
        else "[BROKEN_CLAIM_DETECTED]"
    )
    print(f"{tag} kind={kind} age={age:.0f}s file={path.name}")
    print(f"  user: {user}")
    print(f"  text: {text}")
    print(f"  CLAIMED_FILE: {path}")


def _emit_sidecar_failures_if_any() -> None:
    """sidecar 作成失敗があれば stdout に surfacing する（最後に呼ぶ）"""
    if not _SIDECAR_FAILURES:
        return
    print(
        f"[HOOK_SIDECAR_FAILED] sidecar 作成に {len(_SIDECAR_FAILURES)} 件失敗しました。"
        "exactly-once 抑制が壊れて重複通知 or 無通知のリスクがあります。"
        "権限や fs を確認してください。"
    )
    for m in _SIDECAR_FAILURES[:5]:
        print(f"  - {m}")


def main() -> int:
    # limit まで集めて早期 return（O(N+k log N) 走査）
    candidates = _collect_stale(MAX_MESSAGES_PER_CALL)
    if not candidates:
        _emit_sidecar_failures_if_any()
        return 0

    # sidecar 作成に成功した（＝この hook が通知権を獲得した）分だけ
    # emit する。他プロセスが先取りした場合は emit しない（exactly-once）
    emitted: list[tuple[Path, dict, float, str]] = []
    for path, data, age, kind in candidates:
        if _create_sidecar(path.name, reason=f"age={age:.0f}s {kind}"):
            emitted.append((path, data, age, kind))

    if not emitted:
        # 全件が他プロセスに取られた or sidecar 作成が全て失敗した。
        # race lose は silent、失敗があれば surfacing する必要がある。
        _emit_sidecar_failures_if_any()
        return 0

    stale_count = sum(1 for _, _, _, k in emitted if k == "stale")
    broken_count = sum(1 for _, _, _, k in emitted if k == "broken")
    parts = []
    if stale_count:
        parts.append(f"未対応 {stale_count} 件")
    if broken_count:
        parts.append(f"破損 {broken_count} 件")
    summary = " / ".join(parts)
    print(
        f"[UNPROCESSED_DISCORD_WARNING] claimed/ に {summary} があります "
        f"(age > {STALE_THRESHOLD_SEC}s)。"
        "対応後、処理済みを示すため claim.status を done/waiting_user に更新するか、"
        "対応不要なら何もせず次回 hook を無視してください（sidecar 作成済み）。"
        "破損ファイルは discord_inbox_monitor.py の quarantine ログを確認してください。"
    )
    for path, data, age, kind in emitted:
        _emit_message(path, data, age, kind)

    _emit_sidecar_failures_if_any()
    # 注入 1 回の間だけ採用、次回 hook では sidecar があるため再注入されない
    return 0


if __name__ == "__main__":
    sys.exit(main())
