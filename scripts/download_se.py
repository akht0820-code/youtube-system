"""効果音ラボからSE素材をダウンロードして assets/se/ に配置する"""

import json
import subprocess
import sys
import urllib.request
from pathlib import Path

ASSETS_SE = Path(__file__).resolve().parent.parent / "assets" / "se"

# カテゴリ別にダウンロードするSE一覧
# (ファイル名, URL, カテゴリページ(Referer用), 日本語説明)
SE_LIST = [
    # ── surprised: 驚き・衝撃 (15個) ──
    ("surprised/don1.mp3",       "https://soundeffect-lab.info/sound/anime/mp3/don-1.mp3",       "anime", "ドーン"),
    ("surprised/don2.mp3",       "https://soundeffect-lab.info/sound/anime/mp3/doon1.mp3",       "anime", "和太鼓とビブラスラップ"),
    ("surprised/shock1.mp3",     "https://soundeffect-lab.info/sound/anime/mp3/shock1.mp3",      "anime", "ショック1"),
    ("surprised/shock3.mp3",     "https://soundeffect-lab.info/sound/anime/mp3/shock3.mp3",      "anime", "ショック3"),
    ("surprised/surprise1.mp3",  "https://soundeffect-lab.info/sound/anime/mp3/surprise1.mp3",   "anime", "驚く"),
    ("surprised/jean1.mp3",      "https://soundeffect-lab.info/sound/anime/mp3/jean1.mp3",       "anime", "ジャン！"),
    ("surprised/jajean1.mp3",    "https://soundeffect-lab.info/sound/anime/mp3/jajean1.mp3",     "anime", "ジャジャーン！"),
    ("surprised/stunned1.mp3",   "https://soundeffect-lab.info/sound/anime/mp3/stunned1.mp3",    "anime", "目が点になる"),
    ("surprised/despair1.mp3",   "https://soundeffect-lab.info/sound/anime/mp3/despair1.mp3",    "anime", "絶望"),
    ("surprised/shock4.mp3",     "https://soundeffect-lab.info/sound/anime/mp3/shock4.mp3",      "anime", "ハッとするショック"),
    ("surprised/shock5.mp3",     "https://soundeffect-lab.info/sound/anime/mp3/shock5.mp3",      "anime", "深いショック"),
    ("surprised/shock6.mp3",     "https://soundeffect-lab.info/sound/anime/mp3/shock6.mp3",      "anime", "暗い絶望"),
    ("surprised/ban1.mp3",       "https://soundeffect-lab.info/sound/anime/mp3/ban1.mp3",        "anime", "太鼓バンッ"),
    ("surprised/shock2.mp3",     "https://soundeffect-lab.info/sound/anime/mp3/shock2.mp3",      "anime", "ショック2"),
    ("surprised/heart2.mp3",     "https://soundeffect-lab.info/sound/anime/mp3/heart2.mp3",      "anime", "心臓ドキッ"),

    # ── funny: コメディ・ボケ (14個) ──
    ("funny/stupid1.mp3",        "https://soundeffect-lab.info/sound/anime/mp3/stupid1.mp3",     "anime", "間抜け1"),
    ("funny/stupid3.mp3",        "https://soundeffect-lab.info/sound/anime/mp3/stupid3.mp3",     "anime", "間抜け3"),
    ("funny/puyon1.mp3",         "https://soundeffect-lab.info/sound/anime/mp3/puyon1.mp3",      "anime", "ぷよん"),
    ("funny/tsukkomi1.mp3",      "https://soundeffect-lab.info/sound/anime/mp3/tsukkomi-1.mp3",  "anime", "ビシッとツッコミ"),
    ("funny/chan-chan1.mp3",      "https://soundeffect-lab.info/sound/anime/mp3/chan-chan1.mp3",   "anime", "ちゃんちゃん"),
    ("funny/drop1.mp3",          "https://soundeffect-lab.info/sound/anime/mp3/drop1.mp3",       "anime", "落ち込む"),
    ("funny/trumpet-dub1.mp3",   "https://soundeffect-lab.info/sound/anime/mp3/trumpet-dub1.mp3","anime", "へたくそトランペット"),
    ("funny/boyoyon1.mp3",       "https://soundeffect-lab.info/sound/anime/mp3/boyoyon1.mp3",    "anime", "びよよんバウンド"),
    ("funny/pa1.mp3",            "https://soundeffect-lab.info/sound/anime/mp3/pa1.mp3",         "anime", "可愛い表示パッ"),
    ("funny/stupid2.mp3",        "https://soundeffect-lab.info/sound/anime/mp3/stupid2.mp3",     "anime", "間抜け2"),
    ("funny/dondonpafupafu1.mp3","https://soundeffect-lab.info/sound/anime/mp3/dondonpafupafu1.mp3","anime","パフパフ"),
    ("funny/boyon1.mp3",         "https://soundeffect-lab.info/sound/anime/mp3/boyon1.mp3",      "anime", "ボヨンと反発"),
    ("funny/stupid4.mp3",        "https://soundeffect-lab.info/sound/anime/mp3/stupid4.mp3",     "anime", "おどけの場面"),
    ("funny/stupid5.mp3",        "https://soundeffect-lab.info/sound/anime/mp3/stupid5.mp3",     "anime", "しぼむ間抜け"),

    # ── serious: シリアス・警告 (14個) ──
    ("serious/drum-japanese2.mp3","https://soundeffect-lab.info/sound/anime/mp3/drum-japanese2.mp3","anime","和太鼓でドドン"),
    ("serious/gogogogo1.mp3",    "https://soundeffect-lab.info/sound/anime/mp3/gogogogo1.mp3",   "anime", "ゴゴゴゴ"),
    ("serious/fear1.mp3",        "https://soundeffect-lab.info/sound/anime/mp3/fear1.mp3",       "anime", "恐怖"),
    ("serious/text-impact1.mp3", "https://soundeffect-lab.info/sound/anime/mp3/text-impact1.mp3","anime", "文字表示の衝撃音"),
    ("serious/warning1.mp3",     "https://soundeffect-lab.info/sound/button/mp3/warning1.mp3",   "button","警告音"),
    ("serious/fate1.mp3",        "https://soundeffect-lab.info/sound/anime/mp3/fate1.mp3",       "anime", "運命"),
    ("serious/heart1.mp3",       "https://soundeffect-lab.info/sound/anime/mp3/heart1.mp3",      "anime", "心臓の鼓動(4拍)"),
    ("serious/approaching-fear1.mp3","https://soundeffect-lab.info/sound/anime/mp3/approaching-fear1.mp3","anime","迫り来る恐怖"),
    ("serious/thunderstorm1.mp3","https://soundeffect-lab.info/sound/environment/mp3/thunderstorm1.mp3","environment","雷鳴"),
    ("serious/horror-title1.mp3","https://soundeffect-lab.info/sound/anime/mp3/horror-title1.mp3","anime","ホラータイトル"),
    ("serious/text-impact2.mp3", "https://soundeffect-lab.info/sound/anime/mp3/text-impact2.mp3","anime", "映画PV風文字表示"),
    ("serious/drum-japanese1.mp3","https://soundeffect-lab.info/sound/anime/mp3/drum-japanese1.mp3","anime","和太鼓ドン"),
    ("serious/anxiety-piano1.mp3","https://soundeffect-lab.info/sound/anime/mp3/anxiety-piano1.mp3","anime","不安なピアノ前奏"),
    ("serious/dissonance1.mp3",  "https://soundeffect-lab.info/sound/anime/mp3/dissonance1.mp3", "anime", "不協和音の恐怖"),

    # ── positive: ポジティブ・成功 (12個) ──
    ("positive/kira1.mp3",       "https://soundeffect-lab.info/sound/anime/mp3/kira1.mp3",       "anime", "キラッ1"),
    ("positive/kira2.mp3",       "https://soundeffect-lab.info/sound/anime/mp3/kira2.mp3",       "anime", "キラッ2"),
    ("positive/correct1.mp3",    "https://soundeffect-lab.info/sound/anime/mp3/correct1.mp3",    "anime", "クイズ正解"),
    ("positive/levelup1.mp3",    "https://soundeffect-lab.info/sound/anime/mp3/levelup1.mp3",    "anime", "レベルアップ"),
    ("positive/flash1.mp3",      "https://soundeffect-lab.info/sound/anime/mp3/flash1.mp3",      "anime", "ひらめく"),
    ("positive/trumpet1.mp3",    "https://soundeffect-lab.info/sound/anime/mp3/trumpet1.mp3",    "anime", "ファンファーレ"),
    ("positive/shine1.mp3",      "https://soundeffect-lab.info/sound/anime/mp3/shine1.mp3",      "anime", "キラキラ美しい"),
    ("positive/people-performance-cheer1.mp3","https://soundeffect-lab.info/sound/voice/mp3/people/people-performance-cheer1.mp3","voice","歓声と拍手"),
    ("positive/hero1.mp3",       "https://soundeffect-lab.info/sound/anime/mp3/hero1.mp3",       "anime", "ヒーローポーズ"),
    ("positive/gauge-recovery1.mp3","https://soundeffect-lab.info/sound/button/mp3/gauge-recovery1.mp3","button","体力回復"),
    ("positive/decision1.mp3",   "https://soundeffect-lab.info/sound/button/mp3/decision1.mp3",  "button","決定音"),
    ("positive/shine5.mp3",      "https://soundeffect-lab.info/sound/anime/mp3/shine5.mp3",      "anime", "透明感キラキラ"),

    # ── thinking: 考え中・クイズ (6個) ──
    ("thinking/question1.mp3",   "https://soundeffect-lab.info/sound/anime/mp3/question1.mp3",   "anime", "クイズ出題"),
    ("thinking/incorrect1.mp3",  "https://soundeffect-lab.info/sound/anime/mp3/incorrect1.mp3",  "anime", "クイズ不正解"),
    ("thinking/quiz-timer1.mp3", "https://soundeffect-lab.info/sound/anime/mp3/quiz-timer1.mp3", "anime", "制限時間タイマー"),
    ("thinking/quiz-timer-x2-1.mp3","https://soundeffect-lab.info/sound/anime/mp3/quiz-timer-x2-1.mp3","anime","タイムリミット迫る"),
    ("thinking/correct2.mp3",    "https://soundeffect-lab.info/sound/anime/mp3/correct2.mp3",    "anime", "鉄琴ピンポン"),
    ("thinking/question2.mp3",   "https://soundeffect-lab.info/sound/anime/mp3/question2.mp3",   "anime", "はてな？"),

    # ── transition: 場面転換 (8個) ──
    ("transition/shakin1.mp3",   "https://soundeffect-lab.info/sound/anime/mp3/shakin1.mp3",     "anime", "シャキーン1"),
    ("transition/shakin2.mp3",   "https://soundeffect-lab.info/sound/anime/mp3/shakin2.mp3",     "anime", "シャキーン2"),
    ("transition/sceneswitch1.mp3","https://soundeffect-lab.info/sound/anime/mp3/sceneswitch1.mp3","anime","シーン切り替え"),
    ("transition/title1.mp3",    "https://soundeffect-lab.info/sound/anime/mp3/title1.mp3",      "anime", "タイトル表示"),
    ("transition/flee1.mp3",     "https://soundeffect-lab.info/sound/anime/mp3/flee1.mp3",       "anime", "シュッと素早い"),
    ("transition/sceneswitch2.mp3","https://soundeffect-lab.info/sound/anime/mp3/sceneswitch2.mp3","anime","シーン転換ヒュウ"),
    ("transition/drum-roll1.mp3","https://soundeffect-lab.info/sound/anime/mp3/drum-roll1.mp3",  "anime", "ドラムロール生演奏"),
    ("transition/roll-finish1.mp3","https://soundeffect-lab.info/sound/anime/mp3/roll-finish1.mp3","anime","シンバルロール仕上げ"),

    # ── emotional: 感情表現 (8個) ──
    ("emotional/teardrop1.mp3",  "https://soundeffect-lab.info/sound/anime/mp3/teardrop1.mp3",   "anime", "涙がこぼれる"),
    ("emotional/cute-sad1.mp3",  "https://soundeffect-lab.info/sound/anime/mp3/cute-sad1.mp3",   "anime", "しょんぼり"),
    ("emotional/madness1.mp3",   "https://soundeffect-lab.info/sound/anime/mp3/madness1.mp3",    "anime", "狂気"),
    ("emotional/shine6.mp3",     "https://soundeffect-lab.info/sound/anime/mp3/shine6.mp3",      "anime", "ハープのキラキラ"),
    ("emotional/gust1.mp3",      "https://soundeffect-lab.info/sound/anime/mp3/gust1.mp3",       "anime", "冷たい風(ため息)"),
    ("emotional/recollection1.mp3","https://soundeffect-lab.info/sound/anime/mp3/recollection1.mp3","anime","回想シャボン玉"),
    ("emotional/machdash1.mp3",  "https://soundeffect-lab.info/sound/anime/mp3/machdash1.mp3",   "anime", "超高速ダッシュ"),
    ("emotional/heart1.mp3",     "https://soundeffect-lab.info/sound/anime/mp3/heart1.mp3",      "anime", "心臓の鼓動"),
]

