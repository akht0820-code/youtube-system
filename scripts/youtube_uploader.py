# YouTube自動アップロードモジュール

import json
import ssl
import time
import sys
from datetime import datetime, timezone
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from auth_utils import get_credentials


# ── 認証 ─────────────────────────────────────────────────

def _get_youtube_client():
    """OAuth2認証を行いYouTube APIクライアントを返す"""
    return build("youtube", "v3", credentials=get_credentials())


# ── テスト動画判定（全レイヤー共通基準） ─────────────────────

def is_test_video(title: str) -> bool:
    """タイトルが[TEST]で始まる動画はテスト動画として扱う"""
    return title.strip().upper().startswith("[TEST]")


# ── 重複チェック（最低層の防御） ───────────────────────────

def _check_duplicate_on_youtube(youtube) -> str | None:
    """今日アップロード済みで公開予定の動画があるか確認する。

    Returns:
        重複動画のタイトル（あれば）。なければNone。
        API失敗時もNone（安全側: アップロードを止めない）。
    """
    from datetime import timedelta
    try:
        jst = timezone(timedelta(hours=9))
        today_jst = datetime.now(jst).strftime("%Y-%m-%d")

        # 自分のチャンネルの最新動画を取得
        resp = youtube.search().list(
            part="snippet",
            forMine=True,
            type="video",
            maxResults=5,
            order="date",
        ).execute()

        for item in resp.get("items", []):
            title = item["snippet"].get("title", "")
            # テスト動画は重複カウントしない
            if is_test_video(title):
                continue

            vid = item["id"]["videoId"]
            # 詳細ステータスを取得
            detail = youtube.videos().list(
                part="status,contentDetails",
                id=vid,
            ).execute()
            if not detail.get("items"):
                continue
            status = detail["items"][0]["status"]
            privacy = status.get("privacyStatus", "")
            publish_at_str = status.get("publishAt", "")

            # 公開済み動画: 今日アップロードされたpublic動画
            if privacy == "public":
                pub_date = item["snippet"].get("publishedAt", "")[:10]
                if pub_date == datetime.now(timezone.utc).strftime("%Y-%m-%d"):
                    return title

            # 予約投稿: private + publishAtが未来（今日の公開予定）
            if privacy == "private" and publish_at_str:
                try:
                    pub_dt = datetime.fromisoformat(publish_at_str.replace("Z", "+00:00"))
                    pub_jst = pub_dt.astimezone(jst).strftime("%Y-%m-%d")
                    if pub_jst == today_jst and pub_dt > datetime.now(timezone.utc):
                        return title
                except Exception:
                    pass

            # 手動で非公開にした動画(publishAtなし)はスキップ = ブロックしない
    except Exception:
        pass  # API失敗時は安全側に倒す（アップロードを止めない）

    return None


# ── アップロード ──────────────────────────────────────────

