# 動画生成モジュール（16:9 / 1920×1080 / MP4）

import gc
import json
import math
import os
import random
import re
import shutil
import subprocess
import sys
import textwrap
import wave
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from font_utils import load_font

# moviepy不使用 — 音声処理は全てffmpegで実行（省メモリ）
from PIL import Image, ImageDraw

load_dotenv(Path(__file__).parent.parent / ".env")

# ── 定数 ────────────────────────────────────────────────
RESOLUTION = (1920, 1080)
FPS = 30
BGM_VOLUME = 0.12          # BGMの音量（音声に対する比率）
BGM_FADEIN  = 1.0          # BGMフェードイン秒数
BGM_FADEOUT = 3.0          # BGMフェードアウト秒数

ENCODE_PRESET  = os.getenv("ENCODE_PRESET",  "veryfast")
ENCODE_THREADS = int(os.getenv("ENCODE_THREADS", "0"))


ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CHAR_DIR   = ASSETS_DIR / "characters"
BG_DIR     = ASSETS_DIR / "backgrounds"
BGM_DIR    = ASSETS_DIR / "bgm"

# 字幕エリア
SUBTITLE_BAR_Y      = 860   # 字幕バーの上端Y座標
SUBTITLE_BAR_HEIGHT = 190   # 字幕バーの高さ
SUBTITLE_PADDING    = 24    # 字幕テキストの左右余白

# 口パクアニメーション（話し中の口形状サイクル）
MOUTH_ANIM_FPS = 8           # 秒間8フレームで口形状を切り替え

# 話者キャラのボブアニメーション（上下揺れ）
BOB_FREQ = 1.8               # 揺れ周波数（Hz）— 1秒に約2往復
BOB_AMP  = 7                 # 振幅（ピクセル）— わずかな揺れ

# キャラクター（饅頭）配置設定
# x_center: 饅頭中心X座標, bottom: 饅頭底辺Y座標, height: 饅頭の高さ(px)
# flip_h: True で水平反転して中央方向に向かせる
CHAR_CONFIG = {
    "魔理沙": {
        "x_center":      310,
        "bottom":        SUBTITLE_BAR_Y,        # 字幕バー上端にぴったり接する
        "height":        720,                   # 帽子込みを補正: 顔64.4%×720≈464px ≈ 霊夢顔77.4%×600≈464px
        "flip_h":        False,
        "mouth_cy_ratio": 0.55,                 # 帽子が大きく顔が下寄りなので低めに設定
    },
    "霊夢": {
        "x_center":      1610,
        "bottom":        SUBTITLE_BAR_Y + 10,   # 字幕バーに少し近い位置
        "height":        720,                   # 魔理沙と同サイズ
        "flip_h":        False,
        "mouth_cy_ratio": 0.73,                 # 顔がほぼ全体に広がるので高め
    },
}

# キャラクター名の表示色
NAME_COLORS = {
    "魔理沙": (255, 220, 80),   # 黄色
    "霊夢":   (255, 130, 180),  # ピンク
}

# ── nicotalk改 パーツ合成方式 ─────────────────────────────────
# 各感情タグ → (顔ベースID, 目ID, 口閉じID, 口開きID) のマッピング
# パーツ: 体(body) → 顔(face) → 目(eyes) → 口(mouth) の順で合成
#
# 霊夢改パーツ: 体1 / 顔9(00a-08b) / 目46(00-42+00a-c) / 口31(00-28+00a-b)
# 魔理沙改パーツ: 体1 / 顔6(01a-06a) / 目36(00-30+00a-e) / 口38(00-32+00a-e)
_KAI_EMOTION_PARTS: dict[str, dict[str, dict[str, str]]] = {
    # ── 霊夢（聞き手・リアクション担当） ──
    # 顔: 00a=通常, 01a=薄ピンク頬  ※02a以上の赤面・06b以上の青ざめは極端な場面のみ
    # 目: 00=通常正面, 03=丸大(驚), 04=細め(真剣), 05=半閉じ笑(嬉), 06=やや大(不安),
    #     07=見開き(興奮), 08=閉じ^_^(安堵), 09=大見開(衝撃), 10=半閉じ横(考え),
    #     18=すがめ(怒), 21=伏せ(悲), 22=大丸(好奇), 25=細(ニヤリ), 26=視線逸らし
    # 口: 00=閉, 01=あ(発話), 02=小四角(驚), 03=大開(衝撃), 04=小丸, 05=大開,
    #     06=丸開, 07=笑い開, 08=歯見せ, 11=平ら, 13=への字, 14=横口,
    #     18=一文字, 19=微笑, 20=驚き開, 21=歯見せ笑, 22=発話, 28=穏やか微笑, 00a=微開
    "霊夢": {
        #                  顔ベース   目       口閉じ   口開き
        "normal":      {"face": "00a", "eyes": "00",  "mc": "00",  "mo": "01"},
        "happy":       {"face": "00a", "eyes": "05",  "mc": "19",  "mo": "07"},
        "surprised":   {"face": "00a", "eyes": "03",  "mc": "00",  "mo": "02"},
        "serious":     {"face": "00a", "eyes": "04",  "mc": "18",  "mo": "06"},
        "worried":     {"face": "00a", "eyes": "06",  "mc": "11",  "mo": "20"},
        "excited":     {"face": "00a", "eyes": "07",  "mc": "19",  "mo": "08"},
        "shocked":     {"face": "00a", "eyes": "09",  "mc": "00",  "mo": "03"},
        "embarrassed": {"face": "01a", "eyes": "26",  "mc": "14",  "mo": "06"},
        "thinking":    {"face": "00a", "eyes": "10",  "mc": "00",  "mo": "00a"},
        "sad":         {"face": "00a", "eyes": "21",  "mc": "13",  "mo": "22"},
        "relieved":    {"face": "00a", "eyes": "08",  "mc": "28",  "mo": "06"},
        "angry":       {"face": "00a", "eyes": "18",  "mc": "18",  "mo": "06"},
        "curious":     {"face": "00a", "eyes": "22",  "mc": "00",  "mo": "03"},
        "awkward":     {"face": "01a", "eyes": "10",  "mc": "14",  "mo": "06"},
        "smug":        {"face": "00a", "eyes": "25",  "mc": "19",  "mo": "14"},
        "joyful":      {"face": "00a", "eyes": "07",  "mc": "21",  "mo": "08"},
    },
    # ── 魔理沙（解説役） ──
    # 顔: 01a=標準, 06a=バリエ  ※02a(照れ)は使わない、03b-05b(青ざめ)は極端な場面のみ
    # 目: 00=通常垂れ目, [01=白目風→削除済], 02=やや細(思考), 03=伏せ(悲), 04=横目,
    #     06=垂れ(困惑), 07=やや見開(驚き始め), 10=閉じ穏やか笑, 18=細め真剣,
    #     21=大見開(衝撃), 22=普通丸目, 24=細め(ニヤリ), 26=鋭い(決意), 28=半閉じ(呆れ)
    # 口: 00=閉, 00a=微開, 00b=中開(発話), 01=閉じ微笑, 02=大開笑い, 03=小丸,
    #     04=への字, 06=歯見せ, 07=驚き開, 11=大驚き, 12=叫び, 13=ニヤリ,
    #     15=穏やか微笑, 18=食いしばり, 20=大笑顔, 27=閉じ無表情, 30=小微笑
    "魔理沙": {
        "normal":      {"face": "01a", "eyes": "00",  "mc": "00",  "mo": "00b"},
        "happy":       {"face": "01a", "eyes": "11",  "mc": "01",  "mo": "02"},
        "surprised":   {"face": "01a", "eyes": "07",  "mc": "00",  "mo": "07"},
        "serious":     {"face": "01a", "eyes": "00b", "mc": "00",  "mo": "00b"},
        "worried":     {"face": "01a", "eyes": "06",  "mc": "15",  "mo": "00b"},
        "excited":     {"face": "01a", "eyes": "07",  "mc": "01",  "mo": "02"},
        "shocked":     {"face": "01a", "eyes": "21",  "mc": "00",  "mo": "11"},
        "embarrassed": {"face": "06a", "eyes": "04",  "mc": "15",  "mo": "03"},
        "thinking":    {"face": "01a", "eyes": "02",  "mc": "00",  "mo": "00a"},
        "sad":         {"face": "01a", "eyes": "03",  "mc": "15",  "mo": "03"},
        "relieved":    {"face": "01a", "eyes": "10",  "mc": "30",  "mo": "03"},
        "angry":       {"face": "01a", "eyes": "26",  "mc": "18",  "mo": "12"},
        "curious":     {"face": "01a", "eyes": "22",  "mc": "00",  "mo": "03"},
        "awkward":     {"face": "06a", "eyes": "28",  "mc": "15",  "mo": "00a"},
        "smug":        {"face": "01a", "eyes": "24",  "mc": "13",  "mo": "06"},
        "joyful":      {"face": "01a", "eyes": "11",  "mc": "20",  "mo": "02"},
    },
}

# 瞬きシーケンス（目IDの置き換え順序）
# 通常目 → 半閉じ → 閉じ → 半閉じ → 通常 の5フレーム（約167ms）
_BLINK_EYES: dict[str, list[str]] = {
    "霊夢":   ["00a", "00b", "00c", "00b", "00a"],
    "魔理沙": ["00a", "00b", "00c", "00d", "00e", "10", "00e", "00d", "00c", "00b", "00a"],
}
_BLINK_INTERVAL_MIN = 3.0   # 瞬き間隔の最小値（秒）
_BLINK_INTERVAL_MAX = 7.0   # 瞬き間隔の最大値（秒）

# ── リスナーリアクション（話者感情 → 聞き手感情タグ） ──────────────────
# 聞き手はデフォルト normal だが、強い感情には連動して反応する
_LISTENER_REACTION: dict[str, str] = {
    "shocked":   "surprised",
    # "surprised" は頻出すぎるため連動を抑制（リスナーはnormal維持）
    "excited":   "happy",
    "joyful":    "surprised",
    "angry":     "worried",
    "sad":       "worried",
}

# ── 口パク形状シーケンス（閉→微開→中開→大開→中開→微開のサイクル） ─────
# 各キャラ × 感情ごとに、発話時に循環する口パーツIDのリスト
# mc(閉じ口)で始まり、mo(大開き)をピークにするサイクルで喋っている感じを出す
_MOUTH_SEQUENCE: dict[str, dict[str, list[str]]] = {
    "霊夢": {
        # 感情ごとに自然な口形状シーケンス（閉→微開→開→大開→開→微開）
        "normal":      ["00",  "00a", "01",  "01",  "00a", "00"],
        "happy":       ["19",  "00a", "07",  "08",  "07",  "19"],
        "surprised":   ["00",  "02",  "20",  "02",  "20",  "00"],
        "serious":     ["18",  "00a", "06",  "06",  "00a", "18"],
        "worried":     ["11",  "00a", "20",  "20",  "00a", "11"],
        "excited":     ["19",  "00a", "08",  "07",  "08",  "19"],
        "shocked":     ["00",  "02",  "03",  "03",  "02",  "00"],
        "embarrassed": ["14",  "00a", "06",  "06",  "00a", "14"],
        "thinking":    ["00",  "00a", "00a", "03",  "00a", "00"],
        "sad":         ["13",  "00a", "22",  "22",  "00a", "13"],
        "relieved":    ["28",  "00a", "06",  "06",  "00a", "28"],
        "angry":       ["18",  "00a", "06",  "06",  "00a", "18"],
        "curious":     ["00",  "00a", "03",  "03",  "00a", "00"],
        "awkward":     ["14",  "00a", "06",  "06",  "00a", "14"],
        "smug":        ["19",  "14",  "14",  "07",  "14",  "19"],
        "joyful":      ["21",  "00a", "08",  "07",  "08",  "21"],
    },
    "魔理沙": {
        "normal":      ["00",  "00a", "00b", "00b", "00a", "00"],
        "happy":       ["01",  "00a", "02",  "02",  "00a", "01"],
        "surprised":   ["00",  "00a", "07",  "07",  "00a", "00"],
        "serious":     ["00",  "00a", "00b", "00b", "00a", "00"],
        "worried":     ["15",  "00a", "00b", "00b", "00a", "15"],
        "excited":     ["01",  "00a", "02",  "02",  "00a", "01"],
        "shocked":     ["00",  "00a", "11",  "11",  "00a", "00"],
        "embarrassed": ["15",  "00a", "03",  "03",  "00a", "15"],
        "thinking":    ["00",  "00a", "00a", "03",  "00a", "00"],
        "sad":         ["15",  "00a", "03",  "03",  "00a", "15"],
        "relieved":    ["30",  "00a", "03",  "03",  "00a", "30"],
        "angry":       ["18",  "00a", "12",  "12",  "00a", "18"],
        "curious":     ["00",  "00a", "03",  "03",  "00a", "00"],
        "awkward":     ["15",  "00a", "00a", "03",  "00a", "15"],
        "smug":        ["13",  "00a", "06",  "06",  "00a", "13"],
        "joyful":      ["20",  "00a", "02",  "02",  "00a", "20"],
    },
}


