# 実行後モニタリング＆自動最適化モジュール
#
# run.bat から generator.py の直後に呼び出す。
# 本日の run.log を解析して:
#   1. フェーズ別所要時間を抽出
#   2. エラー件数・種類を集計
#   3. 投稿成否・タイトルを確認
#   4. 履歴 logs/perf_history.json に追記
#   5. ntfy でダイジェスト通知を送信
#   6. ボトルネック・頻出エラーを検出して改善ヒントを表示

import json
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

BASE_DIR   = Path(__file__).resolve().parent.parent
LOG_DIR    = BASE_DIR / "logs"
OUTPUT_DIR = BASE_DIR / "output"
PERF_JSON  = LOG_DIR / "perf_history.json"
_WAV_KEEP_DAYS = 14  # WAV音声ディレクトリを保持する日数

# ログのフェーズ完了行パターン: "→ フェーズN完了 (XXs)"
_PHASE_RE  = re.compile(r"フェーズ(\d+)完了\s+\((\d+)s\)")
# エラー行パターン（[!]はセクション画像失敗等の警告に使われるため除外）
_ERROR_RE  = re.compile(r"\[エラー\]|\[致命的エラー\]|ERROR|Traceback")
# 音声生成行: "N 件の音声ファイルを保存"
_AUDIO_RE  = re.compile(r"(\d+)\s*件の音声ファイルを保存")
# アップロード成功行: "予約投稿完了" or "公開完了" or "URL: https://"
_UPLOAD_RE = re.compile(r"(予約投稿完了|公開完了|URL:\s*https://)")
# 投稿URL
_URL_RE    = re.compile(r"URL:\s*(https://\S+)")
# タイトル行: "タイトル: ..." or "タイトル     : ..."
_TITLE_RE  = re.compile(r"タイトル\s*:\s*(.+)")
# サムネイルキャプション
_CAPTION_RE = re.compile(r"サムネイルキャプション:\s*(.+)")


def _read_today_log() -> str:
    """本日の run.log から最後の実行分を読む"""
    # run.bat のリダイレクト先は logs/run.log（追記式）
    # ※ YYYYMMDD.log は error_logger.py の構造化ログで別物なので使わない
    run_log = LOG_DIR / "run.log"
    if not run_log.exists():
        return ""
    content = run_log.read_text(encoding="utf-8", errors="replace")
    # 最後の "=== BATCH START ===" 以降を返す（今回の実行分のみ）
    lines = content.splitlines()
    last_start = -1
    for i, line in enumerate(lines):
        if "BATCH START" in line:
            last_start = i
    if last_start >= 0:
        return "\n".join(lines[last_start:])
    return content


def _parse_log(log: str) -> dict:
    """ログを解析して実行結果を辞書で返す"""
    result: dict = {
        "date":          datetime.now().strftime("%Y-%m-%d"),
        "phases":        {},   # {フェーズ番号: 秒数}
        "total_sec":     0,
        "error_count":   0,
        "error_lines":   [],
        "audio_count":   0,
        "upload_ok":     False,
        "video_url":     "",
        "title":         "",
        "caption":       "",
    }

    for line in log.splitlines():
        # フェーズ完了
        m = _PHASE_RE.search(line)
        if m:
            phase = int(m.group(1))
            sec   = int(m.group(2))
            result["phases"][str(phase)] = sec
            result["total_sec"] = max(result["total_sec"], sec)

        # エラー
        if _ERROR_RE.search(line):
            result["error_count"] += 1
            result["error_lines"].append(line.strip()[:120])

        # 音声ファイル数
        m = _AUDIO_RE.search(line)
        if m:
            result["audio_count"] = int(m.group(1))

        # アップロード成否
        if _UPLOAD_RE.search(line):
            result["upload_ok"] = True

        # URL
        m = _URL_RE.search(line)
        if m:
            result["video_url"] = m.group(1)

        # タイトル（「タイトルを生成しています」等は除外）
        m = _TITLE_RE.search(line)
        if m:
            title_val = m.group(1).strip()
            if title_val and not title_val.startswith("(") and "生成" not in title_val:
                result["title"] = title_val

        # キャプション
        m = _CAPTION_RE.search(line)
        if m:
            result["caption"] = m.group(1).strip()

    return result


