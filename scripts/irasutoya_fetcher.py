# irasutoya_fetcher.py — いらすとや から関連イラストを検索・ダウンロードするモジュール
# 台本のセクションキーワードに基づいて画像を取得し assets/irasutoya/ にキャッシュする

from __future__ import annotations
import hashlib
import re
import time
import urllib.request
import urllib.parse
from pathlib import Path
from typing import Iterator

_CACHE_DIR = Path(__file__).parent.parent / "assets" / "irasutoya"
_BASE_URL   = "https://www.irasutoya.com"
_SEARCH_URL = "https://www.irasutoya.com/search/label/{keyword}"
_QUERY_URL  = "https://www.irasutoya.com/search?q={keyword}&max-results=10"

# フォールバック画像マップ（検索失敗時用）
_FALLBACK_KEYWORDS: dict[str, list[str]] = {
    "春":       ["春", "桜", "花"],
    "体":       ["人体", "体"],
    "ストレス": ["ストレス", "悩み"],
    "睡眠":     ["寝る人", "眠い"],
    "食事":     ["食事", "食べ物"],
    "運動":     ["運動", "体操"],
    "医師":     ["医師", "病院"],
}

# キーワード別の検索優先順位リスト
# 単一オブジェクト・シンプルなキャラ画像が多いキーワードを先に試す
# シーン画像が混じりやすい汎用キーワードは後回し
_KEYWORD_PRIORITY: dict[str, list[str]] = {
    "コーヒー":   ["コーヒーカップ", "コーヒー豆", "コーヒー"],
    "お茶":       ["緑茶", "お茶", "湯呑み"],
    "緑茶":       ["緑茶", "急須", "お茶"],
    "紅茶":       ["紅茶", "ティーカップ", "紅茶"],
    "アルコール": ["ビール", "お酒", "ワイン"],
    "寝る人":     ["寝る人", "枕", "眠い"],
    "運動":       ["ウォーキング", "ジョギング", "体操"],
    "食事":       ["食事", "弁当", "料理"],
    "ストレス":   ["ストレス", "悩む人", "頭を抱える"],
    "腸":         ["腸", "胃腸", "消化"],
    "脳":         ["脳", "思考", "記憶"],
    "心臓":       ["心臓", "心拍", "血管"],
    "血圧":       ["血圧計", "血圧", "高血圧"],
    "血糖値":     ["血糖値", "糖尿病", "インスリン"],
    "ダイエット": ["ダイエット", "体重計", "肥満"],
    "筋トレ":     ["筋トレ", "ダンベル", "筋肉"],
    "歯みがき":   ["歯ブラシ", "歯みがき", "歯"],
    "野菜":       ["野菜", "サラダ", "ブロッコリー"],
    "果物":       ["果物", "りんご", "みかん"],
}

# セクション名によく使われる抽象的なフィラーワード（検索キーワードとして無意味）
_FILLER_WORDS: frozenset[str] = frozenset({
    "ちょっと", "ちなみ", "それで", "だから", "つまり", "もちろん",
    "なんと", "みなさ", "さらに", "まずは", "という", "ところ",
    "なぜか", "でもな", "しかし", "あのな", "実はな", "そこで",
    "いかが", "どうも", "今回は", "今日は", "皆さん", "おまけ",
    "まとめ", "最後に", "最初に", "この動", "その前", "ところで",
})