def upload_video(
    video_path: Path,
    title: str,
    description: str,
    tags: list[str],
    thumbnail_path: Path | None = None,
    publish_at: datetime | None = None,
    privacy: str | None = None,
) -> str:
    """
    動画をYouTubeにアップロードする

    Args:
        video_path:      動画ファイルのパス
        title:           動画タイトル
        description:     動画説明文
        tags:            タグのリスト
        thumbnail_path:  サムネイル画像のパス（省略可）
        publish_at:      予約投稿の日時（Noneなら即公開）

    Returns:
        アップロードされた動画のID
    """
    if not video_path.exists():
        raise FileNotFoundError(f"動画ファイルが見つかりません: {video_path}")

    youtube = _get_youtube_client()

    # ── 最低層の重複防御: YouTube APIで今日の公開予定動画を確認 ──
    # テスト動画のアップロード時は重複チェック自体をスキップ
    if not is_test_video(title):
        _dup_title = _check_duplicate_on_youtube(youtube)
        if _dup_title:
            raise RuntimeError(
                f"[upload_video] 今日の公開予定動画が既に存在します: 「{_dup_title}」。"
                f"重複アップロードを防止しました。"
            )

    # privacy を明示指定しない限り public にはしない（誤公開防止）
    # - privacy 指定あり → そちらを優先
    # - publish_at あり  → "private"（YouTube が指定時刻に自動公開）
    # - どちらもなし     → "private"（意図しない即時公開を防ぐ）
    # 即時公開したい場合は明示的に privacy="public" を渡すこと
    if privacy:
        privacy_status = privacy
    elif publish_at:
        privacy_status = "private"
    else:
        # デフォルトは非公開（意図しない即時公開を防ぐ）
        privacy_status = "private"

    body = {
        "snippet": {
            "title": title,
            "description": description,
            "tags": tags,
            "categoryId": "27",          # 教育カテゴリ
            "defaultLanguage": "ja",
            "defaultAudioLanguage": "ja",
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
            # YouTube 2025年ポリシー: AI生成コンテンツの開示義務
            # AIで作成・加工した音声・映像を含む場合は True を設定する
            "containsSyntheticMedia": True,
        },
    }

    if publish_at:
        # YouTube APIはUTC・ISO 8601形式で受け付ける
        if publish_at.tzinfo is None:
            # タイムゾーン未指定ならJSTとして扱いUTCに変換
            from datetime import timedelta
            publish_at = publish_at.replace(tzinfo=timezone(timedelta(hours=9)))
        body["status"]["publishAt"] = publish_at.astimezone(timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )

    # 動画ファイルをチャンク分割でアップロード（大容量対応）
    media = MediaFileUpload(
        str(video_path),
        mimetype="video/mp4",
        chunksize=10 * 1024 * 1024,  # 10MB単位
        resumable=True,
    )

    request = youtube.videos().insert(
        part="snippet,status",   # status に containsSyntheticMedia を含む
        body=body,
        media_body=media,
    )

    print("YouTubeにアップロードしています...")
    response = None
    retries = 0
    _MAX_RETRIES = 5
    while response is None:
        try:
            status, response = request.next_chunk()
            if status:
                pct = int(status.progress() * 100)
                print(f"  アップロード中... {pct}%", end="\r")
            retries = 0
        except (ssl.SSLEOFError, ssl.SSLError, ConnectionResetError, TimeoutError) as e:
            retries += 1
            if retries > _MAX_RETRIES:
                raise
            wait = min(2 ** retries, 60)
            print(f"\n  [ネットワーク一時エラー] {e.__class__.__name__}: {e}")
            print(f"  {wait}秒後にチャンクを再試行します ({retries}/{_MAX_RETRIES})...")
            time.sleep(wait)
        except HttpError as e:
            # 5xx は一時的サーバーエラーとしてリトライ
            if e.resp.status in (500, 502, 503, 504):
                retries += 1
                if retries > _MAX_RETRIES:
                    raise
                wait = min(2 ** retries, 60)
                print(f"\n  [サーバーエラー {e.resp.status}] {wait}秒後にリトライ ({retries}/{_MAX_RETRIES})...")
                time.sleep(wait)
            else:
                raise

    video_id = response["id"]
    print(f"  アップロード完了！ 動画ID: {video_id}")

    # サムネイルを設定
    if thumbnail_path and thumbnail_path.exists():
        print("  サムネイルを設定しています...")
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path)),
        ).execute()
        print("  サムネイル設定完了")

    return video_id


def delete_auto_captions(video_id: str) -> int:
    """YouTubeの自動生成字幕を削除する。

    焼き込み字幕と重複するため、自動生成字幕は不要。
    アップロード直後は自動字幕がまだ生成されていないことがあるため、
    run_monitor.py等から事後的に呼び出すことを想定。

    Returns:
        削除した字幕トラック数
    """
    youtube = _get_youtube_client()
    try:
        captions = youtube.captions().list(
            part="snippet",
            videoId=video_id,
        ).execute()

        deleted = 0
        for item in captions.get("items", []):
            track_kind = item["snippet"].get("trackKind", "")
            # ASR = Automatic Speech Recognition（自動生成字幕）
            if track_kind == "ASR":
                caption_id = item["id"]
                lang = item["snippet"].get("language", "")
                youtube.captions().delete(id=caption_id).execute()
                print(f"  自動字幕を削除しました: {lang} (ID: {caption_id})")
                deleted += 1
        return deleted
    except Exception as e:
        print(f"  [警告] 自動字幕削除失敗（処理続行）: {e}")
        return 0


def get_video_url(video_id: str) -> str:
    return f"https://youtu.be/{video_id}"


def delete_video(video_id: str) -> None:
    """YouTubeから動画を削除する"""
    youtube = _get_youtube_client()
    youtube.videos().delete(id=video_id).execute()
    print(f"  動画を削除しました: {video_id}")


# ── CLI ──────────────────────────────────────────────────

def _parse_publish_at(text: str) -> datetime | None:
    """
    「2026/03/25 18:00」などの入力をdatetimeに変換する
    空文字またはスキップなら None を返す
    """
    text = text.strip()
    if not text or text.lower() in ("skip", "s", "スキップ", ""):
        return None
    for fmt in ("%Y/%m/%d %H:%M", "%Y-%m-%d %H:%M", "%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    raise ValueError(f"日時の形式が認識できません: {text}\n例: 2026/03/25 18:00")


if __name__ == "__main__":
    args = sys.argv[1:]

    if "--auth" in args:
        # 認証だけ行う
        print("YouTube APIの認証を開始します...")
        _get_youtube_client()
        print("認証完了！token.json に保存されました。")

    elif "--upload" in args:
        # 手動アップロード: python youtube_uploader.py --upload <動画> <タイトル>
        if len(args) < 3:
            print("使い方: python youtube_uploader.py --upload <動画パス> <タイトル>")
            sys.exit(1)
        video  = Path(args[1])
        title  = args[2]
        vid_id = upload_video(video, title, "", [])
        print(f"URL: {get_video_url(vid_id)}")

    else:
        print("使い方:")
        print("  python youtube_uploader.py --auth          認証（初回のみ）")
        print("  python youtube_uploader.py --upload <動画> <タイトル>  手動アップロード")
