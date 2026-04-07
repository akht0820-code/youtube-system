# download_bgm.py — BGM追加ガイド（DOVA-SYNDROME 厳選リスト）
#
# 実行すると現在のBGM一覧と手順を表示します:
#   python scripts/download_bgm.py
#
# ── DOVA-SYNDROME ────────────────────────────────────────────────────────────
# YouTube収益化OK / 著作権フリー / クレジット不要
# ダウンロード方法: 各URLにブラウザでアクセス → 「DOWNLOAD FILE」クリック
# ダウンロード先: このスクリプトと同じ場所にある assets/bgm/ フォルダに置く
# ─────────────────────────────────────────────────────────────────────────────

from pathlib import Path

BGM_DIR = Path(__file__).resolve().parent.parent / "assets" / "bgm"

# ── 厳選BGMリスト ──────────────────────────────────────────────────────────
RECOMMENDED = [
    # ── 落ち着いた解説系（本編通常 / ピアノ・アコースティック）────────────
    {
        "title":    "昼下がり気分",
        "author":   "KK",
        "genre":    "ピアノ・穏やか・日常",
        "use":      "本編通常（最もおすすめ）",
        "dl_count": "約37万DL",
        "url":      "https://dova-s.jp/bgm/detail/4695/download",
        "filename": "bgm3_昼下がり気分.mp3",
    },
    {
        "title":    "日曜の午後",
        "author":   "KK",
        "genre":    "ピアノ・穏やか・コメディー",
        "use":      "本編通常（トーク動画向き）",
        "dl_count": "約19万DL",
        "url":      "https://dova-s.jp/bgm/detail/4658/download",
        "filename": "bgm4_日曜の午後.mp3",
    },
    {
        "title":    "自宅にて",
        "author":   "KK",
        "genre":    "ピアノ・日常・温かい",
        "use":      "本編通常（長め5:56 / ループ向き）",
        "dl_count": "約19万DL",
        "url":      "https://dova-s.jp/bgm/detail/4041/download",
        "filename": "bgm5_自宅にて.mp3",
    },
    {
        "title":    "神隠しの真相",
        "author":   "しゃろう",
        "genre":    "ピアノ・ヒーリング・和風",
        "use":      "本編通常（和風テーマ・自律神経向き）",
        "dl_count": "約20万DL",
        "url":      "https://dova-s.jp/bgm/detail/7674/download",
        "filename": "bgm6_神隠しの真相.mp3",
    },
    # ── 明るい・前向き（まとめ・エンドカード）───────────────────────────
    {
        "title":    "Morning",
        "author":   "しゃろう",
        "genre":    "アコースティック・カントリー・ポップ",
        "use":      "まとめ・エンドカード（サイト内最人気クラス）",
        "dl_count": "約62万DL",
        "url":      "https://dova-s.jp/bgm/detail/2445/download",
        "filename": "bgm7_Morning.mp3",
    },
    {
        "title":    "野良猫は宇宙を目指した",
        "author":   "しゃろう",
        "genre":    "ロック・ポップ・爽やか",
        "use":      "まとめ・エンディング",
        "dl_count": "約44万DL",
        "url":      "https://dova-s.jp/bgm/detail/2862/download",
        "filename": "bgm8_野良猫は宇宙を目指した.mp3",
    },
    {
        "title":    "ほんわかぷっぷー",
        "author":   "もっぴーさうんど",
        "genre":    "クラシック・木管・明るい",
        "use":      "エンドカード・軽快なまとめ",
        "dl_count": "約30万DL",
        "url":      "https://dova-s.jp/bgm/detail/1854/download",
        "filename": "bgm9_ほんわかぷっぷー.mp3",
    },
    # ── 茶番劇・コミカル系（メインBGM最優先 / 明るく・テンポよく・ゆっくり動画定番）──
    # ※ 未ダウンロード時はbgm7-9(明るい系)で代替。URLはブラウザで開いてDOWNLOAD FILEをクリック
    {
        "title":    "焼きそば行進曲",
        "author":   "もっぴーさうんど",
        "genre":    "マーチ・コミカル・ゆっくり茶番劇定番",
        "use":      "メインBGM（茶番劇・解説）",
        "dl_count": "約18万DL",
        "url":      "https://dova-s.jp/bgm/play1788.html",
        "filename": "bgm12_焼きそば行進曲.mp3",
    },
    {
        "title":    "楽しい帰り道",
        "author":   "DOVA-SYNDROME",
        "genre":    "ほのぼの・明るい・テンポよし",
        "use":      "メインBGM（ゆるめ茶番劇・日常解説）",
        "dl_count": "—",
        "url":      "https://dova-s.jp/bgm/play3438.html",
        "filename": "bgm13_楽しい帰り道.mp3",
    },
    {
        "title":    "Fancy Pop",
        "author":   "DOVA-SYNDROME",
        "genre":    "ポップ・明るい・テンポよし",
        "use":      "メインBGM（テンポよい解説）",
        "dl_count": "—",
        "url":      "https://dova-s.jp/bgm/play17411.html",
        "filename": "bgm14_Fancy_Pop.mp3",
    },
    {
        "title":    "ゆかいな仲間",
        "author":   "いまたく",
        "genre":    "アコースティック・コミカル・明るい",
        "use":      "メインBGM（霊夢・魔理沙のやり取りに合う）",
        "dl_count": "—",
        "url":      "https://dova-s.jp/bgm/play11074.html",
        "filename": "bgm15_ゆかいな仲間.mp3",
    },
    # ── 緊張感・シリアス（衝撃パート・冒頭フック）───────────────────────
    {
        "title":    "全てを創造する者「Dominus Deus」",
        "author":   "KK",
        "genre":    "オーケストラ・コーラス・エピック",
        "use":      "衝撃パート・冒頭フック",
        "dl_count": "約10万DL",
        "url":      "https://dova-s.jp/bgm/detail/5588/download",
        "filename": "bgm10_Dominus_Deus.mp3",
    },
    {
        "title":    "不穏",
        "author":   "こっけ（西本康佑）",
        "genre":    "ピアノ・弦楽・ホラー",
        "use":      "衝撃パート・不安感演出（作者が「不安・恐怖を煽る演出向き」と明言）",
        "dl_count": "約8万DL",
        "url":      "https://dova-s.jp/bgm/detail/8333/download",
        "filename": "bgm11_不穏.mp3",
    },
]

