# tts_aquestalk.py — AquesTalk1/2 TTS via 32-bit PowerShell + pykakasi 漢字変換
# TTS_PROVIDER=aquestalk の場合に tts.py から呼び出される
# 霊夢=AquesTalk1 女性1(f1)、魔理沙=AquesTalk1 女性2(f2) — お手本準拠の正式設定

from __future__ import annotations
import subprocess
import tempfile
import os
import re
from pathlib import Path

# 32-bit PowerShell パス（候補順に検索）
_PS32_CANDIDATES = [
    r"C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe",
    r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe",
]
_PS32: str | None = next((p for p in _PS32_CANDIDATES if Path(p).exists()), None)
_PS_SCRIPT = Path(__file__).parent / "aquestalk_synth.ps1"

# キャラクター → AquesTalk1/2 voice 名マッピング
_CHAR_MAP: dict[str, str] = {
    "reimu":  "reimu",
    "霊夢":   "reimu",
    "marisa": "marisa",
    "魔理沙": "marisa",
}

_SPEED_MAP: dict[str, int] = {
    "reimu":  118,   # ボケ役: やや遅め
    "marisa": 138,   # 解説役: やや速め
}

# fugashi (MeCab) — pykakasi より正確なかな変換
_tagger = None

def _get_tagger():
    global _tagger
    if _tagger is None:
        import fugashi
        _tagger = fugashi.Tagger()
    return _tagger

# カタカナ→ひらがな変換テーブル
_KATA2HIRA = str.maketrans(
    "アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン"
    "ァィゥェォッャュョーヴガギグゲゴザジズゼゾダヂヅデドバビブベボパピプペポ",
    "あいうえおかきくけこさしすせそたちつてとなにぬねのはひふへほまみむめもやゆよらりるれろわをん"
    "ぁぃぅぇぉっゃゅょーゔがぎぐげござじずぜぞだぢづでどばびぶべぼぱぴぷぺぽ"
)


# ── 数字→日本語変換 ──────────────────────────────────────────────────

# 1〜99の数字読み
_ONES = ["", "いち", "に", "さん", "よん", "ご", "ろく", "なな", "はち", "きゅう"]
_TENS = ["", "じゅう", "にじゅう", "さんじゅう", "よんじゅう",
         "ごじゅう", "ろくじゅう", "ななじゅう", "はちじゅう", "きゅうじゅう"]

# 百の位: 連濁・促音便ルール
# 300=さんびゃく、600=ろっぴゃく、800=はっぴゃく
_HYAKU = {
    1: "ひゃく",   2: "にひゃく",  3: "さんびゃく",
    4: "よんひゃく", 5: "ごひゃく",  6: "ろっぴゃく",
    7: "ななひゃく", 8: "はっぴゃく", 9: "きゅうひゃく",
}

# 千の位: 連濁・促音便ルール
# 3000=さんぜん、8000=はっせん
_SEN = {
    1: "せん",    2: "にせん",   3: "さんぜん",
    4: "よんせん",  5: "ごせん",   6: "ろくせん",
    7: "ななせん",  8: "はっせん",  9: "きゅうせん",
}


def _int_to_jp(n: int) -> str:
    """整数（0〜9999）を日本語読みに変換（連濁・促音便対応）"""
    if n == 0:
        return "ぜろ"
    parts = []
    if n >= 1000:
        k = n // 1000
        parts.append(_SEN[k])
        n %= 1000
    if n >= 100:
        h = n // 100
        parts.append(_HYAKU[h])
        n %= 100
    if n >= 10:
        t = n // 10
        o = n % 10
        parts.append(("" if t == 1 else _ONES[t]) + "じゅう")
        if o:
            parts.append(_ONES[o])
    elif n > 0:
        parts.append(_ONES[n])
    return "".join(parts)