# 健康動画で頻出するキーワードの事前マッピング（拡張版）
_KEYWORD_MAP: dict[str, str] = {
    # 季節・体調
    "自律神経":   "ストレス",
    "年度末":     "ビジネス",
    "春バテ":     "春",
    "だるい":     "疲れた人",
    "眠い":       "眠い 睡眠",
    "イライラ":   "怒り",
    "呼吸":       "呼吸",
    "入浴":       "お風呂",
    "朝日":       "朝",
    "花粉症":     "花粉症",
    "腸活":       "食事 健康",
    "発酵食品":   "発酵食品",
    "ヨーグルト": "ヨーグルト",
    # 歯・口腔
    "歯みがき":   "歯みがき",
    "歯磨き":     "歯みがき",
    "歯ブラシ":   "歯ブラシ",
    "歯周病":     "歯周病",
    "虫歯":       "虫歯",
    "フロス":     "デンタルフロス",
    "デンタル":   "歯みがき",
    "口臭":       "口臭",
    "歯茎":       "歯周病",
    "歯科":       "歯医者",
    "口腔":       "歯みがき",
    # 生活習慣病
    "コレステロール": "コレステロール",
    "血糖":       "血糖値",
    "血圧":       "血圧",
    "糖尿病":     "糖尿病",
    "メタボ":     "メタボリックシンドローム",
    "心臓":       "心臓",
    "動脈硬化":   "血管",
    # 食事・栄養
    "カルシウム": "牛乳",
    "ビタミン":   "野菜",
    "たんぱく質": "肉",
    "食物繊維":   "野菜",
    "塩分":       "塩",
    "砂糖":       "お菓子",
    "脂肪":       "食べ物",
    # 運動・体
    "ウォーキング": "散歩",
    "ストレッチ": "体操",
    "筋肉":       "筋トレ",
    "肥満":       "体重計",
    # 生活習慣
    "睡眠":       "寝る人",
    "メラトニン": "寝る人",
    "運動":       "運動",
    "喫煙":       "タバコ",
    "飲酒":       "お酒",
    "食事":       "食事",
    # 飲み物・食品（よく出るタイトルワード）
    "コーヒー":   "コーヒー",
    "緑茶":       "緑茶",
    "お茶":       "お茶",
    "紅茶":       "紅茶",
    "アルコール": "お酒",
    # 外見・体の変化
    "白髪":       "おじいさん",   # いらすとやの"白髪"検索は精度が低いのでシニア画像で代替
    "薄毛":       "はげ",
    "肥満":       "体重計",
    "老化":       "おじいさん",
    "病気":       "体調不良",
    "不調":       "体調不良",
    # 臓器・身体部位（具体的なもの）
    "腸":         "腸",
    "脳":         "脳",
    "心臓":       "心臓",
    "肝臓":       "肝臓",
    "腎臓":       "腎臓",
    "筋肉":       "筋トレ",
    # 症状・疾患
    "頭痛":       "頭痛",
    "肩こり":     "肩こり",
    "腰痛":       "腰痛",
    "便秘":       "便秘",
    "むくみ":     "むくみ",
    "疲れ":       "疲れた人",
    "冷え":       "冷え性",
    "アレルギー": "アレルギー",
    "認知症":     "認知症",
    "がん":       "がん 癌",
    # 栄養素・成分
    "カフェイン": "コーヒー",
    "糖質":       "お菓子",
    "タンパク質": "肉",
    "食物繊維":   "野菜",
    "ポリフェノール": "ワイン",
    # 感情・状態（抽象語→いらすとやで実際にヒットする検索語に変換）
    "元気":       "ガッツポーズ",
    "幸せ":       "ガッツポーズ",
    "健康":       "ガッツポーズ",
    "心の健康":   "リラックス",
    "精神":       "リラックス",
    "メンタル":   "リラックス",
    "セロトニン": "リラックス",
    "消化":       "胃腸",
    "胃腸":       "胃腸",
    "不安":       "不安な人",
    "落ち込む":   "落ち込む人",
    "喜ぶ":       "喜ぶ人",
    "悲しい":     "泣く人",
    "怒る":       "怒る人",
    "驚く":       "驚く人",
    "悩む":       "悩む人",
    "困る":       "困る人",
    "笑う":       "笑う人",
    "泣く":       "泣く人",
    "疲れる":     "疲れた人",
    "眠い":       "眠い人",
    "痛い":       "痛がる人",
    "嬉しい":     "喜ぶ人",
    "つらい":     "疲れた人",
    "だるい":     "疲れた人",
    "不足":       "疲れた人",
    # 抽象的なvisual_hint → 具体的な検索キーワードへの変換
    "リラックスする人": "リラックス",
    "衝撃の事実":     "驚く人",
    "無限ループ":     "繰り返し",
    "壊れた家":       "災害",
    "優しい世界":     "平和",
    "解決策":         "ひらめき",
    "イライラする脳": "怒り",
    "スマホのバッテリー切れ": "スマホ 充電",
    "血糖値グラフ":   "血糖値",
    "脳の比較画像":   "脳",
    "卵と納豆":       "卵",
    "卵と納豆と散歩":  "卵",
    "マグネシウムとビタミンB": "サプリメント",
    "肉と大豆":       "肉",
    "睡眠ホルモン":   "寝る人",
    "夜のウォーキング": "散歩",
    "チャンネル登録ボタン": "チャンネル登録",
    "アミノ酸の構造式": "化学式",
    "怒る会社員":     "怒る",
    "落ち込む高齢者": "落ち込む",
    "悩む中年":       "悩む",
    "足がつる人":     "足がつる",
    "目の痙攣":       "痙攣",
    "スマホを見る人": "スマホ",
    "ブルーライト":   "スマホ",
    "スマホ禁止":     "スマホ",
    "F1レース":       "車",
    "怒る鬼":         "鬼",
    "3倍":            "三倍",
}