def _load_history() -> list[dict]:
    """過去の実行履歴を読み込む"""
    if PERF_JSON.exists():
        try:
            return json.loads(PERF_JSON.read_text(encoding="utf-8"))
        except Exception:
            pass
    return []


def _save_history(history: list[dict]) -> None:
    """実行履歴を保存する（最新100件まで）"""
    LOG_DIR.mkdir(exist_ok=True)
    PERF_JSON.write_text(
        json.dumps(history[-100:], ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def _detect_bottlenecks(history: list[dict]) -> list[str]:
    """直近10件の履歴からボトルネックと頻出エラーを検出する"""
    hints = []
    recent = history[-10:] if len(history) >= 3 else history

    # フェーズ別平均時間
    phase_times: dict[str, list[int]] = {}
    for r in recent:
        for ph, sec in r.get("phases", {}).items():
            phase_times.setdefault(ph, []).append(sec)

    phase_avgs = {ph: sum(v)/len(v) for ph, v in phase_times.items()}

    if phase_avgs:
        slowest = max(phase_avgs, key=lambda k: phase_avgs[k])
        slowest_avg = phase_avgs[slowest]
        _PHASE_NAMES = {"1":"台本生成","2":"台本修復・発音補正","3":"説明文+背景+キャプション","4":"音声+動画生成"}
        name = _PHASE_NAMES.get(slowest, f"フェーズ{slowest}")
        if slowest_avg > 120:
            hints.append(f"[注意] ボトルネック: {name} が平均 {slowest_avg:.0f}s かかっています")

    # 失敗率
    fail_rate = sum(1 for r in recent if not r.get("upload_ok")) / max(len(recent), 1)
    if fail_rate >= 0.3:
        hints.append(f"[注意] アップロード失敗率が高い ({fail_rate*100:.0f}%) → 認証・ネットワークを確認")

    # エラー頻出ワード
    all_errors = [e for r in recent for e in r.get("error_lines", [])]
    if len(all_errors) >= 5:
        hints.append(f"[注意] 直近10回で {len(all_errors)} 件のエラー → logs/perf_history.json で詳細確認")

    # 音声ファイル0件
    zero_audio = sum(1 for r in recent if r.get("audio_count", 0) == 0)
    if zero_audio >= 2:
        hints.append(f"[注意] 音声生成が {zero_audio} 回ゼロ件 → AquesTalk/音声合成の状態を確認")

    return hints


def _youtube_safety_check() -> list[str]:
    """YouTube APIで今日の動画を検査し、問題があれば自動非公開にする。

    検査項目:
    - 重複動画（同日に複数の公開/予約動画） → 短い方を非公開化
    - 短すぎる動画（3分未満） → 即非公開化

    Returns:
        実行したアクションのリスト
    """
    actions = []
    _MIN_DURATION_SEC = 180  # 3分
    try:
        from auth_utils import get_credentials
        from googleapiclient.discovery import build
        from youtube_uploader import delete_auto_captions

        youtube = build("youtube", "v3", credentials=get_credentials())
        jst = timezone(timedelta(hours=9))
        today_jst = datetime.now(jst).strftime("%Y-%m-%d")

        # 自分のチャンネルの最新動画を取得
        resp = youtube.search().list(
            part="snippet",
            forMine=True,
            type="video",
            maxResults=10,
            order="date",
        ).execute()

        # 今日の動画を収集
        today_videos = []
        for item in resp.get("items", []):
            vid = item["id"]["videoId"]
            title = item["snippet"].get("title", "")
            published = item["snippet"].get("publishedAt", "")[:10]

            detail = youtube.videos().list(
                part="status,contentDetails",
                id=vid,
            ).execute()
            if not detail.get("items"):
                continue
            d = detail["items"][0]
            status = d["status"]
            privacy = status.get("privacyStatus", "")
            publish_at_str = status.get("publishAt", "")

            # 動画の尺をパース（ISO 8601 duration: PT13M52S）
            dur_str = d.get("contentDetails", {}).get("duration", "")
            dur_sec = _parse_iso_duration(dur_str)

            is_today = False
            # 公開済み: publishedAtが今日
            if privacy == "public" and published == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                is_today = True
            # 予約投稿: publishAtが今日（JST）
            if privacy == "private" and publish_at_str:
                try:
                    pub_dt = datetime.fromisoformat(publish_at_str.replace("Z", "+00:00"))
                    if pub_dt.astimezone(jst).strftime("%Y-%m-%d") == today_jst:
                        is_today = True
                except Exception:
                    pass

            if is_today:
                today_videos.append({
                    "id": vid,
                    "title": title,
                    "privacy": privacy,
                    "duration": dur_sec,
                    "publish_at": publish_at_str,
                })

        # 検査1: 短すぎる動画を非公開化
        for v in today_videos:
            if v["duration"] > 0 and v["duration"] < _MIN_DURATION_SEC:
                _set_private(youtube, v["id"])
                msg = f"短すぎる動画を非公開化: {v['title'][:30]} ({v['duration']}秒)"
                actions.append(msg)
                print(f"  [自動修復] {msg}")

        # 検査2: 重複動画（短い方を非公開化、同じ尺なら後からの方を非公開化）
        active = [v for v in today_videos if v["id"] not in
                  [a.split("(")[0] for a in actions]]  # 既に非公開化したものを除外
        if len(active) >= 2:
            # 最も長い動画を残し、他を非公開化
            active.sort(key=lambda v: v["duration"], reverse=True)
            keep = active[0]
            for v in active[1:]:
                _set_private(youtube, v["id"])
                msg = f"重複動画を非公開化: {v['title'][:30]} ({v['duration']}秒) → 残す: {keep['title'][:20]}"
                actions.append(msg)
                print(f"  [自動修復] {msg}")

        # 検査3: 今日の動画の自動生成字幕を削除（焼き込み字幕と重複するため）
        for v in today_videos:
            try:
                deleted = delete_auto_captions(v["id"])
                if deleted:
                    msg = f"自動字幕を削除: {v['title'][:30]} ({deleted}トラック)"
                    actions.append(msg)
                    print(f"  [自動修復] {msg}")
            except Exception as _ce:
                print(f"  [警告] 自動字幕削除失敗({v['id']}): {_ce}")

    except Exception as e:
        print(f"  [警告] YouTube安全チェック失敗（処理続行）: {e}")

    return actions


def _parse_iso_duration(dur: str) -> int:
    """ISO 8601 duration (PT13M52S) を秒数に変換する"""
    if not dur:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", dur)
    if not m:
        return 0
    h = int(m.group(1) or 0)
    mi = int(m.group(2) or 0)
    s = int(m.group(3) or 0)
    return h * 3600 + mi * 60 + s


def _set_private(youtube, video_id: str) -> None:
    """動画を非公開に設定する"""
    youtube.videos().update(
        part="status",
        body={
            "id": video_id,
            "status": {"privacyStatus": "private"},
        },
    ).execute()
    print(f"  → 動画 {video_id} を非公開に設定しました")


def _cleanup_old_audio_dirs() -> int:
    """キャッシュクリーンアップスキルに委譲する"""
    try:
        from skills.skill_cache_cleanup import run_cache_cleanup
        report = run_cache_cleanup()
        return len(report.get("old_wav_dirs", [])) + len(report.get("temp_files", []))
    except Exception:
        # フォールバック: スキルが使えない場合は従来ロジック
        import time as _time
        cutoff = _time.time() - _WAV_KEEP_DAYS * 86400
        deleted = 0
        try:
            for d in OUTPUT_DIR.iterdir():
                if d.is_dir() and re.match(r"\d{8}_\d{6}_", d.name):
                    if d.stat().st_mtime < cutoff:
                        shutil.rmtree(d, ignore_errors=True)
                        deleted += 1
        except Exception:
            pass
        return deleted


def _build_notify_message(result: dict, hints: list[str]) -> tuple[str, str]:
    """ntfy 用のタイトルと本文を組み立てる"""
    if result["upload_ok"]:
        title_str = "[OK] 投稿完了"
    else:
        title_str = "[NG] 投稿失敗"

    lines = []
    if result["title"]:
        lines.append(f"動画: {result['title'][:30]}")
    if result["video_url"]:
        lines.append(f"URL: {result['video_url']}")

    # フェーズ別タイム
    phase_names = {"1":"台本","2":"修復","3":"並列","4":"音声+動画"}
    phase_strs = [f"{phase_names.get(k,'?')}:{v}s" for k, v in sorted(result["phases"].items())]
    if phase_strs:
        lines.append("時間: " + " / ".join(phase_strs))

    lines.append(f"エラー: {result['error_count']} 件")

    if hints:
        lines.append("")
        lines.extend(hints)

    return title_str, "\n".join(lines)


def run_monitor() -> dict:
    """メイン処理。解析結果を返す。"""
    print("\n=== [run_monitor] 実行結果を解析しています... ===")

    log = _read_today_log()
    if not log:
        print("  ログファイルが見つかりません → スキップ")
        return {}

    result  = _parse_log(log)
    history = _load_history()
    history.append(result)
    _save_history(history)

    hints = _detect_bottlenecks(history)

    # コンソール出力
    print(f"  日付         : {result['date']}")
    print(f"  タイトル     : {result['title'] or '(不明)'}")
    print(f"  投稿         : {'成功' if result['upload_ok'] else '失敗'}")
    print(f"  エラー       : {result['error_count']} 件")
    if result["phases"]:
        phase_names = {"1":"台本生成","2":"修復+補正","3":"並列生成","4":"音声+動画"}
        for ph, sec in sorted(result["phases"].items()):
            name = phase_names.get(ph, f"フェーズ{ph}")
            bar  = "█" * min(int(sec / 10), 40)
            print(f"  {name:<12}: {sec:>4}s {bar}")
    if result["audio_count"]:
        print(f"  音声ファイル : {result['audio_count']} 件")
    if hints:
        print("\n  【最適化ヒント】")
        for h in hints:
            print(f"    {h}")

    # ntfy 通知
    try:
        from notifier import notify_report
        msg_title, msg_body = _build_notify_message(result, hints)
        notify_report(msg_title, msg_body, priority="default" if result["upload_ok"] else "high")
        print("\n  ntfy 通知を送信しました")
    except Exception as e:
        print(f"  ntfy 通知スキップ: {e}")

    print(f"\n  履歴: {len(history)} 件蓄積 → {PERF_JSON}")

    # YouTube安全チェック（重複・短尺動画の自動非公開化）
    print("\n  YouTube安全チェックを実行しています...")
    safety_actions = _youtube_safety_check()
    if safety_actions:
        # 自動修復を行った場合は緊急通知
        try:
            from notifier import notify_report
            action_text = "\n".join(f"- {a}" for a in safety_actions)
            notify_report(
                "[自動修復] YouTube動画を非公開化しました",
                f"以下の動画を自動的に非公開にしました:\n{action_text}",
                priority="urgent",
            )
        except Exception:
            pass
    else:
        print("  YouTube安全チェック: 問題なし")

    # 古い音声ディレクトリを削除（MP4が完成済みのため不要）
    deleted = _cleanup_old_audio_dirs()
    if deleted:
        print(f"  クリーンアップ: {deleted} 件の古い音声フォルダを削除しました")

    return result


if __name__ == "__main__":
    run_monitor()
    sys.exit(0)  # run.bat から呼ばれるため常に0を返す（監視失敗でタスク再起動させない）