# 助数詞ごとの読み方（数字との連濁・促音便を考慮）
# key: 助数詞文字列, value: {数字: 読み} または None（汎用変換を使う）
_COUNTER_READS: dict[str, dict[int, str]] = {
    "割": {1: "いちわり", 2: "にわり", 3: "さんわり", 4: "よんわり",
           5: "ごわり", 6: "ろくわり", 7: "ななわり", 8: "はちわり",
           9: "きゅうわり", 10: "じゅうわり"},
    "倍": {1: "いちばい", 2: "にばい", 3: "さんばい", 4: "よんばい",
           5: "ごばい", 6: "ろくばい", 7: "ななばい", 8: "はちばい",
           9: "きゅうばい", 10: "じゅうばい"},
    "番": {1: "いちばん", 2: "にばん", 3: "さんばん", 4: "よんばん",
           5: "ごばん", 6: "ろくばん", 7: "ななばん", 8: "はちばん",
           9: "きゅうばん", 10: "じゅうばん"},
    "種類": {1: "いっしゅるい", 2: "にしゅるい", 3: "さんしゅるい",
             4: "よんしゅるい", 5: "ごしゅるい"},
    "種": {1: "いっしゅ", 2: "にしゅ", 3: "さんしゅ",
           4: "よんしゅ", 5: "ごしゅ", 6: "ろくしゅ"},
    "つ": {1: "ひとつ", 2: "ふたつ", 3: "みっつ", 4: "よっつ",
           5: "いつつ", 6: "むっつ", 7: "ななつ", 8: "やっつ",
           9: "ここのつ", 10: "とお"},
    "人": {1: "ひとり", 2: "ふたり", 3: "さんにん", 4: "よにん",
           5: "ごにん", 6: "ろくにん", 7: "ななにん", 8: "はちにん",
           9: "きゅうにん", 10: "じゅうにん"},
    "日": {},  # 汎用: Nにち（1日=いちにち、日付は文脈依存のため汎用変換に委ねる）
    "年": {},   # 汎用: Nねん
    "月": {1: "いちがつ", 2: "にがつ", 3: "さんがつ", 4: "しがつ",
           5: "ごがつ", 6: "ろくがつ", 7: "しちがつ", 8: "はちがつ",
           9: "くがつ", 10: "じゅうがつ", 11: "じゅういちがつ", 12: "じゅうにがつ"},
    "個": {1: "いっこ", 2: "にこ", 3: "さんこ", 4: "よんこ",
           5: "ごこ", 6: "ろっこ", 7: "ななこ", 8: "はっこ",
           9: "きゅうこ", 10: "じゅっこ"},
    "回": {1: "いっかい", 2: "にかい", 3: "さんかい", 4: "よんかい",
           5: "ごかい", 6: "ろっかい", 7: "ななかい", 8: "はっかい",
           9: "きゅうかい", 10: "じゅっかい"},
    "杯": {1: "いっぱい", 2: "にはい", 3: "さんばい", 4: "よんはい",
           5: "ごはい", 6: "ろっぱい", 7: "ななはい", 8: "はっぱい",
           9: "きゅうはい", 10: "じゅっぱい"},
    "本": {1: "いっぽん", 2: "にほん", 3: "さんぼん", 4: "よんほん",
           5: "ごほん", 6: "ろっぽん", 7: "ななほん", 8: "はっぽん",
           9: "きゅうほん", 10: "じゅっぽん"},
    "枚": {},  # 汎用: Nまい
    "台": {},  # 汎用: Nだい
    "冊": {1: "いっさつ", 2: "にさつ", 3: "さんさつ"},
    "匹": {1: "いっぴき", 2: "にひき", 3: "さんびき", 4: "よんひき",
           5: "ごひき", 6: "ろっぴき"},
    "頭": {},  # 汎用: Nとう
    "羽": {1: "いちわ", 2: "にわ", 3: "さんわ"},
    "階": {1: "いっかい", 2: "にかい", 3: "さんがい", 4: "よんかい",
           5: "ごかい", 6: "ろっかい", 7: "ななかい", 8: "はっかい",
           9: "きゅうかい", 10: "じゅっかい"},
    "時": {1: "いちじ", 2: "にじ", 3: "さんじ", 4: "よじ",
           5: "ごじ", 6: "ろくじ", 7: "しちじ", 8: "はちじ",
           9: "くじ", 10: "じゅうじ", 11: "じゅういちじ", 12: "じゅうにじ"},
    "時間": {1: "いちじかん", 2: "にじかん", 3: "さんじかん", 4: "よじかん",
             5: "ごじかん", 6: "ろくじかん", 7: "しちじかん", 8: "はちじかん",
             9: "くじかん", 10: "じゅうじかん"},
    "分": {1: "いっぷん", 2: "にふん", 3: "さんぷん", 4: "よんぷん",
           5: "ごふん", 6: "ろっぷん", 7: "ななふん", 8: "はっぷん",
           9: "きゅうふん", 10: "じゅっぷん",
           20: "にじゅっぷん", 30: "さんじゅっぷん",
           40: "よんじゅっぷん", 50: "ごじゅっぷん", 60: "ろくじゅっぷん"},
    "秒": {},  # 汎用: Nびょう
    "番目": {},
    "位": {},
    # ── 記号・単位（数字正規化の前に _normalize_units で変換） ──
    "%": {},   # パーセント
    "kcal": {}, # キロカロリー
    "cal": {},  # カロリー
    "mg": {},   # ミリグラム
    "kg": {},   # キログラム
    "cm": {},   # センチメートル
    "mm": {},   # ミリメートル
    "km": {},   # キロメートル
    "ml": {},   # ミリリットル
    "dB": {},   # デシベル
    "g": {},    # グラム（mg/kgより後にマッチさせるため最後に配置）
    "m": {},    # メートル（mm/km/cmより後）
    "L": {},    # リットル（mlより後）
}