def _make_cache_path(keyword: str) -> Path:
    """キーワードからキャッシュディレクトリパスを作成する"""
    safe = re.sub(r"[^\w\-]", "_", keyword)[:30]
    return _CACHE_DIR / safe


def _score_entry(keyword: str, title: str) -> int:
    """エントリーのタイトルとキーワードの関連度をスコアリングする。

    スコアが高いほど適切な画像。
    - 100: 「{keyword}のイラスト」完全一致（最も適切）
    - 80:  タイトルが「{keyword}の○○のイラスト」等（修飾付き一致）
    - 60:  キーワードがタイトルに含まれる + 人物系（「○○な人」検索で人の画像）
    - 40:  キーワードがタイトルに含まれる（一般一致）
    - 0:   タイトルにキーワードなし
    """
    # キーワードの主要部分を抽出（「元気な人」→「元気」）
    kw_core = re.split(r"[\s　]", keyword)[0]
    kw_core = re.sub(r"(な|の|する|した|い)$", "", kw_core) or kw_core

    if kw_core not in title:
        return 0

    # 「{keyword}のイラスト」完全一致パターン
    if re.match(rf"^{re.escape(kw_core)}のイラスト", title):
        return 100

    # 人物系キーワード（「○○な人」「○○する人」）で人のイラストか
    is_person_query = "人" in keyword
    is_person_result = "人" in title or "男" in title or "女" in title
    if is_person_query and is_person_result:
        return 60

    # 非人物のノイズ除外（「元気のない通貨」「元気なニワトリ」等）
    _NOISE_WORDS = {"通貨", "お金", "お札", "硬貨", "コイン",
                    "ニワトリ", "鶏", "犬", "猫", "動物",
                    "ロボット", "キャラ", "マスコット",
                    "検査", "無呼吸", "ポリグラフ", "症候群",
                    "ケーキ", "オムレツ", "パフェ", "タルト"}
    for noise in _NOISE_WORDS:
        if noise in title:
            return 10  # ノイズは最低スコア

    return 40


def _fetch_image_urls(keyword: str, max_count: int = 5) -> list[str]:
    """いらすとやからキーワードに対応する画像URLリストを取得する（Blogger feeds API使用）

    スコアリング方式: エントリーのタイトルとキーワードの関連度をスコアリングし、
    最も適切な画像を優先的に返す。max-results=50で広く候補を取得し、
    「{keyword}のイラスト」のような正解が後方にあっても拾えるようにする。
    """
    import json as _json
    # 広く候補を取得（いらすとやAPIは最大約50件返す）
    url = f"https://www.irasutoya.com/feeds/posts/default?q={urllib.parse.quote(keyword)}&max-results=50&alt=json"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YukkuriHealthLab/1.0"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = _json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception:
        return []

    entries = data.get("feed", {}).get("entry", [])

    # 全エントリーをスコアリング
    scored: list[tuple[int, str]] = []
    for entry in entries:
        thumb = entry.get("media$thumbnail", {})
        thumb_url = thumb.get("url", "")
        if not thumb_url:
            continue
        high_res = re.sub(r"/s\d+-c/", "/s600/", thumb_url)
        high_res = re.sub(r"/s\d+/", "/s600/", high_res)

        title = entry.get("title", {}).get("$t", "")
        score = _score_entry(keyword, title)
        scored.append((score, high_res))

    # スコア降順でソート（同スコアはAPI順維持）
    scored.sort(key=lambda x: -x[0])

    result = [url for _, url in scored]
    return list(dict.fromkeys(result))[:max_count]  # 重複除去


def _download_image(url: str, dest: Path) -> bool:
    """画像をダウンロードして保存する"""
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) YukkuriHealthLab/1.0",
               "Referer": _BASE_URL}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = resp.read()
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return len(data) > 1000  # 最低 1KB あれば有効とみなす
    except Exception:
        return False


