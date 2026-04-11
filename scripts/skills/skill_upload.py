# スキル: YouTubeアップロード（予約投稿・コミュニティ投稿文生成）

import json
import random
import re
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

from skills._common import (
    call_with_retry,
    check_prerequisites,
    ensure_scripts_path,
    get_llm,
    get_script_json,
    load_manifest,
    update_phase,
    SkillLogger,
)

ensure_scripts_path()

import model_config
from youtube_uploader import upload_video, get_video_url, delete_auto_captions, is_test_video
from notifier import notify_error, notify_success

OUTPUT_DIR = Path(__file__).parent.parent.parent / "output"

# NOTE (Step 2-ε): lock_path は run_upload() 冒頭で channel config から解決する.
# module-level に置いていた hardcoded _lock_path は削除した.
# これにより skill_upload.py 単独実行 (--run-dir 診断等) の --no-upload 経路でも
# channel config 破損時は ChannelLoadError → RuntimeError で fail-closed 化する
# (Codex Medium advisory). lock を使わない no_upload 経路でも config 依存になる点は
# 運用上許容範囲 (診断時もすべての環境整合を優先).


# ── ヘルパー関数 ──────────────────────────────────────────


def generate_community_post(title: str, description: str, url: str, output_dir: Path) -> Path | None:
    """コミュニティ投稿用テキストを生成してファイルに保存する。
    ※ YouTube APIのコミュニティ投稿エンドポイントは2024年に廃止されたため手動投稿用。
    """
    try:
        llm = get_llm()
        prompt = (
            f"以下のYouTube動画のコミュニティ投稿文を150文字以内で書いてください。\n"
            f"タイトル: {title}\n"
            f"ポイント: {description[:200]}\n"
            f"絵文字を2〜3個使い、最後に動画URLを載せる形式で。視聴者の興味を引く一言を入れること。\n"
            f"出力は投稿文のみ（説明不要）。"
        )
        post_text = call_with_retry(
            llm.generate, prompt, model_config.SIMPLE,
            label="コミュニティ投稿生成"
        ).strip()
        if url:
            if url not in post_text:
                post_text += f"\n{url}"
    except Exception as e:
        # フォールバック
        post_text = f"🎥 新動画を公開しました！\n「{title}」\n{url}"

    safe_title = re.sub(r'[\\/:*?"<>|]', "", title)[:30]
    out_path = output_dir / f"community_post_{safe_title}.txt"
    out_path.write_text(post_text, encoding="utf-8")
    return out_path


# ── メインエントリポイント ──────────────────────────────────