# 助数詞サフィックス（長い順にマッチさせるため長さ降順でソート済み）
_COUNTER_SUFFIXES = sorted(_COUNTER_READS.keys(), key=len, reverse=True)

# 助数詞マッチ用正規表現（小数点対応: 2.5倍→にてんごばい）
_COUNTER_RE = re.compile(
    r"(\d+(?:\.\d+)?)(" + "|".join(re.escape(s) for s in _COUNTER_SUFFIXES) + r")"
)

# 汎用助数詞読み（counterごとの表がない場合）
_COUNTER_GENERIC_READ: dict[str, str] = {
    "年": "ねん", "日": "にち", "人": "にん", "枚": "まい", "台": "だい",
    "頭": "とう", "番目": "ばんめ", "位": "い",
    "割": "わり", "倍": "ばい", "番": "ばん",
    "種類": "しゅるい", "種": "しゅ", "つ": "つ",
    "個": "こ", "回": "かい", "杯": "はい", "本": "ほん", "月": "がつ",
    "分": "ふん", "時": "じ", "時間": "じかん", "秒": "びょう",
    # 記号・単位
    "%": "ぱーせんと",
    "kcal": "きろかろりー", "cal": "かろりー",
    "mg": "みりぐらむ", "kg": "きろぐらむ", "g": "ぐらむ",
    "cm": "せんち", "mm": "みり", "km": "きろ", "m": "めーとる",
    "ml": "みりりっとる", "L": "りっとる",
    "dB": "でしべる",
}


def _apply_sokuon(num_read: str, counter_read: str) -> tuple[str, str]:
    """促音便を適用する。

    十(じゅう)/百(ひゃく等)で終わる数字読みの後に
    カ行(k)/パ行(p)で始まる助数詞が続く場合、促音便が発生する。
    例: さんじゅう+ぱーせんと → さんじゅっ+ぱーせんと
        ひゃく+かい → ひゃっ+かい
        にひゃく+こ → にひゃっ+こ

    また、ハ行(h)で始まる助数詞は促音便時にパ行(p)に変わる（連濁）。
    例: さんじゅう+ふん → さんじゅっ+ぷん
        ひゃく+はい → ひゃっ+ぱい
        ひゃく+ほん → ひゃっ+ぽん
    """
    if not num_read or not counter_read:
        return num_read, counter_read

    first = counter_read[0]
    _KA = set("かきくけこ")
    _PA = set("ぱぴぷぺぽ")
    _HA = set("はひふへほ")
    _HA_TO_PA = str.maketrans("はひふへほ", "ぱぴぷぺぽ")

    if not (first in _KA or first in _PA or first in _HA):
        return num_read, counter_read

    # 促音便が発生する条件を判定
    sokuon_juu = num_read.endswith("じゅう")    # 十: 3文字
    sokuon_hyaku = any(num_read.endswith(s) for s in ("ひゃく", "びゃく", "ぴゃく"))

    if not (sokuon_juu or sokuon_hyaku):
        return num_read, counter_read

    # ハ行 → パ行 連濁（促音便が発生する場合のみ）
    if first in _HA:
        counter_read = counter_read[0].translate(_HA_TO_PA) + counter_read[1:]

    # 十の促音便: じゅう(3文字) → じゅっ
    if sokuon_juu:
        return num_read[:-3] + "じゅっ", counter_read

    # 百の促音便: ひゃく/びゃく/ぴゃく → ひゃっ/びゃっ/ぴゃっ
    return num_read[:-1] + "っ", counter_read