def _decompose_keyword(keyword: str) -> list[str]:
    """検索結果0件時にキーワードを分解してフォールバック候補を生成する。

    戦略:
      1. スペース区切りなら各単語を個別に試す
      2. _VISUAL_NOUNS に含まれる部分文字列を抽出
      3. カタカナ3文字以上・漢字2文字以上の部分を抽出
    """
    parts: list[str] = []

    # スペース区切り
    if " " in keyword or "　" in keyword:
        for w in re.split(r"[\s　]+", keyword):
            if w and w not in _IGNORE_WORDS and len(w) >= 2:
                parts.append(w)

    # _VISUAL_NOUNS からの部分一致抽出
    for noun in _VISUAL_NOUNS:
        if noun in keyword and noun not in parts:
            parts.append(noun)

    # カタカナ3文字以上
    for w in re.findall(r"[\u30a0-\u30ff]{3,}", keyword):
        if w not in parts and w not in _IGNORE_WORDS:
            parts.append(w)

    # 漢字2文字以上
    for w in re.findall(r"[\u4e00-\u9fff]{2,}", keyword):
        if w not in parts and w not in _IGNORE_WORDS:
            parts.append(w)

    return parts


def fetch(keyword: str, max_count: int = 3) -> list[Path]:
    """
    キーワードで いらすとや を検索し、画像ファイルパスのリストを返す。
    _KEYWORD_PRIORITY に登録済みのキーワードは、シーン画像が少ない
    具体的なサブキーワードを優先して検索する。
    検索結果0件の場合、キーワードを自動分解して再検索する。

    Args:
        keyword: 検索キーワード（日本語）
        max_count: 最大取得枚数

    Returns:
        ローカルに保存した画像ファイルパスのリスト（空の場合もある）
    """
    # キーワードのマッピング変換
    search_kw = _KEYWORD_MAP.get(keyword, keyword)

    # 優先キーワードリストがあれば複数キーワードを順に試す
    priority_kws = _KEYWORD_PRIORITY.get(search_kw, [search_kw])

    downloaded: list[Path] = []

    for kw in priority_kws:
        if len(downloaded) >= max_count:
            break

        cache_dir = _make_cache_path(kw)
        cache_dir.mkdir(parents=True, exist_ok=True)

        # キャッシュ確認（既存ファイルを追加）
        cached = sorted(cache_dir.glob("*.png")) + sorted(cache_dir.glob("*.jpg"))
        downloaded.extend(p for p in cached if p not in downloaded)

        if len(downloaded) >= max_count:
            break

        # キャッシュ不足なら検索してダウンロード
        img_urls = _fetch_image_urls(kw, max_count=max_count * 2)
        if not img_urls:
            for fb_kw in _FALLBACK_KEYWORDS.get(kw, []):
                img_urls = _fetch_image_urls(fb_kw, max_count=max_count)
                if img_urls:
                    break

        for url in img_urls:
            if len(downloaded) >= max_count:
                break
            ext = ".png" if url.endswith(".png") else ".jpg"
            fname = hashlib.md5(url.encode()).hexdigest()[:12] + ext
            dest = cache_dir / fname
            if dest.exists():
                if dest not in downloaded:
                    downloaded.append(dest)
                continue
            if _download_image(url, dest):
                downloaded.append(dest)
                time.sleep(0.5)  # サーバー負荷対策

    # 検索結果0件: キーワードを自動分解して再検索
    if not downloaded:
        fallback_parts = _decompose_keyword(keyword)
        for fb_kw in fallback_parts:
            if len(downloaded) >= max_count:
                break
            # 再帰を避けるため直接検索
            fb_mapped = _KEYWORD_MAP.get(fb_kw, fb_kw)
            cache_dir = _make_cache_path(fb_mapped)
            cache_dir.mkdir(parents=True, exist_ok=True)
            cached = sorted(cache_dir.glob("*.png")) + sorted(cache_dir.glob("*.jpg"))
            downloaded.extend(p for p in cached if p not in downloaded)
            if len(downloaded) >= max_count:
                break
            img_urls = _fetch_image_urls(fb_mapped, max_count=max_count)
            for url in img_urls:
                if len(downloaded) >= max_count:
                    break
                ext = ".png" if url.endswith(".png") else ".jpg"
                fname = hashlib.md5(url.encode()).hexdigest()[:12] + ext
                dest = cache_dir / fname
                if dest.exists():
                    if dest not in downloaded:
                        downloaded.append(dest)
                    continue
                if _download_image(url, dest):
                    downloaded.append(dest)
                    time.sleep(0.5)

    return downloaded[:max_count]