def main():
    BGM_DIR.mkdir(parents=True, exist_ok=True)
    existing = sorted(BGM_DIR.glob("*.mp3")) + sorted(BGM_DIR.glob("*.wav"))

    print("=" * 60)
    print("  BGM管理ガイド — ゆっくり健康ラボ")
    print("=" * 60)
    print(f"\n現在のBGM: {len(existing)}曲\n")
    for f in existing:
        print(f"  [OK] {f.name}")

    print(f"\n{'─' * 60}")
    print("  追加推奨BGM（DOVA-SYNDROME / YouTube収益化OK）")
    print("  各URLにブラウザでアクセス → 「DOWNLOAD FILE」クリック")
    print(f"  保存先: {BGM_DIR}")
    print(f"{'─' * 60}\n")

    for i, b in enumerate(RECOMMENDED, 1):
        already = any(f.stem.startswith(f"bgm{i+2}") or b["title"] in f.name
                      for f in existing)
        status = "[済] 取得済み" if already else "[--] 未取得"
        print(f"[{i:02d}] {status} {b['use']}")
        print(f"     曲名  : {b['title']} / {b['author']}")
        print(f"     ジャンル: {b['genre']} ({b['dl_count']})")
        print(f"     保存名 : {b['filename']}")
        print(f"     URL   : {b['url']}")
        print()

    missing = len([b for b in RECOMMENDED
                   if not any(b["title"] in f.name for f in existing)])
    print(f"{'─' * 60}")
    print(f"未取得: {missing}曲 / 合計: {len(RECOMMENDED)}曲")
    print(f"10曲以上揃うとvideo_builder.pyが毎回ランダム選択します。")
    print(f"{'─' * 60}\n")

if __name__ == "__main__":
    main()