def _naturalize_before_ten(int_read: str) -> str:
    """小数点「てん」の前の自然な読み変化を適用する。

    カウンター促音便とはルールが異なる:
    - いち/はち → いっ/はっ（ち→っ）
    - じゅう → じゅっ（十の促音便）
    - に → にい、ご → ごお（短い単音の長音挿入）
    - ろく、さん、よん等 → 変化なし
    例: 2.5→にいてん、8.5→はってん、11.5→じゅういってん
    """
    if not int_read:
        return int_read

    # 十の促音便: じゅう → じゅっ
    if int_read.endswith("じゅう"):
        return int_read[:-3] + "じゅっ"

    # ち → っ（いち、はち）
    if int_read.endswith("ち"):
        return int_read[:-1] + "っ"

    # 短い単音の長音挿入
    if int_read == "に":
        return "にい"
    if int_read == "ご":
        return "ごお"

    return int_read


def _read_number_counter(n_str: str, counter: str) -> str:
    """数字+助数詞 → 日本語読み（小数対応・促音便対応）

    n_str: "2" や "2.5" のような数値文字列
    """
    # 小数の場合: "2.5" → "にいてんごばい"
    if "." in n_str:
        int_part, dec_part = n_str.split(".", 1)
        int_read = _int_to_jp(int(int_part)) if int_part else ""
        dec_read = "".join(_ONES[int(d)] if int(d) < 10 else d for d in dec_part)
        generic = _COUNTER_GENERIC_READ.get(counter, counter)
        # 「てん」の前の自然な読み変化
        int_read = _naturalize_before_ten(int_read)
        return int_read + "てん" + dec_read + generic

    n = int(n_str)
    table = _COUNTER_READS.get(counter, {})
    if table and n in table:
        return table[n]
    # 汎用: 数字読み + 助数詞読み + 促音便
    generic = _COUNTER_GENERIC_READ.get(counter, counter)
    num_read = _int_to_jp(n)
    num_read, generic = _apply_sokuon(num_read, generic)
    return num_read + generic


# 単独数字パターン（小数対応）: 助数詞が付かない素の数字
_BARE_NUM_RE = re.compile(r"\d+(?:\.\d+)?")


# ── 読み辞書（aquestalk_dict.txt）の読み込み ────────────────────────────
# フォーマット: 表記<TAB>読み  （長い語を先に書くと優先マッチされる）
_DICT_PATH = Path(__file__).parent / "aquestalk_dict.txt"

def _load_dict() -> list[tuple[re.Pattern, str]]:
    """aquestalk_dict.txt を読み込み、(compiled_pattern, reading) のリストを返す"""
    entries: list[tuple[str, str]] = []
    if _DICT_PATH.exists():
        for line in _DICT_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                word, reading = parts[0].strip(), parts[1].strip()
                if word and reading:
                    entries.append((word, reading))
    # 長い語を先にマッチさせる（部分マッチ防止）
    entries.sort(key=lambda x: len(x[0]), reverse=True)
    return [(re.compile(re.escape(word)), reading) for word, reading in entries]