def fetch_for_script(script: dict, max_per_section: int = 2) -> dict[str, list[Path]]:
    """
    台本 JSON のセクションごとに関連いらすとや画像を取得する。

    Returns:
        section_name -> [image_path, ...] のマッピング
    """
    result: dict[str, list[Path]] = {}

    sections = script.get("sections", [])
    for sec in sections:
        name = sec.get("section", sec.get("name", ""))
        # セクション名は「ちょっと待って」などの抽象的なフックが多いため
        # 実際のセリフ内容のみをキーワード抽出の対象にする
        content = " ".join(
            line.get("text", "") for line in sec.get("lines", [])
        )

        keywords = _extract_keywords(content)
        images: list[Path] = []
        for kw in keywords[:3]:
            imgs = fetch(kw, max_count=max_per_section)
            images.extend(imgs)
            if len(images) >= max_per_section:
                break

        result[name] = images[:max_per_section]

    return result


# 画面に映すべき具体物・行動（いらすとやで見つかりやすいもの）
# ここに登録された単語が最優先で抽出される
_VISUAL_NOUNS: frozenset[str] = frozenset({
    # 食品・飲み物
    "コーヒー", "緑茶", "お茶", "紅茶", "牛乳", "豆乳", "水",
    "プロテイン", "サプリ", "サプリメント", "ヨーグルト", "チーズ",
    "納豆", "豆腐", "卵", "肉", "魚", "野菜", "果物", "米", "パン",
    "ご飯", "味噌汁", "サラダ", "チョコ", "チョコレート", "お菓子",
    "ケーキ", "アイス", "ジュース", "お酒", "ビール", "ワイン",
    "バナナ", "りんご", "トマト", "ブロッコリー", "ニンニク", "しょうが",
    "レモン", "はちみつ", "酢", "梅干し", "キムチ", "味噌", "醤油",
    "塩", "砂糖", "油", "オリーブオイル", "ナッツ", "アーモンド",
    # 体の部位・臓器
    "腸", "脳", "心臓", "肝臓", "腎臓", "胃", "肺", "血管",
    "筋肉", "骨", "関節", "歯", "目", "耳", "肌", "髪",
    # 病気・症状
    "頭痛", "肩こり", "腰痛", "便秘", "むくみ", "冷え性",
    "花粉症", "虫歯", "歯周病", "認知症", "糖尿病", "高血圧",
    # 生活行動
    "階段", "エレベーター", "エスカレーター", "散歩", "ジョギング",
    "筋トレ", "ストレッチ", "体操", "ヨガ", "水泳",
    "歯みがき", "歯磨き", "入浴", "シャワー", "睡眠", "昼寝",
    "料理", "買い物", "掃除", "通勤", "仕事",
    # 場所・道具
    "病院", "薬局", "体重計", "血圧計", "体温計", "薬",
    "注射", "マスク", "スマホ", "パソコン", "テレビ",
    "布団", "枕", "椅子", "机", "ソファ",
})

# キャラ名やセリフのつなぎ言葉（抽出から除外）
_IGNORE_WORDS: frozenset[str] = frozenset({
    "霊夢", "魔理沙", "れいむ", "まりさ",
    "最大", "最近", "最後", "最初", "具体的", "科学的", "劇的",
    "時系列", "面白", "本当", "大丈夫", "大事", "大切", "重要",
    "原因", "結果", "効果", "影響", "問題", "解決", "方法",
    "質問", "意外", "実際", "今回", "今日", "明日", "毎日",
    "動画", "第一歩", "全部", "絶対", "紹介", "説明", "理由",
    "ポイント", "メリット", "デメリット", "バランス", "リスク",
    "タイミング", "テーマ", "データ", "パターン", "レベル",
    "科学的根拠", "継続", "習慣", "変化", "研究", "報告",
    "意識", "無意識", "足腰", "全部私", "絶対見", "注意",
    "感覚", "状態", "程度", "目安", "目的", "意味", "秘密",
    "正体", "常識", "特徴", "証拠", "情報", "知識", "経験",
    "デパート", "カロリー",
}) | _FILLER_WORDS


