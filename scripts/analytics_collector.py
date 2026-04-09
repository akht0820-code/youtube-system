# YouTube動画データ収集モジュール

import re
from datetime import datetime

from analytics_base import StatsCollector


def _parse_iso8601_duration(duration: str) -> int:
    """ISO 8601 duration (PT1H5M30S) を秒数に変換する"""
    if not duration:
        return 0
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", duration)
    if not m:
        return 0
    h, mi, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mi * 60 + s


def _fetch_all_video_stats(youtube) -> list[dict]:
    """
    YouTube APIクライアントを受け取り、チャンネルの全動画統計を返す

    Returns:
        [{"video_id", "title", "published_at", "views", "likes", "comments", "url"}, ...]
    """
    # ── 1. アップロードプレイリストIDを取得 ──────────────
    ch_res = youtube.channels().list(part="contentDetails", mine=True).execute()
    if not ch_res.get("items"):
        raise RuntimeError("チャンネルが見つかりません。認証アカウントを確認してください。")
    uploads_playlist = ch_res["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # ── 2. 全動画IDを収集 ────────────────────────────────
    video_ids = []
    next_page = None
    while True:
        pl_res = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=next_page,
        ).execute()
        video_ids += [item["contentDetails"]["videoId"] for item in pl_res["items"]]
        next_page = pl_res.get("nextPageToken")
        if not next_page:
            break

    if not video_ids:
        return []

    # ── 3. 統計データを50件ずつバッチ取得 ────────────────
    videos = []
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        stats_res = youtube.videos().list(
            part="snippet,statistics,contentDetails",
            id=",".join(batch),
        ).execute()

        for item in stats_res.get("items", []):
            snippet    = item.get("snippet", {})
            statistics = item.get("statistics", {})
            content    = item.get("contentDetails", {})
            video_id   = item["id"]

            published_raw = snippet.get("publishedAt", "")
            published_at  = published_raw[:10] if published_raw else ""

            # ISO 8601 duration (PT5M30S) → 秒数に変換
            duration_sec = _parse_iso8601_duration(content.get("duration", ""))

            videos.append({
                "video_id":     video_id,
                "title":        snippet.get("title", ""),
                "published_at": published_at,
                "views":        int(statistics.get("viewCount",    0)),
                "likes":        int(statistics.get("likeCount",    0)),
                "comments":     int(statistics.get("commentCount", 0)),
                "duration_sec": duration_sec,
                "url":          f"https://youtu.be/{video_id}",
            })

    videos.sort(key=lambda v: v["published_at"], reverse=True)
    return videos


class YouTubeStatsCollector(StatsCollector):
    """YouTube Data API v3 を使って自チャンネルの動画統計を収集する"""

    def collect(self) -> list[dict]:
        from auth_utils import get_credentials
        from googleapiclient.discovery import build

        youtube = build("youtube", "v3", credentials=get_credentials())
        return _fetch_all_video_stats(youtube)