_DICT_PATTERNS: list[tuple[re.Pattern, str]] = _load_dict()


# ── 正規表現が必要な補正パターン（辞書化できないもの） ──────────────────
_REGEX_FIXES: list[tuple[re.Pattern, str]] = [
    # 助詞「は」: 文末・感嘆詞前の は+な/ね/よ → わ+な/ね/よ（pykakasi が花/跳ね等と誤解釈）
    (re.compile(r"は(な)(?=[。、！？\s]|$)"), r"わ\1"),
    (re.compile(r"は(ね)(?=[。、！？\s]|$)"), r"わ\1"),
    (re.compile(r"は(よ)(?=[。、！？\s]|$)"), r"わ\1"),
    # 「何と」= なんと（「何とも」「何となく」は除外）
    (re.compile(r"何と(?!も|なく)"), "なんと"),
    # 「食物」= しょくもつ（「食物連鎖」は除外）
    (re.compile(r"食物(?!連鎖)"), "しょくもつ"),
    # ── 「中」の読み分け ─────────────────────────────────────────────────
    # [名詞/カタカナ]中+助動詞/助詞 → ちゅう（「ダイエット中だし」「運動中に」等）
    # 「中に入る」「箱の中」等の"なか"と区別: 直前に活動名詞が続く場合のみ対象
    (re.compile(r"([ァ-ン一-龯ぁ-んっー]{1}[ァ-ン一-龯ぁ-んっー]*)中(だし|だから|だもの|だもん|なので|なんで)"), r"\1ちゅう\2"),
    (re.compile(r"([ァ-ン一-龯ぁ-んっー]{2,})中(だ|です|でした)(?=[。、！？\s]|$)"), r"\1ちゅう\2"),
    # ── 「日」の読み分け ─────────────────────────────────────────────────
    # 形容詞（〜い）・形容動詞（〜な）・連体修飾（〜の）+ 日 → ひ
    # 例: 「忙しい日」→ いそがしいひ、「特別な日」→ とくべつなひ
    # lookahead: 助詞(が/を/は/も/に/で/から/まで)・句読点・文末
    (re.compile(r"([いなの])日(?=[だがをはもにでからまで、。！？\s]|$)"), r"\1ひ"),
    # 動詞連体形（〜る）+ 日 → ひ（「頑張る日」「疲れる日」等）
    (re.compile(r"(る)日(?=[だがをはもにでからまで、。！？\s]|$)"), r"\1ひ"),
    # ── 「人」の読み分け ─────────────────────────────────────────────────
    # 形容詞（〜い）・形容動詞（〜な）・連体修飾（〜の）+ 人 → ひと
    (re.compile(r"([いなの])人(?=[だがをはもにでからまで、。！？\s]|$)"), r"\1ひと"),
]


def _apply_reading_fixes(text: str) -> str:
    """辞書＋正規表現パターンで読み誤りを事前補正する"""
    # 辞書エントリ（長い語優先の単純置換）
    for pattern, reading in _DICT_PATTERNS:
        text = pattern.sub(reading, text)
    # 正規表現が必要なパターン
    for pattern, repl in _REGEX_FIXES:
        text = pattern.sub(repl, text)
    return text


# ── 記号・全角文字の正規化（数字正規化の前に実行）──────────────────

# 全角→半角 数字・英字・記号
_FULLWIDTH_TABLE = str.maketrans(
    "０１２３４５６７８９"
    "ＡＢＣＤＥＦＧＨＩＪＫＬＭＮＯＰＱＲＳＴＵＶＷＸＹＺ"
    "ａｂｃｄｅｆｇｈｉｊｋｌｍｎｏｐｑｒｓｔｕｖｗｘｙｚ"
    "％＋＝＆",
    "0123456789"
    "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    "abcdefghijklmnopqrstuvwxyz"
    "%+=&"
)

# 丸数字 → 「だいN」
_CIRCLED_NUMBERS = {
    "①": "だいいち、", "②": "だいに、", "③": "だいさん、",
    "④": "だいよん、", "⑤": "だいご、", "⑥": "だいろく、",
    "⑦": "だいなな、", "⑧": "だいはち、", "⑨": "だいきゅう、",
    "⑩": "だいじゅう、",
}