def _extract_keywords(text: str) -> list[str]:
    """
    テキストから「画面に映すべき具体物・行動」を抽出する。

    優先順位:
      1. _KEYWORD_MAP に登録済みの既知キーワード（健康ワード→いらすとや検索語）
      2. _VISUAL_NOUNS に登録済みの具体物・行動（食品・体の部位・生活行動等）
      3. カタカナ3文字以上（栄養素名・外来語）※キャラ名は除外
      4. 漢字2文字以上（臓器・症状等）※抽象語・キャラ名は除外
    """
    found: list[str] = []

    # 1. 既知の重要キーワードを最優先で検出
    for kw in _KEYWORD_MAP:
        if kw in text and kw not in found:
            found.append(kw)

    # 2. 具体物・行動ワード
    for w in _VISUAL_NOUNS:
        if w in text and w not in found:
            found.append(w)

    if found:
        return found[:3]

    # 3. カタカナ3文字以上（栄養素名・食品名）※ノイズ除外
    for w in re.findall(r"[\u30a0-\u30ff]{3,8}", text):
        if w not in found and w not in _IGNORE_WORDS:
            found.append(w)
        if len(found) >= 3:
            return found

    # 4. 漢字2文字以上（臓器・症状等）※抽象語・キャラ名除外
    for w in re.findall(r"[\u4e00-\u9fff]{2,6}", text):
        if w not in found and w not in _IGNORE_WORDS:
            found.append(w)
        if len(found) >= 3:
            return found

    return found


def fetch_for_line(text: str) -> "Path | None":
    """セリフ1行からキーワードを抽出し、最適ないらすとや画像1枚を返す。

    動詞的な内容（走る、食べる等）→ 人のいらすと
    名詞的な内容（コーヒー、脂肪等）→ 物体のいらすと
    見つからなければ None。
    """
    keywords = _extract_keywords(text)
    if not keywords:
        return None
    for kw in keywords[:2]:
        imgs = fetch(kw, max_count=1)
        if imgs:
            return imgs[0]
    return None


def prefetch_for_lines(lines: list[dict],
                       section_breaks: "list[int] | None" = None) -> dict[int, "Path | None"]:
    """台本の全セリフに対していらすとや画像を事前取得する。

    話題が変わったタイミングでのみ画像を切り替える。
    - 同じキーワードが続く間は同じ画像を維持
    - キーワードが変わっても、前回の切り替えから最低 _MIN_HOLD_LINES 行は維持
    - セクション境界では必ず切り替えを試みる
    - visual_hint があればそれを優先

    Args:
        lines: [{"text": "...", "visual_hint": "...", ...}, ...] のリスト
        section_breaks: セクション先頭行のインデックスリスト（必ず画像切り替え）

    Returns:
        index -> image_path のマッピング
    """
    _MIN_HOLD_LINES = 3  # 最低3行（約10秒）は同じ画像を維持
    _section_set = set(section_breaks or [])

    result: dict[int, "Path | None"] = {}
    cur_img: "Path | None" = None
    cur_kw = ""
    lines_since_change = 0
    used_imgs: set[str] = set()  # 同じ画像の過剰使い回し防止

    for i, line in enumerate(lines):
        # キーワード抽出
        hint = (line.get("visual_hint") or "").strip()
        if hint:
            kw = hint
        else:
            text = line.get("text", "")
            keywords = _extract_keywords(text)
            kw = keywords[0] if keywords else ""

        is_section_break = i in _section_set
        kw_changed = kw and kw != cur_kw
        held_enough = lines_since_change >= _MIN_HOLD_LINES

        # 画像切り替え判断
        should_change = False
        if is_section_break and kw:
            # セクション境界: 必ず切り替えを試みる
            should_change = True
        elif kw_changed and held_enough:
            # キーワード変化 + 最低表示行数を満たしている
            should_change = True

        if should_change:
            imgs = fetch(kw, max_count=2)
            if imgs:
                # 可能なら前回と違う画像を選ぶ
                new_img = None
                for img in imgs:
                    if str(img) not in used_imgs:
                        new_img = img
                        break
                if new_img is None:
                    new_img = imgs[0]
                cur_img = new_img
                cur_kw = kw
                used_imgs.add(str(cur_img))
                lines_since_change = 0

        result[i] = cur_img
        lines_since_change += 1

    return result


if __name__ == "__main__":
    import sys
    kw = sys.argv[1] if len(sys.argv) > 1 else "春バテ"
    print(f"検索: {kw}")
    paths = fetch(kw, max_count=3)
    for p in paths:
        print(f"  {p} ({p.stat().st_size} bytes)")
