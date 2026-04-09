# プリフライトチェック — 毎日13:00に実行
#
# 今日の動画が18:00に予定通り公開されるか事前確認する。
# 問題があれば自動修復（途中再開・メタデータ修正）し、
# 修復不能なら詳細診断付きで高優先度通知する。
#
# 役割:
#   1. 検証ツール: 10:00のパイプラインが成功したことを確認
#   2. 最後の砦: 失敗していたら途中再開 or 丸ごと再実行
#   3. 診断レポーター: 何が起きたか・何を試したかを通知
#
# 実行: python scripts/preflight_check.py
# タスクスケジューラ: run_preflight.bat (毎日 13:00)

import json
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
OUTPUT_DIR = BASE_DIR / "output"
LOG_DIR = BASE_DIR / "logs"

# scripts/ を path に追加
sys.path.insert(0, str(Path(__file__).parent))
from notifier import notify_error, notify_report
from error_logger import log_error, log_info

JST = timezone(timedelta(hours=9))


# ── パイプライン途中再開 ─────────────────────────────────────

# フェーズ実行順序（self_review は thumbnail の後に挟む）
_RESUME_PHASES = [
    "script_gen",
    "metadata",
    "pronunciation",
    "se_assign",
    "prosody",
    "tts",
    "video_build",
    "thumbnail",
    "self_review",
    "upload",
]


def _get_first_incomplete_phase(manifest: dict) -> str | None:
    """最初の未完了フェーズを返す。全完了なら None"""
    phases = manifest.get("phases", {})
    for phase_name in _RESUME_PHASES:
        # self_review は pipeline.json に必ずしも存在しない
        if phase_name == "self_review":
            if phase_name not in phases:
                continue
            if phases[phase_name]["status"] != "completed":
                return phase_name
        elif phase_name in phases and phases[phase_name]["status"] != "completed":
            return phase_name
    return None


def resume_pipeline(run_dir: Path) -> dict:
    """パイプラインを失敗フェーズから再開する。

    Returns:
        {"resumed": True/False, "completed": True/False,
         "phases_run": [...], "error": str|None}
    """
    from skills._common import load_manifest
    from skills.self_healing import run_phase_with_healing

    result = {
        "resumed": False,
        "completed": False,
        "phases_run": [],
        "error": None,
    }

    try:
        manifest = load_manifest(run_dir)
    except Exception as e:
        result["error"] = f"pipeline.json 読み込み失敗: {e}"
        return result

    theme = manifest.get("theme", "")
    start_phase = _get_first_incomplete_phase(manifest)

    if start_phase is None:
        # 全フェーズ完了済み
        result["completed"] = True
        return result

    print(f"  [途中再開] フェーズ '{start_phase}' から再開します")
    result["resumed"] = True

    # 再開位置のインデックスを取得
    try:
        start_idx = _RESUME_PHASES.index(start_phase)
    except ValueError:
        result["error"] = f"不明なフェーズ: {start_phase}"
        return result

    # 各フェーズを順番に実行
    for phase_name in _RESUME_PHASES[start_idx:]:
        # 既に完了済みならスキップ
        phases = manifest.get("phases", {})
        if phase_name in phases and phases[phase_name]["status"] == "completed":
            continue

        print(f"  [途中再開] {phase_name} を実行中...")
        try:
            _run_single_phase(phase_name, run_dir, theme, run_phase_with_healing)
            result["phases_run"].append(phase_name)
            # manifest を再読み込み（フェーズが更新しているので）
            manifest = load_manifest(run_dir)
        except Exception as e:
            result["error"] = f"{phase_name} で失敗: {type(e).__name__}: {e}"
            result["phases_run"].append(f"{phase_name}(FAILED)")
            print(f"  [途中再開] {phase_name} で失敗: {e}")
            return result

    result["completed"] = True
    print(f"  [途中再開] 全フェーズ完了: {', '.join(result['phases_run'])}")
    return result