def _normalize_symbols(text: str) -> str:
    """記号・全角文字を正規化する（数字正規化の前に実行）"""
    # 全角→半角
    text = text.translate(_FULLWIDTH_TABLE)

    # 全角コロン → 読点
    text = text.replace("：", "、")

    # 温度記号
    text = re.sub(r"(\d)℃", r"\1ど", text)
    text = re.sub(r"(\d)°C", r"\1ど", text)

    # 矢印 → 「から」
    text = text.replace("→", "から")
    text = text.replace("←", "から")

    # 丸数字
    for circle, reading in _CIRCLED_NUMBERS.items():
        text = text.replace(circle, reading)

    # スラッシュ（英字間: DHA/EPA → DHAとEPA）
    text = re.sub(r"([A-Za-z]+)/([A-Za-z]+)", r"\1と\2", text)

    return text


def _normalize_numbers(text: str) -> str:
    """数字を含む表現をひらがな読みに変換する（AquesTalk1用前処理）"""
    # Step1: 数字+助数詞を変換（小数対応、長い助数詞優先でマッチ）
    def _replace_counter(m: re.Match) -> str:
        n_str = m.group(1)  # "2" or "2.5"
        counter = m.group(2)
        return _read_number_counter(n_str, counter)

    text = _COUNTER_RE.sub(_replace_counter, text)

    # Step2: 残った素の数字を汎用変換（小数対応、最大4桁）
    def _replace_bare(m: re.Match) -> str:
        raw = m.group(0)
        if "." in raw:
            int_part, dec_part = raw.split(".", 1)
            int_n = int(int_part) if int_part else 0
            if int_n > 9999:
                return raw
            int_read = _int_to_jp(int_n) if int_part else ""
            dec_read = "".join(_ONES[int(d)] if int(d) < 10 else d for d in dec_part)
            return int_read + "てん" + dec_read
        n = int(raw)
        if n > 9999:
            return raw
        return _int_to_jp(n)

    text = _BARE_NUM_RE.sub(_replace_bare, text)

    # Step3: 「人」の読み補正
    #   数字+人 は Step1 で処理済み（ひとり/ふたり/さんにん/823→はちひゃく...にん等）
    #   残った「〜る人」「〜の人」「〜い人」等ひらがなに続く人は「ひと」と読む
    #   除外: 人数/人口/人工/人材/人事/日本人 等（漢字が後に続く場合はそのまま）
    text = re.sub(
        r"([あ-ん])(人)(?![\u4e00-\u9fff数口材事工])",
        lambda m: m.group(1) + "ひと",
        text,
    )

    return text


# 公開API: pronunciation.py から数字正規化を呼べるようにする
normalize_numbers = _normalize_numbers


# ── 助詞補正 ─────────────────────────────────────────────────────────

# AquesTalk1 は「は」を常に「HA」と読む。
# 助詞として使われる「は」（topic marker）→「わ」に変換する。
# 助詞として使われる「へ」（direction marker）→「え」に変換する。
#
# 方針: 数字正規化（_normalize_numbers）の前に fugashi でテキストを解析し、
#       助詞の「は」「へ」を先に変換してから数字正規化を行う。
#       こうすることで、数字正規化後の「はっぱい」等の「は」を誤変換しない。


def _particle_fix(text: str) -> str:
    """助詞「は」→「わ」、「へ」→「え」に変換する（数字正規化の前に実行）

    fugashi の POSタグで正確に助詞を検出するため誤変換が起きない。
    数字・漢字・英字は surface のまま保持する（変換しない）。
    """
    tagger = _get_tagger()
    parts = []
    for word in tagger(text):
        surface = word.surface
        if word.feature.pos1 == "助詞":
            if surface == "は":
                parts.append("わ")
                continue
            elif surface == "へ":
                parts.append("え")
                continue
        parts.append(surface)
    return "".join(parts)