# ── 発話中感情変化マップ（メイン感情 → 途中で変わりうる感情候補） ─────
# グループ内遷移を優先（_EYE_SHAPE_GROUPSと整合させること）
# グループA(開き目): normal, surprised, excited, curious, joyful(霊夢のみ)
# グループB(細目): serious, smug, angry, awkward(魔理沙のみ)
# グループC(垂れ/閉じ): thinking, worried, sad, relieved, awkward(霊夢のみ)
# グループD(感情的): sad(霊夢), embarrassed, happy, joyful(魔理沙), shocked
_EMOTION_MID_SWITCH: dict[str, list] = {
    "happy":       ["embarrassed", "shocked"],  # D内遷移
    "excited":     ["surprised", "curious"],     # A内遷移
    "surprised":   ["excited", "curious"],       # A内遷移
    "shocked":     ["embarrassed", "happy"],     # D内遷移
    "serious":     ["angry"],                     # B内遷移（smug除外: ウインク頻出防止）
    "worried":     ["thinking", "relieved"],     # C内遷移
    "thinking":    ["worried", "relieved"],      # C内遷移
    "embarrassed": ["happy", "shocked"],         # D内遷移
    "sad":         ["embarrassed", "shocked", "worried", "thinking"],  # D内(霊夢) + C内(魔理沙)
    "angry":       ["serious"],                   # B内遷移（smug除外: ウインク頻出防止）
    "relieved":    ["thinking", "worried"],      # C内遷移
    "curious":     ["surprised", "excited"],     # A内遷移
    "awkward":     ["worried", "thinking", "serious", "angry"],  # C内(霊夢) + B内(魔理沙)
    "smug":        ["serious", "angry"],          # B内遷移
    "joyful":      ["excited", "surprised", "happy", "shocked"],  # A内(霊夢) + D内(魔理沙)
    "normal":      [],
}

# ── 瞬きスケジュール ──────────────────────────────────────
def _generate_blink_schedule(total_duration: float,
                             interval_min: float = _BLINK_INTERVAL_MIN,
                             interval_max: float = _BLINK_INTERVAL_MAX,
                             double_blink_chance: float = 0.0) -> list[float]:
    """動画全体の瞬きタイムスタンプをランダム生成する。
    double_blink_chance: 二連続瞬きの確率（0.0-1.0）
    """
    schedule = []
    t = random.uniform(1.0, 3.0)
    while t < total_duration:
        schedule.append(t)
        # 二連続瞬き: 短い間隔でもう1回
        if double_blink_chance > 0 and random.random() < double_blink_chance:
            t += 0.45  # 0.45秒後にもう1回（瞬きアニメ完了後）
            if t < total_duration:
                schedule.append(t)
        t += random.uniform(interval_min, interval_max)
    return schedule


def _get_blink_eye(char_name: str, abs_time: float,
                   blink_schedule: list[float]) -> "str | None":
    """現在時刻が瞬き中なら瞬き目IDを返す。それ以外はNone"""
    blink_seq = _BLINK_EYES.get(char_name)
    if not blink_seq:
        return None
    blink_dur = len(blink_seq) / FPS
    for bt in blink_schedule:
        if bt <= abs_time < bt + blink_dur:
            idx = int((abs_time - bt) * FPS)
            if 0 <= idx < len(blink_seq):
                return blink_seq[idx]
            return None
        if bt > abs_time + 1.0:
            break  # 未来の瞬きはスキップ
    return None


# アニメーションオーバーレイ設定
_ANIM_CYCLE_FRAMES = 12  # 1ループのステップ数（FPS=30・2フレーム刻みで約0.8秒ループ）
_overlay_cache: dict[tuple, "tuple | None"] = {}  # (emotion, char, step) → (np, ox, oy) or None — 最大360エントリ(自然収束)


def _draw_emotion_fx(img: Image.Image, emotion: str) -> Image.Image:
    """感情タグに対応するPIL描画エフェクトを重ねて返す。
    静止エフェクトは最小限。アニメーションは _build_anim_overlay で担当。
    """
    # 静止エフェクトは何もしない（アニメオーバーレイに一本化）
    return img

# ── 目の形状グループ（mid-switchはグループ内遷移のみ許可） ─────
# 形状が似た目同士でグループ化し、急激な目変化を防ぐ
_EYE_SHAPE_GROUPS: dict[str, list[list[str]]] = {
    "霊夢": [
        # A: 開き目系（通常〜やや大きい丸目）
        ["normal", "surprised", "excited", "curious", "joyful"],
        # B: 細目系（鋭い・すがめ）
        ["serious", "smug", "angry"],
        # C: 垂れ/閉じ系（穏やか・不安・考え中）
        ["thinking", "worried", "relieved", "awkward"],
        # D: 感情的（伏せ目・逸らし目・見開き）
        ["sad", "embarrassed", "shocked", "happy"],
    ],
    "魔理沙": [
        # A: 開き目系（通常垂れ目〜やや見開き〜丸目）
        ["normal", "surprised", "excited", "curious"],
        # B: 細目系（鋭い・ニヤリ・呆れ）
        ["serious", "smug", "angry", "awkward"],
        # C: 垂れ/閉じ系（思考・心配・穏やか閉じ目）
        ["thinking", "worried", "sad", "relieved"],
        # D: 感情的（横目・笑い閉じ・大見開き）
        ["embarrassed", "happy", "joyful", "shocked"],
    ],
}

def _get_eye_group(char_name: str, emotion: str) -> list[str]:
    """指定キャラ・感情が属する目グループを返す"""
    for group in _EYE_SHAPE_GROUPS.get(char_name, _EYE_SHAPE_GROUPS.get("霊夢", [])):
        if emotion in group:
            return group
    return []


# mid-switch確率（チューニング用定数）
_MID_SWITCH_CHANCE_MEDIUM = 0.20   # 中セリフ(1.5-3.5s): 20%で変化
_MID_SWITCH_CHANCE_LONG   = 0.50   # 長セリフ(>3.5s): 50%で1回変化


def _get_emotion_sequence(emotion: str, dur: float,
                          char_name: str = "") -> list:
    """発話時間に応じた感情変化シーケンスを返す。
    Returns: [(開始比率float, emotion_tag), ...]
      短い(<1.5s)  → 1感情
      中(1.5-3.5s) → 20%で変化
      長(>3.5s)    → 50%で1回変化（中間地点）
    mid-switch先は同じ目グループ内に制限（急激な目変化防止）
    """
    variants = _EMOTION_MID_SWITCH.get(emotion, [])
    if not variants or dur < 1.5:
        return [(0.0, emotion)]
    # グループ制限: 同じ目形状グループ内の遷移先のみ許可
    if char_name:
        eye_group = _get_eye_group(char_name, emotion)
        variants = [v for v in variants if v in eye_group]
    if not variants:
        return [(0.0, emotion)]
    # 確率チェック
    if dur < 3.5:
        if random.random() > _MID_SWITCH_CHANCE_MEDIUM:
            return [(0.0, emotion)]
        em2 = random.choice(variants)
        return [(0.0, emotion), (0.50, em2)]
    # 長セリフ: 50%で中間地点に1回だけ変化
    if random.random() > _MID_SWITCH_CHANCE_LONG:
        return [(0.0, emotion)]
    em2 = random.choice(variants)
    return [(0.0, emotion), (0.50, em2)]