def _run_single_phase(phase_name: str, run_dir: Path, theme: str, healing_fn):
    """個別フェーズを実行する"""

    if phase_name == "script_gen":
        from skills.skill_script_gen import run_script_gen
        # script_gen は theme が必要。healing 経由だと引数が合わないので直接呼ぶ
        sg = run_script_gen(run_dir, theme)
        if not sg:
            raise RuntimeError("台本生成に失敗しました")

    elif phase_name == "metadata":
        from skills.skill_metadata import run_metadata
        run_metadata(run_dir)

    elif phase_name == "pronunciation":
        from skills.skill_pronunciation import run_pronunciation
        run_pronunciation(run_dir)
        # 発音変更後のキャッシュクリーンアップ
        try:
            from skills.skill_cache_cleanup import run_cache_cleanup
            cleanup = run_cache_cleanup(run_dir=run_dir)
            if cleanup.get("stale_wav"):
                print(f"    [キャッシュ] {len(cleanup['stale_wav'])} WAV削除")
        except Exception:
            pass

    elif phase_name == "se_assign":
        from skills.skill_se_assign import run_se_assign
        run_se_assign(run_dir)

    elif phase_name == "prosody":
        from skills.skill_prosody import run_prosody
        run_prosody(run_dir)

    elif phase_name == "tts":
        from skills.skill_tts import run_tts
        healing_fn("tts", run_tts, run_dir)

    elif phase_name == "video_build":
        from skills.skill_video_build import run_video_build
        healing_fn("video_build", run_video_build, run_dir)

    elif phase_name == "thumbnail":
        from skills.skill_thumbnail import run_thumbnail
        run_thumbnail(run_dir)

    elif phase_name == "self_review":
        from skills.skill_self_review import run_self_review
        review = run_self_review(run_dir)
        if review.get("needs_repair"):
            # 台本修復 → TTS以降を再実行
            print("    [自動修復] 台本修復済み → 再生成中...")
            from skills.skill_pronunciation import run_pronunciation as rp
            from skills.skill_tts import run_tts as rt
            from skills.skill_video_build import run_video_build as rvb
            from skills.skill_thumbnail import run_thumbnail as rth
            rp(run_dir)
            healing_fn("tts", rt, run_dir)
            healing_fn("video_build", rvb, run_dir)
            rth(run_dir)

    elif phase_name == "upload":
        from skills.skill_upload import run_upload
        import random
        wait_sec = random.randint(30, 120)
        print(f"    アップロード前 {wait_sec}秒待機...")
        import time
        time.sleep(wait_sec)
        run_upload(
            run_dir,
            publish_time="18:00",
            skip_wait=True,
        )

    else:
        raise ValueError(f"未対応フェーズ: {phase_name}")


# ── 診断サマリ生成 ────────────────────────────────────────────

def _build_diagnostic_summary(run_dir: Path | None) -> str:
    """run.log と healing_log から診断サマリを生成する"""
    lines = []

    # 1. pipeline.json の healing_log を収集
    if run_dir:
        try:
            manifest = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))
            for phase_name, phase in manifest.get("phases", {}).items():
                healing = phase.get("healing_log", [])
                if healing:
                    lines.append(f"[{phase_name}] 自己修復 {len(healing)}回:")
                    for entry in healing:
                        lines.append(
                            f"  {entry.get('attempt')}. [{entry.get('diagnosis')}] "
                            f"{entry.get('fix_applied')} -> {entry.get('fix_result')}"
                        )
                elif phase.get("status") == "failed":
                    err = phase.get("error", "不明")
                    lines.append(f"[{phase_name}] 失敗: {err}")
        except Exception:
            pass

    # 2. run.log の最後のエラー情報を収集
    run_log = LOG_DIR / "run.log"
    if run_log.exists():
        try:
            content = run_log.read_text(encoding="utf-8", errors="replace")
            # 今日のログだけ抽出
            today_str = datetime.now().strftime("%Y/%m/%d")
            today_lines = []
            for line in content.splitlines():
                if today_str in line or (today_lines and not line.startswith("[")):
                    today_lines.append(line)
            # エラー行を抽出
            error_lines = [
                l for l in today_lines
                if any(kw in l.lower() for kw in [
                    "error", "failed", "traceback", "exception",
                    "エラー", "失敗", "致命的",
                ])
            ]
            if error_lines:
                lines.append("\n[run.log エラー抜粋]")
                # 最後の10行まで
                for el in error_lines[-10:]:
                    lines.append(f"  {el[:120]}")
        except Exception:
            pass

    # 3. preflight.log の今日分
    pf_log = LOG_DIR / "preflight.log"
    if pf_log.exists():
        try:
            content = pf_log.read_text(encoding="utf-8", errors="replace")
            today_str = datetime.now().strftime("%Y/%m/%d")
            pf_lines = [l for l in content.splitlines() if today_str in l]
            if pf_lines:
                lines.append("\n[preflight.log]")
                for pl in pf_lines[-5:]:
                    lines.append(f"  {pl[:120]}")
        except Exception:
            pass

    if not lines:
        lines.append("診断情報なし（ログが空か読み取れません）")

    return "\n".join(lines)