def _kanji_to_hira(text: str) -> str:
    """漢字混じりのテキストをひらがな主体に変換する（fugashi / MeCab 版）

    数字正規化後に呼ぶ。助詞の変換は _particle_fix で先に実施済みなので
    ここでは kanji/katakana → hiragana 変換のみ行う。
    """
    tagger = _get_tagger()
    parts = []
    for word in tagger(text):
        kana = word.feature.kana
        if kana and kana != "*" and kana != "":
            parts.append(kana.translate(_KATA2HIRA))
        else:
            parts.append(word.surface)
    return "".join(parts)


# ── 拗音近似マップ（AquesTalk1非対応の外来音を近似音に変換）──────
# 小書き仮名(ぁぃぅぇぉ)の一律変換より先に適用する
_YOUON_MAP = {
    "じぇ": "ぜ",   # ジェ≒ゼ（ジェットコースター→ゼットコースター等）
    "しぇ": "せ",   # シェ≒セ
    "てぃ": "ち",   # ティ≒チ
    "でぃ": "じ",   # ディ≒ジ
    "ふぁ": "は",   # ファ≒ハ
    "ふぃ": "ひ",   # フィ≒ヒ
    "ふぇ": "へ",   # フェ≒ヘ
    "ふぉ": "ほ",   # フォ≒ホ
    "とぅ": "つ",   # トゥ≒ツ
    "どぅ": "ず",   # ドゥ≒ズ
}

# ── バリデーション（Rule 5: 未変換記号の自動検出）──────────────────

# AquesTalkで消える文字（ひらがな・カタカナ・句読点以外）を事前検出
_UNCONVERTED_RE = re.compile(r"[A-Za-z0-9%℃°&=+/①-⑩]")
# 警告済みパターンをキャッシュ（同一セッションで重複警告を抑制）
_warned_patterns: set[str] = set()


def _warn_unconverted(hira_text: str, original: str) -> None:
    """かな変換後のテキストに未変換の記号・英字が残っていたら警告する"""
    found = _UNCONVERTED_RE.findall(hira_text)
    if not found:
        return
    unique = set(found)
    new_warns = unique - _warned_patterns
    if new_warns:
        _warned_patterns.update(new_warns)
        chars = ", ".join(sorted(new_warns))
        preview = original[:40]
        print(f"  [!] 未変換文字検出: [{chars}] in \"{preview}\"")
        print(f"      → _normalize_symbols または aquestalk_dict.txt への追加を検討してください")


def _clean_for_aquestalk(text: str) -> str:
    """AquesTalk1 が受け付けない文字を除去・置換する"""
    # 記号を句読点に変換
    text = text.replace("…", "、")
    text = text.replace("・", "、")
    text = text.replace("〜", "ー")
    text = text.replace("～", "ー")
    text = text.replace("—", "、")
    text = text.replace("―", "、")
    text = text.replace("–", "、")
    # 感嘆符・疑問符 → 句点
    text = text.replace("！", "。")
    text = text.replace("!",  "。")
    text = text.replace("？", "。")
    text = text.replace("?",  "。")
    # 括弧類を除去
    text = re.sub(r"[「」【】『』〔〕〈〉（）()\[\]{}]", "", text)
    # AquesTalk1 非対応文字を置換
    text = text.replace("づ", "ず").replace("ぢ", "じ")
    # 拗音パターンを近似音に変換（小書き仮名の一律変換より先に処理）
    for src, dst in _YOUON_MAP.items():
        text = text.replace(src, dst)
    text = text.replace("ぁ", "あ").replace("ぃ", "い").replace("ぅ", "う")
    text = text.replace("ぇ", "え").replace("ぉ", "お")
    text = text.replace("ゔ", "ぶ").replace("ゕ", "か").replace("ゖ", "け")
    # ひらがな・カタカナ・句読点のみ残す（スペース類は除外: AT1-105 の原因になるため）
    text = re.sub(r"[^\u3041-\u3093\u309B\u309C\u30A0-\u30FA\u30FC\u30FBー、。]", "", text)
    # 連続する句読点を圧縮
    text = re.sub(r"[、。]{2,}", "、", text)
    text = text.strip()

    # AquesTalk1 は「ん」を文頭に置けない（鼻音は母音の後にのみ現れる）
    # 1) テキスト全体が「ん」系のみ → 「うん。」
    # 2) 「ん」で始まる長いテキスト → 先頭の「ん+句読点」を「うん+句読点」に置換
    if re.fullmatch(r"ん+[ー、。]*", text):
        text = "うん。"
    elif text.startswith("ん"):
        text = re.sub(r"^ん+([。、]?)", r"うん\1", text)

    # 末尾が「、」なら「。」に置き換え（「、。」の二重句読点を防ぐ）
    if text and text[-1] == "、":
        text = text[:-1] + "。"
    elif text and text[-1] != "。":
        text += "。"
    return text