def _build_anim_overlay(emotion: str, char: str, step: int) -> "tuple | None":
    """感情アニメーションオーバーレイを生成（キャッシュ前の実描画処理）。
    Returns: (RGBA numpy配列 shape(200,200,4), x座標, y座標) or None
    """
    cfg = CHAR_CONFIG.get(char)
    if not cfg:
        return None

    size_w, size_h = 200, 110  # テキストにちょうど収まるキャンバス
    img  = Image.new("RGBA", (size_w, size_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img, "RGBA")

    N = _ANIM_CYCLE_FRAMES
    t = step / N  # 0.0 〜 <1.0

    # キャラ位置に基づくオーバーレイ配置（実際の頭頂部の真上に乗せる）
    # スプライト上部の透明余白を考慮して実際の頭頂位置を計算
    _HEAD_PADDING: dict[str, float] = {"霊夢": 0.33, "魔理沙": 0.15}
    padding_ratio = _HEAD_PADDING.get(char, 0.20)
    char_top = cfg["bottom"] - cfg["height"]
    real_head_top = char_top + int(cfg["height"] * padding_ratio)
    ox = cfg["x_center"] - size_w // 2  # キャラ中央
    oy = real_head_top - size_h  # キャンバス下端 = 頭頂部（ボブはフレームループで加算）

    if emotion in ("surprised", "shocked"):
        # ！！マーク（独自バウンスなし — ボブのみで動く）
        alpha = int(200 + 55 * abs(math.sin(t * math.pi)))
        font_e = load_font(80)
        bbox_e = font_e.getbbox("！！")
        tw = bbox_e[2] - bbox_e[0]
        text_x = (size_w - tw) // 2
        text_y = 10
        draw.text((text_x + 4, text_y + 4), "！！", font=font_e, fill=(0, 0, 0, 140))
        draw.text((text_x, text_y), "！！", font=font_e, fill=(230, 30, 30, alpha))

    elif emotion == "curious":
        # ！？マーク（独自バウンスなし — ボブのみで動く）
        alpha = int(200 + 50 * abs(math.sin(t * math.pi)))
        font_e = load_font(80)
        bbox_e = font_e.getbbox("！？")
        tw = bbox_e[2] - bbox_e[0]
        text_x = (size_w - tw) // 2
        text_y = 10
        draw.text((text_x + 4, text_y + 4), "！？", font=font_e, fill=(0, 0, 0, 140))
        draw.text((text_x, text_y), "！？", font=font_e, fill=(230, 30, 30, alpha))

    elif emotion == "awkward":
        # 汗マーク（；）
        alpha = int(180 + 60 * abs(math.sin(t * math.pi)))
        font_e = load_font(72)
        text = "；"
        bbox_e = font_e.getbbox(text)
        tw = bbox_e[2] - bbox_e[0]
        text_x = (size_w - tw) // 2
        text_y = 10
        draw.text((text_x + 3, text_y + 3), text, font=font_e, fill=(0, 0, 0, 120))
        draw.text((text_x, text_y), text, font=font_e, fill=(80, 120, 200, alpha))

    elif emotion == "smug":
        # キラリマーク（☆）
        alpha = int(180 + 70 * abs(math.sin(t * math.pi * 1.5)))
        font_e = load_font(72)
        text = "☆"
        bbox_e = font_e.getbbox(text)
        tw = bbox_e[2] - bbox_e[0]
        text_x = (size_w - tw) // 2
        text_y = 10
        draw.text((text_x + 3, text_y + 3), text, font=font_e, fill=(0, 0, 0, 120))
        draw.text((text_x, text_y), text, font=font_e, fill=(255, 200, 0, alpha))

    else:
        return None

    return np.array(img), ox, oy  # shape: (200, 200, 4) RGBA


def _get_anim_overlay(emotion: str, char: str, step: int) -> "tuple | None":
    """アニメーションオーバーレイをキャッシュ付きで取得する。"""
    key = (emotion, char, step)
    if key not in _overlay_cache:
        _overlay_cache[key] = _build_anim_overlay(emotion, char, step)
    return _overlay_cache[key]


def _apply_anim_overlay(frame_np: np.ndarray,
                        overlay_rgba: np.ndarray,
                        ox: int, oy: int) -> np.ndarray:
    """RGBAオーバーレイをRGBフレーム(numpy)にアルファブレンドで合成（in-place）。"""
    h, w    = frame_np.shape[:2]
    oh, ow  = overlay_rgba.shape[:2]

    x0 = max(0, ox);   y0 = max(0, oy)
    x1 = min(w, ox + ow);  y1 = min(h, oy + oh)
    if x0 >= x1 or y0 >= y1:
        return frame_np

    sx0, sy0 = x0 - ox, y0 - oy
    sx1, sy1 = sx0 + (x1 - x0), sy0 + (y1 - y0)

    src   = overlay_rgba[sy0:sy1, sx0:sx1].astype(np.float32)
    dst   = frame_np[y0:y1, x0:x1].astype(np.float32)
    alpha = src[:, :, 3:4] / 255.0
    frame_np[y0:y1, x0:x1] = np.clip(
        dst * (1.0 - alpha) + src[:, :, :3] * alpha, 0, 255
    ).astype(np.uint8)
    return frame_np


FONT_NAME     = load_font(38)   # キャラクター名
FONT_SUBTITLE = load_font(68)   # 字幕テキスト（やや大きめ・高齢者配慮）

# 字幕バーのカラー（お手本スタイル：白い角丸帯で統一）
_SUBTITLE_BAR_COLORS = [
    (255, 255, 255, 215),   # 白（お手本準拠）
]


# ── 素材読み込み ──────────────────────────────────────────

def _load_background(bg_path: "Path | None" = None) -> Image.Image:
    """
    背景画像を読み込む。
    優先順位: bg_path引数 → assets/backgrounds/bg.* → グラデーション生成
    """
    # 1. 引数で指定されたパス（AI生成画像など）
    if bg_path and Path(bg_path).exists():
        img = Image.open(bg_path).convert("RGBA")
        return img.resize(RESOLUTION, Image.LANCZOS)

    # 2. assetsフォルダ内の固定背景画像
    for ext in ("png", "jpg", "jpeg"):
        path = BG_DIR / f"bg.{ext}"
        if path.exists():
            img = Image.open(path).convert("RGBA")
            return img.resize(RESOLUTION, Image.LANCZOS)

    # 3. 背景画像がない場合: 黒→ダークグレーのグラデーション
    bg = Image.new("RGBA", RESOLUTION, (0, 0, 0, 255))
    draw = ImageDraw.Draw(bg)
    for y in range(RESOLUTION[1]):
        gray = int(20 + (y / RESOLUTION[1]) * 30)
        draw.line([(0, y), (RESOLUTION[0], y)], fill=(gray, gray, gray, 255))
    return bg


def _load_kai_sprites(name: str) -> dict[str, dict[str, Image.Image]]:
    """nicotalk改のパーツ画像を全て読み込む。

    Returns:
        {"body": {"00": Image}, "face": {"00a": Image, ...},
         "eyes": {"00": Image, ...}, "mouth": {"00": Image, ...},
         "other": {"01": Image, ...}}
    """
    _DIR_MAP = {"霊夢": "reimu_kai", "魔理沙": "marisa_kai"}
    _CHAR_NAMES = {"霊夢": "ゆっくり霊夢改", "魔理沙": "ゆっくり魔理沙改"}
    base_dir = CHAR_DIR / _DIR_MAP[name] / _CHAR_NAMES[name]

    parts: dict[str, dict[str, Image.Image]] = {}
    for part_key, dir_name in [("body", "体"), ("face", "顔"),
                                ("eyes", "目"), ("mouth", "口"), ("other", "他")]:
        part_dir = base_dir / dir_name
        if not part_dir.exists():
            parts[part_key] = {}
            continue
        imgs = {}
        for f in sorted(part_dir.glob("*.png")):
            imgs[f.stem] = Image.open(f).convert("RGBA")
        parts[part_key] = imgs
    return parts


# パーツ合成済みキャラ画像のキャッシュ（行ごとにクリア）
_kai_char_cache: dict[tuple, Image.Image] = {}


def _compose_kai_character(parts: dict, emotion: str, char_name: str,
                           mouth_open: "bool | int", blink_eye: "str | None",
                           cfg: dict, is_speaking: bool) -> Image.Image:
    """パーツを合成してリサイズ済みキャラ画像を返す。キャッシュ付き。
    mouth_open: False=閉じ, True=開き(従来互換), int=口形状フェーズ(0-5)
    """
    cache_key = (char_name, emotion, mouth_open, blink_eye, is_speaking)
    if cache_key in _kai_char_cache:
        return _kai_char_cache[cache_key]

    emap = _KAI_EMOTION_PARTS.get(char_name, {}).get(emotion)
    if not emap:
        emap = _KAI_EMOTION_PARTS.get(char_name, {}).get("normal", {})

    # 体（元のbodyをそのまま使用 — 自然な肌色を維持）
    body = parts["body"].get("00")
    if body is None:
        body = Image.new("RGBA", (400, 400), (0, 0, 0, 0))
    result = body.copy()

    # 顔ベース（魔理沙: 頬赤み感情のみ顔パーツを合成、それ以外は貼らない — 明るみ防止）
    _BLUSH_EMOTIONS = {"embarrassed", "awkward"}  # 意図的に頬ピンクを使う感情
    skip_face = (char_name == "魔理沙" and emotion not in _BLUSH_EMOTIONS)
    if not skip_face:
        face_id = emap.get("face", "00a")
        face = parts["face"].get(face_id) or next(iter(parts["face"].values()), None)
        if face:
            result = Image.alpha_composite(result, face)

    # 目（瞬き中は瞬き目で上書き）
    if blink_eye and blink_eye in parts["eyes"]:
        eye_img = parts["eyes"][blink_eye]
    else:
        eye_id = emap.get("eyes", "00")
        eye_img = parts["eyes"].get(eye_id) or parts["eyes"].get("00")
    if eye_img:
        result = Image.alpha_composite(result, eye_img)

    # 口（mouth_open: False=閉, True=全開(互換), int=シーケンスフェーズ）
    if isinstance(mouth_open, int):
        seq = _MOUTH_SEQUENCE.get(char_name, {}).get(emotion)
        if seq:
            mouth_id = seq[mouth_open % len(seq)]
        else:
            mouth_id = emap.get("mo", "02") if (mouth_open % 6) >= 2 else emap.get("mc", "00")
    elif mouth_open:
        mouth_id = emap.get("mo", "02")
    else:
        mouth_id = emap.get("mc", "00")
    mouth_img = parts["mouth"].get(mouth_id) or parts["mouth"].get("00")
    if mouth_img:
        result = Image.alpha_composite(result, mouth_img)

    # 装飾パーツ（涙・汗エフェクト — 特定感情のみ）
    # 霊夢の他パーツ: 01=汗粒, 02=涙(中), 03=涙(大)
    _OTHER_MAP = {
        "shocked":  "01",   # 汗
        "sad":      "02",   # 涙
        "worried":  "01",   # 汗
    }
    other_id = _OTHER_MAP.get(emotion)
    if other_id and other_id in parts.get("other", {}):
        result = Image.alpha_composite(result, parts["other"][other_id])

    # 高さに合わせてリサイズ
    height = cfg["height"]
    ratio = height / result.height
    new_w = int(result.width * ratio)
    result = result.resize((new_w, height), Image.LANCZOS)
    if cfg.get("flip_h", False):
        result = result.transpose(Image.FLIP_LEFT_RIGHT)

    # 聞き手は暗く・小さく
    if not is_speaking:
        r, g, b, a = result.split()
        r = r.point(lambda x: int(x * 0.45))
        g = g.point(lambda x: int(x * 0.45))
        b = b.point(lambda x: int(x * 0.45))
        result = Image.merge("RGBA", (r, g, b, a))
        sh = int(result.height * 0.88)
        sw = int(result.width * 0.88)
        result = result.resize((sw, sh), Image.LANCZOS)

    _kai_char_cache[cache_key] = result
    return result


# ── フレーム合成 ──────────────────────────────────────────

def _draw_text_with_outline(draw: ImageDraw.Draw, pos: tuple, text: str,
                             font, fill, outline=(0, 0, 0), outline_width=3):
    """縁取り付きテキストを描画する（Pillow組み込みstroke_width使用）"""
    draw.text(pos, text, font=font, fill=fill,
              stroke_width=outline_width, stroke_fill=outline)


def _wrap_subtitle(text: str, font, max_width: int) -> list[str]:
    """字幕テキストを max_width に収まるよう折り返す"""
    lines = []
    current = ""
    for char in text:
        test = current + char
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] > max_width:
            lines.append(current)
            current = char
        else:
            current = test
    if current:
        lines.append(current)
    return lines


def _load_irasutoya_panel(img_path: "Path | None") -> "Image.Image | None":
    """いらすとや画像を中央パネル用にリサイズして返す（透過PNG対応）"""
    if not img_path or not Path(img_path).exists():
        return None
    try:
        img = Image.open(img_path).convert("RGBA")
        # 最大サイズ: 中央エリア (幅554, 高さ514) に収まるよう縦横比を保持
        border = 4
        max_w, max_h = 640 - border * 2, 600 - border * 2
        ratio = min(max_w / img.width, max_h / img.height)
        new_w = int(img.width * ratio)
        new_h = int(img.height * ratio)
        resized = img.resize((new_w, new_h), Image.LANCZOS)
        # 白枠（3px）を追加（お手本準拠）
        bordered = Image.new("RGBA", (new_w + border * 2, new_h + border * 2), (255, 255, 255, 255))
        bordered.paste(resized, (border, border), resized)
        return bordered
    except Exception:
        return None


# いらすとやパネルのキャッシュ（同じ画像の重複ロードを防ぐ）
_irasutoya_cache: dict[str, "Image.Image | None"] = {}  # 1動画あたり最大~50エントリ(自然収束)

# ── ホワイトボード描画 ────────────────────────────────────────
_WB_WIDTH  = 620   # ホワイトボードの幅
_WB_HEIGHT = 540   # ホワイトボードの高さ
_WB_PAD    = 24    # 内側余白
_WB_Y      = 45    # 上端Y座標
_WB_TITLE_FONT  = load_font(26)
_WB_ITEM_FONT   = load_font(30)
_WB_BULLET_COLOR = (0, 50, 120, 255)     # 濃い青
_WB_TITLE_COLOR  = (100, 100, 100, 255)  # グレー
_WB_BG_COLOR     = (255, 255, 255, 235)  # 白（やや透過）
_WB_BORDER_COLOR = (180, 180, 180, 255)  # 枠線グレー
_wb_cache: dict[str, Image.Image] = {}