# ── 今日のパイプラインを探す ──────────────────────────────

def _list_today_run_dirs() -> list[tuple[Path, dict]]:
    """今日作成された run_dir と manifest の一覧（名前降順）を返す。"""
    today_prefix = datetime.now().strftime("%Y%m%d")
    items: list[tuple[Path, dict]] = []
    try:
        for d in OUTPUT_DIR.iterdir():
            if d.is_dir() and d.name.startswith(today_prefix):
                pipeline = d / "pipeline.json"
                if pipeline.exists():
                    try:
                        manifest = json.loads(pipeline.read_text(encoding="utf-8"))
                    except Exception:
                        manifest = {}
                    items.append((d, manifest))
    except Exception:
        pass
    items.sort(key=lambda t: t[0].name, reverse=True)
    return items


def _is_upload_completed(manifest: dict) -> bool:
    return manifest.get("phases", {}).get("upload", {}).get("status") == "completed"


def _is_resumable(manifest: dict) -> bool:
    """未完了(upload未完了)かつ completed 以外のrun。"""
    phases = manifest.get("phases", {})
    upload = phases.get("upload", {})
    if upload.get("status") == "completed":
        return False
    # 少なくとも script_gen が存在しているrunなら再開対象とみなす
    return "script_gen" in phases


def find_today_run_dir(prefer: str = "auto") -> Path | None:
    """今日作成された run_dir を探す（YYYYMMDD_ プレフィックス）。

    status-aware 選択（2026-04-09事故対策: ただ最新を返すと壊れたrunを掴む）。

    prefer:
      - "upload_completed": upload.completed な最新のrunのみ返す（なければ None）
      - "resumable": upload 未完了の最新のrunを返す（なければ None）
      - "auto": upload_completed を優先、無ければ resumable、それも無ければ最新
      - "latest": 旧挙動（名前の降順で先頭）
    """
    items = _list_today_run_dirs()
    if not items:
        return None

    if prefer == "latest":
        return items[0][0]

    upload_done = [d for d, m in items if _is_upload_completed(m)]
    resumable   = [d for d, m in items if _is_resumable(m)]

    if prefer == "upload_completed":
        return upload_done[0] if upload_done else None
    if prefer == "resumable":
        return resumable[0] if resumable else None

    # auto
    if upload_done:
        return upload_done[0]
    if resumable:
        return resumable[0]
    return items[0][0]


def find_today_video_id() -> str | None:
    """今日のパイプラインから video_id を取得する。

    サイレントフォールバック禁止（2026-04-09事故対策）:
    以前は upload_completed が無ければ run.log 全体から最初の動画IDを
    取る実装だったが、日付スコープがないため「昨日以前のアップ動画を
    今日の対象として検証する」誤動作が起こり得た。
    今日の manifest に upload_completed が無ければ None を返す。
    """
    # 複数runがあった場合、video_idはupload完了済みのrunからのみ取る
    run_dir = find_today_run_dir(prefer="upload_completed")
    if not run_dir:
        return None
    try:
        manifest = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))
        upload_phase = manifest.get("phases", {}).get("upload", {})
        for out in upload_phase.get("outputs", []):
            if isinstance(out, str) and len(out) == 11 and not out.startswith("http"):
                return out  # video_id は11文字
            if isinstance(out, str) and "youtu.be/" in out:
                return out.split("youtu.be/")[-1]
        # outputs に video_id がなければ error も確認
        return None
    except Exception:
        return None


# ── YouTube API チェック ──────────────────────────────────

def check_youtube_status(video_id: str) -> dict:
    """YouTube APIで動画のステータスを取得する"""
    from youtube_uploader import _get_youtube_client

    youtube = _get_youtube_client()
    response = youtube.videos().list(
        part="snippet,status",
        id=video_id,
    ).execute()

    items = response.get("items", [])
    if not items:
        return {"found": False, "error": f"動画 {video_id} が見つかりません"}

    video = items[0]
    snippet = video.get("snippet", {})
    status = video.get("status", {})

    result = {
        "found": True,
        "video_id": video_id,
        "title": snippet.get("title", ""),
        "description": snippet.get("description", ""),
        "tags": snippet.get("tags", []),
        "privacy_status": status.get("privacyStatus", ""),
        "publish_at": status.get("publishAt", ""),
        "contains_synthetic_media": status.get("containsSyntheticMedia"),
        "upload_status": status.get("uploadStatus", ""),
        "has_thumbnail": bool(snippet.get("thumbnails", {}).get("default")),
    }
    return result