def run_upload(
    run_dir: str | Path,
    publish_time: str | None = None,
    publish_hours: int = 0,
    no_upload: bool = False,
    skip_wait: bool = False,
) -> dict:
    """YouTubeアップロードスキルを実行する。

    Args:
        run_dir: パイプラインの実行ディレクトリ
        publish_time: 予約投稿時刻（"HH:MM" 形式、過ぎていたら翌日）
        publish_hours: N時間後に予約投稿（0=即公開）
        no_upload: True ならアップロードをスキップ
        skip_wait: True ならボット判定回避の待機をスキップ

    Returns:
        {"video_id": str|None, "url": str|None, "community_post": str|None}
    """
    run_dir = Path(run_dir)
    logger = SkillLogger(run_dir, "upload")
    update_phase(run_dir, "upload", "in_progress")

    try:
        # ── Step 2-ε: channel config から lock_path を解決 (fail-closed) ──
        # --no-upload 経路でも config 破損時は RuntimeError で落ちる (Codex Medium advisory 合意済み).
        # 注: 外側 try の中に置くことで, config 読込失敗時も update_phase("failed") +
        # notify_error が発動する (Codex P2 指摘 2026-04-11 対応).
        try:
            from _channel import load_channel, ChannelLoadError
            _cfg = load_channel('health')
        except (ImportError, ChannelLoadError) as _ce:
            raise RuntimeError(f"チャンネル設定読込失敗 (upload): {_ce}") from _ce
        _lock_path = Path(__file__).parent.parent.parent / _cfg.paths.lock_file

        # 前提チェック: video_build と thumbnail が完了していること
        if not check_prerequisites(run_dir, "upload", ["video_build", "thumbnail"]):
            raise RuntimeError("前提フェーズ 'video_build' または 'thumbnail' が未完了です")

        manifest = load_manifest(run_dir)

        # 動画パスの取得（video_build フェーズの出力から）
        # サイレントフォールバック禁止（2026-04-09事故対策）:
        # 以前は video_build.outputs で見つからない場合 script_gen.outputs → .mp4 推測で
        # 隣接する古いMP4を掴む可能性があった。fail-closed に変更。
        video_path = None
        vb_outputs = manifest["phases"]["video_build"].get("outputs", [])
        for out in vb_outputs:
            if out.endswith(".mp4"):
                candidate = run_dir.parent / out if not Path(out).is_absolute() else Path(out)
                if candidate.exists():
                    video_path = candidate
                    break
        if video_path is None or not video_path.exists():
            raise FileNotFoundError(
                f"動画ファイルが video_build.outputs に見つかりません: {run_dir} "
                f"outputs={vb_outputs}"
            )

        # メタデータの取得
        metadata_path = run_dir / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"metadata.json が見つかりません: {metadata_path}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        script = get_script_json(run_dir)
        youtube_title = metadata.get("youtube_title", script.get("youtube_title", script.get("title", "")))
        description = metadata.get("description", "")
        tags = metadata.get("tags", ["ゆっくり解説", "健康"])
        theme = script.get("title", youtube_title)

        # サムネイルパスの取得（thumbnail フェーズの出力から）
        thumbnail_path = None
        th_outputs = manifest["phases"]["thumbnail"].get("outputs", [])
        for out in th_outputs:
            if out.endswith(".png") or out.endswith(".jpg"):
                candidate = run_dir.parent / out if not Path(out).is_absolute() else Path(out)
                if candidate.exists():
                    # C バリアントを優先
                    if "_C" in out:
                        thumbnail_path = candidate
                        break
                    elif thumbnail_path is None:
                        thumbnail_path = candidate

        logger.log("【YouTubeアップロード】")
        logger.log(f"  動画: {video_path}")
        logger.log(f"  タイトル: {youtube_title}")
        if thumbnail_path:
            logger.log(f"  サムネイル: {thumbnail_path}")

        video_id = None
        url = None

        if no_upload:
            logger.log("アップロードをスキップしました（--no-upload 指定）")
        else:
            # ── 1日1本ガード: 排他ロック付き重複アップロード防止 ──
            _upload_lock_file = _lock_path.with_suffix(".lock")
            _upload_lock_file.parent.mkdir(exist_ok=True)
            _lock_fd = open(_upload_lock_file, "w")
            _lock_fd.write("L")
            _lock_fd.flush()
            try:
                if sys.platform == "win32":
                    import msvcrt
                    _lock_fd.seek(0)
                    msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(_lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (IOError, OSError):
                _lock_fd.close()
                _msg = "別のアップロードプロセスが実行中です。1日1本ルールにより中止します。"
                logger.log(f"[重複チェック] {_msg}")
                raise RuntimeError(_msg)

            try:
                # JST日付でチェック（YouTube APIのUTC publishedAtと整合させる）
                _JST_OFFSET = timedelta(hours=9)
                _now_jst = datetime.utcnow() + _JST_OFFSET
                today_str = _now_jst.strftime("%Y-%m-%d")
                # UTC換算の当日開始/終了（JSTの当日0:00-23:59 = UTCの前日15:00-当日14:59）
                _today_utc_start = (_now_jst.replace(hour=0, minute=0, second=0) - _JST_OFFSET).strftime("%Y-%m-%dT%H:%M:%SZ")

                _already_uploaded = False

                # チェック1: ローカルの投稿記録（形式: "YYYY-MM-DD|video_id" or "YYYY-MM-DD"）
                try:
                    if _lock_path.exists():
                        _lock_content = _lock_path.read_text(encoding="utf-8").strip()
                        _lock_parts = _lock_content.split("|", 1)
                        last_date = _lock_parts[0]
                        _recorded_vid = _lock_parts[1] if len(_lock_parts) > 1 else ""
                        if last_date == today_str:
                            # 記録された動画IDがYouTubeで有効か検証
                            if _recorded_vid:
                                try:
                                    from youtube_uploader import _get_youtube_client as _gc
                                    _yt_check = _gc()
                                    _v_detail = _yt_check.videos().list(
                                        part="snippet,status", id=_recorded_vid
                                    ).execute()
                                    if _v_detail.get("items"):
                                        _v_title = _v_detail["items"][0].get("snippet", {}).get("title", "")
                                        # テスト動画は重複カウントしない
                                        if is_test_video(_v_title):
                                            logger.log(f"[重複チェック] 記録済み動画はテスト動画 → 再アップロード許可: {_v_title[:40]}")
                                        else:
                                            _v_privacy = _v_detail["items"][0]["status"].get("privacyStatus", "")
                                            if _v_privacy in ("public", "private"):
                                                _publish_at = _v_detail["items"][0]["status"].get("publishAt", "")
                                                if _v_privacy == "public" or _publish_at:
                                                    _already_uploaded = True
                                                    logger.log(f"[重複チェック] ローカル記録: 本日({today_str})アップロード済み(ID:{_recorded_vid}, 状態:{_v_privacy})")
                                                else:
                                                    # 非公開かつ予約なし = 手動で非公開にされた不良動画 → ブロックしない
                                                    logger.log(f"[重複チェック] 記録済み動画{_recorded_vid}は非公開(予約なし) → 再アップロード許可")
                                    else:
                                        # 動画が削除されている → ブロックしない
                                        logger.log(f"[重複チェック] 記録済み動画{_recorded_vid}は削除済み → 再アップロード許可")
                                except Exception as _ve:
                                    # API失敗時はローカル記録を信頼してブロック
                                    _already_uploaded = True
                                    logger.log(f"[重複チェック] YouTube検証失敗、安全側でブロック: {_ve}")
                            else:
                                # 旧形式（日付のみ）の場合はそのままブロック
                                _already_uploaded = True
                                logger.log(f"[重複チェック] ローカル記録: 本日({today_str})すでにアップロード済み")
                except Exception:
                    pass

                # チェック2: YouTube APIで当日アップロード済み動画を確認（クォータ節約: channels+playlistItems）
                if not _already_uploaded:
                    try:
                        from youtube_uploader import _get_youtube_client
                        _yt = _get_youtube_client()
                        # アップロードプレ��リストIDを取得���1ユニット）
                        _ch = _yt.channels().list(part="contentDetails", mine=True).execute()
                        _uploads_pl = _ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
                        # 最新5件を取得（1ユニット）
                        _pl_items = _yt.playlistItems().list(
                            part="snippet", playlistId=_uploads_pl, maxResults=5
                        ).execute()
                        for _item in _pl_items.get("items", []):
                            _pub_utc = _item["snippet"].get("publishedAt", "")
                            # UTC→JST変換して日付比較
                            if _pub_utc:
                                try:
                                    _pub_dt = datetime.strptime(_pub_utc, "%Y-%m-%dT%H:%M:%SZ") + _JST_OFFSET
                                    if _pub_dt.strftime("%Y-%m-%d") == today_str:
                                        _dup_title = _item["snippet"]["title"]
                                        # テスト動画は重複カウントしない（共通判定）
                                        if is_test_video(_dup_title):
                                            logger.log(
                                                f"[重複チェック] テスト動画をスキップ"
                                                f"「{_dup_title}」(UTC: {_pub_utc})"
                                            )
                                            continue
                                        _already_uploaded = True
                                        logger.log(
                                            f"[重複チェック] YouTube API: 本日アップロード済み動画を検出"
                                            f"「{_dup_title}」(UTC: {_pub_utc})"
                                        )
                                        break
                                except ValueError:
                                    pass
                    except Exception as _e:
                        # API失敗時は安全側に倒す（ローカルチェックが通過済みなら続行、未通過なら中止）
                        if _lock_path.exists():
                            logger.log(f"[重複チェック] YouTube API確認失敗、ローカル記録なし → 続行: {_e}")
                        else:
                            logger.log(f"[重複チェック] YouTube API確認失敗、ローカル記録もなし → 続行（初回）: {_e}")

                if _already_uploaded:
                    _msg = f"本日({today_str} JST)はすでに動画がアップロードされています。1日1本ルールにより中止します。"
                    logger.log(f"[重複チェック] {_msg}")
                    from notifier import notify_error as _ne
                    _ne("重複アップロード防止", RuntimeError(_msg))
                    raise RuntimeError(_msg)

                logger.log(f"[重複チェック] OK: 本日({today_str} JST)の投稿はまだありません")

                # ボット判定回避の待機（1〜5分のランダム待機）
                if not skip_wait:
                    wait_sec = random.randint(60, 300)
                    logger.log(f"アップロード前に {wait_sec} 秒待機しています（ボット判定回避）...")
                    time.sleep(wait_sec)

                # 予約投稿時刻の決定
                publish_at = None
                if publish_time:
                    h, m = map(int, publish_time.split(":"))
                    publish_at = datetime.now().replace(hour=h, minute=m, second=0, microsecond=0)
                    if publish_at <= datetime.now():
                        publish_at += timedelta(days=1)
                elif publish_hours > 0:
                    publish_at = datetime.now() + timedelta(hours=publish_hours)

                # アップロード実行
                video_id = upload_video(
                    video_path=video_path,
                    title=youtube_title,
                    description=description,
                    tags=tags,
                    thumbnail_path=thumbnail_path,
                    publish_at=publish_at,
                    privacy="public" if publish_at is None else None,
                )
                url = get_video_url(video_id)

                if publish_at:
                    logger.log(f"予約投稿完了！ {publish_at.strftime('%Y/%m/%d %H:%M')} に公開されます")
                else:
                    logger.log("公開完了！")
                logger.log(f"URL: {url}")

                # 自動生成字幕の削除（焼き込み字幕と重複するため不要）
                # アップロード直後はまだ生成されていない場合が多いが、試行しておく
                try:
                    deleted_captions = delete_auto_captions(video_id)
                    if deleted_captions:
                        logger.log(f"  自動字幕を {deleted_captions} トラック削除しました")
                    else:
                        logger.log("  自動字幕はまだ生成されていません（run_monitorで再試行します）")
                except Exception as _cap_e:
                    logger.log(f"  [!] 自動字幕削除スキップ（後で再試行）: {_cap_e}")

                # 成功通知
                notify_success(theme, url)

                # 1日1本ガード: 投稿成功日+動画IDを記録（ロック保持中に書き込み）
                # テスト動画は1日1本ルールの対象外なので記録しない
                if not is_test_video(youtube_title):
                    _lock_path.write_text(f"{today_str}|{video_id}", encoding="utf-8")
                else:
                    logger.log("[重複チェック] テスト動画のため last_upload_date.txt への記録をスキップ")

            finally:
                # ロック解放
                if sys.platform == "win32":
                    import msvcrt
                    try:
                        _lock_fd.seek(0)
                        msvcrt.locking(_lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                    except OSError:
                        pass
                else:
                    import fcntl
                    fcntl.flock(_lock_fd, fcntl.LOCK_UN)
                _lock_fd.close()

        # コミュニティ投稿テキストを生成
        community_post_path = None
        try:
            community_post_path = generate_community_post(
                youtube_title, description, url or "", OUTPUT_DIR
            )
            if community_post_path:
                logger.log(f"コミュニティ投稿文: {community_post_path}")
                logger.log("  ※ YouTubeスタジオ → コミュニティ → 新しい投稿 に貼り付けてください")
        except Exception as e:
            logger.log(f"  [!] コミュニティ投稿文生成スキップ: {e}")

        # パイプライン状態を更新
        output_files = []
        if video_id:
            output_files.append(f"video_id:{video_id}")
        if url:
            output_files.append(f"url:{url}")
        if community_post_path:
            output_files.append(str(community_post_path.name))
        update_phase(run_dir, "upload", "completed", outputs=output_files)

        result = {
            "video_id": video_id,
            "url": url,
            "community_post": str(community_post_path) if community_post_path else None,
        }
        logger.log("アップロードスキル完了")
        return result

    except Exception as e:
        update_phase(run_dir, "upload", "failed", error=str(e))
        notify_error("YouTubeアップロード", e)
        raise


# ── CLI ──────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="YouTubeアップロードスキル")
    parser.add_argument("--run-dir", required=True, help="パイプラインの実行ディレクトリ")
    parser.add_argument("--publish-time", type=str, default=None,
                        help="予約投稿時刻（HH:MM形式、過ぎていたら翌日）")
    parser.add_argument("--publish-hours", type=int, default=0,
                        help="N時間後に予約投稿（0=即公開）")
    parser.add_argument("--no-upload", action="store_true",
                        help="アップロードをスキップ")
    parser.add_argument("--skip-wait", action="store_true",
                        help="ボット判定回避の待機をスキップ")
    args = parser.parse_args()

    result = run_upload(
        args.run_dir,
        publish_time=args.publish_time,
        publish_hours=args.publish_hours,
        no_upload=args.no_upload,
        skip_wait=args.skip_wait,
    )
    print(f"\n動画ID: {result['video_id']}")
    print(f"URL: {result['url']}")
    if result["community_post"]:
        print(f"コミュニティ投稿文: {result['community_post']}")


if __name__ == "__main__":
    main()