def synthesize(text: str, character: str, output_path: Path, speed: int | None = None) -> Path:
    """
    テキストを AquesTalk1 で音声合成し WAV ファイルに保存する。

    Args:
        text: 合成するテキスト（漢字可）
        character: キャラクター名（"reimu" / "marisa" / "霊夢" / "魔理沙"）
        output_path: 出力 WAV ファイルパス
        speed: 話速（None = キャラクターデフォルト）

    Returns:
        output_path
    """
    if _PS32 is None:
        raise RuntimeError(
            "32-bit PowerShell が見つかりません。AquesTalk は実行できません。\n"
            "確認パス: " + ", ".join(_PS32_CANDIDATES)
        )

    voice = _CHAR_MAP.get(character, "reimu")
    spd   = speed if speed is not None else _SPEED_MAP.get(voice, 100)

    # Step0: 助詞「は」→「わ」「へ」→「え」を最初に変換（漢字テキストで実行）
    #        fugashi は漢字混じりテキストで最も正確に助詞を検出できる。
    #        辞書補正後のひらがなテキストでは誤解析が起きる
    #        （例: 「人は白髪」→「ひとはしらが」→ fugashi が「はしら(柱)」と誤解析）
    text = _particle_fix(text)

    # Step1: 事前読み補正（辞書置換）
    text = _apply_reading_fixes(text)

    # Step2: 記号・全角文字の正規化（℃→ど、→→から、①→だいいち 等）
    text = _normalize_symbols(text)

    # Step3: 数字を日本語読みに変換（7割→ななわり、3回→さんかい 等）
    text_normalized = _normalize_numbers(text)

    # Step4: 漢字→ひらがな変換（助詞変換は Step0 で完了済み）
    hira_text = _kanji_to_hira(text_normalized)

    # Step4.5: バリデーション — 未変換の記号・単位・英字を検出して警告
    _warn_unconverted(hira_text, text)

    # Step5: AquesTalk1 用クリーニング
    clean_text = _clean_for_aquestalk(hira_text)
    if not clean_text:
        raise ValueError(f"テキストが空になりました: {text!r}")

    # テキストを UTF-8 一時ファイルに書き出す
    tmp_fd, tmp_txt = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(clean_text)
    except Exception:
        os.close(tmp_fd)
        raise

    win_txt = tmp_txt
    win_out = str(output_path)
    win_ps  = str(_PS_SCRIPT)

    output_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        result = subprocess.run(
            [
                _PS32,
                "-ExecutionPolicy", "Bypass",
                "-File", win_ps,
                "-Character", voice,
                "-TextFile", win_txt,
                "-Output", win_out,
                "-Speed", str(spd),
            ],
            capture_output=True,
            text=False,
            timeout=60,
        )

        stdout = (result.stdout or b"").decode("cp932", errors="replace").strip()
        stderr = (result.stderr or b"").decode("cp932", errors="replace").strip()
        if result.returncode != 0 or "ERROR" in stdout or "SYNTH_ERROR" in stdout:
            raise RuntimeError(
                f"AquesTalk1 失敗 (code={result.returncode}): {stdout} | {stderr}"
            )

        if not output_path.exists():
            raise RuntimeError(f"出力ファイルが生成されませんでした: {output_path}")

        return output_path
    finally:
        try:
            os.unlink(tmp_txt)
        except Exception:
            pass