# ── チェック項目 ──────────────────────────────────────────

def run_checks(video_id: str) -> list[dict]:
    """全チェック項目を実行し、問題リストを返す"""
    issues = []

    try:
        status = check_youtube_status(video_id)
    except Exception as e:
        issues.append({
            "check": "youtube_api",
            "severity": "error",
            "message": f"YouTube API接続失敗: {e}",
            "auto_fix": False,
        })
        return issues

    if not status["found"]:
        issues.append({
            "check": "video_exists",
            "severity": "error",
            "message": status.get("error", "動画が見つかりません"),
            "auto_fix": False,
        })
        return issues

    # 1. アップロード完了チェック
    if status["upload_status"] != "processed":
        issues.append({
            "check": "upload_status",
            "severity": "error" if status["upload_status"] == "failed" else "warning",
            "message": f"アップロード状態: {status['upload_status']}（expected: processed）",
            "auto_fix": False,
        })

    # 2. 公開予約時刻チェック（18:00 JST）
    publish_at = status.get("publish_at", "")
    if publish_at:
        try:
            pub_dt = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
            pub_jst = pub_dt.astimezone(JST)
            expected_hour = 18
            if pub_jst.hour != expected_hour:
                issues.append({
                    "check": "publish_time",
                    "severity": "warning",
                    "message": f"公開予約: {pub_jst.strftime('%H:%M')} JST（expected: {expected_hour}:00）",
                    "auto_fix": True,
                    "fix_action": "update_publish_time",
                })
            # 日付チェック: 今日の公開か
            today = datetime.now(JST).date()
            if pub_jst.date() != today:
                issues.append({
                    "check": "publish_date",
                    "severity": "warning",
                    "message": f"公開日が今日ではありません: {pub_jst.date()} (today: {today})",
                    "auto_fix": False,
                })
        except Exception as e:
            issues.append({
                "check": "publish_time_parse",
                "severity": "warning",
                "message": f"公開予約時刻の解析失敗: {publish_at} ({e})",
                "auto_fix": False,
            })
    elif status["privacy_status"] == "private":
        issues.append({
            "check": "no_schedule",
            "severity": "error",
            "message": "非公開のまま公開予約が設定されていません",
            "auto_fix": True,
            "fix_action": "set_publish_time",
        })

    # 3. タイトル/説明文チェック
    if not status["title"] or len(status["title"]) < 5:
        issues.append({
            "check": "title",
            "severity": "error",
            "message": f"タイトルが空または短すぎます: 「{status['title']}」",
            "auto_fix": False,
        })
    if not status["description"] or len(status["description"]) < 50:
        issues.append({
            "check": "description",
            "severity": "warning",
            "message": f"説明文が短すぎます: {len(status.get('description', ''))}文字",
            "auto_fix": False,
        })

    # 4. タグチェック
    if not status["tags"]:
        issues.append({
            "check": "tags",
            "severity": "warning",
            "message": "タグが設定されていません",
            "auto_fix": False,
        })

    # 5. サムネイルチェック
    if not status["has_thumbnail"]:
        issues.append({
            "check": "thumbnail",
            "severity": "error",
            "message": "サムネイルが設定されていません",
            "auto_fix": True,
            "fix_action": "upload_thumbnail",
        })

    # 6. AI開示チェック
    # 注: YouTube APIは containsSyntheticMedia を読み取り時に返さないことがある
    # アップロード時に True を送信しているため、None は「取得不可」として warning に留める
    if status["contains_synthetic_media"] is False:
        issues.append({
            "check": "synthetic_media",
            "severity": "error",
            "message": "containsSyntheticMedia が False に設定されています",
            "auto_fix": False,
        })
    elif status["contains_synthetic_media"] is None:
        issues.append({
            "check": "synthetic_media",
            "severity": "warning",
            "message": "containsSyntheticMedia がAPIから取得できません（送信側では True 設定済み）",
            "auto_fix": False,
        })

    return issues


# ── 自動修復 ──────────────────────────────────────────────

def auto_fix(video_id: str, issue: dict) -> bool:
    """可能な問題を自動修復する。成功=True"""
    action = issue.get("fix_action", "")

    if action == "upload_thumbnail":
        return _fix_upload_thumbnail(video_id)
    elif action in ("update_publish_time", "set_publish_time"):
        return _fix_publish_time(video_id)

    return False