REFERER_MAP = {
    "anime":  "https://soundeffect-lab.info/sound/anime/",
    "button": "https://soundeffect-lab.info/sound/button/",
    "environment": "https://soundeffect-lab.info/sound/environment/",
    "voice": "https://soundeffect-lab.info/sound/voice/",
}


def download_se():
    """効果音ラボからSE素材をダウンロードする"""
    ASSETS_SE.mkdir(parents=True, exist_ok=True)

    catalog = {}
    success = 0
    skipped = 0
    failed = 0

    for rel_path, url, category, description in SE_LIST:
        dest = ASSETS_SE / rel_path
        dest.parent.mkdir(parents=True, exist_ok=True)

        # 既にダウンロード済みならスキップ
        if dest.exists() and dest.stat().st_size > 100:
            skipped += 1
            se_cat = rel_path.split("/")[0]
            se_id = dest.stem
            catalog[f"{se_cat}/{se_id}"] = {
                "file": rel_path,
                "category": se_cat,
                "description": description,
            }
            continue

        referer = REFERER_MAP.get(category, REFERER_MAP["anime"])
        req = urllib.request.Request(url, headers={
            "Referer": referer,
            "User-Agent": "Mozilla/5.0",
        })

        try:
            data = urllib.request.urlopen(req, timeout=15).read()
            dest.write_bytes(data)
            se_cat = rel_path.split("/")[0]
            se_id = dest.stem
            catalog[f"{se_cat}/{se_id}"] = {
                "file": rel_path,
                "category": se_cat,
                "description": description,
            }
            print(f"  [OK] {rel_path} ({len(data)//1024}KB) - {description}")
            success += 1
        except Exception as e:
            print(f"  [NG] {rel_path} - {e}")
            failed += 1

    # カタログJSON保存
    catalog_path = ASSETS_SE / "se_catalog.json"
    catalog_path.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"\n完了: {success}件ダウンロード / {skipped}件スキップ / {failed}件失敗")
    print(f"カタログ: {catalog_path} ({len(catalog)}件)")
    return catalog


if __name__ == "__main__":
    download_se()
