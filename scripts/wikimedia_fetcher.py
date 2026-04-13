# wikimedia_fetcher.py — Wikimedia Commons 画像取得
#
# 生物の和名・学名で Commons を検索し、ライセンス情報付きの画像を取得する。
# ライセンス情報が取れない画像は fail-closed で破棄。

import html
import os
import re
import time
from dataclasses import dataclass, asdict
from pathlib import Path

import requests

API_URL = "https://commons.wikimedia.org/w/api.php"
USER_AGENT = "YukkuriCreaturesBot/1.0 (yukkuri-health-lab; automated educational content)"
REQUEST_INTERVAL = 1.0  # Wikimedia API ポリシー: 1秒間隔
REQUEST_TIMEOUT = 15

# 許可ライセンス（ホワイトリスト、小文字で判定）
ALLOWED_LICENSE_PATTERNS = [
    "cc by-sa",
    "cc by ",
    "cc-by-sa",
    "cc-by ",
    "cc0",
    "public domain",
    "pd-",
    "pd ",
]

# 除外する MIME タイプ
EXCLUDED_MIME = {"image/svg+xml", "application/pdf", "image/gif"}

_last_request_time = 0.0


@dataclass
class WikimediaImage:
    """Wikimedia Commons の画像情報。"""
    title: str          # ファイルタイトル (File:xxx.jpg)
    url: str            # 元画像の直URL
    thumb_url: str      # サムネイルURL (1280px幅)
    width: int          # 元画像の幅
    height: int         # 元画像の高さ
    author: str         # 著作者名（HTMLタグ除去済み）
    license_name: str   # ライセンス名 (例: "CC BY-SA 4.0")
    license_url: str    # ライセンスURL

    def to_dict(self) -> dict:
        return asdict(self)

    def credit_text(self) -> str:
        """クレジット表記用テキスト。"""
        return f"{self.author} / {self.license_name}"


def _rate_limit():
    """API リクエスト間隔を保証する。"""
    global _last_request_time
    elapsed = time.time() - _last_request_time
    if elapsed < REQUEST_INTERVAL:
        time.sleep(REQUEST_INTERVAL - elapsed)
    _last_request_time = time.time()


def _strip_html(text: str) -> str:
    """HTML タグを除去してプレーンテキストにする。"""
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    return text.strip()


def _is_allowed_license(license_name: str) -> bool:
    """ライセンスがホワイトリストに含まれるか判定。"""
    if not license_name:
        return False
    lower = license_name.lower().strip()
    for pattern in ALLOWED_LICENSE_PATTERNS:
        if pattern in lower:
            return True
    return False


def _extract_image_info(page: dict) -> WikimediaImage | None:
    """API レスポンスの1ページからライセンス検証済み WikimediaImage を抽出。

    ライセンス情報が不足・不許可の場合は None を返す（fail-closed）。
    """
    imageinfo_list = page.get("imageinfo", [])
    if not imageinfo_list:
        return None

    ii = imageinfo_list[0]

    # MIME チェック
    mime = ii.get("mime", "")
    if mime in EXCLUDED_MIME:
        return None

    # 画像URLの存在チェック
    url = ii.get("url", "")
    thumb_url = ii.get("thumburl", "")
    if not url:
        return None

    # ライセンス情報の抽出
    ext = ii.get("extmetadata", {})
    license_name = ext.get("LicenseShortName", {}).get("value", "")
    license_url = ext.get("LicenseUrl", {}).get("value", "")
    author_raw = ext.get("Artist", {}).get("value", "")

    # fail-closed: ライセンス名が取れないor許可リストにない → 破棄
    if not _is_allowed_license(license_name):
        return None

    # fail-closed: 著作者名が取れない → 破棄
    author = _strip_html(author_raw)
    if not author:
        return None

    return WikimediaImage(
        title=page.get("title", ""),
        url=url,
        thumb_url=thumb_url or url,
        width=ii.get("width", 0),
        height=ii.get("height", 0),
        author=author,
        license_name=license_name,
        license_url=license_url,
    )


def search_images(query: str, limit: int = 5) -> list[WikimediaImage]:
    """Wikimedia Commons で画像を検索し、ライセンス検証済みの結果を返す。

    Args:
        query: 検索語（和名・学名どちらでも可）
        limit: 返却する最大件数（デフォルト5）

    Returns:
        WikimediaImage のリスト。ライセンス不明の画像は除外済み。
        ネットワークエラー時は空リストを返す。
    """
    if not query or not query.strip():
        return []

    _rate_limit()

    # API リクエスト件数はフィルタ後に limit 件残るよう多めに取得
    fetch_limit = min(limit * 3, 50)

    params = {
        "action": "query",
        "generator": "search",
        "gsrnamespace": 6,  # File namespace
        "gsrsearch": query,
        "gsrlimit": fetch_limit,
        "prop": "imageinfo",
        "iiprop": "url|extmetadata|size|mime",
        "iiurlwidth": 1280,
        "format": "json",
    }

    try:
        resp = requests.get(
            API_URL,
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[wikimedia_fetcher] 検索エラー: {e}")
        return []

    pages = data.get("query", {}).get("pages", {})
    if not pages:
        return []

    results = []
    # 検索スコア順（index順）でソート
    sorted_pages = sorted(pages.values(), key=lambda p: p.get("index", 9999))

    for page in sorted_pages:
        img = _extract_image_info(page)
        if img is not None:
            results.append(img)
            if len(results) >= limit:
                break

    return results


def fetch_image(url: str, save_path: str) -> bool:
    """画像をダウンロードしてローカルに保存する。

    Args:
        url: 画像の直URL
        save_path: 保存先パス

    Returns:
        True: 保存成功、False: 失敗
    """
    if not url:
        return False

    _rate_limit()

    try:
        resp = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=30,
            stream=True,
        )
        resp.raise_for_status()

        save_dir = os.path.dirname(save_path)
        if save_dir:
            os.makedirs(save_dir, exist_ok=True)

        tmp_path = save_path + ".tmp"
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)
        os.replace(tmp_path, save_path)
        return True

    except (requests.RequestException, OSError) as e:
        print(f"[wikimedia_fetcher] ダウンロードエラー: {e}")
        # tmp ファイルの残骸を掃除
        tmp_path = save_path + ".tmp"
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
        return False