def _fix_upload_thumbnail(video_id: str) -> bool:
    """サムネイルをアップロードする"""
    # アップロード済みrunからサムネイル画像を引く
    run_dir = find_today_run_dir(prefer="upload_completed")
    if not run_dir:
        return False

    try:
        manifest = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))
        thumb_outputs = manifest.get("phases", {}).get("thumbnail", {}).get("outputs", [])
        for out in thumb_outputs:
            p = run_dir.parent / out if not Path(out).is_absolute() else Path(out)
            if p.exists() and p.suffix in (".png", ".jpg"):
                from youtube_uploader import _get_youtube_client
                from googleapiclient.http import MediaFileUpload
                youtube = _get_youtube_client()
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(str(p)),
                ).execute()
                print(f"  [自動修復] サムネイルをアップロードしました: {p.name}")
                return True
    except Exception as e:
        print(f"  [自動修復失敗] サムネイル: {e}")
    return False


def _fix_publish_time(video_id: str) -> bool:
    """公開予約時刻を今日の18:00（過ぎていたら翌日18:00）に設定する"""
    try:
        from youtube_uploader import _get_youtube_client
        youtube = _get_youtube_client()

        target = datetime.now(JST).replace(hour=18, minute=0, second=0, microsecond=0)
        if target <= datetime.now(JST):
            target += timedelta(days=1)

        target_utc = target.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")

        youtube.videos().update(
            part="status",
            body={
                "id": video_id,
                "status": {
                    "privacyStatus": "private",
                    "publishAt": target_utc,
                },
            },
        ).execute()
        print(f"  [自動修復] 公開予約を {target.strftime('%Y/%m/%d %H:%M')} JST に設定しました")
        return True
    except Exception as e:
        print(f"  [自動修復失敗] 公開予約: {e}")
    return False


# ── メインフロー ──────────────────────────────────────────