def _render_whiteboard(section_title: str, items: list[str],
                       is_summary: bool = False) -> Image.Image:
    """ホワイトボード画像を生成する。
    items: 表示する箇条書きテキストのリスト（累積済み）
    """
    cache_key = f"{section_title}:{len(items)}:{is_summary}"
    if cache_key in _wb_cache:
        return _wb_cache[cache_key]

    wb = Image.new("RGBA", (_WB_WIDTH, _WB_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(wb)

    # 背景（角丸矩形 + 枠線）
    draw.rounded_rectangle(
        [0, 0, _WB_WIDTH - 1, _WB_HEIGHT - 1],
        radius=16, fill=_WB_BG_COLOR, outline=_WB_BORDER_COLOR, width=2,
    )

    # タイトル（上部）
    title_text = "まとめ" if is_summary else section_title
    _draw_text_with_outline(draw, (_WB_PAD, _WB_PAD - 2), title_text,
                            _WB_TITLE_FONT, _WB_TITLE_COLOR, (255, 255, 255, 255), 1)

    # 区切り線
    line_y = _WB_PAD + 30
    draw.line([_WB_PAD, line_y, _WB_WIDTH - _WB_PAD, line_y],
              fill=(200, 200, 200, 255), width=2)

    # 箇条書き
    y = line_y + 12
    line_height = 42 if len(items) <= 6 else 36
    item_font = _WB_ITEM_FONT if len(items) <= 6 else load_font(26)
    for i, item_text in enumerate(items):
        bullet = f"  {item_text}"
        # 丸マーク
        bullet_y = y + (line_height - 12) // 2
        draw.ellipse([_WB_PAD + 4, bullet_y, _WB_PAD + 16, bullet_y + 12],
                     fill=_WB_BULLET_COLOR)
        _draw_text_with_outline(draw, (_WB_PAD + 22, y), bullet,
                                item_font, _WB_BULLET_COLOR, (255, 255, 255, 255), 1)
        y += line_height

    # 上限32エントリ（約40MB）を超えたら古い半分を破棄
    if len(_wb_cache) > 32:
        for _old_k in list(_wb_cache)[:16]:
            del _wb_cache[_old_k]
    _wb_cache[cache_key] = wb
    return wb


# ── セクション間トランジション + セクション表紙 ──────────────────
# セクション切り替え時に挿入する演出（BGM一時停止 + SE + タイトルカード）
TRANSITION_WIPE_SEC  = 0.7   # ワイプアニメーション秒数
TRANSITION_CARD_SEC  = 2.0   # セクション表紙の表示秒数
TRANSITION_TOTAL_SEC = 3.0   # トランジション全体の秒数（ワイプ+表紙+余白）
_TRANSITION_COLOR    = (76, 175, 80)    # 健康チャンネルの緑
_TRANSITION_COLOR2   = (200, 230, 201)  # 薄い緑
_CARD_OVERLAY_ALPHA  = 140              # 表紙背景の暗さ（0-255）
_CARD_NUMBER_FONT    = load_font(120)
_CARD_TITLE_FONT     = load_font(64)
_CARD_THEME_FONT     = load_font(28)
_CARD_LINE_COLOR     = (76, 175, 80, 200)  # 緑アクセントライン


def _render_transition_frame(progress: float) -> np.ndarray:
    """緑→白のワイプトランジション（progress: 0.0→1.0）"""
    img = Image.new("RGB", RESOLUTION, (255, 255, 255))
    draw = ImageDraw.Draw(img)
    w, h = RESOLUTION
    # ワイプ位置（左端→右端）
    wipe_x = int(progress * (w + 400)) - 200  # 余白を持たせてスムーズに
    # グラデーション帯（200px幅）
    grad_width = 200
    for x in range(max(0, wipe_x - grad_width), min(w, wipe_x)):
        ratio = (x - (wipe_x - grad_width)) / grad_width
        r = int(_TRANSITION_COLOR2[0] + (255 - _TRANSITION_COLOR2[0]) * ratio)
        g = int(_TRANSITION_COLOR2[1] + (255 - _TRANSITION_COLOR2[1]) * ratio)
        b = int(_TRANSITION_COLOR2[2] + (255 - _TRANSITION_COLOR2[2]) * ratio)
        draw.line([(x, 0), (x, h)], fill=(r, g, b))
    # ワイプ済み部分（緑→薄緑グラデーション）
    if wipe_x - grad_width > 0:
        for x in range(0, min(w, wipe_x - grad_width)):
            ratio = x / max(1, wipe_x - grad_width)
            r = int(_TRANSITION_COLOR[0] + (_TRANSITION_COLOR2[0] - _TRANSITION_COLOR[0]) * ratio)
            g = int(_TRANSITION_COLOR[1] + (_TRANSITION_COLOR2[1] - _TRANSITION_COLOR[1]) * ratio)
            b = int(_TRANSITION_COLOR[2] + (_TRANSITION_COLOR2[2] - _TRANSITION_COLOR[2]) * ratio)
            draw.line([(x, 0), (x, h)], fill=(r, g, b))
    return np.array(img, dtype=np.uint8)


def _render_title_card(section_number: int, section_title: str,
                       video_theme: str,
                       title_card_bg: "Image.Image | None" = None) -> np.ndarray:
    """セクション表紙を描画する"""
    w, h = RESOLUTION
    # 背景画像があればリサイズ+暗くする、なければ緑グラデーション
    if title_card_bg is not None:
        bg = title_card_bg.resize((w, h), Image.LANCZOS).convert("RGBA")
        overlay = Image.new("RGBA", (w, h), (0, 0, 0, _CARD_OVERLAY_ALPHA))
        bg = Image.alpha_composite(bg, overlay)
    else:
        bg = Image.new("RGBA", (w, h), (30, 60, 30, 255))
        draw_bg = ImageDraw.Draw(bg)
        # シンプルなグラデーション背景
        for y in range(h):
            ratio = y / h
            r = int(20 + 40 * ratio)
            g = int(50 + 80 * ratio)
            b = int(20 + 40 * ratio)
            draw_bg.line([(0, y), (w, y)], fill=(r, g, b, 255))

    draw = ImageDraw.Draw(bg)

    # 上下の緑アクセントライン
    draw.rectangle([(0, 0), (w, 8)], fill=_CARD_LINE_COLOR)
    draw.rectangle([(0, h - 8), (w, h)], fill=_CARD_LINE_COLOR)

    # セクション番号（緑の円 + 白文字）
    circle_r = 80
    circle_cx = w // 2
    circle_cy = h // 2 - 120
    draw.ellipse(
        [(circle_cx - circle_r, circle_cy - circle_r),
         (circle_cx + circle_r, circle_cy + circle_r)],
        fill=(76, 175, 80, 230),
    )
    num_text = str(section_number)
    num_bbox = _CARD_NUMBER_FONT.getbbox(num_text)
    num_w = num_bbox[2] - num_bbox[0]
    num_h = num_bbox[3] - num_bbox[1]
    draw.text(
        (circle_cx - num_w // 2, circle_cy - num_h // 2 - 10),
        num_text, fill=(255, 255, 255, 255), font=_CARD_NUMBER_FONT,
    )

    # セクションタイトル（白文字、縁取り付き）
    # タイトルから不要な記号を除去
    clean_title = section_title.strip()
    for prefix in ("【", "】"):
        clean_title = clean_title.replace(prefix, "")
    title_y = circle_cy + circle_r + 30
    title_bbox = _CARD_TITLE_FONT.getbbox(clean_title)
    title_w = title_bbox[2] - title_bbox[0]
    title_x = (w - title_w) // 2
    # 縁取り（黒）
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            if dx * dx + dy * dy <= 9:
                draw.text((title_x + dx, title_y + dy), clean_title,
                          fill=(0, 0, 0, 200), font=_CARD_TITLE_FONT)
    draw.text((title_x, title_y), clean_title,
              fill=(255, 255, 255, 255), font=_CARD_TITLE_FONT)

    # 動画テーマ名（下部、薄い白文字）
    theme_bbox = _CARD_THEME_FONT.getbbox(video_theme)
    theme_w = theme_bbox[2] - theme_bbox[0]
    draw.text(
        ((w - theme_w) // 2, h - 80),
        video_theme, fill=(255, 255, 255, 150), font=_CARD_THEME_FONT,
    )

    return np.array(bg.convert("RGB"), dtype=np.uint8)


# ベースフレーム（字幕+背景+いらすとや）の1エントリキャッシュ
_base_frame_cache: list = [None, None]  # [cache_key, PIL Image]
# 字幕バーオーバーレイのキャッシュ（色が変わらない限り再利用）
_subtitle_overlay_cache: list = [None, None]  # [subtitle_bar_color, PIL Image]


def compose_frame(character: str, text: str,
                  bg: Image.Image,
                  kai_sprites: dict,
                  subtitle_bar_color: tuple = (255, 255, 255, 215),
                  irasutoya_img_path: "Path | None" = None,
                  emotion: str = "normal",
                  mouth_open: "bool | int" = False,
                  bob_offset: int = 0,
                  blink_eyes: "dict | None" = None,
                  listener_emotion: str = "normal",
                  per_char_emotion: "dict[str, str] | None" = None,
                  whiteboard_img: "Image.Image | None" = None) -> np.ndarray:
    """1フレームの画像を合成してnumpy配列で返す。

    Args:
        character: 現在話しているキャラクター名
        text: 字幕テキスト
        bg: 背景画像
        kai_sprites: {キャラ名: {part: {id: Image}}} nicotalk改パーツ
        subtitle_bar_color: 字幕バー色 (RGBA)
        irasutoya_img_path: いらすとや画像パス（省略可）
        emotion: 話者の感情タグ
        mouth_open: False=閉, True=開(互換), int=口形状フェーズ(0-5)
        blink_eyes: {キャラ名: 瞬き目ID or None} 瞬き状態
        listener_emotion: 聞き手の感情タグ
    """
    # ベースフレーム（背景+いらすとやのみ）をキャッシュ付きで生成
    _bk = (id(bg), str(irasutoya_img_path), id(whiteboard_img))
    if _base_frame_cache[0] == _bk:
        frame = _base_frame_cache[1].copy()
    else:
        frame = bg.copy()

        # ── 中央パネル: ホワイトボード or いらすとや画像 ──
        if whiteboard_img is not None:
            # ホワイトボード表示（いらすとやより優先）
            center_x = RESOLUTION[0] // 2
            wb_x = center_x - whiteboard_img.width // 2
            wb_y = _WB_Y
            frame.paste(whiteboard_img, (wb_x, wb_y), whiteboard_img)
        else:
            # いらすとや画像を中央上部に配置
            ira_key = str(irasutoya_img_path) if irasutoya_img_path else ""
            if ira_key not in _irasutoya_cache:
                _irasutoya_cache[ira_key] = _load_irasutoya_panel(irasutoya_img_path)
            ira_panel = _irasutoya_cache.get(ira_key)
            if ira_panel:
                center_x = RESOLUTION[0] // 2
                panel_x  = center_x - ira_panel.width // 2
                panel_y  = 60
                pad = 18
                panel_bg = Image.new("RGBA", RESOLUTION, (0, 0, 0, 0))
                panel_draw = ImageDraw.Draw(panel_bg)
                panel_draw.rounded_rectangle(
                    [panel_x - pad, panel_y - pad,
                     panel_x + ira_panel.width + pad, panel_y + ira_panel.height + pad],
                    radius=20, fill=(255, 255, 255, 200),
                )
                frame = Image.alpha_composite(frame, panel_bg)
                frame.paste(ira_panel, (panel_x, panel_y), ira_panel)

        _base_frame_cache[0] = _bk
        _base_frame_cache[1] = frame.copy()

    # ── キャラクターをパーツ合成で配置（字幕バーの奥側） ──
    for name, cfg in CHAR_CONFIG.items():
        parts = kai_sprites.get(name)
        if not parts:
            continue
        is_speaking = (name == character) or (character == "両者")
        if per_char_emotion and name in per_char_emotion:
            char_emo = per_char_emotion[name]
        else:
            char_emo = emotion if is_speaking else listener_emotion
        char_mouth = mouth_open if is_speaking else False
        blink_eye = (blink_eyes or {}).get(name)

        img = _compose_kai_character(parts, char_emo, name,
                                     char_mouth, blink_eye, cfg, is_speaking)
        x = cfg["x_center"] - img.width // 2
        y = cfg["bottom"] - img.height + (bob_offset if is_speaking else 0)
        frame.paste(img, (x, y), img)

    # ── 字幕バー（角丸帯）をキャラの上に重ねる ──
    # プリレンダ済みオーバーレイを使い回す（色が同じなら毎フレーム再生成不要）
    if _subtitle_overlay_cache[0] != subtitle_bar_color:
        _ov = Image.new("RGBA", RESOLUTION, (0, 0, 0, 0))
        _ov_draw = ImageDraw.Draw(_ov)
        _ov_draw.rounded_rectangle(
            [0, SUBTITLE_BAR_Y, RESOLUTION[0], RESOLUTION[1] + 40],
            radius=22, fill=subtitle_bar_color,
        )
        _subtitle_overlay_cache[0] = subtitle_bar_color
        _subtitle_overlay_cache[1] = _ov
    frame = Image.alpha_composite(frame, _subtitle_overlay_cache[1])

    draw = ImageDraw.Draw(frame)

    # ── 字幕テキスト（お手本準拠スタイル） ──
    # 霊夢: 白文字 + 赤枠　魔理沙: 黄文字 + 黒枠
    # 両者: 2段表示（上段=霊夢色、下段=魔理沙色で同じテキストを重ねる）
    max_w = RESOLUTION[0] - SUBTITLE_PADDING * 2

    if character == "両者":
        # ハモり演出: 霊夢色・魔理沙色の2段字幕
        duo_styles = [
            ((255, 255, 255, 255), (200, 20, 20)),   # 霊夢: 白+赤縁
            ((255, 235, 0, 255),   (0, 0, 0)),        # 魔理沙: 黄+黒縁
        ]
        duo_font = load_font(80)
        duo_line_h = 90
        duo_y = SUBTITLE_BAR_Y + (SUBTITLE_BAR_HEIGHT - len(duo_styles) * duo_line_h) // 2
        for fill_c, outline_c in duo_styles:
            bbox = duo_font.getbbox(text)
            text_w = bbox[2] - bbox[0]
            text_x = (RESOLUTION[0] - text_w) // 2
            _draw_text_with_outline(
                draw, (text_x, duo_y), text,
                font=duo_font, fill=fill_c,
                outline=outline_c, outline_width=4,
            )
            duo_y += duo_line_h
    else:
        if character == "霊夢":
            subtitle_text_color = (255, 255, 255, 255)     # 白
            subtitle_outline    = (200, 20, 20)             # 赤縁
        else:
            subtitle_text_color = (255, 235, 0, 255)        # 黄色
            subtitle_outline    = (0, 0, 0)                 # 黒縁
        # まず2行フォントで折り返し、1行に収まるなら大きいフォントに切り替える
        wrapped = _wrap_subtitle(text, FONT_SUBTITLE, max_w)
        if len(wrapped) == 1:
            # 1行のみ → バーいっぱいの大フォント（最大100px）で再レンダリング
            font_large = load_font(100)
            bbox_large = font_large.getbbox(wrapped[0])
            if bbox_large[2] - bbox_large[0] <= max_w:
                active_font = font_large
                line_height = 110
            else:
                active_font = FONT_SUBTITLE
                line_height = 80
        elif len(wrapped) > 2:
            # 3行以上 → フォントを縮小して2行に収める
            _try_font = FONT_SUBTITLE
            _try_size = 68
            for _try_size in [56, 48, 40]:
                _try_font = load_font(_try_size)
                wrapped = _wrap_subtitle(text, _try_font, max_w)
                if len(wrapped) <= 2:
                    break
            # 40pxでも3行以上なら最大2行に切り詰める
            if len(wrapped) > 2:
                wrapped = wrapped[:2]
            active_font = _try_font
            line_height = _try_size + 12
        else:
            active_font = FONT_SUBTITLE
            line_height = 80
        num_lines = min(len(wrapped), 2)
        text_y = SUBTITLE_BAR_Y + (SUBTITLE_BAR_HEIGHT - num_lines * line_height) // 2
        for line in wrapped[:2]:
            bbox   = active_font.getbbox(line)
            text_w = bbox[2] - bbox[0]
            text_x = (RESOLUTION[0] - text_w) // 2
            _draw_text_with_outline(
                draw, (text_x, text_y), line,
                font=active_font, fill=subtitle_text_color,
                outline=subtitle_outline, outline_width=4,
            )
            text_y += line_height

    return np.asarray(frame)[:, :, :3].copy()


# ── BGM合成 ───────────────────────────────────────────────

# ファイル名 → (曲名, 作者, ライセンス表記) のクレジット辞書
# DOVA-SYNDROME: YouTube収益化OK・クレジット任意（記載推奨）
BGM_CREDITS: dict[str, tuple[str, str, str]] = {
    "bgm1_dova":                    ("（BGM1）",            "DOVA-SYNDROME",       "https://dova-s.jp/"),
    "bgm2_dova":                    ("（BGM2）",            "DOVA-SYNDROME",       "https://dova-s.jp/"),
    "bgm3_昼下がり気分":             ("昼下がり気分",         "KK",                  "https://dova-s.jp/bgm/detail/4695"),
    "bgm4_日曜の午後":               ("日曜の午後",           "KK",                  "https://dova-s.jp/bgm/detail/4658"),
    "bgm5_自宅にて":                 ("自宅にて",             "KK",                  "https://dova-s.jp/bgm/detail/4041"),
    "bgm6_神隠しの真相":             ("神隠しの真相",         "しゃろう",             "https://dova-s.jp/bgm/detail/7674"),
    "bgm7_Morning":                 ("Morning",             "しゃろう",             "https://dova-s.jp/bgm/detail/2445"),
    "bgm8_野良猫は宇宙を目指した":   ("野良猫は宇宙を目指した", "しゃろう",           "https://dova-s.jp/bgm/detail/2862"),
    "bgm9_ほんわかぷっぷー":         ("ほんわかぷっぷー",      "もっぴーさうんど",     "https://dova-s.jp/bgm/detail/1854"),
    "bgm10_Dominus_Deus":           ("全てを創造する者",      "KK",                  "https://dova-s.jp/bgm/detail/5588"),
    "bgm11_不穏":                   ("不穏",                 "こっけ（西本康佑）",   "https://dova-s.jp/bgm/detail/8333"),
    "bgm12_焼きそば行進曲":          ("焼きそば行進曲",        "もっぴーさうんど",     "https://dova-s.jp/bgm/play1788.html"),
    "bgm13_楽しい帰り道":            ("楽しい帰り道",          "DOVA-SYNDROME",       "https://dova-s.jp/bgm/play3438.html"),
    "bgm14_Fancy_Pop":              ("Fancy Pop",            "DOVA-SYNDROME",       "https://dova-s.jp/bgm/play17411.html"),
    "bgm15_ゆかいな仲間":            ("ゆかいな仲間",          "いまたく",             "https://dova-s.jp/bgm/play11074.html"),
}


def get_bgm_credit(bgm_path: "Path | None") -> tuple[str, str, str] | None:
    """BGMファイルのクレジット情報を返す。見つからなければNone"""
    if bgm_path is None:
        return None
    stem = Path(bgm_path).stem
    return BGM_CREDITS.get(stem)


# BGMカテゴリ（ファイル名プレフィックスで分類）
# bgm3-6  = 落ち着いた解説系
# bgm7-9  = 明るい・前向き（まとめ/ED）
# bgm10+  = 衝撃パート（緊張感・シリアス）
# bgm12-15 = 茶番劇系（コミカル・明るい・テンポよし）— 要ダウンロード
def _get_bgm_files(category: str | None = None) -> list:
    """カテゴリ別にBGMファイルを返す。categoryがNoneなら全ファイルから選ぶ"""
    all_files = list(BGM_DIR.glob("*.mp3")) + list(BGM_DIR.glob("*.wav"))
    if not all_files or category is None:
        return all_files

    def _num(p):
        m = re.match(r"bgm(\d+)", p.stem)
        return int(m.group(1)) if m else 99

    if category == "main":
        # メインBGM: 茶番劇系(12-15)があればそれを優先、なければ明るい系(7-9)、最後に通常系(3-6)
        charade = [f for f in all_files if 12 <= _num(f) <= 15]
        if charade:
            return charade
        bright = [f for f in all_files if 7 <= _num(f) <= 9]
        return bright if bright else [f for f in all_files if 3 <= _num(f) <= 6]
    elif category == "ending":
        filtered = [f for f in all_files if 7 <= _num(f) <= 9]
    elif category == "impact":
        filtered = [f for f in all_files if _num(f) >= 10]
    else:
        filtered = all_files

    return filtered if filtered else all_files


def _select_bgm(category: str | None = None) -> "Path | None":
    """カテゴリに合ったBGMファイルをランダム選択して返す"""
    bgm_files = _get_bgm_files(category)
    if not bgm_files:
        return None
    return random.choice(bgm_files)


# ── メイン処理 ────────────────────────────────────────────

def build_video(script: dict, audio_dir: Path, output_path: Path,
                bg_path: "Path | None" = None) -> "tuple[Path, list[Path], list[float], float]":
    """台本JSONと音声ファイルから動画を生成する。
    Returns: (video_path, used_bgm_paths, section_timestamps, total_duration)
    """
    print("動画を生成しています...")
    print(f"  エンコード設定: preset={ENCODE_PRESET}, threads={ENCODE_THREADS or 'auto'}")

    # 字幕バーの色をランダム選択（毎動画で見た目に変化を出す）
    subtitle_bar_color = random.choice(_SUBTITLE_BAR_COLORS)

    # 素材を読み込む（AI生成背景があればそれを優先）
    bg = _load_background(bg_path)
    if bg_path and Path(bg_path).exists():
        print(f"  AI生成背景画像を使用: {Path(bg_path).name}")

    # nicotalk改パーツを読み込む（体/顔/目/口の個別パーツ）
    kai_sprites: dict[str, dict] = {}
    for name in CHAR_CONFIG:
        kai_sprites[name] = _load_kai_sprites(name)
        n_eyes = len(kai_sprites[name].get("eyes", {}))
        n_mouth = len(kai_sprites[name].get("mouth", {}))
        n_face = len(kai_sprites[name].get("face", {}))
        print(f"  キャラ画像 {name}: nicotalk改 目{n_eyes}/口{n_mouth}/顔{n_face}パーツ読み込み済み")

    # いらすとや画像を話題転換点で取得（セリフごとではなく話題が変わったときに切り替え）
    print("  いらすとや画像を取得しています...")
    all_lines: list[dict] = []
    _section_breaks: list[int] = []  # セクション先頭行のインデックス
    for section in script.get("sections", []):
        _section_breaks.append(len(all_lines))
        for line in section.get("lines", []):
            all_lines.append(line)

    line_ira_images: dict[int, "Path | None"] = {}
    try:
        _clipart_provider = os.getenv("CLIPART_PROVIDER", "gemini").lower()
        if _clipart_provider == "irasutoya":
            from irasutoya_fetcher import prefetch_for_lines
        else:
            from clipart_generator import prefetch_for_lines
        line_ira_images = prefetch_for_lines(all_lines, section_breaks=_section_breaks)
        found = sum(1 for v in line_ira_images.values() if v)
        unique = len(set(str(v) for v in line_ira_images.values() if v))
        print(f"  いらすとや画像: {unique}種類を{len(all_lines)}セリフに配置")
    except Exception as e:
        print(f"  いらすとや取得スキップ: {e}")

    # セリフリストを事前に収集（音声ファイルが存在するものだけ）
    line_entries = []  # [(line_num, character, text, audio_path, ira_img_path, emotion), ...]
    _section_first_line: list[int] = []  # 各セクションの先頭line_entryインデックス
    _script_idx_to_entry: dict[int, int] = {}  # スクリプト全行idx → line_entryインデックス
    line_num = 1
    line_idx = 0
    for section in script.get("sections", []):
        _sec_first = len(line_entries)  # このセクションの先頭位置を記録
        for line in section.get("lines", []):
            audio_path = audio_dir / f"{line_num:03d}_{line['character']}.wav"
            if audio_path.exists():
                _script_idx_to_entry[line_idx] = len(line_entries)
                ira_path = line_ira_images.get(line_idx)
                emotion = line.get("emotion", "normal")
                line_entries.append((line_num, line["character"], line["text"], audio_path, ira_path, emotion))
            line_num += 1
            line_idx += 1
        _section_first_line.append(_sec_first)

    if not line_entries:
        raise ValueError("有効なクリップがありません。音声ファイルを確認してください。")

    # ── セクション間トランジション情報の前処理 ──────────────────────────
    # _transition_at: セクション先頭line_entryインデックス → (sec_number, sec_title, sec_type)
    _transition_at: dict[int, tuple[int, str, str]] = {}
    _section_types: list[str] = []
    _section_titles: list[str] = []
    for _sec_i, section in enumerate(script.get("sections", [])):
        _sec_type = section.get("type", "chapter")
        _sec_title = section.get("section", section.get("title", ""))
        _section_types.append(_sec_type)
        _section_titles.append(_sec_title)

    if len(_section_first_line) >= 2:
        _chapter_num = 0
        for _sec_i in range(1, len(_section_first_line)):
            _prev_type = _section_types[_sec_i - 1] if _sec_i - 1 < len(_section_types) else ""
            _cur_type = _section_types[_sec_i] if _sec_i < len(_section_types) else ""
            _cur_title = _section_titles[_sec_i] if _sec_i < len(_section_titles) else ""
            # intro→chapter, chapter→chapter, chapter→summary の間にのみ挿入
            if (_prev_type in ("intro", "chapter") and
                    _cur_type in ("chapter", "summary", "outro", "conclusion", "ending")):
                if _cur_type == "chapter":
                    _chapter_num += 1
                    _num = _chapter_num
                elif _cur_type in ("summary", "outro", "conclusion", "ending"):
                    _num = _chapter_num + 1
                else:
                    _num = _sec_i
                first_idx = _section_first_line[_sec_i]
                if first_idx < len(line_entries):
                    _transition_at[first_idx] = (_num, _cur_title, _cur_type)
        if _transition_at:
            print(f"  セクショントランジション: {len(_transition_at)}箇所に挿入")

    # セクション表紙画像を事前生成（トランジションがある場合のみ）
    _title_card_images: dict[int, "Image.Image | None"] = {}
    _video_theme = script.get("theme", script.get("title", ""))
    if _transition_at:
        try:
            from image_generator import generate_section_image
            _tc_dir = output_path.parent / "title_cards"
            _tc_dir.mkdir(exist_ok=True)
            for _tc_idx, (_tc_num, _tc_title, _tc_type) in _transition_at.items():
                _tc_path = _tc_dir / f"title_card_{_tc_num:02d}.jpg"
                _tc_content = _tc_title
                _tc_img_path = generate_section_image(_tc_content, _tc_path,
                                                      width=1920, height=1080)
                if _tc_img_path and _tc_img_path.exists():
                    _title_card_images[_tc_idx] = Image.open(_tc_img_path).convert("RGBA")
                    print(f"    表紙画像生成: [{_tc_num}] {_tc_title[:20]}")
                else:
                    _title_card_images[_tc_idx] = None
        except Exception as e:
            print(f"  セクション表紙画像の生成スキップ: {e}")

    # ── ホワイトボード情報の前処理 ──────────────────────────────────
    # wb_schedule[line_entry_index] = (section_title, [accumulated_items], is_summary)
    _wb_schedule: dict[int, tuple[str, list[str], bool]] = {}

    def _clean_wb_title(raw_title: str) -> str:
        """ホワイトボードタイトルからランキング番号・装飾を除去する"""
        # 「第N位：」「第N位＆第N位：」パターン
        cleaned = re.sub(r'第\d+位(?:＆第\d+位)*[：:]\s*', '', raw_title)
        # 「【暴露N】」「【衝撃N】」等のパターン
        cleaned = re.sub(r'【[^】]*\d+[^】]*】\s*', '', cleaned)
        return cleaned.strip() or raw_title  # 全部消えた場合は元に戻す
    _wb_se_lines: set[int] = set()  # ホワイトボード出現でSEを鳴らすline_entryインデックス
    _wb_summary_items = script.get("whiteboard_summary", [])

    _sec_offset = 0
    for _sec_i, section in enumerate(script.get("sections", [])):
        sec_type = section.get("type", "chapter")
        sec_title = _clean_wb_title(section.get("section", section.get("title", "")))
        wb_items_def = section.get("whiteboard", [])
        sec_lines = section.get("lines", [])
        sec_first = _section_first_line[_sec_i] if _sec_i < len(_section_first_line) else 0

        if sec_type == "summary" and _wb_summary_items:
            # まとめセクション: 全行でホワイトボード表示（出しっぱなし）
            for _li in range(len(sec_lines)):
                _abs_idx = sec_first + _li
                if _abs_idx < len(line_entries):
                    _wb_schedule[_abs_idx] = ("まとめ", list(_wb_summary_items), True)
            if sec_first < len(line_entries):
                _wb_se_lines.add(sec_first)
        elif sec_type in ("chapter",) and wb_items_def:
            # chapter: 魔理沙のセリフ内容とwhiteboard textを照合して表示タイミングを決定
            _WB_HOLD_LINES = 5  # ホワイトボード表示後の維持行数
            accumulated: list[str] = []

            # 各whiteboard itemに対応する魔理沙の行を検出
            trigger_lines: list[int] = []
            used_lines: set[int] = set()

            def _extract_wb_keywords(wb_text: str) -> list[str]:
                """ホワイトボードテキストからマッチ用キーワードを抽出"""
                # 記号・助詞・英字で分割
                tokens = re.split(
                    r'[→←↑↓、。！？\s（）()「」『』＝=：:／/・%％倍本分A-Za-z]+', wb_text
                )
                keywords = []
                for t in tokens:
                    if len(t) >= 2:
                        keywords.append(t)
                # 数字（29, 15, 120など）を個別に抽出
                nums = re.findall(r'\d+', wb_text)
                keywords.extend(nums)
                # カタカナ語を個別に抽出（2文字以上）
                katakana = re.findall(r'[\u30A0-\u30FF]{2,}', wb_text)
                keywords.extend(katakana)
                # 漢字2文字以上の連続を抽出
                kanji = re.findall(r'[\u4E00-\u9FFF]{2,}', wb_text)
                keywords.extend(kanji)
                return list(dict.fromkeys(keywords))  # 重複除去、順序保持

            for wb_item in wb_items_def:
                text_item = wb_item.get("text", "")
                _wb_keywords = _extract_wb_keywords(text_item)
                best_line = -1
                best_score = 0
                # characterフィールドで魔理沙の行を検索（speakerも後方互換で対応）
                for _li, line_data in enumerate(sec_lines):
                    if _li in used_lines:
                        continue
                    _ch = line_data.get("character", line_data.get("speaker", ""))
                    if _ch != "魔理沙":
                        continue
                    line_text = line_data.get("text", "")
                    score = sum(1 for kw in _wb_keywords if kw in line_text)
                    if score > best_score:
                        best_score = score
                        best_line = _li
                if best_line >= 0:
                    trigger_lines.append(best_line)
                    used_lines.add(best_line)
                else:
                    # マッチしない場合: セクションを等分割して配置
                    n_items = len(wb_items_def)
                    idx = len(trigger_lines)
                    fallback = int(len(sec_lines) * (idx + 1) / (n_items + 1))
                    trigger_lines.append(min(fallback, len(sec_lines) - 1))

            # trigger_lineの昇順でソート（項目順序を保持）
            item_order = sorted(range(len(wb_items_def)), key=lambda i: trigger_lines[i])

            # 累積表示: 各項目の表示開始行を記録し、セクション末尾まで維持
            # 一度表示した項目は消えない（順次追加していく）
            _item_show_starts: list[tuple[int, list[str]]] = []  # (show_start, accumulated_snapshot)
            for _wi_idx, _wi in enumerate(item_order):
                wb_item = wb_items_def[_wi]
                trigger = trigger_lines[_wi]
                text_item = wb_item.get("text", "")
                accumulated.append(text_item)
                show_start = trigger + 1  # 話した次の行から表示
                _item_show_starts.append((show_start, list(accumulated)))
                # SE は表示開始行
                _abs_show = sec_first + show_start
                if _abs_show < len(line_entries):
                    _wb_se_lines.add(_abs_show)

            # セクション内の各行に対して、その時点での累積状態を設定
            for _li in range(len(sec_lines)):
                # この行で表示すべき累積項目を決定（最後にshow_startを超えたもの）
                current_items = None
                for _show_start, _snapshot in _item_show_starts:
                    if _li >= _show_start:
                        current_items = _snapshot
                if current_items is not None:
                    _abs_idx = sec_first + _li
                    if _abs_idx < len(line_entries):
                        _wb_schedule[_abs_idx] = (sec_title, list(current_items), False)

    if _wb_schedule:
        print(f"  ホワイトボード: {len(_wb_se_lines)}回出現、{len(_wb_schedule)}フレーム区間で表示")

    # ── ffmpegのパスを取得 ───────────────────────────────────────
    try:
        from imageio_ffmpeg import get_ffmpeg_exe as _get_ffmpeg_exe
        _ffmpeg_bin = _get_ffmpeg_exe()
    except Exception:
        _ffmpeg_bin = shutil.which("ffmpeg") or "ffmpeg"

    # ── ステップ1: 全音声の尺を取得（wave module、省メモリ） ────────
    def _get_wav_duration(p: Path) -> float:
        with wave.open(str(p), "rb") as wf:
            return wf.getnframes() / wf.getframerate()

    _speech_durations: list[float] = [_get_wav_duration(e[3]) for e in line_entries]

    # セリフ間に無音を挿入（余白を持たせて聞きやすくする）
    # キャラ切替: 450ms / 同キャラ連続: 300ms / ハモり後: 800ms
    _SWITCH_SILENCE_SEC = 0.45
    _SAME_CHAR_SILENCE_SEC = 0.30
    _HAMORI_SILENCE_SEC = 0.80

    _INTRO_SILENCE_SEC = 0.50  # 動画冒頭の余白（視聴者が聞き取りやすいように）

    _silence_before: list[float] = []
    _prev_char = None
    for entry in line_entries:
        cur_char = entry[1]
        silence = 0.0
        if _prev_char is not None:
            if _prev_char == "両者":
                silence = _HAMORI_SILENCE_SEC
            elif cur_char != _prev_char:
                silence = _SWITCH_SILENCE_SEC
            else:
                silence = _SAME_CHAR_SILENCE_SEC
        else:
            # 最初の行の前に冒頭余白を挿入
            silence = _INTRO_SILENCE_SEC
        _silence_before.append(silence)
        _prev_char = cur_char

    # ── セクショントランジション用の無音時間を加算 ──
    # トランジション区間ではBGMをフェードアウト→無音→フェードインするので
    # セクション先頭行の前に追加の無音を挿入する
    if _transition_at:
        for _tr_idx in _transition_at:
            if _tr_idx < len(_silence_before):
                _silence_before[_tr_idx] += TRANSITION_TOTAL_SEC

    # ── SE pause情報を先に収集（タイミング算出前に適用する必要がある）──
    _se_dir = Path(__file__).resolve().parent.parent / "assets" / "se"
    _SE_CATEGORY_VOLUME = {
        "surprised": 0.40, "funny": 0.40, "serious": 0.35,
        "positive": 0.30, "thinking": 0.25, "transition": 0.30, "emotional": 0.30,
    }
    _SE_DEFAULT_VOLUME = 0.35
    _se_catalog_path = _se_dir / "se_catalog.json"
    _se_catalog = {}
    if _se_catalog_path.exists():
        _se_catalog = json.loads(_se_catalog_path.read_text(encoding="utf-8"))

    _se_pause_map: dict[int, float] = {}  # line_entryインデックス → pause秒
    _se_pause_count = 0
    _se_line_idx = 0
    for _sec in script.get("sections", []):
        for _line in _sec.get("lines", []):
            se_id = _line.get("se")
            _entry_idx = _script_idx_to_entry.get(_se_line_idx)
            if se_id and _entry_idx is not None:
                se_info = _se_catalog.get(se_id, {})
                se_file = _se_dir / se_info.get("file", "")
                if se_file.exists():
                    pause = _line.get("se_pause")
                    if isinstance(pause, (int, float)) and pause > 0:
                        _se_pause_map[_entry_idx] = float(pause)
                        _se_pause_count += 1
            _se_line_idx += 1

    # SE後の「間」を適用 — 次の行のsilence_beforeに加算（タイミング算出前に反映）
    if _se_pause_map:
        for _pause_idx, _pause_sec in _se_pause_map.items():
            _next_idx = _pause_idx + 1
            if _next_idx < len(_silence_before):
                _silence_before[_next_idx] += _pause_sec

    # タイミング算出（SE pause反映済み）
    _clip_durations = [s + d for s, d in zip(_silence_before, _speech_durations)]
    total_duration = sum(_clip_durations)

    # 各セリフの開始時刻を算出
    _line_start_times: list[float] = []
    _t_acc = 0.0
    for _d in _clip_durations:
        _line_start_times.append(_t_acc)
        _t_acc += _d

    # セクション別の実際の開始時刻を算出（目次タイムスタンプ用）
    _section_timestamps: list[float] = []
    for first_idx in _section_first_line:
        if first_idx < len(_clip_durations):
            ts = sum(_clip_durations[:first_idx])
        else:
            ts = total_duration
        _section_timestamps.append(ts)
    print(f"  セクション別タイムスタンプ: {[f'{t:.0f}s' for t in _section_timestamps]}")

    # ── ステップ2: ffmpegで音声トラック（セリフ+BGM+SE）を生成（省メモリ）──
    # SE配置情報を収集（正確な_line_start_timesを使用）
    _se_entries: list[tuple[Path, float, float]] = []  # (file_path, start_sec, volume)
    _se_combo_count = 0
    _se_line_idx = 0
    for _sec in script.get("sections", []):
        for _line in _sec.get("lines", []):
            se_id = _line.get("se")
            _entry_idx = _script_idx_to_entry.get(_se_line_idx)
            if se_id and _entry_idx is not None:
                se_info = _se_catalog.get(se_id, {})
                se_file = _se_dir / se_info.get("file", "")
                if se_file.exists():
                    cat = se_info.get("category", "")
                    vol = se_info.get("volume", _SE_CATEGORY_VOLUME.get(cat, _SE_DEFAULT_VOLUME))
                    offset = _line.get("se_offset", "start")
                    base_time = _line_start_times[_entry_idx]
                    if offset == "reaction":
                        se_start = base_time + _silence_before[_entry_idx] + 0.3
                    elif offset == "end":
                        se_start = base_time + _clip_durations[_entry_idx] - 0.5
                    else:
                        se_start = base_time
                    _se_entries.append((se_file, max(0, se_start), vol))
                    # 連鎖SE（combo）
                    combo_id = _line.get("se_combo")
                    if combo_id and combo_id in _se_catalog:
                        combo_info = _se_catalog[combo_id]
                        combo_file = _se_dir / combo_info.get("file", "")
                        combo_delay = _line.get("se_combo_delay", 1.0)
                        if combo_file.exists():
                            combo_cat = combo_info.get("category", "")
                            combo_vol = combo_info.get("volume",
                                _SE_CATEGORY_VOLUME.get(combo_cat, _SE_DEFAULT_VOLUME))
                            _se_entries.append((combo_file, max(0, se_start + combo_delay), combo_vol))
                            _se_combo_count += 1
            _se_line_idx += 1
    # ── ホワイトボード出現SE ──
    _wb_se_file = _se_dir / "transition" / "sword-gesture3.mp3"
    _wb_se_volume = 0.25
    _wb_se_count = 0
    if _wb_se_lines and _wb_se_file.exists():
        for _wb_line_idx in _wb_se_lines:
            if _wb_line_idx < len(_line_start_times):
                _se_entries.append((_wb_se_file, _line_start_times[_wb_line_idx], _wb_se_volume))
                _wb_se_count += 1
        if _wb_se_count:
            print(f"  ホワイトボードSE({_wb_se_count}件)を追加しました")

    # ── セクショントランジションSE ──
    _tr_se_count = 0
    if _transition_at:
        _tr_se_wipe = _se_dir / "transition" / "sceneswitch1.mp3"
        _tr_se_title = _se_dir / "transition" / "title1.mp3"
        _tr_se_wipe_vol = 0.35
        _tr_se_title_vol = 0.30
        for _tr_idx in _transition_at:
            if _tr_idx < len(_line_start_times):
                # トランジション区間の開始時刻 = セリフ開始時刻（silenceの先頭）
                _tr_base = _line_start_times[_tr_idx]
                # ワイプSE: トランジション開始0.3秒後
                if _tr_se_wipe.exists():
                    _se_entries.append((_tr_se_wipe, max(0, _tr_base + 0.3), _tr_se_wipe_vol))
                    _tr_se_count += 1
                # タイトル表示SE: ワイプ後（0.7秒後）
                if _tr_se_title.exists():
                    _se_entries.append((_tr_se_title, max(0, _tr_base + TRANSITION_WIPE_SEC + 0.3),
                                       _tr_se_title_vol))
                    _tr_se_count += 1
        if _tr_se_count:
            print(f"  トランジションSE({_tr_se_count}件)を追加しました")

    if _se_entries:
        _extras = []
        if _se_combo_count:
            _extras.append(f"combo {_se_combo_count}件")
        if _se_pause_count:
            _extras.append(f"pause {_se_pause_count}件")
        if _tr_se_count:
            _extras.append(f"transition {_tr_se_count}件")
        _extra_str = f" ({', '.join(_extras)})" if _extras else ""
        print(f"  SE({len(_se_entries)}件)を合成します{_extra_str}")

    # ── BGM選択 ──
    sections = script.get("sections", [])
    last_type = sections[-1].get("type", "") if sections else ""
    has_ending = last_type in ("summary", "outro", "conclusion", "ending", "まとめ")

    # bgm_specs: [(path, start_sec, duration, volume, fadein, fadeout), ...]
    _bgm_specs: list[tuple[Path, float, float, float, float, float]] = []
    _used_bgm_paths: list[Path] = []

    # トランジションがある場合: セクション境界でBGMを分割（フェードアウト→無音→フェードイン）
    _TR_BGM_FADEOUT = 0.5    # トランジション前のBGMフェードアウト
    _TR_BGM_FADEIN  = 0.5    # トランジション後のBGMフェードイン

    if _transition_at:
        # BGM分割点を収集（トランジション位置の時刻）
        _bgm_split_times: list[float] = []
        for _tr_idx in sorted(_transition_at.keys()):
            if _tr_idx < len(_line_start_times):
                _bgm_split_times.append(_line_start_times[_tr_idx])

        main_bgm_path = _select_bgm(category="main")
        ending_bgm_path = _select_bgm(category="ending") if has_ending else None
        # エンディング切り替え時刻
        _ending_t = None
        if has_ending and len(line_entries) >= 6:
            last_sec_start_idx = min(
                sum(len(s.get("lines", [])) for s in sections[:-1]),
                len(line_entries) - 1,
            )
            _ending_t = sum(_clip_durations[:last_sec_start_idx])

        # 分割点でBGMセグメントを生成
        _seg_starts = [0.0] + _bgm_split_times
        _seg_ends = _bgm_split_times + [total_duration]
        for _si in range(len(_seg_starts)):
            _s = _seg_starts[_si]
            _e = _seg_ends[_si]
            # トランジション無音区間をスキップ: セグメント開始をトランジション後にずらす
            if _si > 0:
                _s += TRANSITION_TOTAL_SEC  # トランジション区間後に開始
            _dur = _e - _s
            if _dur <= 0:
                continue
            # エンディングBGMの切り替え判定
            if _ending_t is not None and _s >= _ending_t and ending_bgm_path:
                _bgm_path = ending_bgm_path
            else:
                _bgm_path = main_bgm_path
            if _bgm_path:
                _fi = _TR_BGM_FADEIN if _si > 0 else BGM_FADEIN
                _fo = _TR_BGM_FADEOUT if _si < len(_seg_starts) - 1 else BGM_FADEOUT
                _bgm_specs.append((_bgm_path, _s, _dur, BGM_VOLUME, _fi, _fo))
        if main_bgm_path:
            _used_bgm_paths.append(main_bgm_path)
        if ending_bgm_path and ending_bgm_path != main_bgm_path:
            _used_bgm_paths.append(ending_bgm_path)
        if _bgm_specs:
            print(f"  BGMを合成します（{len(_bgm_specs)}セグメントに分割、トランジション区間で無音）")
        else:
            print("  BGMファイルが見つかりません（assets/bgm/ に配置してください）")
    elif has_ending and len(line_entries) >= 6:
        last_sec_start_idx = min(
            sum(len(s.get("lines", [])) for s in sections[:-1]),
            len(line_entries) - 1,
        )
        transition_t = sum(_clip_durations[:last_sec_start_idx])
        main_bgm_path = _select_bgm(category="main")
        ending_bgm_path = _select_bgm(category="ending")
        if main_bgm_path:
            _bgm_specs.append((main_bgm_path, 0, transition_t, BGM_VOLUME, BGM_FADEIN, BGM_FADEOUT))
            _used_bgm_paths.append(main_bgm_path)
        if ending_bgm_path:
            _bgm_specs.append((ending_bgm_path, transition_t, total_duration - transition_t,
                               BGM_VOLUME, BGM_FADEIN, BGM_FADEOUT))
            if ending_bgm_path != main_bgm_path:
                _used_bgm_paths.append(ending_bgm_path)
        if _bgm_specs:
            print(f"  BGMを合成します（本編BGM + エンディングBGM 切り替え @ {transition_t:.1f}s）")
        else:
            print("  BGMファイルが見つかりません（assets/bgm/ に配置してください）")
    else:
        _main_bgm_path = _select_bgm(category="main")
        if _main_bgm_path:
            _bgm_specs.append((_main_bgm_path, 0, total_duration, BGM_VOLUME, BGM_FADEIN, BGM_FADEOUT))
            _used_bgm_paths = [_main_bgm_path]
            print("  BGMを合成します（本編BGM）")
        else:
            print("  BGMファイルが見つかりません（assets/bgm/ に配置してください）")

    # ── ステップ2a: セリフWAVを事前結合（Windows コマンドライン長制限回避） ──
    import time as _time_mod
    _ts = int(_time_mod.time())
    _temp_speech = output_path.with_suffix(f"._{_ts}_temp_speech.wav")
    _speech_filter = output_path.with_suffix("._speech_filter.txt")

    # セリフ用filter_complex: 各WAVをリサンプル→無音挿入→concat
    # 入力数が多くてもfilterはファイル経由なので問題ない
    # 入力リストもファイル経由で渡す（-i @listは非対応なのでバッチ処理）
    _speech_filter_lines: list[str] = []
    _speech_concat_labels: list[str] = []
    _speech_silence_idx = 0

    # concat demuxer用ファイルリストを生成（コマンドラインに-iを並べない）
    _concat_list = output_path.with_suffix("._concat_list.txt")
    _resampled_dir = output_path.parent / f"._{_ts}_resampled"
    _resampled_dir.mkdir(exist_ok=True)

    # 各セリフWAVを44100Hz/stereo/s16にリサンプルし、無音と交互にリスト化
    _concat_entries: list[str] = []
    _silence_cache: dict[str, Path] = {}  # duration -> silence wav path

    print(f"  セリフ{len(line_entries)}本を事前結合しています...")
    for _i, _entry in enumerate(line_entries):
        # 無音挿入
        if _silence_before[_i] > 0:
            _sdur = _silence_before[_i]
            _sdur_key = f"{_sdur:.4f}"
            if _sdur_key not in _silence_cache:
                _sil_path = _resampled_dir / f"silence_{_sdur_key}.wav"
                subprocess.run(
                    [_ffmpeg_bin, "-y", "-f", "lavfi", "-i",
                     f"anullsrc=r=44100:cl=stereo",
                     "-t", _sdur_key, "-ar", "44100", "-ac", "2",
                     "-sample_fmt", "s16", str(_sil_path)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30
                )
                _silence_cache[_sdur_key] = _sil_path
            _concat_entries.append(
                f"file '{str(_silence_cache[_sdur_key]).replace(chr(92), '/')}'"
            )

        # セリフWAVをリサンプル
        _rs_path = _resampled_dir / f"rs_{_i:04d}.wav"
        subprocess.run(
            [_ffmpeg_bin, "-y", "-i", str(_entry[3]),
             "-ar", "44100", "-ac", "2", "-sample_fmt", "s16",
             str(_rs_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30
        )
        _concat_entries.append(f"file '{str(_rs_path).replace(chr(92), '/')}'")

    # concat demuxerリストを書き出し
    _concat_list.write_text("\n".join(_concat_entries), encoding="utf-8")

    # ffmpeg concat demuxerでセリフを1ファイルに結合
    _speech_cmd = [
        _ffmpeg_bin, "-y", "-f", "concat", "-safe", "0",
        "-i", str(_concat_list),
        "-ar", "44100", "-ac", "2",
        str(_temp_speech),
    ]
    _speech_log = output_path.with_suffix("._speech_concat.log")
    with open(_speech_log, "w", encoding="utf-8") as _slf:
        try:
            _speech_result = subprocess.run(
                _speech_cmd, stderr=_slf, stdout=subprocess.DEVNULL, timeout=300
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffmpegセリフ結合タイムアウト（300秒超過）")

    if _speech_result.returncode != 0:
        _err_tail = ""
        try:
            _err_tail = _speech_log.read_text(encoding="utf-8")[-500:]
        except Exception:
            pass
        raise RuntimeError(f"ffmpegセリフ結合失敗 (code={_speech_result.returncode}): {_err_tail}")

    # 一時ファイル削除（リトライ付き）
    from skills._common import _safe_unlink, _safe_rmtree
    _safe_unlink(_concat_list)
    _safe_unlink(_speech_log)
    _safe_rmtree(_resampled_dir)
    print("  セリフ結合完了")

    # ── ステップ2b: speech + BGM + SE を合成 ──
    _temp_audio = output_path.with_suffix(f"._{_ts}_temp_audio.wav")
    _filter_script = output_path.with_suffix("._filter.txt")
    _input_args: list[str] = []
    _filter_lines: list[str] = []
    _input_idx = 0

    # 入力0: 事前結合済みセリフ
    _input_args.extend(["-i", str(_temp_speech)])
    _filter_lines.append(f"[0]acopy[speech]")
    _input_idx = 1

    # BGM入力
    _bgm_labels: list[str] = []
    for _bi, (_bgm_path, _bgm_start, _bgm_dur, _bgm_vol, _bgm_fi, _bgm_fo) in enumerate(_bgm_specs):
        _input_args.extend(["-stream_loop", "-1", "-i", str(_bgm_path)])
        _fo_start = max(0, _bgm_dur - _bgm_fo)
        _blabel = f"bgm{_bi}"
        _delay_ms = int(_bgm_start * 1000)
        _af = (f"[{_input_idx}]atrim=duration={_bgm_dur:.3f},"
               f"volume={_bgm_vol},"
               f"afade=t=in:d={_bgm_fi},"
               f"afade=t=out:st={_fo_start:.3f}:d={_bgm_fo},"
               f"aresample=44100,aformat=sample_fmts=s16:channel_layouts=stereo")
        if _delay_ms > 0:
            _af += f",adelay={_delay_ms}|{_delay_ms}"
        _af += f"[{_blabel}]"
        _filter_lines.append(_af)
        _bgm_labels.append(f"[{_blabel}]")
        _input_idx += 1

    # SE入力（amovieでfilter内から直接読み込み、-iを使わない）
    # これによりコマンドライン長を大幅に削減（WinError 206対策）
    _se_labels: list[str] = []
    for _si, (_se_path, _se_start, _se_vol) in enumerate(_se_entries):
        _delay_ms = int(_se_start * 1000)
        _se_lbl = f"se{_si}"
        # amovieのパスはfilter_complex_script経由なのでコマンドライン長に影響しない
        # filtergraph構文文字をエスケープ（: , ; [ ] ' とバックスラッシュ）
        _escaped = str(_se_path).replace("\\", "/")
        for _ch in (":", "'", ",", ";", "[", "]"):
            _escaped = _escaped.replace(_ch, f"\\{_ch}")
        _filter_lines.append(
            f"amovie={_escaped},aresample=44100,aformat=sample_fmts=s16:channel_layouts=stereo,"
            f"volume={_se_vol},adelay={_delay_ms}|{_delay_ms}[{_se_lbl}]"
        )
        _se_labels.append(f"[{_se_lbl}]")

    # 全トラックをamixで合成（normalize=0で入力数による音量低下を防止）
    _all_mix = ["[speech]"] + _bgm_labels + _se_labels
    _n_mix = len(_all_mix)
    if _n_mix == 1:
        # セリフのみ（BGM/SEなし）
        _filter_lines.append("[speech]acopy[out]")
    else:
        # normalize=0: 入力数が増えても音量を下げない（ffmpeg 7.0+対応）
        # weights=全入力1で各トラックの音量をそのまま維持
        _weights = " ".join(["1"] * _n_mix)
        _filter_lines.append(
            f"{''.join(_all_mix)}amix=inputs={_n_mix}:duration=first:dropout_transition=0:normalize=0:weights={_weights}[out]"
        )

    # filterをファイルに書き出し（コマンドライン長制限回避）
    _filter_script.write_text(";\n".join(_filter_lines), encoding="utf-8")

    _mix_cmd = [
        _ffmpeg_bin, "-y",
    ] + _input_args + [
        "-filter_complex_script", str(_filter_script),
        "-map", "[out]",
        "-ar", "44100", "-ac", "2",
        str(_temp_audio),
    ]
    # コマンド長ガード（Windows CreateProcess上限 32768文字）
    import subprocess as _sp_check
    _cmd_len = len(_sp_check.list2cmdline(_mix_cmd))
    if _cmd_len > 28000:
        print(f"  [警告] ffmpegコマンド長 {_cmd_len} 文字（上限32768）")
    print(f"  ffmpegで音声を合成しています（入力{_input_idx}トラック, SE={len(_se_entries)}件amovie）...")
    _mix_log = output_path.with_suffix("._audio_mix.log")
    with open(_mix_log, "w", encoding="utf-8") as _mlf:
        try:
            _mix_result = subprocess.run(
                _mix_cmd, stderr=_mlf, stdout=subprocess.DEVNULL, timeout=300
            )
        except subprocess.TimeoutExpired:
            raise RuntimeError("ffmpeg音声合成タイムアウト（300秒超過）")

    if _mix_result.returncode != 0:
        _err_tail = ""
        try:
            _err_tail = _mix_log.read_text(encoding="utf-8")[-500:]
        except Exception:
            pass
        # filter_scriptとログを残してデバッグ可能にする
        raise RuntimeError(f"ffmpeg音声合成失敗 (code={_mix_result.returncode}): {_err_tail}")
    # 成功時のみ一時ファイルを削除（リトライ付き）
    _safe_unlink(_filter_script)
    _safe_unlink(_mix_log)
    _safe_unlink(_temp_speech)
    print("  音声合成完了")

    # ── ステップ3: ビデオフレームをffmpegにストリーミング ──────────
    # パーツ合成方式: 毎フレーム合成（ベースフレームはキャッシュ、キャラのみ差し替え）
    print(f"  {len(line_entries)} クリップをストリーミングエンコードしています...")
    W, H = RESOLUTION
    # タイムスタンプ付きで毎回ユニーク名にする（前回のロック回避）
    import time as _time_mod
    _ts = int(_time_mod.time())
    _temp_video = output_path.with_suffix(f"._{_ts}_temp_video.mp4")
    _mouth_iv = 1.0 / MOUTH_ANIM_FPS

    _ffcmd = [
        _ffmpeg_bin, "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{W}x{H}", "-pix_fmt", "rgb24", "-r", str(FPS),
        "-i", "pipe:0",
        "-an",
        "-vcodec", "libx264",
        "-preset", ENCODE_PRESET,
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        str(_temp_video),
    ]
    _ffmpeg_log = output_path.with_suffix(".ffmpeg.log")
    _ff_logfile = open(_ffmpeg_log, "w", encoding="utf-8")
    _proc = subprocess.Popen(_ffcmd, stdin=subprocess.PIPE, stderr=_ff_logfile)

    # 瞬きスケジュールをキャラごとに2種類生成
    # 話者用: 通常間隔(3-7秒)
    # 聞き手用: やや短め(2.5-5秒) + 15%で二連続瞬き（聞いている人の自然な瞬き）
    _blink_speaking: dict[str, list[float]] = {}
    _blink_listening: dict[str, list[float]] = {}
    for _cname in CHAR_CONFIG:
        _blink_speaking[_cname] = _generate_blink_schedule(total_duration)
        _blink_listening[_cname] = _generate_blink_schedule(
            total_duration, interval_min=2.5, interval_max=5.0,
            double_blink_chance=0.15)
    print(f"  瞬きスケジュール生成済み（話者/聞き手で独立）")

    # 累積フレーム数で管理することでクリップごとの切り捨て誤差の積み上がりを防ぐ
    _frames_written = 0
    _total_frames_enc = 0
    _time_acc = 0.0
    _bob_period = max(1, int(FPS / BOB_FREQ))

    _prev_text = ""  # 前の行の字幕（無音期間中に表示）
    _prev_char = ""  # 前の行の話者
    _prev_emotion = "normal"
    _prev_ira_path = None  # 前の行のいらすとや画像（無音期間中に維持）

    for _i, (_entry, _dur) in enumerate(zip(line_entries, _clip_durations)):
        _, _char, _text, _audio_path, _ira_path, _emotion = _entry
        _sil = _silence_before[_i]    # この行の前の無音秒数
        _spk = _speech_durations[_i]  # 音声のみの尺

        # キャッシュサイズ制限（メモリ節約: 最大64エントリ超過で古い方から削除）
        if len(_kai_char_cache) > 64:
            for _old_key in list(_kai_char_cache)[:32]:
                del _kai_char_cache[_old_key]

        # 感情変化シーケンス（長いセリフは途中で表情が変わる）— 発話部分の尺で計算
        # 「両者」(greeting行)は独自の感情選択を使うためmid-switchスキップ
        if _char == "両者":
            _emotion_seq = [(0.0, _emotion)]
        else:
            _emotion_seq = _get_emotion_sequence(_emotion, _spk, char_name=_char)

        # greeting行（両者ハモり）は各キャラ独立で笑顔系感情をランダム選択
        _GREETING_EMOTIONS = ["happy", "excited", "relieved"]
        _greeting_emo: dict[str, str] = {}
        if _char == "両者":
            for _cname in CHAR_CONFIG:
                _greeting_emo[_cname] = random.choice(_GREETING_EMOTIONS)

        # 聞き手のリアクション感情
        _listener_emo = _LISTENER_REACTION.get(_emotion, "normal")

        # このセリフの絶対開始時刻
        _line_start = _time_acc

        # 累積時間からフレーム数を逆算
        _time_acc += _dur
        _target_frames = round(_time_acc * FPS)
        _n_frames = max(1, _target_frames - _frames_written)
        _frames_written = _target_frames

        # トランジション情報（この行がトランジション対象か）
        _tr_info = _transition_at.get(_i)  # (sec_number, sec_title, sec_type) or None
        _tr_wipe_frames = round(TRANSITION_WIPE_SEC * FPS)   # ワイプフレーム数
        _tr_card_frames = round(TRANSITION_CARD_SEC * FPS)   # 表紙フレーム数
        _tr_total_frames = round(TRANSITION_TOTAL_SEC * FPS)  # トランジション全体フレーム数

        for _fi in range(_n_frames):
            _t = _fi / FPS
            _abs_t = _line_start + _t
            _in_silence = _t < _sil  # 無音期間中か？
            _speech_t = _t - _sil    # 発話開始からの経過時間

            # ── セクショントランジション: 無音期間の先頭部分をトランジション画面に差し替え ──
            if _tr_info and _in_silence and _t < TRANSITION_TOTAL_SEC:
                _tr_num, _tr_title, _tr_type = _tr_info
                _tr_t = _t  # トランジション内での経過時間
                if _tr_t < TRANSITION_WIPE_SEC:
                    # ワイプアニメーション
                    _progress = _tr_t / TRANSITION_WIPE_SEC
                    _frame_np = _render_transition_frame(_progress)
                else:
                    # セクション表紙
                    _tc_bg = _title_card_images.get(_i)
                    _frame_np = _render_title_card(
                        _tr_num, _tr_title, _video_theme, _tc_bg)
                try:
                    _proc.stdin.write(_frame_np.tobytes())
                except (BrokenPipeError, OSError) as _pipe_err:
                    _proc.wait()
                    _ff_logfile.close()
                    _ff_stderr = _ffmpeg_log.read_text(encoding="utf-8", errors="replace") if _ffmpeg_log.exists() else ""
                    raise RuntimeError(
                        f"ffmpegパイプが切断されました (frame {_total_frames_enc}): {_pipe_err}\n"
                        f"ffmpeg stderr:\n{_ff_stderr[-2000:]}"
                    ) from _pipe_err
                _total_frames_enc += 1
                if _total_frames_enc % 1500 == 0:
                    gc.collect()
                continue  # 通常のフレーム合成をスキップ

            # ボブオフセット（絶対時刻ベースで行をまたいでも連続的に揺れる）
            _bob_y = round(BOB_AMP * math.sin(2 * math.pi * BOB_FREQ * _abs_t))

            # ── 口パク: 無音期間中は閉じ口、発話中のみアニメーション ──
            if _in_silence or _speech_t < 0.08 or _speech_t > _spk - 0.08:
                _mouth_open = 0
            else:
                _mouth_open = int(_speech_t / _mouth_iv) % 6

            # ── 字幕: 無音期間中は前の行の字幕を維持（最初の行は空） ──
            if _in_silence:
                _show_text = _prev_text if _i > 0 else ""
                _show_char = _prev_char if _i > 0 else _char
            else:
                _show_text = _text
                _show_char = _char

            # ── 話者感情: 無音期間中は前の感情を維持、発話中は変化シーケンス ──
            if _in_silence:
                _cur_emotion = _prev_emotion if _i > 0 else _emotion
            else:
                _cur_emotion = _emotion
                for (_ratio, _em) in reversed(_emotion_seq):
                    if _spk > 0 and _speech_t / _spk >= _ratio:
                        _cur_emotion = _em
                        break

            # 瞬き状態（話者/聞き手で別スケジュール）
            _blink_eyes: dict[str, "str | None"] = {}
            for _cname in CHAR_CONFIG:
                _is_speaker = (_cname == _char) or (_char == "両者")
                _sched = _blink_speaking[_cname] if _is_speaker else _blink_listening[_cname]
                _blink_eyes[_cname] = _get_blink_eye(_cname, _abs_t, _sched)

            # ホワイトボード判定（言い終わった直後＝次の行の無音区間で即表示）
            _wb_info = _wb_schedule.get(_i)
            _wb_img_cur = None
            if _wb_info:
                _wb_title, _wb_items, _wb_is_summary = _wb_info
                _wb_img_cur = _render_whiteboard(_wb_title, _wb_items, is_summary=_wb_is_summary)
            _wb_img = _wb_img_cur

            # いらすとや画像: 無音中は前の行の画像を維持（字幕と同期）
            _show_ira = (_prev_ira_path if _in_silence and _i > 0 else _ira_path)
            # フレーム合成（ホワイトボード表示中はいらすとや非表示）
            _frame_np = compose_frame(
                _show_char, _show_text, bg, kai_sprites, subtitle_bar_color,
                _show_ira if _wb_img is None else None,
                emotion=_cur_emotion, mouth_open=_mouth_open,
                bob_offset=_bob_y, blink_eyes=_blink_eyes,
                listener_emotion=_listener_emo,
                per_char_emotion=_greeting_emo if _greeting_emo else None,
                whiteboard_img=_wb_img)

            # アニメーションオーバーレイを合成（発話開始から1.5秒だけ表示、ボブ連動）
            if not _in_silence and _speech_t < 1.5:
                _anim_step = (_fi // 2) % _ANIM_CYCLE_FRAMES
                _ov = _get_anim_overlay(_cur_emotion, _char, _anim_step)
                if _ov is not None:
                    _ov_arr, _ox, _ov_y = _ov
                    _frame_np = _apply_anim_overlay(_frame_np, _ov_arr, _ox, _ov_y + _bob_y)

            try:
                _proc.stdin.write(_frame_np.tobytes())
            except (BrokenPipeError, OSError) as _pipe_err:
                _proc.wait()
                _ff_logfile.close()
                _ff_stderr = _ffmpeg_log.read_text(encoding="utf-8", errors="replace") if _ffmpeg_log.exists() else ""
                raise RuntimeError(
                    f"ffmpegパイプが切断されました (frame {_total_frames_enc}): {_pipe_err}\n"
                    f"ffmpeg stderr:\n{_ff_stderr[-2000:]}"
                ) from _pipe_err
            _total_frames_enc += 1

            # 1500フレームごとにGC実行 + メモリチェック + 進捗表示
            if _total_frames_enc % 1500 == 0:
                gc.collect()
                _total_target = round(total_duration * FPS)
                _pct = _total_frames_enc / max(1, _total_target) * 100
                # メモリ残量チェック（1GB未満で緊急キャッシュクリア）
                try:
                    _mem_avail = 9999
                    if sys.platform == "win32":
                        import ctypes as _ct
                        class _MSEX(_ct.Structure):
                            _fields_ = [("dwLength",_ct.c_ulong),("dwMemoryLoad",_ct.c_ulong),
                                        ("ullTotalPhys",_ct.c_ulonglong),("ullAvailPhys",_ct.c_ulonglong),
                                        ("ullTotalPageFile",_ct.c_ulonglong),("ullAvailPageFile",_ct.c_ulonglong),
                                        ("ullTotalVirtual",_ct.c_ulonglong),("ullAvailVirtual",_ct.c_ulonglong),
                                        ("ullAvailExtendedVirtual",_ct.c_ulonglong)]
                        _ms = _MSEX(); _ms.dwLength = _ct.sizeof(_ms)
                        _ct.windll.kernel32.GlobalMemoryStatusEx(_ct.byref(_ms))
                        _mem_avail = int(_ms.ullAvailPhys // (1024 * 1024))
                    else:
                        # WSL: /proc/meminfo でWSL内空きを確認
                        with open("/proc/meminfo") as _mf:
                            for _ml in _mf:
                                if _ml.startswith("MemAvailable:"):
                                    _mem_avail = int(_ml.split()[1]) // 1024
                                    break
                        # 10000フレームごとにWindowsホスト側の空きも確認
                        if _total_frames_enc % 10000 == 0:
                            try:
                                _ps_out = subprocess.run(
                                    ["powershell.exe", "-NoProfile", "-Command",
                                     "(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory"],
                                    capture_output=True, text=True, timeout=5
                                )
                                if _ps_out.returncode == 0 and _ps_out.stdout.strip().isdigit():
                                    _win_avail = int(_ps_out.stdout.strip()) // 1024
                                    _mem_avail = min(_mem_avail, _win_avail)
                            except Exception:
                                pass
                    if _mem_avail < 2048:
                        _kai_char_cache.clear()
                        _wb_cache.clear()
                        _irasutoya_cache.clear()
                        gc.collect()
                        print(f"  [メモリ警告] 空き{_mem_avail}MB(<2GB) → キャッシュ全クリア")
                except Exception:
                    pass
                print(f"  エンコード進捗: {_total_frames_enc}/{_total_target}フレーム ({_pct:.0f}%)")

        # 次の行のために今の状態を保存
        _prev_text = _text
        _prev_char = _char
        _prev_emotion = _cur_emotion
        _prev_ira_path = _ira_path

    _proc.stdin.close()
    _proc.wait()
    _ff_logfile.close()
    if _proc.returncode != 0:
        _ff_stderr = _ffmpeg_log.read_text(encoding="utf-8", errors="replace") if _ffmpeg_log.exists() else ""
        raise RuntimeError(f"ffmpegエンコード失敗 (code {_proc.returncode}):\n{_ff_stderr[-2000:]}")
    print(f"  エンコード完了: {_total_frames_enc}フレーム")

    # ── ステップ4: 映像と音声をmux して最終MP4を生成 ──────────────
    # mux前にGCでメモリを解放（エンコードで使ったキャッシュを回収）
    _wb_cache.clear()
    _irasutoya_cache.clear()
    _kai_char_cache.clear()
    _overlay_cache.clear()
    _base_frame_cache[0] = None
    _base_frame_cache[1] = None
    gc.collect()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  MP4を書き出しています → {output_path}")
    _mux_cmd = [
        _ffmpeg_bin, "-y",
        "-i", str(_temp_video),
        "-i", str(_temp_audio),
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(output_path),
    ]
    _mux_log = output_path.with_suffix(".mux.log")
    with open(_mux_log, "w", encoding="utf-8") as _mux_logfile:
        _mux_result = subprocess.run(_mux_cmd, stderr=_mux_logfile)
    if _mux_result.returncode != 0:
        _mux_stderr = _mux_log.read_text(encoding="utf-8", errors="replace") if _mux_log.exists() else ""
        # tempファイルは残す（再試行可能にする）
        raise RuntimeError(
            f"音声mux失敗 (code {_mux_result.returncode}):\n{_mux_stderr[-2000:]}"
        )
    # 成功時のみtempファイルを削除（リトライ付き、ロック時はorphan cleanupに任せる）
    for _tf in [_temp_video, _temp_audio, _mux_log]:
        _safe_unlink(_tf)

    print(f"完了！動画を保存しました: {output_path}")
    return output_path, _used_bgm_paths, _section_timestamps, total_duration


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 3:
        print("使い方: python video_builder.py <台本JSON> <音声フォルダ>")
        print("例: python video_builder.py ../output/20260322_test.json ../output/20260322_test/")
        sys.exit(1)

    script_path = Path(sys.argv[1])
    audio_dir   = Path(sys.argv[2])
    output_path = script_path.with_suffix(".mp4")

    script = json.loads(script_path.read_text(encoding="utf-8"))
    build_video(script, audio_dir, output_path)