def run_preflight() -> dict:
    """プリフライトチェックを実行する。

    フロー:
      Step 1: 今日のパイプライン状態を確認
      Step 2: 未完了なら途中再開（self_healing付き）
      Step 3: パイプラインがなければ exit(2) → run_preflight.bat が generator.py を呼ぶ
      Step 4: YouTube API でアップロード状態を検証
      Step 5: メタデータ不備を自動修復
      Step 6: 最終判定 → OK通知 or 診断サマリ付き高優先度通知

    Exit codes:
      0: 全チェック通過
      1: 修復不能な問題あり（通知済み）
      2: パイプライン自体がない → run_preflight.bat で generator.py を実行すべき
    """
    print("=== プリフライトチェック ===")
    print(f"実行時刻: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    result = {
        "checked_at": datetime.now().isoformat(),
        "video_id": None,
        "issues": [],
        "fixes_attempted": 0,
        "fixes_succeeded": 0,
        "resume_result": None,
        "passed": False,
    }

    # ── Step 1: パイプライン存在確認 ─────────────────────────
    # status-aware: upload完了済み > 再開可能な未完了 > その他
    # これにより「失敗した新規run + 成功済みrun」の共存時に成功runを検証できる
    run_dir = find_today_run_dir(prefer="auto")

    if not run_dir:
        print("  [NG] 今日のパイプラインが見つかりません")
        print("  → generator.py による全体生成が必要です")
        notify_report(
            "[注意] プリフライト: パイプラインなし",
            "今日の動画パイプラインが見つかりません。generator.py を実行します。",
            priority="high",
        )
        # exit(2) で run_preflight.bat に「generator.py を呼べ」と伝える
        result["issues"].append({
            "check": "no_pipeline",
            "severity": "error",
            "message": "パイプラインなし → generator.py 再実行",
            "auto_fix": False,
        })
        _save_report(run_dir, result)
        return result

    # ── Step 2: パイプライン状態確認 + 途中再開 ──────────────
    try:
        manifest = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))
        pipeline_status = manifest.get("status", "unknown")
    except Exception as e:
        print(f"  [NG] pipeline.json 読み込み失敗: {e}")
        pipeline_status = "unknown"
        manifest = {}

    if pipeline_status != "completed":
        # パイプラインが未完了 → 途中再開を試みる
        failed_phases = [
            name for name, phase in manifest.get("phases", {}).items()
            if phase.get("status") not in ("completed", "pending")
        ]
        print(f"  [NG] パイプライン未完了 (status={pipeline_status})")
        if failed_phases:
            print(f"       失敗フェーズ: {', '.join(failed_phases)}")

        print("  → 途中再開を試みます...")
        resume_result = resume_pipeline(run_dir)
        result["resume_result"] = resume_result

        if resume_result["completed"]:
            print(f"  [OK] 途中再開成功: {', '.join(resume_result['phases_run'])}")
        else:
            err_msg = resume_result.get("error", "不明なエラー")
            print(f"  [NG] 途中再開失敗: {err_msg}")
            result["issues"].append({
                "check": "resume_failed",
                "severity": "error",
                "message": f"途中再開失敗: {err_msg}",
                "auto_fix": False,
            })

    # ── Step 3: video_id を取得 ──────────────────────────────
    video_id = find_today_video_id()
    result["video_id"] = video_id

    if not video_id:
        result["issues"].append({
            "check": "video_id",
            "severity": "error",
            "message": "動画IDが見つかりません。アップロードされていない可能性があります。",
            "auto_fix": False,
        })
        print(f"  [NG] 動画IDが見つかりません")
    else:
        print(f"  動画ID: {video_id}")

        # ── Step 4: YouTube API チェック ─────────────────────
        issues = run_checks(video_id)
        result["issues"].extend(issues)

        # ── Step 5: メタデータ自動修復 ───────────────────────
        for issue in issues:
            if issue.get("auto_fix"):
                result["fixes_attempted"] += 1
                if auto_fix(video_id, issue):
                    result["fixes_succeeded"] += 1
                    issue["fixed"] = True

    # ── Step 6: 最終判定 + 通知 ──────────────────────────────
    errors = [i for i in result["issues"] if i["severity"] == "error" and not i.get("fixed")]
    result["passed"] = len(errors) == 0

    if result["passed"]:
        # 成功
        warnings = [i for i in result["issues"] if i["severity"] == "warning"]
        msg = "18:00公開の準備OK"
        if (result.get("resume_result") or {}).get("resumed"):
            phases = (result.get("resume_result") or {}).get("phases_run", [])
            msg += f" (途中再開: {', '.join(phases)})"
        if warnings:
            msg += f" (警告{len(warnings)}件)"
        if result["fixes_succeeded"] > 0:
            msg += f" (自動修復{result['fixes_succeeded']}件)"
        notify_report("[OK] プリフライト合格", msg)
        log_info(f"preflight: {msg}")
        print(f"\n[OK] {msg}")
    else:
        # 失敗 → 診断サマリ付きで高優先度通知
        error_msgs = "\n".join(f"- {i['message']}" for i in errors)
        diag = _build_diagnostic_summary(run_dir)

        notify_body = (
            f"18:00公開に問題があります:\n"
            f"{error_msgs}\n\n"
            f"--- 診断サマリ ---\n"
            f"{diag}"
        )
        notify_report(
            "[NG] プリフライト失敗 - 手動確認が必要",
            notify_body,
            priority="urgent",
        )
        log_error("preflight", ValueError(f"{len(errors)}件のエラー"))
        print(f"\n[NG] プリフライト失敗: {len(errors)} 件のエラー")
        print(f"\n--- 診断サマリ ---\n{diag}")

    # ── レポート保存 ─────────────────────────────────────────
    _save_report(run_dir, result)

    return result


def _save_report(run_dir: Path | None, result: dict):
    """プリフライト結果をJSONファイルに保存する"""
    if not run_dir:
        return
    try:
        report_path = run_dir / "preflight_report.json"
        report_path.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        print(f"レポート: {report_path}")
    except Exception as e:
        print(f"  [警告] レポート保存失敗: {e}")


if __name__ == "__main__":
    try:
        result = run_preflight()
    except Exception as e:
        # 予期しないクラッシュ → exit=1（生成を走らせない）
        print(f"[致命的] プリフライトがクラッシュしました: {e}")
        try:
            from notifier import notify_error
            notify_error("プリフライト クラッシュ", e)
        except Exception:
            pass
        sys.exit(1)

    if not result["passed"]:
        # exit=2: パイプラインが存在しない → 新規生成が必要
        # exit=3: リジューム失敗 → 新規生成で再試行
        # exit=1: それ以外の異常 → 生成を走らせない（通知のみ）
        issues = result.get("issues", [])
        no_pipeline = any(i["check"] == "no_pipeline" for i in issues)
        resume_failed = any(i["check"] == "resume_failed" for i in issues)
        if no_pipeline:
            sys.exit(2)
        elif resume_failed:
            sys.exit(3)
        else:
            # 検証エラー等 → 生成しても無意味なので通知のみ
            sys.exit(1)
    sys.exit(0)
