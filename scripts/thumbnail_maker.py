# サムネイル自動生成モジュール（1280×720 JPG）
#
# ゆっくり健康ラボ v2 — 定番デザイン完全再現
#
# レイアウト:
#   背景      = テーマ別カラフルグラデーション（集中線は廃止）
#   上段      = タイトル 1〜2行（白 or 黄色文字 + 黒縁取り）
#   中央      = いらすとや画像（白背景除去済み）
#   下段      = ミステリーテキスト（●●を赤文字で描画）
#   左下      = 魔理沙饅頭
#   右下      = 霊夢饅頭
#
# バリアント:
#   A: カラフルグラデ + 通常テキスト + いらすとや + 饅頭（スタンダード）
#   B: やや暗めグラデ + ●●伏せ字 + 吹き出し（ミステリー強調）
#   C: ツートーン背景 + 超特大テキスト（インパクト重視）

from __future__ import annotations

import math
import os
import random
import re
import sys
from pathlib import Path

from font_utils import load_font
from PIL import Image, ImageDraw, ImageEnhance

RESOLUTION = (1280, 720)

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets"
CHAR_DIR   = ASSETS_DIR / "characters"
IRA_DIR    = ASSETS_DIR / "irasutoya"

# ── テーマ別カラーパレット（集中線の代わりの定番カラー）───────────────────────
_THEME_PALETTES: dict[str, dict] = {
    "food": {
        "top":         (80, 200, 50),
        "bot":         (30, 140, 10),
        "dark_top":    (40, 130, 20),
        "dark_bot":    (15, 80,  5),
        # バリアントC: 食欲・活力を表すオレンジ。〇〇は黄色（高コントラスト）
        "twotone_top": (210, 90, 10),
        "C_mask":      (255, 245, 20),   # 黄色: オレンジ背景で最も映える
    },
    "sleep": {
        "top":         (40, 50, 160),
        "bot":         (90, 30, 145),
        "dark_top":    (25, 30, 110),
        "dark_bot":    (60, 15, 95),
        # バリアントC: 深夜感・落ち着きの深い青。〇〇はエメラルド（青との補色）
        "twotone_top": (25, 45, 165),
        "C_mask":      (20, 220, 160),   # エメラルド: 深青背景で清潔感を演出
    },
    "exercise": {
        "top":         (0, 175, 225),
        "bot":         (0, 95, 195),
        "dark_top":    (0, 110, 155),
        "dark_bot":    (0, 65, 135),
        # バリアントC: エネルギッシュな緑。〇〇は黄色（躍動感）
        "twotone_top": (15, 160, 70),
        "C_mask":      (255, 245, 20),   # 黄色: 緑背景でスポーティな印象
    },
    "dental": {
        "top":         (0, 175, 205),
        "bot":         (0, 110, 160),
        "dark_top":    (0, 115, 145),
        "dark_bot":    (0, 70, 115),
        # バリアントC: 清潔感・爽やかさのティール。〇〇は白（清潔感の極み）
        "twotone_top": (0, 150, 185),
        "C_mask":      (255, 255, 255),  # 白: ティール背景で清潔感を強調
    },
    "mental": {
        "top":         (165, 95, 215),
        "bot":         (100, 55, 185),
        "dark_top":    (110, 55, 165),
        "dark_bot":    (70, 25, 130),
        # バリアントC: 安心・癒しの落ち着いた紫。〇〇はゴールド（高貴・特別感）
        "twotone_top": (100, 50, 190),
        "C_mask":      (255, 215, 60),   # ゴールド: 紫背景で品格を演出
    },
    "warning": {
        "top":         (230, 40, 40),
        "bot":         (185, 80, 0),
        "dark_top":    (165, 20, 20),
        "dark_bot":    (130, 55, 0),
        # バリアントC: 危険・緊急感の赤。〇〇は白（最高コントラスト・緊急感）
        "twotone_top": (200, 20, 20),
        "C_mask":      (255, 255, 255),  # 白: 赤背景で最も目立つ・警告感
    },
    "general": {
        "top":         (60, 190, 80),
        "bot":         (25, 130, 45),
        "dark_top":    (30, 125, 40),
        "dark_bot":    (10, 75, 20),
        # バリアントC: 万能の落ち着いたスカイブルー。〇〇はエメラルド
        "twotone_top": (35, 115, 200),
        "C_mask":      (20, 220, 160),   # エメラルド: 青系背景の汎用
    },
}

# テーマ別の上段テキスト色
_THEME_LINE1_COLORS: dict[str, tuple] = {
    "food":     (255, 240, 60),   # 黄色
    "sleep":    (200, 185, 255),  # ラベンダー
    "exercise": (255, 255, 255),  # 白
    "dental":   (220, 255, 255),  # 水色系白
    "mental":   (255, 215, 255),  # ピンク系
    "warning":  (255, 255, 60),   # 黄色
    "general":  (255, 240, 60),   # 黄色
}

# バッジワード
_BADGE_WORDS_RED    = ["危険", "禁止", "注意", "ヤバい", "やばい", "警告", "有毒", "緊急"]
_BADGE_WORDS_YELLOW = ["衝撃", "必見", "判明", "驚愕", "意外", "秘密", "実は"]

# ── 2ch風リアクションコメント（第三者・視聴者目線）────────────────────────────
# ルール:
#   ✅ 視聴者が動画を見てつぶやくコメント（好奇心・驚き・共感・不安）
#   ❌ 製作者目線のコメント（「〇〇の人へ」「今すぐ試して」等）
#   ❌ 2個の同時表示で重複しない（random.sampleで保証済み）
_REACTION_POOL: dict[str, list[str]] = {
    "food":     [
        "なにそれ気になる",
        "早く教えて！",
        "え、どういうこと!?",
        "うそでしょ!?",
        "これ私もやってた…",
        "全然知らなかった",
        "え待って、ヤバい",
        "気になりすぎる",
        "もっと詳しく！",
        "ガチか…",
        "それ毎日やってた",
        "え、本当に!?",
    ],
    "sleep":    [
        "なにそれ気になる",
        "早く教えて！",
        "え、それが原因!?",
        "うそ、マジで!?",
        "気になって寝れない",
        "ガチか…",
        "え待って怖い",
        "もっと知りたい！",
        "全然知らなかった",
        "それって私のこと!?",
        "え、どういうこと!?",
        "これ誰か教えてほしかった",
    ],
    "exercise": [
        "なにそれ気になる",
        "早く教えて！",
        "え、そうなの!?",
        "うそ、ガチで!?",
        "もっと聞きたい",
        "全然知らなかった",
        "え待ってやばい",
        "気になりすぎる",
        "これ誰も教えてくれなかった",
        "ほんとに!?",
        "え、どういうこと!?",
        "なんで今まで知らなかったんだ",
    ],
    "dental":   [
        "なにそれ気になる",
        "早く教えて！",
        "え、マジで!?",
        "うそでしょ!?",
        "全然知らなかった",
        "ガチで怖い",
        "え待って、やばい",
        "気になりすぎる",
        "これ知りたかった！",
        "え、どういうこと!?",
        "それって本当!?",
    ],
    "mental":   [
        "なにそれ気になる",
        "早く教えて！",
        "え、そういうこと!?",
        "うそでしょ…",
        "気になって仕方ない",
        "全然知らなかった",
        "ガチか…",
        "え待って",
        "もっと知りたい！",
        "これ私のことだ…",
        "え、どういうこと!?",
        "なんか怖いけど気になる",
    ],
    "warning":  [
        "なにそれ気になる",
        "早く教えて！",
        "え、やばすぎ!?",
        "うそ、ほんとに!?",
        "全然知らなかった",
        "ガチで怖い",
        "え待って、マジ!?",
        "気になりすぎる",
        "これ知らなかったら…",
        "え、どういうこと!?",
        "こわいけど気になる",
    ],
    "general":  [
        "なにそれ気になる",
        "早く教えて！",
        "え、どういうこと!?",
        "うそでしょ!?",
        "全然知らなかった",
        "ガチか…",
        "え待って",
        "気になりすぎる",
        "もっと詳しく！",
        "これ本当!?",
        "それって私のことじゃん",
        "なんで今まで知らなかったんだ",
    ],
}

# ── ミニトピックバッジ（タイトルキーワード別）──────────────────────────────
_MINI_TOPIC_MAP: dict[str, list[str]] = {
    "コーヒー":      ["集中力UP↑", "老化予防効果", "適量が大事", "飲みすぎ注意"],
    "緑茶":          ["カテキン効果", "老化を防ぐ!", "飲み方が大事", "がん予防?"],
    "白髪":          ["食事が原因!?", "栄養不足NG", "ストレスも影響", "改善できる!"],
    "睡眠":          ["深い眠り術", "7時間が最適", "脳が休む時間", "寝不足は危険"],
    "不眠":          ["眠れない原因", "改善できる!", "食事との関係", "スマホNG"],
    "運動":          ["5分でOK!", "毎日必要!?", "効果的な時間帯", "やりすぎ注意"],
    "ダイエット":    ["リバウンド注意", "食事制限NG!?", "脂肪が燃える時", "正しい方法"],
    "腸":            ["腸活で変わる!", "善玉菌を増やせ", "食べ物が大事", "メンタルにも"],
    "腸活":          ["善玉菌が鍵!", "ヨーグルトOK", "食物繊維が大事", "30日で変化"],
    "血圧":          ["塩分に注意!", "運動も効果的", "食事で改善!", "危険な数値"],
    "コレステロール": ["食べ物で変わる", "善玉と悪玉", "運動が効果的", "食事が大事"],
    "ストレス":      ["解消法あった!", "体への影響", "自律神経に関係", "食事で改善"],
    "免疫":          ["腸が7割!", "睡眠が大事", "食べ物で強化", "ストレスNG"],
    "老化":          ["食事で防げる", "運動が効果的", "睡眠も大事!", "実は○○が原因"],
    "血糖":          ["食べる順番!", "GI値を知れ", "運動でリセット", "間食が危険"],
    "糖質":          ["摂りすぎ注意!", "選び方が大事", "置き換えレシピ", "意外な食品も"],
    "肥満":          ["原因は○○!?", "食事が9割", "正しい運動法", "リバウンドしない"],
    "納豆":          ["毎日がベスト", "食べる時間帯", "組み合わせ注意", "驚きの効果"],
    "食習慣":        ["朝食が鍵!", "食べる順番!", "間食のルール", "続けることが大事"],
    "歯":            ["磨き方が大事", "フロス必須!", "食後すぐはNG!?", "歯周病注意"],
    "筋肉":          ["食事が重要!", "タンパク質量", "効果的な時間帯", "休息も必要"],
    "認知症":        ["予防できる!", "食事が大事", "運動で防ぐ", "睡眠との関係"],
    "_food":         ["食べ方が大事!", "量より質!", "継続が鍵", "驚きの効果"],
    "_sleep":        ["質が大事!", "時間帯が鍵", "食事との関係", "寝不足の危険"],
    "_exercise":     ["継続が鍵!", "正しい方法で", "食事との組み合わせ", "やりすぎ注意"],
    "_warning":      ["今すぐやめて!", "○○が原因!?", "危険なサイン", "対策はコレ"],
    "_mental":       ["メンタルに影響", "改善できる!", "○○が大事", "試してみて"],
    "_dental":       ["磨き方が鍵!", "歯周病に注意", "フロス必須!", "口臭の原因も"],
    "_general":      ["科学的に証明!", "意外な真実!", "続けると効果", "知らないと損"],
}


def _make_mini_topics(title: str, theme: str) -> list[str]:
    """タイトルから3〜4個のミニトピックを生成する"""
    for kw, topics in _MINI_TOPIC_MAP.items():
        if not kw.startswith("_") and kw in title:
            return topics[:4]
    default_key = f"_{theme}"
    return (_MINI_TOPIC_MAP.get(default_key) or _MINI_TOPIC_MAP["_general"])[:4]


def _draw_mini_topics(canvas: Image.Image, topics: list[str],
                      x: int, y_start: int, max_h: int,
                      max_badge_w: int = 260) -> None:
    """カラフルな箇条書きバッジを縦に並べる（2ch系サムネ風・スマホ視認性重視）"""
    _TOPIC_COLORS = [
        (210, 30, 30),    # 赤
        (25, 130, 200),   # 青
        (25, 160, 70),    # 緑
        (200, 115, 0),    # オレンジ
    ]
    # スマホ視認性のため最低34px確保（26pxはスマホでほぼ読めない）
    topics = topics[:3]  # 大きいフォントに合わせて3つに制限
    font = load_font(34)
    line_h = font.getbbox("あ")[3]
    pad_x, pad_y = 12, 7
    spacing = 8

    # スペースに収まるように縮小（最低28px）
    total_needed = len(topics) * (line_h + pad_y * 2 + spacing)
    if total_needed > max_h:
        font = load_font(28)
        line_h = font.getbbox("あ")[3]
        spacing = 6

    draw = ImageDraw.Draw(canvas)
    cy = y_start
    for i, topic in enumerate(topics):
        color = _TOPIC_COLORS[i % len(_TOPIC_COLORS)]
        tw = font.getbbox(topic)[2]
        # バッジ幅が max_badge_w を超える場合はフォントを縮小して収める
        badge_font = font
        while tw + pad_x * 2 > max_badge_w and badge_font.size > 14:
            badge_font = load_font(badge_font.size - 2)
            tw = badge_font.getbbox(topic)[2]
        th = badge_font.getbbox("あ")[3]
        rx2 = x + tw + pad_x * 2
        ry2 = cy + th + pad_y * 2
        if cy + th + pad_y * 2 > y_start + max_h:
            break
        # ドロップシャドウ
        draw.rounded_rectangle([x + 3, cy + 3, rx2 + 3, ry2 + 3],
                               radius=7, fill=(0, 0, 0, 120))
        # カラー背景
        draw.rounded_rectangle([x, cy, rx2, ry2], radius=7, fill=(*color, 235))
        # 白テキスト（細い縁取り付き）
        tx, ty = x + pad_x, cy + pad_y
        for ddx in (-1, 0, 1):
            for ddy in (-1, 0, 1):
                if ddx or ddy:
                    draw.text((tx + ddx, ty + ddy), topic, font=badge_font,
                              fill=(0, 0, 0), anchor="lt")
        draw.text((tx, ty), topic, font=badge_font, fill=(255, 255, 255), anchor="lt")
        cy = ry2 + spacing


def _pick_sparse_comment_spots(
    topic_img: Image.Image,
    ix: int, iy: int,
    avoid_rects: list[tuple[int, int, int, int]],
    n: int = 2,
) -> list[tuple[int, int]]:
    """いらすとやのアルファチャンネルを分析し、コンテンツ密度が低い（透明に近い）
    上部エリアのアンカースポットを1点見つけ、その真下にn個縦並びで返す。

    ・アルファ値が低い = キャラや物体がいないエリア → 顔・物体と重ならない
    ・いらすとや上半分のみ検索し、2つをまとめて上エリアに集約する
    ・avoid_rects（タイトル・キャラクター）も回避
    """
    img_rgba = topic_img.convert("RGBA")
    alpha_ch = img_rgba.split()[3]          # "L" モード（グレースケール）
    img_w, img_h = img_rgba.size

    BUBBLE_W, BUBBLE_H = 160, 42            # 吹き出し概算サイズ
    STACK_GAP = 8                           # 縦並びの間隔
    GRID = 8                                # グリッド分割数

    # いらすとや上半分（〜55%）のみをアンカー候補とする
    candidates = []
    for row in range(GRID):
        cy_frac = (row + 0.5) / GRID
        if cy_frac > 0.55:                  # 上半分のみ
            continue
        for col in range(GRID):
            cx_img = int(img_w * (col + 0.5) / GRID)
            cy_img = int(img_h * cy_frac)

            # アンカー + 2枚目（真下）の両方の密度を計算
            boxes = [
                (cx_img, cy_img),
                (cx_img, cy_img + BUBBLE_H + STACK_GAP),
            ]
            total_density = 0.0
            for bx_c, by_c in boxes:
                box = (
                    max(0, bx_c - BUBBLE_W // 2),
                    max(0, by_c - BUBBLE_H // 2),
                    min(img_w, bx_c + BUBBLE_W // 2),
                    min(img_h, by_c + BUBBLE_H // 2),
                )
                region = alpha_ch.crop(box)
                px_vals = list(region.getdata())
                total_density += sum(px_vals) / max(1, len(px_vals))

            canvas_cx = ix + cx_img
            canvas_cy = iy + cy_img

            # スコア: 合計密度（低いほど良い）+ 上部・右寄り優先
            pos_bonus = row * 8 + (GRID - 1 - col) * 4
            candidates.append((total_density + pos_bonus, canvas_cx, canvas_cy))

    candidates.sort()

    for _score, anchor_cx, anchor_cy in candidates:
        # アンカー + 真下の2点を計算
        spots = [(anchor_cx, anchor_cy)]
        for k in range(1, n):
            spots.append((anchor_cx, anchor_cy + k * (BUBBLE_H + STACK_GAP)))

        # 全スポットが avoid_rects を回避 & キャンバス内か確認
        all_ok = True
        for cx, cy in spots:
            bx1, by1 = cx - BUBBLE_W // 2, cy - BUBBLE_H // 2
            bx2, by2 = cx + BUBBLE_W // 2, cy + BUBBLE_H // 2
            if any(not (bx2 < rx1 or bx1 > rx2 or by2 < ry1 or by1 > ry2)
                   for rx1, ry1, rx2, ry2 in avoid_rects):
                all_ok = False
                break
            if bx1 < 5 or bx2 > RESOLUTION[0] - 5 or by1 < 5 or by2 > RESOLUTION[1] - 5:
                all_ok = False
                break
        if all_ok:
            return spots

    return []


def _draw_reaction_comments(canvas: Image.Image, theme: str,
                             spots: list[tuple[int, int]],
                             angle: int = 0,
                             preselected: list[str] | None = None) -> list[str]:
    """2ch風リアクションコメント吹き出しをspots位置に描画する。
    angle: ミステリーテキストの傾き角度（PIL反時計回り）に連動して吹き出しも傾ける。
    preselected: 事前に選択済みのテキストリスト（Noneの場合はpoolからランダム選択）
    戻り値: 実際に描画したテキストリスト（霊夢吹き出しとの重複回避に使用）
    """
    pool = _REACTION_POOL.get(theme, _REACTION_POOL["general"])
    n = min(len(spots), len(pool))
    chosen = preselected[:n] if preselected else random.sample(pool, n)
    font = load_font(23)
    pad_x, pad_y = 9, 6
    margin = 4  # 回転時のクリッピング防止余白

    for comment, (cx, cy) in zip(chosen, spots):
        tw = font.getbbox(comment)[2]
        th = font.getbbox(comment)[3]
        bw = tw + pad_x * 2
        bh = th + pad_y * 2

        # 小サーフェスに吹き出しを描画（ドロップシャドウ付きで重なり時も視認性確保）
        _shadow = 3
        surf = Image.new("RGBA", (bw + margin * 2 + _shadow, bh + margin * 2 + _shadow), (0, 0, 0, 0))
        sdraw = ImageDraw.Draw(surf)
        rx1, ry1 = margin, margin
        rx2, ry2 = margin + bw, margin + bh
        # ドロップシャドウ（いらすとやと重なっても泡を浮き立たせる）
        sdraw.rounded_rectangle([rx1 + _shadow, ry1 + _shadow, rx2 + _shadow, ry2 + _shadow],
                                 radius=10, fill=(0, 0, 0, 110))
        sdraw.rounded_rectangle([rx1, ry1, rx2, ry2], radius=10,
                                 fill=(255, 255, 255, 245))
        sdraw.rounded_rectangle([rx1, ry1, rx2, ry2], radius=10,
                                 outline=(60, 60, 60, 220), width=2)
        tx, ty = rx1 + pad_x, ry1 + pad_y
        sdraw.text((tx, ty), comment, font=font, fill=(20, 20, 20), anchor="lt")

        # ミステリーテキストと同じ角度で回転（連動）
        if angle != 0:
            surf = surf.rotate(angle, expand=True, resample=Image.BICUBIC)

        # spot中心に配置してキャンバスにはみ出さないようクランプ
        dx = cx - surf.width // 2
        dy = cy - surf.height // 2
        dx = max(0, min(dx, RESOLUTION[0] - surf.width))
        dy = max(0, min(dy, RESOLUTION[1] - surf.height))
        canvas.alpha_composite(surf, dest=(dx, dy))

    return chosen

# レイアウト定数
TEXT_LEFT   = 30
TEXT_TOP    = 80   # 上端クリップ防止のため余白を確保（強調文字の上はみ出し込み）
TEXT_MAX_W  = 1060  # 右端余白を広くとる（強調文字のはみ出し防止）

FONT_MAX    = 150   # タイトルをより大きく・インパクト重視
FONT_MIN    = 62
FONT_STEP   = 6

_MANJU_H       = 400   # 霊夢: 魔理沙と同サイズに統一
_MANJU_H_MARISA = 400  # 魔理沙（帽子込み）: 顔64.4%×400≈258px（帽子高め分を加算）
_TOPIC_MAX_H = 420
_MYSTERY_Y   = 540   # タイトル領域を拡大するため下方へ移動
_MYSTERY_FS  = 78    # サブ要素なのでメインタイトルより小さく

# ミステリーオーバーレイのバリエーション
# PIL の rotate は反時計回り → 正角度 = 右端が上がる = 右肩上がり
# style: "white"=白+黒縁, "yellow"=黄+黒縁, "orange"=オレンジ+黒縁,
#        "red"=赤+黒縁, "double"=白+白外縁+黒内縁（二重縁取り・最強視認性）
# align: "right"=右端揃え（斜め向き）, "center"=中央揃え（水平向き）
_MYSTERY_OVERLAY_VARIANTS: list[dict] = [
    # ── 斜め（右肩上がり）パターン ──────────────────────────────────────────
    {"angle":  5, "x_frac": 0.52, "y_frac": 0.76, "scale": 1.00, "style": "white",  "align": "right"},
    {"angle":  7, "x_frac": 0.50, "y_frac": 0.77, "scale": 0.95, "style": "yellow", "align": "right"},
    {"angle":  8, "x_frac": 0.53, "y_frac": 0.75, "scale": 1.03, "style": "double", "align": "right"},
    {"angle": 10, "x_frac": 0.50, "y_frac": 0.76, "scale": 1.05, "style": "white",  "align": "right"},
    {"angle": 12, "x_frac": 0.51, "y_frac": 0.74, "scale": 0.95, "style": "orange", "align": "right"},
    {"angle": 14, "x_frac": 0.52, "y_frac": 0.77, "scale": 1.00, "style": "yellow", "align": "right"},
    {"angle": 15, "x_frac": 0.50, "y_frac": 0.75, "scale": 1.03, "style": "double", "align": "right"},
    {"angle":  6, "x_frac": 0.54, "y_frac": 0.76, "scale": 0.95, "style": "white",  "align": "right"},
    {"angle":  9, "x_frac": 0.49, "y_frac": 0.78, "scale": 1.00, "style": "red",    "align": "right"},
    {"angle": 11, "x_frac": 0.51, "y_frac": 0.74, "scale": 1.05, "style": "yellow", "align": "right"},
    {"angle": 13, "x_frac": 0.50, "y_frac": 0.77, "scale": 0.95, "style": "double", "align": "right"},
    {"angle":  8, "x_frac": 0.55, "y_frac": 0.75, "scale": 1.00, "style": "orange", "align": "right"},
    {"angle": 10, "x_frac": 0.50, "y_frac": 0.76, "scale": 1.03, "style": "red",    "align": "right"},
    {"angle":  6, "x_frac": 0.51, "y_frac": 0.77, "scale": 0.95, "style": "white",  "align": "right"},
    # ── 水平（傾けなし）パターン ─────────────────────────────────────────────
    {"angle":  0, "x_frac": 0.58, "y_frac": 0.80, "scale": 1.00, "style": "white",  "align": "center"},
    {"angle":  0, "x_frac": 0.57, "y_frac": 0.79, "scale": 0.95, "style": "yellow", "align": "center"},
    {"angle":  0, "x_frac": 0.60, "y_frac": 0.81, "scale": 1.03, "style": "double", "align": "center"},
    {"angle":  0, "x_frac": 0.55, "y_frac": 0.80, "scale": 1.05, "style": "white",  "align": "center"},
    {"angle":  0, "x_frac": 0.60, "y_frac": 0.79, "scale": 0.95, "style": "orange", "align": "center"},
    {"angle":  0, "x_frac": 0.57, "y_frac": 0.82, "scale": 1.00, "style": "yellow", "align": "center"},
    {"angle":  0, "x_frac": 0.59, "y_frac": 0.80, "scale": 1.03, "style": "red",    "align": "center"},
    {"angle":  0, "x_frac": 0.56, "y_frac": 0.81, "scale": 0.95, "style": "double", "align": "center"},
    # ── わずかに傾けるパターン（斜めと水平の中間・クリーンな見た目）────────────
    {"angle":  2, "x_frac": 0.57, "y_frac": 0.79, "scale": 1.00, "style": "white",  "align": "center"},
    {"angle":  3, "x_frac": 0.58, "y_frac": 0.80, "scale": 0.95, "style": "yellow", "align": "center"},
    {"angle":  2, "x_frac": 0.60, "y_frac": 0.79, "scale": 1.00, "style": "double", "align": "center"},
    {"angle":  4, "x_frac": 0.56, "y_frac": 0.80, "scale": 1.03, "style": "orange", "align": "center"},
    {"angle":  3, "x_frac": 0.59, "y_frac": 0.81, "scale": 0.95, "style": "red",    "align": "center"},
]

# スタイル別テキスト色定義
_OVERLAY_STYLES: dict[str, dict] = {
    "white":  {"fill": (255, 255, 255), "outline1": (0, 0, 0),   "outline2": None,      "outline_w": 10},
    "yellow": {"fill": (255, 240, 20),  "outline1": (0, 0, 0),   "outline2": None,      "outline_w": 10},
    "orange": {"fill": (255, 150, 0),   "outline1": (0, 0, 0),   "outline2": None,      "outline_w": 10},
    "red":    {"fill": (240, 30, 30),   "outline1": (0, 0, 0),   "outline2": None,      "outline_w": 10},
    # 二重縁取り: outline1=外縁(白・太い), outline2=内縁(黒・細い)
    "double": {"fill": (255, 255, 255), "outline1": (255,255,255), "outline2": (0,0,0), "outline_w": 14},
}


# ── テーマ検出 ──────────────────────────────────────────────────────────────

def _detect_theme(title: str) -> str:
    """タイトルから健康テーマを検出してパレットキーを返す"""
    if re.search(r'睡眠|不眠|寝|夜中|夜間|熟睡|起き', title):
        return "sleep"
    if re.search(r'運動|筋|ダイエット|体重|脂肪|ウォーキング|歩く', title):
        return "exercise"
    if re.search(r'歯|口腔|歯周|虫歯|口臭', title):
        return "dental"
    if re.search(r'危険|警告|リスク|ヤバ|やばい|禁止|毒|注意', title):
        return "warning"
    if re.search(r'メンタル|ストレス|うつ|不安|笑|幸せ|精神|心', title):
        return "mental"
    if re.search(r'食|栄養|野菜|果物|肉|魚|卵|納豆|発酵|腸|消化|味噌|血糖|ビタミン', title):
        return "food"
    return "general"


# ── 背景生成（3種）──────────────────────────────────────────────────────────

def _make_colorful_gradient_bg(theme: str, dark: bool = False) -> Image.Image:
    """テーマに合ったカラフルグラデーション背景を生成する（集中線の代替）"""
    palette = _THEME_PALETTES.get(theme, _THEME_PALETTES["general"])
    top = palette["dark_top"] if dark else palette["top"]
    bot = palette["dark_bot"] if dark else palette["bot"]
    bg = Image.new("RGBA", RESOLUTION)
    draw = ImageDraw.Draw(bg)
    for y in range(RESOLUTION[1]):
        t = y / RESOLUTION[1]
        r = int(top[0] + t * (bot[0] - top[0]))
        g = int(top[1] + t * (bot[1] - top[1]))
        b = int(top[2] + t * (bot[2] - top[2]))
        draw.line([(0, y), (RESOLUTION[0], y)], fill=(r, g, b, 255))
    return bg


def _make_twotone_bg(theme: str) -> Image.Image:
    """上下2色に分割したツートーン背景を生成する（バリアントC用）"""
    palette = _THEME_PALETTES.get(theme, _THEME_PALETTES["general"])
    top_color = palette["twotone_top"]
    bot_color = (18, 18, 18)
    bg = Image.new("RGBA", RESOLUTION)
    draw = ImageDraw.Draw(bg)
    split_y = int(RESOLUTION[1] * 0.45)
    draw.rectangle([0, 0, RESOLUTION[0], split_y], fill=(*top_color, 255))
    draw.rectangle([0, split_y, RESOLUTION[0], RESOLUTION[1]], fill=(*bot_color, 255))
    # 分割線: 明るいライン（デザイン要素 — メイン/サブの境界を明示）
    draw.rectangle([0, split_y, RESOLUTION[0], split_y + 4], fill=(*top_color, 200))
    return bg


def _make_gradient_bg(palette_name: str) -> Image.Image:
    """後方互換用（廃止予定）。カラフルグラデーションにリダイレクト"""
    return _make_colorful_gradient_bg("general", dark=False)


# ── いらすとや白背景除去 ────────────────────────────────────────────────────

def _remove_white_bg(img: Image.Image, threshold: int = 230) -> Image.Image:
    """いらすとや画像の白背景を透過に変換する（Pillowのみで実装）"""
    img = img.convert("RGBA")
    data = list(img.getdata())
    new_data = [
        (r, g, b, 0) if (r >= threshold and g >= threshold and b >= threshold)
        else (r, g, b, a)
        for r, g, b, a in data
    ]
    img.putdata(new_data)
    return img


def _is_good_irasutoya_image(img_rgba: Image.Image) -> bool:
    """シンプルなキャラ・物体絵かどうかを判定してシーン画像を弾く。

    判定基準:
      1. アスペクト比: 横長すぎる（>1.8）→ パノラマ/場面画像 → 除外
      2. 左右分布チェック: 左1/3・右1/3の両方に≥18%のopaque → 複数被写体が分散した
         シーン画像（人+ロボット+テーブルなど）→ 除外
         単一被写体（ボトル・キャラ1人・食品）は中央集中なので左右の片方が薄い
    """
    w, h = img_rgba.size
    if h == 0:
        return False
    if w / h > 1.8:
        return False

    # 高速化のため小サイズにリサイズして計算
    sw, sh = min(w, 120), min(h, 120)
    small_alpha = img_rgba.resize((sw, sh), Image.NEAREST).split()[3]
    data = list(small_alpha.getdata())

    t = max(1, sw // 3)
    left_op = sum(1 for y in range(sh) for x in range(t)
                  if data[y * sw + x] >= 10)
    right_op = sum(1 for y in range(sh) for x in range(sw - t, sw)
                   if data[y * sw + x] >= 10)
    zone = t * sh

    left_r  = left_op  / zone
    right_r = right_op / zone

    # 左右両方に18%以上の描画 → 複数被写体が分散したシーン画像 → 除外
    if left_r > 0.18 and right_r > 0.18:
        return False
    return True


# ── いらすとや画像取得 ───────────────────────────────────────────────────────

def _get_topic_image(title: str, keywords: list[str] | None = None) -> Image.Image | None:
    """いらすとや画像を1枚取得してリサイズ・白背景除去する。
    keywords: AI指定の検索キーワード（指定時はタイトル解析をスキップ）
    """
    if keywords:
        # AI指定キーワードを直接使用（テーマ合致率を最大化）
        search_kws = keywords
    else:
        # 従来ロジック: タイトルから正規表現でキーワード抽出
        _PRIORITY_NOUNS = re.compile(
            r'(コーヒー|緑茶|お茶|納豆|豆腐|卵|牛乳|野菜|果物|魚|肉|サーモン|鮭|玄米|白米|'
            r'ヨーグルト|チーズ|味噌|醤油|砂糖|塩|油|オリーブ油|アボカド|ブルーベリー|'
            r'バナナ|リンゴ|りんご|みかん|ニンジン|玉ねぎ|ほうれん草|ブロッコリー|'
            r'白髪|髪|肌|骨|筋肉|腸|血|脳|心臓|目|歯|爪|体|睡眠|運動|歩く|笑い|'
            r'血糖値|血圧|コレステロール|尿酸|体重|ダイエット|老化|免疫)'
        )
        m = _PRIORITY_NOUNS.search(title)
        priority_kw = m.group(1) if m else None

        cleaned = re.sub(r"[をがはにでとのもやへ、。！？「」【】●◯\s]", " ", title)
        cleaned = re.sub(r"(毎日|続ける|続けると|食べる|飲む|起きる|なる|する|いる|ある|知る|増やす|減らす|防ぐ|改善|効果|意外|実は|衝撃|驚|まさか)", " ", cleaned)
        words = [w for w in cleaned.split() if len(w) >= 2]

        search_kws = []
        if priority_kw:
            search_kws.append(priority_kw)
        search_kws += [w for w in words[:4] if w != priority_kw]

    # 複数候補を取得して品質フィルタで最良の1枚を選ぶ
    try:
        # サムネイルでは常にいらすとやを使用（本編のGemini画像とは別）
        from irasutoya_fetcher import fetch
        _is_gemini = False
        fallback_img = None
        for kw in search_kws[:5]:
            candidates = fetch(kw, max_count=6)
            for img_path in candidates:
                try:
                    img = Image.open(img_path).convert("RGBA")
                    # Gemini生成画像は白背景除去をスキップ（カラー背景のため除去すると消える）
                    has_transparency = _has_alpha_transparency(img)
                    img_clean = img if (has_transparency or _is_gemini) else _remove_white_bg(img)
                    ratio = _TOPIC_MAX_H / img_clean.height
                    new_w = int(img_clean.width * ratio)
                    resized = img_clean.resize((new_w, _TOPIC_MAX_H), Image.LANCZOS)
                    # Gemini生成画像はフィルタをスキップ（いらすとや用フィルタは不適切）
                    if _is_gemini or _is_good_irasutoya_image(img_clean):
                        return resized
                    elif fallback_img is None:
                        fallback_img = resized
                except Exception:
                    continue
        if fallback_img is not None:
            return fallback_img
    except Exception as _e_topic:
        print(f"  [THUMB] いらすとや例外: {_e_topic}")
    return None


def _has_alpha_transparency(img: Image.Image) -> bool:
    """画像が既に意味のあるアルファチャンネル（透過）を持っているか判定する。"""
    if img.mode != "RGBA":
        return False
    alpha = img.split()[3]
    # 全ピクセルの5%以上が透明（alpha < 20）なら透過済みとみなす
    data = list(alpha.getdata())
    transparent = sum(1 for a in data if a < 20)
    return transparent > len(data) * 0.05


def _get_scatter_images(title: str, count: int = 3, keywords: list[str] | None = None) -> list[Image.Image]:
    """複数の小さいいらすとや画像を取得する（散らばし装飾用）。
    keywords: AI指定の検索キーワード（指定時はタイトル解析をスキップ）
    """
    results: list[Image.Image] = []
    try:
        from irasutoya_fetcher import _KEYWORD_MAP
        _clipart_provider = os.getenv("CLIPART_PROVIDER", "gemini").lower()
        if _clipart_provider == "irasutoya":
            from irasutoya_fetcher import fetch
        else:
            from clipart_generator import fetch

        if keywords:
            # AI指定キーワードを直接使用
            kws = list(keywords)
        else:
            kws: list[str] = []

            # 1. irasutoya_fetcherの既知キーワードマップを最優先（関連性が高い）
            for kw in _KEYWORD_MAP:
                if kw in title and kw not in kws:
                    kws.append(kw)

            # 2. 具体的な食材・食品・身体部位（いらすとや検索で意味ある結果が出るもの）
            _PN = re.compile(
                r'(コーヒー|緑茶|お茶|紅茶|納豆|豆腐|卵|牛乳|野菜|果物|魚|肉|サーモン|鮭|'
                r'玄米|白米|ヨーグルト|チーズ|味噌|醤油|砂糖|塩|油|アボカド|バナナ|リンゴ|りんご|'
                r'みかん|ニンジン|玉ねぎ|ほうれん草|ブロッコリー|トマト|きのこ|しょうが|ニンニク|レモン|'
                r'白髪|筋肉|腸|脳|心臓|歯|睡眠|運動|病気|老化|肥満)'
            )
            for m in _PN.finditer(title):
                if m.group(1) not in kws:
                    kws.append(m.group(1))

        seen_paths: set = set()
        for kw in kws[:6]:
            if len(results) >= count:
                break
            imgs = fetch(kw, max_count=2)
            for ip in imgs:
                if ip in seen_paths:
                    continue
                seen_paths.add(ip)
                try:
                    h = random.randint(130, 190)
                    img = Image.open(ip).convert("RGBA")
                    if not _has_alpha_transparency(img):
                        img = _remove_white_bg(img)
                    ratio = h / img.height
                    img = img.resize((int(img.width * ratio), h), Image.LANCZOS)
                    results.append(img)
                except Exception:
                    pass
                if len(results) >= count:
                    break
    except Exception:
        pass
    return results


def _draw_scatter_irasutoya(canvas: Image.Image, title: str,
                            title_bottom_y: int, reimu_rx: int = 380,
                            reimu_rw: int = 320,
                            keywords: list[str] | None = None) -> None:
    """
    中央霊夢の左右の空白エリアに小さいいらすとや画像を散らす。
    画像はランダムな位置・サイズで配置してサムネのバリエーションを出す。
    keywords: AI指定の検索キーワード（指定時はタイトル解析をスキップ）
    """
    imgs = _get_scatter_images(title, count=3, keywords=keywords)
    if not imgs:
        return

    W, H = RESOLUTION
    # 配置可能エリア: タイトル下端〜ミステリーテキスト上端
    y_top = title_bottom_y + 10
    y_bot = _MYSTERY_Y - 15

    if y_bot - y_top < 60:
        return  # スペースが足りない場合はスキップ

    # 有効ゾーンのみ抽出（幅が小さすぎるゾーンは除外）してシャッフル
    all_zones = [
        (10, reimu_rx - 20),                 # 左ゾーン
        (reimu_rx + reimu_rw + 10, W - 10),  # 右ゾーン
    ]
    # 各画像の最大幅に対して有効なゾーンだけ残す（min幅 80px）
    valid_zones = [(zx1, zx2) for zx1, zx2 in all_zones if zx2 - zx1 >= 80]
    if not valid_zones:
        return
    random.shuffle(valid_zones)

    placed = 0
    zone_idx = 0
    for img in imgs:
        if placed >= 2 or zone_idx >= len(valid_zones):
            break
        # 幅が足りないゾーンはスキップして次のゾーンを試す
        while zone_idx < len(valid_zones):
            zx1, zx2 = valid_zones[zone_idx]
            if zx2 - zx1 >= img.width + 10:
                break
            zone_idx += 1
        if zone_idx >= len(valid_zones):
            break
        zx1, zx2 = valid_zones[zone_idx]
        # ランダムな x/y 位置（ゾーン内）
        ix = random.randint(zx1, max(zx1, zx2 - img.width))
        iy_range = y_bot - y_top - img.height
        iy = y_top + (random.randint(0, max(0, iy_range)) if iy_range > 0 else 0)
        _paste_with_shadow(canvas, img, (ix, iy), shadow_offset=4, shadow_alpha=70)
        placed += 1
        zone_idx += 1


# ── ドロップシャドウ ────────────────────────────────────────────────────────

def _paste_with_shadow(
    canvas: Image.Image,
    img: Image.Image,
    pos: tuple[int, int],
    shadow_offset: int = 6,
    shadow_alpha: int = 100,
) -> None:
    """画像をドロップシャドウ付きで貼り付ける"""
    shadow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    # シャドウ（黒・半透明）
    shadow_img = Image.new("RGBA", img.size, (0, 0, 0, shadow_alpha))
    mask = img.split()[3] if img.mode == "RGBA" else None
    shadow.paste(shadow_img, (pos[0] + shadow_offset, pos[1] + shadow_offset), mask)
    canvas.alpha_composite(shadow)
    canvas.paste(img, pos, img if img.mode == "RGBA" else None)


# ── キャラクター（nicotalk改パーツ合成）────────────────────────────────────────

# video_builder と同じパーツ合成システムを使用
from video_builder import _load_kai_sprites, _compose_kai_character, _KAI_EMOTION_PARTS

# サムネ用表情 → nicotalk改感情タグのマッピング（エイリアス含む）
_THUMB_EXPR_MAP: dict[str, str] = {
    "serious":        "serious",
    "surprised":      "surprised",
    "happy":          "happy",
    "worried":        "worried",
    "surprised_open": "shocked",
    "worried_open":   "worried",
    "normal":         "normal",
    "angry":          "angry",
    "thinking":       "thinking",
    "excited":        "excited",
    "sad":            "sad",
    "shocked":        "shocked",
    "embarrassed":    "embarrassed",
    "relieved":       "relieved",
    "curious":        "curious",
    "smug":           "smug",
    "joyful":         "joyful",
    # エイリアス: Geminiが返しうる表現を網羅
    "confused":       "worried",
    "nervous":        "worried",
    "scared":         "shocked",
    "frightened":     "shocked",
    "proud":          "smug",
    "confident":      "smug",
    "annoyed":        "angry",
    "frustrated":     "angry",
    "delighted":      "joyful",
    "cheerful":       "happy",
    "concerned":      "worried",
    "anxious":        "worried",
    "amazed":         "shocked",
    "skeptical":      "thinking",
    "doubtful":       "thinking",
}


def _expr_from_bubble(bubble_text: str, role: str = "reimu") -> str:
    """吹き出しテキストの内容からキャラの役割に応じた表情を自動導出する。

    role: "marisa"=解説/煽り役（真剣・得意が基本）
          "reimu"=驚き/共感役（驚き・心配が基本）

    Geminiの表情指定に依存せず、セリフと表情の100%一致を保証する。
    感情カテゴリ内で重み付きランダム選択し、同じ顔ばかりになるのを防ぐ。
    """
    def _pick(options: list[tuple[str, int]]) -> str:
        """重み付きランダム選択。options: [(表情, 重み), ...]"""
        pool = []
        for expr, weight in options:
            pool.extend([expr] * weight)
        return random.choice(pool)

    if not bubble_text:
        if role == "marisa":
            return _pick([("serious", 6), ("smug", 3), ("thinking", 1)])
        return _pick([("surprised", 5), ("worried", 3), ("curious", 2)])

    _is_marisa = (role == "marisa")

    # ── 怒り・煽り（両キャラ共通）
    if re.search(r"ふざけ|許さ|いい加減|バカ|アホ|やめろ|するな", bubble_text):
        return _pick([("angry", 7), ("serious", 3)])

    # ── 驚き・衝撃（「マジ」「えっ」「うそ」等）
    if re.search(r"[!！]{2}|えっ|うそ|ヤバ|![\?？]|[\?？]!", bubble_text):
        if _is_marisa:
            return _pick([("surprised", 6), ("serious", 3), ("excited", 1)])
        return _pick([("shocked", 5), ("surprised", 4), ("worried", 1)])

    if re.search(r"マジ[!！?？で]", bubble_text):
        if _is_marisa:
            return _pick([("serious", 6), ("surprised", 3), ("smug", 1)])
        return _pick([("shocked", 5), ("surprised", 3), ("worried", 2)])

    # ── 恐怖・危険キーワード
    if re.search(r"怖|恐ろし|死ぬ|壊れ|溶け|蝕|崩壊|破壊|縮む|腐る", bubble_text):
        if _is_marisa:
            return _pick([("serious", 6), ("angry", 2), ("worried", 2)])
        return _pick([("worried", 5), ("shocked", 3), ("sad", 2)])

    # ── 心配・不安
    if re.search(r"大丈夫|心配|不安|辛|つら|のに[…。]|かも[…。]|だけど", bubble_text):
        if _is_marisa:
            return _pick([("worried", 5), ("serious", 4), ("thinking", 1)])
        return _pick([("worried", 6), ("sad", 3), ("surprised", 1)])

    # ── 余韻（「…」で終わる）
    if re.search(r"[…。]{2,}|\.{3}", bubble_text):
        if _is_marisa:
            return _pick([("serious", 5), ("thinking", 3), ("worried", 2)])
        return _pick([("worried", 5), ("sad", 3), ("thinking", 2)])

    # ── 得意・自信（魔理沙の煽り）
    if re.search(r"だぜ|ぜ[!！]|んだ[!！]|教えて[やあ]|知って[たる]|当然|もちろん", bubble_text):
        if _is_marisa:
            return _pick([("smug", 5), ("serious", 3), ("excited", 2)])
        return _pick([("surprised", 5), ("curious", 3), ("worried", 2)])

    # ── 驚き（軽度: 「!」「?」1個）
    if re.search(r"[!！]|[?？]|まさか|知らなかった|そうなの|本当|ホント", bubble_text):
        if _is_marisa:
            return _pick([("serious", 5), ("surprised", 3), ("smug", 2)])
        return _pick([("surprised", 5), ("curious", 3), ("shocked", 2)])

    # ── 嬉しい・ポジティブ
    if re.search(r"やった|嬉し|良かった|すごい|最高|楽し|ありがと|よし", bubble_text):
        return _pick([("happy", 5), ("excited", 3), ("joyful", 2)])

    # ── 疑問・考え中
    if re.search(r"なぜ|どうして|不思議|うーん", bubble_text):
        if _is_marisa:
            return _pick([("thinking", 6), ("serious", 3), ("curious", 1)])
        return _pick([("curious", 5), ("thinking", 3), ("surprised", 2)])

    # ── 悲しい
    if re.search(r"悲し|泣|残念|寂し|切な", bubble_text):
        if _is_marisa:
            return _pick([("worried", 5), ("sad", 3), ("serious", 2)])
        return _pick([("sad", 5), ("worried", 4), ("embarrassed", 1)])

    # ── フォールバック: セリフ末尾で判定
    _end = bubble_text.rstrip()
    if _end.endswith(("ぜ", "だ", "ぞ")):
        if _is_marisa:
            return _pick([("smug", 5), ("serious", 4), ("excited", 1)])
        return _pick([("serious", 5), ("surprised", 3), ("curious", 2)])
    if _end.endswith(("…", "。。", "...")):
        if _is_marisa:
            return _pick([("serious", 5), ("thinking", 3), ("worried", 2)])
        return _pick([("worried", 5), ("sad", 3), ("thinking", 2)])
    if _end.endswith(("！", "!", "!?")):
        if _is_marisa:
            return _pick([("serious", 5), ("excited", 3), ("surprised", 2)])
        return _pick([("surprised", 5), ("shocked", 3), ("excited", 2)])

    # 最終フォールバック（normalは避ける）
    if _is_marisa:
        return _pick([("serious", 5), ("smug", 3), ("thinking", 2)])
    return _pick([("surprised", 4), ("worried", 3), ("curious", 3)])

# キャッシュ: キャラ名 → パーツ辞書
_thumb_kai_cache: dict[str, dict] = {}


def _load_manju_expr(name: str, height: int, expr: str) -> Image.Image | None:
    """nicotalk改パーツを合成してサムネ用キャラ画像を返す"""
    if name not in _thumb_kai_cache:
        _thumb_kai_cache[name] = _load_kai_sprites(name)
    parts = _thumb_kai_cache[name]
    if not parts or not parts.get("body"):
        return None

    emotion = _THUMB_EXPR_MAP.get(expr, "normal")
    cfg = {"height": height, "flip_h": False}
    return _compose_kai_character(
        parts, emotion, name,
        mouth_open=False, blink_eye=None,
        cfg=cfg, is_speaking=True,
    )


def _load_manju(name: str, height: int) -> Image.Image | None:
    """フォールバック: デフォルト表情で読み込み"""
    return _load_manju_expr(name, height, "normal")


def _select_char_expressions(title: str, theme: str) -> tuple[str, str]:
    """タイトル・テーマから魔理沙・霊夢の表情を選ぶ。
    魔理沙: 解説者→serious基本、驚き事実→surprised、ポジティブ→happy
    霊夢:  ボケ役→surprised基本、不安系→worried、ポジティブ→happy

    戻り値: (marisa_expr, reimu_expr)  例: ("serious", "surprised")
    """
    # 危険・警告・リスク系 → 魔理沙=厳しい顔、霊夢=心配顔
    if re.search(r"(危険|リスク|ヤバ|禁止|悪化|老化|蝕む|弱る|壊す|毒|害|やってはいけない|NG)", title):
        return random.choice([("serious", "worried"), ("serious", "worried")])

    # 睡眠・疲労・メンタル系 → 魔理沙=心配、霊夢=心配
    if re.search(r"(睡眠|眠れ|不眠|ストレス|メンタル|うつ|疲れ|疲労|だるい)", title):
        return random.choice([("serious", "worried"), ("worried", "worried")])

    # 驚き・衝撃・意外性 → 魔理沙=驚き、霊夢=驚き
    if re.search(r"(実は|意外|まさか|衝撃|知らなかった|嘘|逆効果|間違い|倍|激変)", title):
        return random.choice([("surprised", "surprised"), ("serious", "surprised")])

    # ポジティブ・改善・効果系 → 魔理沙=得意顔、霊夢=嬉しい
    if re.search(r"(改善|向上|回復|健康|長寿|美肌|若返|ダイエット成功|増やす)", title):
        return random.choice([("happy", "happy"), ("happy", "surprised")])

    # 食事・習慣テーマ → 魔理沙=解説顔、霊夢=驚き（よくある霊夢のボケ後の反応）
    if re.search(r"(食べ|飲む|食事|コーヒー|緑茶|お茶|習慣|毎日|続ける)", title):
        return random.choice([("serious", "surprised"), ("serious", "worried")])

    # デフォルト: 魔理沙=解説・ちょっとキツめ、霊夢=驚き
    theme_map = {
        "food":     ("serious",   "surprised"),
        "sleep":    ("serious",   "worried"),
        "dental":   ("serious",   "worried"),
        "mental":   ("worried",   "worried"),
        "exercise": ("happy",     "surprised"),
        "general":  ("serious",   "surprised"),
    }
    return theme_map.get(theme, ("serious", "surprised"))


# ── 中央霊夢ビックリ演出 ─────────────────────────────────────────────────────

# ビックリマークのバリエーション定義: (dx_offset, dy, size, color)
# dx_offset は霊夢の右端からの追加オフセット（霊夢右脇・右上に配置）
_CENTER_REIMU_PATTERNS = [
    # 右大1つ
    [(10, 0, 140, (255, 40, 40))],
    # 右に縦2つ
    [(10, -20, 120, (255, 40, 40)), (15, 100, 80, (255, 210, 0))],
    # 右に大＋小
    [(8, 10, 150, (255, 40, 40)), (60, -30, 75, (255, 210, 0))],
    # 右に3連
    [(5, -30, 100, (255, 40, 40)), (10, 60, 80, (255, 210, 0)), (20, 140, 90, (255, 40, 40))],
    # 右大2つ横並び
    [(5, 20, 130, (255, 40, 40)), (70, 40, 100, (255, 40, 40))],
    # 右超大1つ
    [(5, -10, 170, (255, 40, 40))],
]

# 中央霊夢に使う表情リスト
_CENTER_REIMU_EXPRS = ["surprised", "worried", "happy", "surprised_open", "worried_open"]


def _draw_center_reimu(canvas: Image.Image, top_margin: int = 150) -> bool:
    """
    タイトルテキスト下中央に霊夢を大きく配置し、右横にビックリマークを描画する。
    top_margin: タイトルテキスト下端+余白。これ以下に霊夢の上端を置く。
    配置した場合はTrueを返す（右下霊夢をスキップするため）。
    """
    available_h = _MYSTERY_Y - top_margin - 20
    CENTER_H = min(340, max(available_h, 120))
    if CENTER_H < 120:
        return False

    expr = random.choice(_CENTER_REIMU_EXPRS)
    reimu = _load_manju_expr("霊夢", CENTER_H, expr)
    if not reimu:
        return False

    # 霊夢を水平中央寄り（少し左にして右に！が入る余地を作る）
    rx = max(100, (RESOLUTION[0] - reimu.width) // 2 - 80)
    ry = top_margin + 5

    pattern = random.choice(_CENTER_REIMU_PATTERNS)
    draw = ImageDraw.Draw(canvas)

    # ビックリマーク（霊夢の右脇）
    for dx_offset, dy, fs, color in pattern:
        ex = rx + reimu.width + dx_offset
        ey = max(top_margin, ry + dy)
        if ex + fs > RESOLUTION[0] - 5 or ey + fs > _MYSTERY_Y:
            continue
        efont = load_font(fs)
        for ddx in range(-10, 11, 3):
            for ddy in range(-10, 11, 3):
                if ddx or ddy:
                    draw.text((ex + ddx, ey + ddy), "！", font=efont,
                              fill=(0, 0, 0), anchor="lt")
        draw.text((ex, ey), "！", font=efont, fill=color, anchor="lt")

    _paste_with_shadow(canvas, reimu, (rx, ry), shadow_offset=8, shadow_alpha=120)
    return True


# ── テキスト描画 ─────────────────────────────────────────────────────────────

def _outlined_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    fill: tuple = (255, 255, 255),
    outline: tuple = (0, 0, 0),
    outline_w: int = 10,
    anchor: str = "lt",
) -> None:
    """黒縁取り＋影付きテキストを描画する"""
    x, y = xy
    # ドロップシャドウ（右下3〜4pxオフセット）
    draw.text((x + 4, y + 4), text, font=font, fill=(0, 0, 0, 160), anchor=anchor)
    # 縁取り（5〜6px相当）
    for dx in range(-outline_w, outline_w + 1, 2):
        for dy in range(-outline_w, outline_w + 1, 2):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline, anchor=anchor)
    # 本文
    draw.text((x, y), text, font=font, fill=fill, anchor=anchor)


def _draw_gradient_text(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    color1: tuple,
    color2: tuple,
    outline: tuple = (0, 0, 0),
    outline_w: int = 12,
) -> int:
    """
    左→右グラデーションで1行テキストを描画する。
    縁取り→ドロップシャドウ→本文の順で描画。
    戻り値: 描画したテキストの横幅（px）
    """
    x, y = xy
    total_w = font.getbbox(text)[2]

    # ドロップシャドウ
    draw.text((x + 5, y + 5), text, font=font, fill=(0, 0, 0, 140), anchor="lt")
    # 縁取り
    for dx in range(-outline_w, outline_w + 1, 2):
        for dy in range(-outline_w, outline_w + 1, 2):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline, anchor="lt")
    # グラデーション本文（文字単位で色を変える）
    cx = x
    for ch in text:
        cw = font.getbbox(ch)[2]
        ratio = (cx - x) / total_w if total_w > 0 else 0
        ratio = max(0.0, min(1.0, ratio))
        r = int(color1[0] + ratio * (color2[0] - color1[0]))
        g = int(color1[1] + ratio * (color2[1] - color1[1]))
        b = int(color1[2] + ratio * (color2[2] - color1[2]))
        draw.text((cx, y), ch, font=font, fill=(r, g, b), anchor="lt")
        cx += cw
    return total_w


# 強調キーワードパターン: マッチした部分はオレンジ〜赤でグラデーション描画
_EMPHASIS_RE = re.compile(
    r'(\d+(?:[,\.]\d+)?(?:倍|%|％|円|人|年|歳|日|回|個|種|位|kg|g|mg|ml|L|分|秒|時間|ヶ月|週))'  # 数値+単位
    r'|([1-9][0-9]?(?:つ|本|枚|杯|口|粒))'  # 個数
    r'|(危険|警告|ヤバい|ヤバ|禁止|緊急|衝撃|まさか|衝撃|禁断|激変|激減|激増|爆発|超)'  # 強調語
    r'|([〇○●■◆▲△★☆◇□？]{2,})',  # 伏せ字マスク記号 → emph扱いで黄色大きく
)

# 行1グラデーション: 黄→オレンジ（明るく目立つ）
_LINE1_GRAD_C1 = (255, 240, 20)   # 黄色
_LINE1_GRAD_C2 = (255, 140, 0)    # オレンジ
# 強調キーワード: 単色（全テーマ共通・サイズ差で十分に際立つため色は統一）
_EMPH_COLOR = (255, 240, 20)      # 行1と同じ明るい黄色


_EMPH_SCALE = 1.7  # 強調単語のフォントサイズ倍率（競合分析: 数字は1.5-2x推奨→1.7倍）

# 名詞（健康トピックの主役）→ 白で描画して動詞・助動詞と色を区別する
_NOUN_RE = re.compile(
    r'(白髪|コーヒー|緑茶|お茶|紅茶|納豆|豆腐|卵|牛乳|野菜|果物|魚|肉|サーモン|鮭|'
    r'玄米|白米|ご飯|ヨーグルト|チーズ|味噌|醤油|砂糖|塩|油|アボカド|バナナ|リンゴ|りんご|'
    r'みかん|ニンジン|玉ねぎ|ほうれん草|ブロッコリー|トマト|きのこ|しょうが|ニンニク|レモン|'
    r'髪|肌|骨|筋肉|腸|血|脳|心臓|目|歯|爪|'
    r'血糖値|血圧|コレステロール|尿酸|体重|老化|免疫|食習慣|食事|習慣|睡眠|運動|笑い)'
)


_MAX_EMPH_COUNT = 2  # 強調ワードは最大2個まで（やりすぎると効果が薄れる）

# AIアートディレクターが指定した強調ワード（directiveモード時にセット）
_DIRECTIVE_EMPH_WORDS: list[str] = []


def _segment_text(text: str) -> list[tuple[str, str]]:
    """テキストをnoun/emph/normalセグメントに分割する。
    _DIRECTIVE_EMPH_WORDSがセットされている場合はAI指定ワードを優先。
    emphは最大_MAX_EMPH_COUNT個まで。超過分は長い順に優先し、残りはnormalに降格。
    """
    emph_matches: list[tuple[int, int]] = []
    if _DIRECTIVE_EMPH_WORDS:
        # AIが指定した強調ワードをテキスト内から検索
        for word in _DIRECTIVE_EMPH_WORDS:
            idx = text.find(word)
            if idx >= 0:
                emph_matches.append((idx, idx + len(word)))
    if not emph_matches:
        # AI指定がない or マッチしない場合は従来の正規表現フォールバック
        for m in _EMPHASIS_RE.finditer(text):
            emph_matches.append((m.start(), m.end()))
    # emph が _MAX_EMPH_COUNT を超えたら、長い(=目立つ)順に上位だけ残す
    if len(emph_matches) > _MAX_EMPH_COUNT:
        emph_matches.sort(key=lambda x: -(x[1] - x[0]))
        emph_matches = emph_matches[:_MAX_EMPH_COUNT]
    emph_set = set(emph_matches)

    found: list[tuple[int, int, str]] = []
    for s, e in emph_set:
        found.append((s, e, "emph"))
    for m in _NOUN_RE.finditer(text):
        s, e = m.start(), m.end()
        # emphと重複しない場合のみnounとして追加
        if not any(fs <= s < fe or fs < e <= fe for fs, fe, _ in found):
            found.append((s, e, "noun"))
    found.sort(key=lambda x: x[0])
    segments: list[tuple[str, str]] = []
    last = 0
    for s, e, kind in found:
        if s > last:
            segments.append((text[last:s], "normal"))
        segments.append((text[s:e], kind))
        last = e
    if last < len(text):
        segments.append((text[last:], "normal"))
    return segments


def _draw_rich_line(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    line_index: int = 0,
    outline_w: int = 12,
    font_size: int = 0,
) -> None:
    """
    ゆっくり系テキスト描画: 行0はグラデーション黄→オレンジ、
    行1以降は白。強調パターン（数値・危険ワード）はオレンジ→赤グラデーション＋サイズ1.4倍。
    ベースライン合わせで描画するため、強調文字が下揃えで大きく表示される。
    """
    x, y = xy
    # noun/emph/normal セグメントに分割
    segments = _segment_text(text)

    # 強調・名詞セグメントが存在しない場合は一括描画（競合分析: 全行白に統一、emph黄色が最大限際立つ）
    if all(k == "normal" for _, k in segments):
        _outlined_text(draw, (x, y), text, font,
                       fill=(255, 255, 255), outline=(0, 0, 0), outline_w=outline_w)
        return

    # 強調フォントを準備（通常フォントより大きい）
    if font_size > 0:
        emph_fs = min(FONT_MAX, int(font_size * _EMPH_SCALE))
    else:
        # フォントサイズを推定（フォントオブジェクトから）
        try:
            emph_fs = min(FONT_MAX, int(font.size * _EMPH_SCALE))
        except AttributeError:
            emph_fs = FONT_MAX
    emph_font = load_font(emph_fs)

    # ベースライン位置を計算（通常フォントの下端をベースラインとする）
    normal_h = font.getbbox("あ")[3]        # 通常フォントの高さ
    emph_h   = emph_font.getbbox("あ")[3]   # 強調フォントの高さ
    # 強調文字のy座標: 通常文字の下端と揃える（上にはみ出す）
    emph_y_offset = normal_h - emph_h  # 負の値 → 強調文字は上に飛び出す

    # 各セグメントの描画位置を事前計算（正確な左端x座標を保持）
    # 全角変換廃止: 1.7倍フォントで十分大きく、全角だと文字間隔が広がりすぎる
    seg_info: list[tuple] = []  # (cx, ey, fnt, sw, display_text, kind)
    cx = x
    for seg_text, kind in segments:
        fnt = emph_font if kind == "emph" else font
        ey  = y + emph_y_offset if kind == "emph" else y
        disp = seg_text
        sw   = fnt.getbbox(disp)[2]
        seg_info.append((cx, ey, fnt, sw, disp, kind))
        cx += sw

    # 1パス目: 縁取り — normal/noun → emph の順で描画（emph が最前面に来るよう）
    for pass_kind in ("normal_noun", "emph"):
        for (sx, sy, fnt, sw, disp, kind) in seg_info:
            is_emph = kind == "emph"
            if pass_kind == "emph" and not is_emph:
                continue
            if pass_kind == "normal_noun" and is_emph:
                continue
            ow = outline_w + 2 if is_emph else (outline_w + 1 if kind == "noun" else outline_w)
            # ドロップシャドウ
            draw.text((sx + 5, sy + 5), disp, font=fnt, fill=(0, 0, 0, 140), anchor="lt")
            # 縁取り
            for dx in range(-ow, ow + 1, 2):
                for dy in range(-ow, ow + 1, 2):
                    if dx != 0 or dy != 0:
                        draw.text((sx + dx, sy + dy), disp, font=fnt,
                                  fill=(0, 0, 0), anchor="lt")

    # 2パス目: 本文グラデーション — normal/noun → emph の順で描画（emph が最前面）
    for pass_kind in ("normal_noun", "emph"):
        for (sx, sy, fnt, sw, disp, kind) in seg_info:
            is_emph = kind == "emph"
            if pass_kind == "emph" and not is_emph:
                continue
            if pass_kind == "normal_noun" and is_emph:
                continue
            if is_emph:
                # 強調: マスク記号（〇〇）はバリアント別カラー、数字等は黄色統一
                color = _CURRENT_MASK_COLOR if _MASK_SYMBOL_RE.fullmatch(disp) else _EMPH_COLOR
                draw.text((sx, sy), disp, font=fnt, fill=color, anchor="lt")
            elif kind == "noun":
                draw.text((sx, sy), disp, font=fnt, fill=(255, 255, 255), anchor="lt")
            else:
                # 全行通常部分: 白（競合分析: 白または黄色のみに統一、emph黄色が際立つ）
                draw.text((sx, sy), disp, font=fnt, fill=(255, 255, 255), anchor="lt")


def _split_text(text: str, font, max_width: int) -> list[str]:
    """テキストを自然な区切りで最大3行に折り返す（行頭に句読点を置かない）

    行分割ルール（優先順）:
      1. 句読点（！。、）
      2. 条件節・理由節の末尾: 〜ると/〜から/〜ので/〜たら/〜すると 等で分割
         → CAUSE（条件）| RESULT（結果）の構造を保つ
         例: 「スマホを見ると」| 「睡眠の質が3倍悪化する」
      3. 注目ワード（実は・なんと）の前
      4. 助詞（を・が・は・に等）
      5. 強制改行（幅超過時）

    NG例: 「スマホ」| 「を見ると睡眠の質が…」（名詞で切れて意味が途切れる）
    OK例: 「スマホを見ると」| 「睡眠の質が3倍悪化する」（条件節で区切る）
    """
    # 行頭禁則文字（これらで始まる行は作らない）
    _KINSOKU_HEAD = set("、。！？・」』）】〕")

    if font.getbbox(text)[2] <= max_width:
        return [text]

    # ── 条件節・理由節の末尾（後ろで切る: 条件|結果 の構造を保つ）─────────────
    # 例: 「スマホを見ると」|「睡眠の質が…」「食べると」|「老化が加速」
    _COND_SEPS = (
        "し続けると", "し続けれ", "し続けた",    # し続ける系
        "してしまうと", "してしまい",
        "するとき", "すると", "したら", "すれば", "したい", "しない",
        "できると", "できない",
        "わかると", "なると", "なったら",
        "んだら",   # 飲んだら/読んだら (む/ぶ/ぬ → んだら)
        "いたら",   # 聞いたら/歩いたら (く → いたら)
        "ったら",   # 使ったら/取ったら (う/つ → ったら)
        "けたら",   # 続けたら/食べたら (ける/ける → けたら)
        "ると",   # Vると (見ると/食べると/飲むと→む+と→むと で別途対応)
        "むと",   # 飲むと/含むと
        "うと",   # 使うと/補うと
        "くと",   # 聞くと/歩くと
        "すと",   # 増やすと/出すと
        "ぐと",   # 稼ぐと
        "ないと", "なくて",  # 〜ないと/〜なくて
        "から",   # 理由節: 〜から（結果が続く）
        "ので",   # 理由節: 〜ので
        "けど",   # 逆接: 〜けど
    )

    # ── 接続表現（前で切る: | 実は / | なんと）───────────────────────────────
    _CONJ_BEFORE = ("実は", "実際は", "意外と", "なんと", "まさか")

    _PARTICLES = ["を", "が", "は", "に", "で", "の", "と", "も"]

    def _try_split(sep: str, check_width: bool) -> list[str] | None:
        idx = text.find(sep)
        if not (0 < idx < len(text) - 1):
            return None
        if sep in _COND_SEPS:
            # 条件節・理由節: 「節の末尾」で後ろ切り（条件|結果 の構造を保つ）
            # 例: 「スマホを見ると」|「睡眠の質が3倍悪化する」
            cut_a = idx + len(sep)
            if cut_a < len(text):
                la, lb = text[:cut_a], text[cut_a:]
                # 両行最低4文字以上・行頭禁則チェック
                if lb and lb[0] not in _KINSOKU_HEAD and len(la) >= 4 and len(lb) >= 4:
                    if not check_width or (
                        font.getbbox(la)[2] <= max_width and font.getbbox(lb)[2] <= max_width
                    ):
                        return [la, lb]
        elif sep in _CONJ_BEFORE:
            # 接続表現: 「前で切る」（|実は / |なんと）
            cut = idx
            la, lb = text[:cut], text[cut:]
            if len(la) >= 2 and len(lb) >= 2:
                if not check_width or (
                    font.getbbox(la)[2] <= max_width and font.getbbox(lb)[2] <= max_width
                ):
                    return [la, lb]
        else:
            cut = idx + (1 if sep in ("！", "。", "、") else 0)
            l1, l2 = text[:cut], text[cut:]
            if l2 and l2[0] in _KINSOKU_HEAD:
                cut += 1
                l1, l2 = text[:cut], text[cut:]
            if l2 and len(l1) >= 4 and len(l2) >= 4:
                if not check_width or (
                    font.getbbox(l1)[2] <= max_width and font.getbbox(l2)[2] <= max_width
                ):
                    return [l1, l2]
        return None

    # ── 優先順位: COND_SEP > 句読点 > CONJ_BEFORE > 助詞 ────────────────────
    # 各パスで全候補を収集し、テキスト中間点（45%）に最も近い分割点を選ぶ。
    # 「少し手前で切る」ことで2行のバランスが良くなる。
    _mid_target = len(text) * 0.45  # 少し手前（45%）が視覚的にバランスよい

    def _best_midpoint(candidates: list) -> list[str] | None:
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    # パス1: COND_SEP（幅制約あり）— midpoint最近傍を選択
    _hits1 = []
    for sep in _COND_SEPS:
        result = _try_split(sep, check_width=True)
        if result:
            _hits1.append((abs(len(result[0]) - _mid_target), result))
    if _hits1:
        return _best_midpoint(_hits1)

    # パス2: 句読点・CONJ_BEFORE（幅制約あり）
    for sep in ["！", "。", "、", *_CONJ_BEFORE]:
        result = _try_split(sep, check_width=True)
        if result:
            return result

    # パス2.5: CONJ_BEFORE（幅制約なし — フォント縮小前提）句読点の後の「実は」なども対象
    for sep in _CONJ_BEFORE:
        result = _try_split(sep, check_width=False)
        if result:
            return result

    # パス3: COND_SEP（幅制約なし — フォント縮小前提）— midpoint最近傍
    _hits3 = []
    for sep in _COND_SEPS:
        result = _try_split(sep, check_width=False)
        if result:
            _hits3.append((abs(len(result[0]) - _mid_target), result))
    if _hits3:
        return _best_midpoint(_hits3)

    # パス4: 助詞（幅制約あり）— midpoint最近傍
    _hits4 = []
    for sep in _PARTICLES:
        result = _try_split(sep, check_width=True)
        if result:
            _hits4.append((abs(len(result[0]) - _mid_target), result))
    if _hits4:
        return _best_midpoint(_hits4)

    # パス5: 助詞（幅制約なし）— midpoint最近傍
    _hits5 = []
    for sep in _PARTICLES:
        result = _try_split(sep, check_width=False)
        if result:
            _hits5.append((abs(len(result[0]) - _mid_target), result))
    if _hits5:
        return _best_midpoint(_hits5)

    lines, cur = [], ""
    for i, ch in enumerate(text):
        test = cur + ch
        if font.getbbox(test)[2] > max_width:
            if cur:
                # 次の文字が禁則文字なら現在行に含める
                if ch in _KINSOKU_HEAD:
                    cur += ch
                lines.append(cur)
            cur = "" if ch in _KINSOKU_HEAD else ch
            if len(lines) >= 2:
                lines.append(text[i + (1 if ch in _KINSOKU_HEAD else 0):])
                return lines[:3]
        else:
            cur = test
    if cur:
        lines.append(cur)
    return lines[:3]


def _rendered_line_width(text: str, font) -> int:
    """強調語の拡大描画を考慮した実際の描画幅を返す"""
    segments = _segment_text(text)
    if all(k == "normal" for _, k in segments):
        return font.getbbox(text)[2]
    try:
        emph_fs = min(FONT_MAX, int(font.size * _EMPH_SCALE))
    except AttributeError:
        emph_fs = FONT_MAX
    emph_font = load_font(emph_fs)
    total = 0
    for seg_text, kind in segments:
        fnt = emph_font if kind == "emph" else font
        total += fnt.getbbox(seg_text)[2]
    return total


def _best_font(text: str, max_width: int) -> tuple:
    """最大フォントサイズかつ最少行数（2行優先）でフォントを選ぶ。
    強調語の実際の描画幅（_EMPH_SCALE倍）を考慮して右端はみ出しを防ぐ。
    """
    best = None
    for size in range(FONT_MAX, FONT_MIN - 1, -FONT_STEP):
        font  = load_font(size)
        lines = _split_text(text, font, max_width)
        if all(_rendered_line_width(l, font) <= max_width for l in lines):
            if len(lines) <= 2:
                return font, size, lines
            if best is None:
                best = (font, size, lines)
    if best:
        return best
    font = load_font(FONT_MIN)
    return font, FONT_MIN, _split_text(text, font, max_width)


# ── バッジ ──────────────────────────────────────────────────────────────────

def _find_badge(text: str, force: str | None = None, title: str = "") -> tuple[str, tuple] | None:
    """テキストからバッジワードと色を取得する（タイトルに既出の単語はバッジにしない）"""
    if force:
        return force, (210, 20, 20)
    for w in _BADGE_WORDS_RED:
        if w in text and w not in title:
            return w, (210, 20, 20)
    for w in _BADGE_WORDS_YELLOW:
        if w in text and w not in title:
            return w, (210, 160, 0)
    return None


def _draw_badge(draw: ImageDraw.ImageDraw, word: str, color: tuple,
                x: int = TEXT_LEFT, y: int = 22) -> int:
    """角丸バッジを描画してバッジ下端のY座標を返す"""
    font  = load_font(40)
    bbox  = font.getbbox(word)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    px, py = 18, 8
    rx2 = x + tw + px * 2
    ry2 = y + th + py * 2
    draw.rounded_rectangle([x, y, rx2, ry2], radius=12, fill=color)
    draw.text((x + px, y + py), word, font=font, fill=(255, 255, 255), anchor="lt")
    return ry2 + 10


# ── 吹き出し ────────────────────────────────────────────────────────────────

def _draw_balloon(
    canvas: Image.Image,
    text: str,
    x: int,
    y: int,
    font_size: int = 28,
    max_width: int = 320,
) -> tuple[int, int, int, int]:
    """白い角丸吹き出しを描画する（バリアントB用・好奇心ギャップ強化）。
    戻り値: (x1, y1, x2, y2) バウンディングボックス（重複検知用）
    """
    font = load_font(font_size)
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    # テキストが長すぎる場合は縮小
    if tw > max_width:
        font = load_font(max(18, int(font_size * max_width / tw)))
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]

    px, py = 16, 10
    rx1, ry1 = x, y
    rx2 = x + tw + px * 2
    ry2 = y + th + py * 2

    # 右端はみ出し対策
    W = RESOLUTION[0]
    if rx2 > W - 10:
        shift = rx2 - (W - 10)
        rx1 -= shift
        rx2 -= shift

    balloon = Image.new("RGBA", RESOLUTION, (0, 0, 0, 0))
    draw = ImageDraw.Draw(balloon)
    draw.rounded_rectangle([rx1, ry1, rx2, ry2], radius=16, fill=(255, 255, 255, 240))
    # 少し影をつける
    draw.text((rx1 + px + 1, ry1 + py + 1), text, font=font, fill=(0, 0, 0, 80), anchor="lt")
    draw.text((rx1 + px, ry1 + py), text, font=font, fill=(30, 30, 30), anchor="lt")
    canvas.alpha_composite(balloon)
    return (rx1, ry1, rx2, ry2)


# ── 霊夢吹き出し（視聴者代弁・右下キャラ頭上） ──────────────────────────────

_REIMU_REACTIONS: list[str] = [
    "え、マジで!?",
    "知らなかった…",
    "私もやってた！",
    "これヤバくない!?",
    "うそ、ほんとに？",
    "え〜！そうなの？",
    "全然知らなかった！",
    "危なかった…",
    "今すぐ確認しなきゃ！",
    "私だけじゃないよね!?",
    "え！やばい！",
    "なんで誰も教えてくれないの！",
    "ちゃんとやらなきゃ…",
    "これ、うちの話じゃん！",
    "もっと早く知りたかった！",
]

# リアクションコメントとの類似カテゴリを避けるためのキーワードグループ
_REIMU_SIMILAR_GROUPS: list[list[str]] = [
    ["マジ", "うそ", "ヤバ", "やば", "ほんとに"],  # 衝撃・驚き系
    ["知らなかった", "知らな", "もっと早く"],        # 無知系
    ["私も", "私だけ", "うちの", "私のこと"],        # 自分ごと系
    ["今すぐ", "急いで", "確認"],                   # 緊急行動系
    ["なんで", "誰も", "教えて"],                   # 疑問・訴求系
]


def _pick_reimu_reaction(chosen_reaction_texts: list[str]) -> str:
    """リアクションコメントと内容が被らない霊夢吹き出しテキストを選ぶ。
    キーワードグループで使用済みカテゴリを検出し、そのカテゴリの候補を除外する。
    """
    used_groups: set[int] = set()
    for text in chosen_reaction_texts:
        for i, kws in enumerate(_REIMU_SIMILAR_GROUPS):
            if any(kw in text for kw in kws):
                used_groups.add(i)
    safe = [
        t for t in _REIMU_REACTIONS
        if not any(
            any(kw in t for kw in _REIMU_SIMILAR_GROUPS[i])
            for i in used_groups
        )
    ]
    return random.choice(safe if safe else _REIMU_REACTIONS)


# ── 魔理沙×霊夢 会話ペアプール（フォールバック用） ──────────────────────────
# AI生成が失敗した場合のフォールバック。●●は使わない（サムネ吹き出しに伏せ字禁止）。
# (魔理沙セリフ, 霊夢の返し) を一体で定義。
_MYSTERY_CONV_FALLBACK: list[tuple[str, str]] = [
    ("知らないと損するぞ！",                     "早く教えて！"),
    ("まだ知らないのか！？",                     "え、知らなかった…"),
    ("なんで誰も教えないんだ！",                 "ほんとそれ！"),
    ("ずっとだまされてたぞ！",                   "うそ、まじで!?"),
    ("これってヤバくないか！？",                 "やばい！まじで！"),
    ("続けた人とやめた人の差だぜ",               "私どっちだろ…"),
    ("知らないと損しつづけるぞ！",               "損したくない！"),
    ("気づいた時には手遅れだぞ！",               "ちょっと待って!?"),
    ("まだやってるのか！？",                     "え、ダメだったの!?"),
    ("取り返しつかなくなるぞ！",                 "どうすればいいの!?"),
    ("今やめないと後悔するぞ！",                 "やめる！今すぐ！"),
    ("放っておくと手遅れになるんだぜ！",         "やばい！やばい！"),
    ("よかれと思ってやってたのか！？",           "え、逆効果!?"),
    ("ずっと間違ってたのか！？",                 "ずっとやってたのに…"),
    ("正しいと思ってたのが全部ウソだったとはな！", "ウソだったの!?"),
    ("毎日やってたのに逆効果だったとはな！",     "ショック…"),
    ("そういうことだったとはな！",               "えーー！！"),
    ("こんなことになってたとはな！",             "えーー！！"),
    ("身体が悲鳴を上げてたとはな！",             "気づいてなかった…"),
    ("これが毎日の不調の正体だったんだぜ！",     "正体!?"),
    ("みんな気づかずにやってるんだぜ",           "私もかも…"),
    ("もっと早く知りたかったぜ！",               "私も知りたかった！"),
    ("私が教えてやるから見てみろ！",             "気になりすぎる！"),
    ("後悔する前に知っておけぞ！",               "知りたい！"),
    ("これが原因だったとはな！",                 "えーー！！"),
    ("ずっとやってたのに間違いだったとはな！",   "ショック…"),
    ("毎日やってたのに何の意味もなかったんだぜ！", "え、意味なかったの!?"),
    ("30日で身体が変わるぞ！",                   "そんなに早く!?"),
    ("むしろ悪化してたとはな！",                 "えーー！！"),
    ("身体が静かに壊れてたとはな！",             "気づかなかった…"),
]


def _generate_mystery_conversation(title: str) -> tuple[str, str] | None:
    """AIを使ってタイトルに連動した魔理沙・霊夢の吹き出し会話ペアを生成する。

    ルール:
    - 魔理沙: タイトルの内容を補足・煽る（男口調「〜だぜ」「〜ぞ！」「〜とはな！」）
    - 霊夢: タイトルの内容に驚き・共感（「え、〜!?」「私も〜」「〜だったの!?」）
    - ●●（伏せ字）は使用禁止
    - 各セリフ20文字以内
    - タイトルを読んだ視聴者が見て意味が通じること

    失敗時は None を返す（呼び出し側でフォールバック）。
    """
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        from providers import get_llm_client
        import model_config
        from script_repair import extract_json_safe
    except ImportError:
        return None

    prompt = (
        "あなたはYouTubeサムネイルの専門家です。\n"
        "以下のタイトルに対して、魔理沙と霊夢の吹き出しテキストを1ペア生成してください。\n\n"
        f"タイトル: {title}\n\n"
        "## ルール\n"
        "- 魔理沙（煽り役）: タイトルの内容を補足・煽る短いセリフ。男口調（〜だぜ/〜ぞ！/〜とはな！/〜のか！？）\n"
        "  例: 「正しいと思ってたのが全部ウソだったとはな！」「まだやってるのか！？」\n"
        "- 霊夢（共感役）: タイトルの内容に対する驚き・共感・自分ごと化。女口調（〜!?/〜かも…/〜だったの!?）\n"
        "  例: 「私もその一人かも…」「え、ダメだったの!?」\n"
        "- 各セリフは20文字以内（短いほど良い）\n"
        "- ●●（伏せ字）は使用禁止\n"
        "- タイトルのテーマ・キーワードに言及し、タイトルを読んだ人が見て意味が通じること\n"
        "- 会話として噛み合うこと（魔理沙の煽り→霊夢のリアクション）\n\n"
        '## 出力形式（JSONのみ・前置き不要）\n'
        '{"marisa": "セリフ", "reimu": "セリフ"}\n'
    )

    try:
        llm = get_llm_client()
        raw = llm.generate(prompt, model_config.SIMPLE)
        result = extract_json_safe(raw)
        if not isinstance(result, dict):
            return None
        marisa = result.get("marisa", "").strip()
        reimu = result.get("reimu", "").strip()
        if not marisa or not reimu:
            return None
        # バリデーション: 長さ制限
        if len(marisa) > 25 or len(reimu) > 25:
            # 少し長い程度なら許容（描画時にフォント縮小で対応可能）
            if len(marisa) > 35 or len(reimu) > 35:
                print(f"  [吹き出し] セリフが長すぎるため不採用: 魔理沙{len(marisa)}字/霊夢{len(reimu)}字")
                return None
        # バリデーション: ●●禁止
        if "●" in marisa or "●" in reimu:
            marisa = marisa.replace("●●", "").replace("●", "")
            reimu = reimu.replace("●●", "").replace("●", "")
        # セルフチェック: タイトルとの関連性
        if not _check_bubble_relevance(title, marisa, reimu, llm):
            print(f"  [吹き出し] タイトルとの関連性チェック不合格 → フォールバック")
            return None
        print(f"  [吹き出し] AI生成成功: 魔理沙「{marisa}」/ 霊夢「{reimu}」")
        return (marisa, reimu)
    except Exception as e:
        print(f"  [吹き出し] AI生成失敗: {e}")
        return None


def _check_bubble_relevance(title: str, marisa: str, reimu: str, llm) -> bool:
    """吹き出しがタイトルの内容と関連しているかセルフチェックする。
    「この吹き出しはタイトルを読んだ人が見て意味が通じるか？」を判定。
    """
    import model_config
    from script_repair import extract_json_safe

    prompt = (
        "以下のYouTubeサムネイルの吹き出しテキストが、タイトルの内容と関連しているか判定してください。\n\n"
        f"タイトル: {title}\n"
        f"魔理沙の吹き出し: {marisa}\n"
        f"霊夢の吹き出し: {reimu}\n\n"
        "## チェック項目\n"
        "1. タイトルを読んだ視聴者がこの吹き出しを見て「このタイトルの動画の吹き出しだ」と意味が通じるか？\n"
        "2. 吹き出しがタイトルのテーマと全く無関係な内容になっていないか？\n"
        "3. 魔理沙と霊夢の会話が噛み合っているか？\n\n"
        '出力: {"ok": true} または {"ok": false, "reason": "理由"}\n'
    )

    try:
        raw = llm.generate(prompt, model_config.SIMPLE)
        result = extract_json_safe(raw)
        if isinstance(result, dict):
            ok = result.get("ok", False)
            if not ok:
                reason = result.get("reason", "不明")
                print(f"  [吹き出しチェック] NG: {reason}")
            return bool(ok)
    except Exception:
        pass
    # チェック失敗時はOKとして通す（AI障害でサムネ生成全体を止めない）
    return True


def _make_mystery_conversation(title: str) -> tuple[str, str]:
    """タイトルに連動した会話ペア（魔理沙セリフ, 霊夢の返し）を返す。

    優先順位:
      1. AI生成（タイトル連動・セルフチェック付き）
      2. フォールバック: 静的プールからランダム選択
    """
    # AI生成を試行
    ai_result = _generate_mystery_conversation(title)
    if ai_result:
        return ai_result
    # フォールバック: 静的プール
    print(f"  [吹き出し] フォールバック: 静的プールから選択")
    return random.choice(_MYSTERY_CONV_FALLBACK)


def _draw_marisa_speech_bubble(
    canvas: Image.Image,
    text: str,
    marisa_x: int,
    marisa_y: int,
    marisa_w: int,
    font_size: int = 30,
    bubble_y: int | None = None,
) -> None:
    """魔理沙頭上に白い吹き出し（しっぽ付き）で煽りテキストを描画する。
    bubble_y: 吹き出し上端Y座標（霊夢と統一するため外部指定）。"""
    px, py = 14, 10
    max_bubble_w = min(500, RESOLUTION[0] - 16)

    font = load_font(font_size)
    for _ in range(8):
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
        if tw + px * 2 <= max_bubble_w or font_size <= 20:
            break
        font_size -= 2
        font = load_font(font_size)

    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    bubble_w = tw + px * 2
    bubble_h = th + py * 2
    tail_h = 8

    # 魔理沙の頭上・キャンバス中央寄りに配置（左端を魔理沙の中心付近に）
    bx1 = marisa_x + marisa_w // 2 - bubble_w // 2
    bx2 = bx1 + bubble_w
    # 右端はみ出し防止
    if bx2 > RESOLUTION[0] - 8:
        shift = bx2 - (RESOLUTION[0] - 8)
        bx1 -= shift
        bx2 = RESOLUTION[0] - 8
    if bx1 < 8:
        bx1 = 8
        bx2 = min(bx1 + bubble_w, RESOLUTION[0] - 8)

    # 吹き出し位置: bubble_y=霊夢の頭Y座標を基準に両キャラ統一
    _ref_y = bubble_y if bubble_y is not None else marisa_y
    by1 = _ref_y - bubble_h - tail_h
    by2 = by1 + bubble_h

    # しっぽ: 吹き出し下端からキャラの顔へ（常に下向き）
    tail_tip_x = marisa_x + marisa_w * 2 // 5
    tail_tip_y = max(by2 + 15, marisa_y + 10)

    surf = Image.new("RGBA", RESOLUTION, (0, 0, 0, 0))
    d = ImageDraw.Draw(surf)

    d.rounded_rectangle([bx1, by1, bx2, by2], radius=14,
                        fill=(255, 255, 255, 245), outline=(200, 200, 200, 180), width=2)

    tail_base_x = max(bx1 + 20, min(bx2 - 20, tail_tip_x))
    tail_poly = [
        (tail_base_x - 10, by2),
        (tail_base_x + 10, by2),
        (tail_tip_x,       tail_tip_y),
    ]
    d.polygon(tail_poly, fill=(255, 255, 255, 245))

    tx = bx1 + px
    ty = by1 + py
    d.text((tx + 1, ty + 1), text, font=font, fill=(0, 0, 0, 60), anchor="lt")
    d.text((tx, ty), text, font=font, fill=(30, 30, 30, 255), anchor="lt")

    canvas.alpha_composite(surf)


def _draw_reimu_speech_bubble(
    canvas: Image.Image,
    text: str,
    reimu_rx: int,
    reimu_ry: int,
    reimu_w: int,
    font_size: int = 30,
    bubble_y: int | None = None,
) -> None:
    """霊夢頭上に白い吹き出し（しっぽ付き）で視聴者代弁の一言を描画する。"""
    px, py = 14, 10
    # 霊夢の右端〜キャンバス右端 + 左に少しはみ出せる分が使える最大幅
    max_bubble_w = RESOLUTION[0] - 8 - max(0, reimu_rx - 40)

    # テキストが収まるよう必要ならフォントサイズを縮小
    font = load_font(font_size)
    for _ in range(8):
        bbox = font.getbbox(text)
        tw = bbox[2] - bbox[0]
        if tw + px * 2 <= max_bubble_w or font_size <= 20:
            break
        font_size -= 2
        font = load_font(font_size)

    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    bubble_w = tw + px * 2
    bubble_h = th + py * 2
    tail_h = 8   # しっぽの高さ（最小限）

    # 吹き出しを霊夢の頭上・右寄りに配置
    bx1 = reimu_rx + reimu_w // 2 - bubble_w // 2
    bx2 = bx1 + bubble_w
    # 右端はみ出し防止（優先: これを後で上書きしない）
    if bx2 > RESOLUTION[0] - 8:
        shift = bx2 - (RESOLUTION[0] - 8)
        bx1 -= shift
        bx2 = RESOLUTION[0] - 8
    # 左端: キャンバス内に収める（右端クリップが既に反映された後で適用）
    if bx1 < 8:
        bx1 = 8
        bx2 = min(bx1 + bubble_w, RESOLUTION[0] - 8)

    # 吹き出し位置: bubble_y=霊夢の頭Y座標を基準に両キャラ統一
    _ref_y = bubble_y if bubble_y is not None else reimu_ry
    by1 = _ref_y - bubble_h - tail_h
    by2 = by1 + bubble_h

    # しっぽの先端: 霊夢の顔中央付近（常に下向き）
    tail_tip_x = reimu_rx + reimu_w * 2 // 5
    tail_tip_y = max(by2 + 15, reimu_ry + 10)

    surf = Image.new("RGBA", RESOLUTION, (0, 0, 0, 0))
    d = ImageDraw.Draw(surf)

    # 白い丸角矩形
    d.rounded_rectangle([bx1, by1, bx2, by2], radius=14,
                        fill=(255, 255, 255, 245), outline=(200, 200, 200, 180), width=2)

    # しっぽ（三角ポリゴン: 吹き出し底辺の内側からReimu頭頂へ）
    tail_base_x = max(bx1 + 20, min(bx2 - 20, tail_tip_x))
    tail_poly = [
        (tail_base_x - 10, by2),
        (tail_base_x + 10, by2),
        (tail_tip_x,       tail_tip_y),
    ]
    d.polygon(tail_poly, fill=(255, 255, 255, 245))

    # テキスト（黒文字、薄影付き）
    tx = bx1 + px
    ty = by1 + py
    d.text((tx + 1, ty + 1), text, font=font, fill=(0, 0, 0, 60), anchor="lt")
    d.text((tx, ty), text, font=font, fill=(30, 30, 30, 255), anchor="lt")

    canvas.alpha_composite(surf)


# ── ミステリーボトムテキスト ─────────────────────────────────────────────────

def _make_mystery_text(title: str) -> str:
    """タイトルからミステリーテキストを生成（後方互換用ラッパー）。
    内部では _make_mystery_conversation を使用し魔理沙テキストのみ返す。
    霊夢の返しが必要な場合は _make_mystery_conversation を直接使うこと。
    """
    return _make_mystery_conversation(title)[0]


def _make_mystery_text_full(title: str) -> str:
    """旧実装（参照用アーカイブ）。実際には _make_mystery_conversation を使う。"""
    # ── 損失回避（失うことへの恐怖） ─────────────────────────
    if re.search(r"(危険|害|リスク|ヤバ|禁止|悪化|老化|蝕む|弱る|壊す|毒)", title):
        return random.choice([
            "すでに●●が消えてるぞ！",
            "●●がじわじわ壊れてるぜ",
            "気づいた時には手遅れだぞ！",
            "知らないと損するぞ！",
            "まだやってるのか！？",
            "身体がどんどん●●になるぜ",
            "取り返しつかなくなるぞ！",
            "知らなかったじゃ済まないぜ",
            "今すぐやめないと●●になるぞ！",
        ])

    # ── 歯・口腔テーマ ───────────────────────────────────────
    if re.search(r"(歯|口腔|歯茎|虫歯|歯周|フロス|歯ブラシ|口臭|歯磨き|歯みがき)", title):
        return random.choice([
            "口の中で●●が起きてるぞ",
            "磨けてると思ってたのか！？",
            "実はな、●●が原因だったんだぜ",
            "知らないと損するぞ！",
            "毎日磨いてるのに意味ないぞ！",
            "歯医者も驚いた●●だぜ",
            "ずっとやってたのか！？",
        ])

    # ── 身体的変化（体に何かが起きる） ──────────────────────
    if re.search(r"(体|血|内臓|腸|脳|心臓|肌|髪|白髪|骨|細胞|免疫|筋肉)", title):
        return random.choice([
            "身体の中で●●が起きてるぞ",
            "●●がみるみる変わっていくぜ",
            "内側から●●になってたんだぜ",
            "気づかないうちに●●が進むぞ",
            "自分の身体が●●になってるぞ！",
            "こんなことになってたとはな！",
            "知らないと損するぞ！",
            "余裕だと思ってたのか！？",
        ])

    # ── 食べ物・飲み物テーマ（続けると変わる） ──────────────
    if re.search(r"(食べ|飲む|飲み続|食習慣|毎日食|食事|コーヒー|緑茶|お茶|アルコール)", title):
        return random.choice([
            "1ヶ月で身体が激変するぜ",
            "続けると●●が起きるぞ！",
            "やめたとたん●●がよくなるぜ",
            "毎日やってたのか！？",
            "知らないと損するぞ！",
            "これがずっと●●を壊してたんだぜ",
            "もっと早く知りたかったぜ！",
            "ずっと信じてたのか！？",
        ])

    # ── 期待裏切り（思ってたことと違う） ────────────────────
    if re.search(r"(実は|意外|まさか|衝撃|知らなかった|嘘)", title):
        return random.choice([
            "そういうことだったとはな！",
            "ずっと信じてたことが●●だったぞ",
            "よかれと思ってたのか！？",
            "常識が実は●●だったんだぜ",
            "知らないと損するぞ！",
            "私が教えてやるから見てみろ！",
            "なんで誰も教えないんだ！",
            "ずっとだまされてたぞ！",
        ])

    # ── 習慣・行動テーマ ─────────────────────────────────────
    if re.search(r"(習慣|続ける|毎日|ルーティン|やめる)", title):
        return random.choice([
            "続けた人とやめた人の差を見ろ",
            "30日で身体が変わるぞ！",
            "やめたら●●が消えたぜ",
            "知らないと損するぞ！",
            "まだ続けてるのか！？",
            "1日●●分で結果が出るんだぜ",
            "やらないと損しつづけるぞ！",
            "なぜ続けてきたんだ！？",
        ])

    # ── 比較・格差（やる/やらないの差） ────────────────────
    if re.search(r"(ランキング|比較|差|違い|vs)", title):
        return random.choice([
            "知ってる人と知らない人の差だぜ",
            "やった人だけ●●が変わるんだぞ",
            "やらない人は損しつづけるぜ",
            "知らないと損するぞ！",
            "この差ってヤバくないか！？",
            "なぜこんなに違うんだ！",
        ])

    # ── 権威性（医師・研究・データ） ────────────────────────
    if re.search(r"(医師|専門家|研究|データ|論文|証明|発表|学会)", title):
        return random.choice([
            "お医者さんも驚いた●●だぜ",
            "研究でわかった●●の真実だぜ",
            "専門家が警告してるんだぞ！",
            "知らないと損するぞ！",
            "データが示す●●の事実だぜ！",
            "なぜ誰も教えないんだ！",
        ])

    # ── 数字強調テーマ ───────────────────────────────────────
    if re.search(r"([0-9０-９]|倍|%|割|人に1人|万人)", title):
        return random.choice([
            "たった●●日で身体が変わるぞ",
            "知らないと損するぞ！",
            "この数字ヤバくないか！？",
            "●●万人がやってる方法だぜ",
            "もっと早く知りたかったぜ！",
            "まだ知らないのか！？",
        ])

    # ── 睡眠・ストレス・メンタル ────────────────────────────
    if re.search(r"(睡眠|眠れ|不眠|ストレス|メンタル|うつ|疲れ|疲労|だるい)", title):
        return random.choice([
            "●●が原因で眠れてないんだぞ",
            "試したら●●がみるみる良くなるぜ",
            "知らないと損するぞ！",
            "これをやめたら●●が消えるぜ",
            "まだ我慢してるのか！？",
            "なぜ眠れないか教えてやるぜ",
            "ずっと疲れてたのはこれのせいだぞ！",
        ])

    # ── 変化・効果テーマ ─────────────────────────────────────
    if re.search(r"(変化|変わる|効果|効く|改善|向上)", title):
        return random.choice([
            "実はな、●●になってたんだぜ",
            "たった●●で結果が出るんだぜ",
            "●●日後に身体が変わるぞ！",
            "続けた人の身体が●●になるぜ",
            "知らないと損するぞ！",
            "本当に効くのか確認してみろ！",
            "もっと早くやっておけばよかったんだぜ！",
        ])

    # ── 逆張り・否定パターン ────────────────────────────────
    if re.search(r"(逆効果|やってはいけない|NG|ダメ|間違い)", title):
        return random.choice([
            "実はな、●●は逆効果だったんだぜ",
            "●●をやめたら身体が変わったぞ",
            "ずっと間違ってたのか！？",
            "これが間違いだったとは思わなかっただろ！",
            "知らないと損するぞ！",
            "よかれと思ってやってたのか！？",
        ])

    # ── デフォルト ───────────────────────────────────────────
    return random.choice([
        "知らないと損するぞ！",
        "実はな、●●になってたんだぜ",
        "まだ知らないのか！？",
        "なんで誰も教えないんだ！",
        "私が教えてやるから見てみろ！",
        "ずっとだまされてたぞ！",
        "まだ気づいてないのか！？",
        "●●が身体に起きてるんだぜ",
        "知らないと損しつづけるぞ！",
        "これって本当にヤバいぞ！",
    ])


# 分割時に行頭として認識するフック語（2行目を長く・インパクトを後に持たせる）
# ※「あなた」は直後に「は」が続くことが多く行頭助詞になりやすいため除外
_MYSTERY_HOOK_PREFIXES = [
    # 長いものを先に並べて短い前方一致が誤って優先されないようにする
    "じつは", "実は", "ずっと", "なんで", "なぜか", "知らないと",
    "これって", "まだ", "これ", "なぜ", "もし", "あの", "その", "では", "でも",
]


def _split_mystery_lines(text: str) -> list[str]:
    """ミステリーテキストを見やすい2行に分割する。
    優先順位:
      ① ●●直前で分割
      ② 「まだ」「ずっと」等フック語で始まる場合は早期分割（フック行 / 本文行）
      ③ 中間付近の助詞・区切りで分割（2行目が句読点のみになる場合はスキップ）
      ④ 中間強制分割
    """
    if len(text) <= 7:
        return [text]
    mid = len(text) // 2

    # ① ●+ グループの直前で分割（グループが行頭の場合はスキップ）
    #    例: "気づいたら●●が限界に" → "気づいたら" / "●●が限界に"
    #    例: "●●がじわじわ..." → 行頭なのでスキップ → ③の助詞分割へ
    m = re.search(r"●+", text)
    if m and m.start() > 0:
        return [text[: m.start()], text[m.start() :]]

    # ② フック語で始まる場合: フック語を1行目・残りを2行目に（見やすさ重視）
    for prefix in _MYSTERY_HOOK_PREFIXES:
        if text.startswith(prefix) and len(text) - len(prefix) >= 4:
            return [prefix, text[len(prefix):]]

    # ③ 中間前後6文字以内で助詞・区切り文字を探す（右側優先）
    #    以下のケースはスキップ:
    #      a) 2行目が句読点のみ（例: "てるの" / "!?" は不自然）
    #      b) 複合助詞「には」「とも」「でも」等の途中（次の文字が助詞）→ 行頭助詞を防ぐ
    _PUNCT_ONLY = re.compile(r'^[！？!?…。、]+$')
    _COMPOUND_NEXT = {"に": "はもを", "で": "はもを", "と": "はも"}
    candidates = "がはをにでとのも…。、"  # 「か」は動詞活用「なかった」等で、「や」は「やめた」等の動詞頭で誤分割するため除外
    for offset in range(7):
        for i in [mid + offset, mid - offset]:
            if 0 < i < len(text) - 1 and text[i] in candidates:
                second = text[i + 1:]
                # a) 句読点のみになる分割はスキップ
                if _PUNCT_ONLY.fullmatch(second):
                    continue
                # b) 複合助詞の途中で切れる場合はスキップ（2行目が助詞始まり）
                next_ch = text[i + 1] if i + 1 < len(text) else ""
                if next_ch in _COMPOUND_NEXT.get(text[i], ""):
                    continue
                return [text[: i + 1], second]

    # ④ 見つからなければ中間強制分割
    return [text[:mid], text[mid:]]


def _calc_line_widths(parts: list[str], font, circle_r: int, circle_gap: int) -> list[int]:
    """各パーツの描画幅を計算して返す"""
    widths: list[int] = []
    for part in parts:
        if not part:
            widths.append(0)
        elif re.match(r"●+", part):
            n = len(part)
            widths.append(n * circle_r * 2 + (n - 1) * circle_gap)
        else:
            widths.append(font.getbbox(part)[2])
    return widths


def _draw_text_line_on_surf(
    draw, parts: list[str], part_widths: list[int],
    x_start: int, y_base: int, fs: int,
    font, circle_r: int, circle_gap: int, outline_w: int,
    fill_color: tuple = (255, 255, 255),
    outline1: tuple = (0, 0, 0),
    outline2: tuple | None = None,
) -> None:
    """1行分の縁取り＋本文をサーフェスに描画する。
    outline2が指定された場合は二重縁取り（outline1=外縁・太, outline2=内縁・細）。
    """
    text_h = int(fs * 1.25)
    step = max(1, outline_w // 3)

    def _outline_text(x_cur, y_b, part, pw, color, ow):
        if re.match(r"●+", part):
            n = len(part)
            for i in range(n):
                xc = x_cur + i * (circle_r * 2 + circle_gap) + circle_r
                yc = y_b + text_h // 2
                draw.ellipse(
                    [xc - circle_r - ow, yc - circle_r - ow,
                     xc + circle_r + ow, yc + circle_r + ow],
                    fill=color,
                )
        else:
            s = max(1, ow // 3)
            for dx in range(-ow, ow + 1, s):
                for dy in range(-ow, ow + 1, s):
                    if dx != 0 or dy != 0:
                        draw.text((x_cur + dx, y_b + dy), part,
                                  font=font, fill=color, anchor="lt")

    # 外縁（outline1）
    x_cur = x_start
    for part, pw in zip(parts, part_widths):
        if not part or pw == 0:
            x_cur += pw; continue
        _outline_text(x_cur, y_base, part, pw, outline1, outline_w)
        x_cur += pw

    # 内縁（outline2 = 二重縁取り時のみ）
    if outline2 is not None:
        inner_w = max(4, outline_w // 2)
        x_cur = x_start
        for part, pw in zip(parts, part_widths):
            if not part or pw == 0:
                x_cur += pw; continue
            _outline_text(x_cur, y_base, part, pw, outline2, inner_w)
            x_cur += pw

    # 本文
    x_cur = x_start
    for part, pw in zip(parts, part_widths):
        if not part or pw == 0:
            x_cur += pw; continue
        if re.match(r"●+", part):
            n = len(part)
            for i in range(n):
                xc = x_cur + i * (circle_r * 2 + circle_gap) + circle_r
                yc = y_base + text_h // 2
                draw.ellipse(
                    [xc - circle_r, yc - circle_r,
                     xc + circle_r, yc + circle_r],
                    fill=(220, 30, 30),
                )
        else:
            draw.text((x_cur, y_base), part, font=font,
                      fill=fill_color, anchor="lt")
        x_cur += pw


def _mystery_approx_rect(v: dict, text: str) -> tuple[int, int, int, int]:
    """バリアント v のミステリーオーバーレイ近似バウンディングボックスを返す（重複検知用）"""
    scale = v["scale"]
    fs_est = min(150, int(_MYSTERY_FS * scale))
    lines = _split_mystery_lines(text)
    # 日本語1文字の平均幅 ≈ fs * 0.9 で近似
    max_chars = max(len(ln) for ln in lines)
    sw = int(max_chars * fs_est * 0.9 + 40)
    sh = int(fs_est * 1.25 * len(lines) + 30)
    angle_rad = math.radians(v["angle"])
    ca, sa = abs(math.cos(angle_rad)), abs(math.sin(angle_rad))
    rot_w = int(sw * ca + sh * sa)
    rot_h = int(sw * sa + sh * ca)
    cx = int(RESOLUTION[0] * v["x_frac"])
    cy = int(RESOLUTION[1] * v["y_frac"])
    rx = cx - rot_w // 2
    ry = cy - rot_h // 2
    ry = min(ry, RESOLUTION[1] - rot_h - 5)
    ry = max(ry, RESOLUTION[1] // 5)
    return (rx, ry, rx + rot_w, ry + rot_h)


def _rect_overlap_area(r1: tuple, r2: tuple) -> int:
    """2つの矩形 (x1,y1,x2,y2) の重複面積"""
    ox = max(0, min(r1[2], r2[2]) - max(r1[0], r2[0]))
    oy = max(0, min(r1[3], r2[3]) - max(r1[1], r2[1]))
    return ox * oy


def _select_mystery_variant(
    text: str,
    occupied_rects: list[tuple[int, int, int, int]] | None = None,
) -> dict:
    """重複が最小になるミステリーオーバーレイバリアントを選択して返す。"""
    occupied_rects = occupied_rects or []
    shuffled = list(_MYSTERY_OVERLAY_VARIANTS)
    random.shuffle(shuffled)
    if occupied_rects:
        return min(
            shuffled,
            key=lambda cv: sum(
                _rect_overlap_area(_mystery_approx_rect(cv, text), occ)
                for occ in occupied_rects
            ),
        )
    return shuffled[0]


def _draw_mystery_overlay(
    canvas: Image.Image,
    text: str,
    occupied_rects: list[tuple[int, int, int, int]] | None = None,
    target_cy: int | None = None,
    preselected_v: dict | None = None,
) -> None:
    """ミステリーテキストを黒帯なしで大きく斜め/水平オーバーレイ描画する。
    ・●●は赤い塗り円で描画
    ・テキストは自然な区切りで2行に分割
    ・occupied_rects で指定された既描画要素（いらすとや・吹き出し）と
      重複が最小になるバリアントを自動選択する
    ・preselected_v を渡すと選択をスキップしてそのバリアントを使う
    """
    occupied_rects = occupied_rects or []

    # バリアント選択（事前選択があればそれを優先）
    if preselected_v is not None:
        v = preselected_v
    else:
        v = _select_mystery_variant(text, occupied_rects)

    angle    = 0           # ミステリーテキストは常に水平（斜めなし）
    scale    = v["scale"]
    align    = v.get("align", "right")
    cx_pos   = int(RESOLUTION[0] * v["x_frac"])
    cy_pos   = target_cy if target_cy is not None else int(RESOLUTION[1] * v["y_frac"])
    style_d  = _OVERLAY_STYLES.get(v.get("style", "white"), _OVERLAY_STYLES["white"])
    fill_color = style_d["fill"]
    outline1   = style_d["outline1"]
    outline2   = style_d["outline2"]
    outline_w_base = style_d["outline_w"]

    # 2行分割
    lines = _split_mystery_lines(text)

    # フック語（短い1行目）が右寄せだと不自然 → 左揃えに強制
    if len(lines) >= 2 and len(lines[0]) <= 4 and align == "right":
        align = "left"

    # フォントサイズ決定（スケール適用、最大150px）
    fs = min(150, int(_MYSTERY_FS * scale))
    font = load_font(fs)
    circle_r   = int(fs * 0.40)
    circle_gap = 10
    max_overlay_w = int(RESOLUTION[0] * 0.82)

    # バリアントC（target_cy指定時）: 魔理沙の右隣から左揃えで描画
    # 魔理沙: alpha_bbox右=390, canvas x=10 → 視覚右端=400, 余裕+10 → 左境界=410
    # テキスト右端を730に絞り、テキスト塊を魔理沙側（左半分）に確実に収める
    if target_cy is not None:
        _safe_x_left  = 410
        _safe_x_right = 730   # 絞り: 510px→320px。中心=570px(魔理沙側)
        max_overlay_w = _safe_x_right - _safe_x_left  # 320px
        cx_pos = _safe_x_left  # 左端から開始（中央ではなく左端基準に変更）
        align = "left"          # 魔理沙の口から言葉が出る方向＝左揃え

    # 全行の中で最大幅に収まるようフォント縮小
    def _max_line_w(f, cr):
        return max(
            sum(_calc_line_widths(re.split(r"(●+)", ln), f, cr, circle_gap))
            for ln in lines
        )

    # target_cy（魔理沙側ゾーン=320px）では320px内に収めるため下限を下げる
    _fs_min = 40 if target_cy is not None else 70
    while _max_line_w(font, circle_r) > max_overlay_w and fs > _fs_min:
        fs -= 6
        font      = load_font(fs)
        circle_r  = int(fs * 0.40)

    text_h   = int(fs * 1.25)
    line_gap = int(fs * 0.15)
    outline_w = max(outline_w_base, fs // 12)
    pad = outline_w + 10

    # 全行のパーツ幅を計算
    all_parts: list[list[str]]  = [re.split(r"(●+)", ln) for ln in lines]
    all_widths: list[list[int]] = [
        _calc_line_widths(p, font, circle_r, circle_gap) for p in all_parts
    ]
    max_w = max(sum(ws) for ws in all_widths)

    surf_w = max_w + pad * 2
    surf_h = text_h * len(lines) + line_gap * (len(lines) - 1) + pad * 2
    surf   = Image.new("RGBA", (surf_w, surf_h), (0, 0, 0, 0))
    draw   = ImageDraw.Draw(surf)
    # 背景パネルなし — 縁取りで十分な視認性を確保する

    for row, (parts, widths) in enumerate(zip(all_parts, all_widths)):
        line_w = sum(widths)
        # 水平パターン: 中央揃え / 斜めパターン: 右端揃え / フック語: 左揃え
        if align == "center":
            x_start = pad + (max_w - line_w) // 2
        elif align == "left":
            x_start = pad
        else:
            x_start = pad + (max_w - line_w)
        y_base  = pad + row * (text_h + line_gap)
        _draw_text_line_on_surf(
            draw, parts, widths, x_start, y_base, fs,
            font, circle_r, circle_gap, outline_w_base,
            fill_color=fill_color, outline1=outline1, outline2=outline2,
        )

    # 回転してキャンバスに合成
    rotated = surf.rotate(angle, expand=True, resample=Image.BICUBIC)
    ry = cy_pos - rotated.height // 2
    ry_max = RESOLUTION[1] - rotated.height - 5
    ry = min(ry, ry_max)
    ry = max(ry, RESOLUTION[1] // 5)

    if target_cy is not None:
        # バリアントC: 魔理沙の右隣（x=410）から左揃えで配置
        _safe_x_left  = 410
        _safe_x_right = 730   # テキスト塊を魔理沙側（左半分）に収める
        rx = _safe_x_left  # 左端固定
        rx = min(rx, _safe_x_right - rotated.width)  # 右境界を超えない
        rx = max(rx, _safe_x_left)
    else:
        rx = cx_pos - rotated.width // 2
        rx = max(0, min(rx, RESOLUTION[0] - rotated.width))

    canvas.alpha_composite(rotated, dest=(rx, ry))


# ── キャプション解析 ─────────────────────────────────────────────────────────

def _parse_caption(
    thumbnail_caption: str | None,
    title: str,
    text_max_w: int,
) -> tuple[list[str], int]:
    """AIキャプション（「行1|行2」形式）またはタイトルからテキスト行とフォントサイズを返す。
    line2 が長すぎる場合は _split_text で自動分割する。
    """
    if thumbnail_caption:
        parts = thumbnail_caption.strip().split("|", 1)
        line1 = parts[0].strip() if parts else title
        line2 = parts[1].strip() if len(parts) > 1 else ""
        for size in range(FONT_MAX, FONT_MIN - 1, -FONT_STEP):
            font = load_font(size)
            # 両行とも強調込みの実描画幅で判定（3行化を防止）
            if _rendered_line_width(line1, font) <= text_max_w:
                if not line2:
                    return [line1], size
                if _rendered_line_width(line2, font) <= text_max_w:
                    return [line1, line2], size
        # フォント最小でも収まらない場合は2行で返す
        return ([line1, line2] if line2 else [line1]), FONT_MIN

    font, font_size, lines = _best_font(title, text_max_w)
    return lines, font_size


# ── バリアント別テキスト変形 ─────────────────────────────────────────────────

# ── ブラックボックス記号（〇〇統一・バリアント別カラーで差別化）──────────────────
# 全バリアントで〇〇のみ使用。色によってバリアントを区別する。
_MASK_SYMBOLS_A = ["〇〇"]  # A: 黄色〇〇
_MASK_SYMBOLS_B = ["〇〇"]  # B: 赤〇〇
_MASK_SYMBOLS_C = ["〇〇"]  # C: エメラルド〇〇

# バリアント別〇〇カラー（白背景との対比 + 各バリアントの雰囲気に合わせた色）
_MASK_EMPH_COLORS: dict[str, tuple[int, int, int]] = {
    "A": (255, 240, 20),   # 黄色（明るい・スタンダード）
    "B": (255, 60, 60),    # 赤（緊急・注意喚起・CTR最大化）
    "C": (20, 220, 160),   # エメラルド（健康・清潔感・爽やかさ）
}
# 現在描画中のバリアントのマスクカラー（make_thumbnail で設定）
_CURRENT_MASK_COLOR: tuple[int, int, int] = (255, 240, 20)

# 既存マスク記号の検出パターン
_MASK_SYMBOL_RE = re.compile(r"[〇○]{2,}")

# 隠すと最も好奇心を引くパワーワード（先にこれをマスク候補にする）
_POWER_KEYWORD_RE = re.compile(
    r"(老化|糖化|炎症|酸化|腸内|血糖|血圧|睡眠不足|睡眠|食べ方|飲み方|摂り方|"
    r"食習慣|習慣|成分|栄養素|ホルモン|腸内細菌|菌|毒素|発がん|がん|認知症|"
    r"動脈硬化|血栓|心筋梗塞|脳梗塞|糖尿病|肥満|メタボ|免疫|アレルギー|"
    r"コルチゾール|インスリン|コレステロール|中性脂肪)"
)

# ── タイトル構造検出 ─────────────────────────────────────────────────────────
# 「XするとYはどう変わるのか」系: アクション部＋対象部＋疑問で構成
_HOW_CHANGE_RE = re.compile(
    r"^(.+?)(と|で|たら|ても|れば)(.+?)"
    r"(は|が)?(どう変わる|どうなる|どんな効果|何が起き|がどうなる|はどうなる|はどう変"
    r"|どんな変化が起き|どんなことが起き|どんな影響が|どのような変化|どのような影響)",
    re.DOTALL,
)
# 「Xを飲む/食べる/続けると何が起きる」パターン（は/がなし）
_DO_EFFECT_RE = re.compile(
    r"^(.+?[をが].+?[むるけう])(と|で|たら)(.+?)(どうなる|どう変わる|何が起きる|の効果|への影響)",
    re.DOTALL,
)
# 「XがYを○○する/した」パターン（原因→結果で結果が隠せる）
_CAUSE_RESULT_RE = re.compile(
    r"^(.+?[がはでもを].+?)(原因|理由|真相|正体|秘密|裏側|影響)",
)
# トーン検出: ネガティブ（健康被害・リスク系）
_NEG_TONE_RE = re.compile(
    r"(危険|害|リスク|悪化|老化|蝕む|弱る|壊す|毒|禁止|逆効果|不足|NG|ダメ|間違い|ヤバ"
    r"|増える|悪い|ひどい|失う|減る|下がる|崩れ|乱れ|病気|不調|痛い|辛い|苦しい)"
)
# トーン検出: ポジティブ（改善・回復・強化系）
_POS_TONE_RE = re.compile(
    r"(改善|良くなる|上がる|健康|予防|防ぐ|強くなる|向上|回復|下がる|減らす|若返"
    r"|キレイ|美肌|元気|すっきり|ぐっすり|増やす|スッキリ|劇的)"
)


def _to_tara_phrase(phrase: str) -> str:
    """動詞句末尾を「たら」形に変換（接続詞「と」→「たら」代替用）。
    健康動画に頻出する動詞パターンに対応。
    """
    if phrase.endswith("する"):
        return phrase[:-2] + "したら"
    if phrase.endswith(("む", "ぶ", "ぬ")):
        return phrase[:-1] + "んだら"
    if phrase.endswith("く"):
        return phrase[:-1] + "いたら"
    if phrase.endswith("ぐ"):
        return phrase[:-1] + "いだら"
    if phrase.endswith("す"):
        return phrase[:-1] + "したら"
    if phrase.endswith(("つ", "う")):
        return phrase[:-1] + "ったら"
    if phrase.endswith("る"):
        # 五段動詞の例外（い/え段に見えても五段）
        _GODAN_RU = ("走る", "取る", "乗る", "切る", "知る", "入る", "帰る", "要る", "限る", "握る", "終わる", "始まる")
        if any(phrase.endswith(ex) for ex in _GODAN_RU):
            return phrase[:-1] + "ったら"
        # 前の文字がえ段/い段なら一段動詞（食べ→たら、続け→たら）
        _ICHIDAN_PREV = "けげせぜてでねへべめれきぎじちにびみり"
        if len(phrase) >= 2 and phrase[-2] in _ICHIDAN_PREV:
            return phrase[:-1] + "たら"
        return phrase[:-1] + "ったら"  # 五段と仮定
    return phrase + "たら"


def _rewrite_for_mystery(title: str, symbol: str) -> str:
    """タイトルを「内容は伝わる・結果だけ隠す」形式に書き換える。

    原則:
      - 動画が何に関するものかは残す（コーヒー・緑茶・歯磨きなど）
      - 驚く結果・数値・答えだけを○○でマスクする
      - 書き換えにより自然な「結果告知」型タイトルにする

    例:
      「毎日コーヒーを飲むと身体はどう変わるのか」
        → 「毎日コーヒーを飲むと身体が○○になった」

      「緑茶を続けると白髪はどうなるの？」
        → 「緑茶を続けると白髪が○○になった」
    """
    # ① 末尾に「答えとなる名詞」（方法・食べ物・食習慣など）→ それをマスク
    # 「とは」「N選」などのサフィックスも許容
    # 例: 「肩こりが改善する方法」→「肩こりが改善する○○」
    # 例: 「認知症を防ぐ食習慣とは」→「認知症を防ぐ○○とは」
    # 例: 「睡眠の質を上げる食べ物5選」→「睡眠の質を上げる○○5選」
    _ANSWER_NOUN_RE = re.compile(
        r"(する|できる|増やす|防ぐ|改善する|上げる|下げる|抑える|わかる|知る|試す)"
        r"(方法|食べ物|食品|食事|飲み物|運動|習慣|食習慣|理由|原因|食材|食べ方|飲み方)"
        r"(?:[2-9０-９][選個つ種]|とは|って何?|こそが|だけ)?$"
    )
    m = _ANSWER_NOUN_RE.search(title)
    if m:
        return title[: m.start(2)] + symbol + title[m.end(2):]

    # ② 「XするとYはどう変わるのか」→ CTRトーンに合わせた複数バリアント（ネガ重点）
    m = _HOW_CHANGE_RE.match(title)
    if m:
        base      = m.group(1)              # 「毎日コーヒーを飲む」
        connector = m.group(2)              # 「と」「たら」等
        target    = m.group(3).rstrip("はが")  # 「身体」
        # 接続詞変換: 過去/完了形結果には「たら」、継続/条件には「と」
        action_to   = base + connector      # 〜と / 〜で / 〜たら（元のまま）
        action_tara = (                     # 過去形結果向け: 「と」のみ変換
            _to_tara_phrase(base) if connector == "と" else action_to
        )
        # 対象が「〜に」で終わる場合（例:「脳に」→「脳に○○が起きてしまった」）
        if target.endswith("に"):
            neg = [
                f"{action_tara}{target}{symbol}が起きてしまった",
                f"{action_to}{target}{symbol}なことが起きていた",
                f"{action_tara}{target}実は{symbol}が起きていた",
            ]
            pos = [f"{action_tara}{target}{symbol}が起きた"]
        else:
            neg = [
                f"{action_tara}{target}が{symbol}になってしまった",
                f"{action_to}{target}が{symbol}になっていた",
                f"{action_tara}{target}が実は{symbol}だった",
                f"{action_tara}{target}が{symbol}に変わってしまった",
                f"{action_tara}{target}に{symbol}なことが起きていた",
            ]
            pos = [
                f"{action_tara}{target}が{symbol}に激変した",
                f"{action_tara}{target}が{symbol}になった",
                f"{action_tara}{target}が{symbol}に変わった",
            ]
        if _POS_TONE_RE.search(title) and not _NEG_TONE_RE.search(title):
            opts = pos * 2 + neg[:2]
        else:
            opts = neg * 3 + pos[:1]  # ネガ重点（約75%）
        return random.choice(opts)

    # ③ 「Xを飲むと何が起きる/どうなる」→ CTRトーンに合わせた複数バリアント
    m = _DO_EFFECT_RE.match(title)
    if m:
        base      = m.group(1)
        connector = m.group(2)
        action_to   = base + connector
        action_tara = _to_tara_phrase(base) if connector == "と" else action_to
        neg = [
            f"{action_tara}{symbol}になってしまった",
            f"{action_to}{symbol}になっていた",
            f"{action_tara}{symbol}に変わってしまった",
            f"実は{action_tara}{symbol}だった",
        ]
        pos = [
            f"{action_tara}{symbol}になった",
            f"{action_tara}{symbol}に激変した",
        ]
        if _POS_TONE_RE.search(title) and not _NEG_TONE_RE.search(title):
            opts = pos * 2 + neg[:1]
        else:
            opts = neg * 3 + pos[:1]  # ネガ重点
        return random.choice(opts)

    # ③ 「Xが原因/理由/秘密」→ 「Xが○○の原因だった」式を維持してパワーワードをマスク
    m = _CAUSE_RESULT_RE.match(title)
    if m:
        pw = _POWER_KEYWORD_RE.search(title)
        if pw:
            return title[: pw.start()] + symbol + title[pw.end():]

    # ③.5 「〜が/〜を + 末尾の結果語」パターン → 末尾の結果語をマスク（主語・トピックは残す）
    # ルール: 「何の動画か」が分かる主語（老化・植物など）は残し、「驚く結果」だけ隠す
    # 例: 「実は老化が加速」→「実は老化が●●」（老化=トピックなので残す、加速=結果なので隠す）
    # 例: 「記憶力が低下」→「記憶力が●●」 / 「免疫が急上昇」→「免疫が●●」
    _end_result = re.search(
        r"(?:が|を)([\u3040-\u9fff\u30a0-\u30ffA-Za-z0-9ａ-ｚＡ-Ｚ０-９]{2,6})$",
        title,
    )
    if _end_result:
        return title[: _end_result.start(1)] + symbol + title[_end_result.end(1):]

    # ④ パワーワードをマスク（化学物質・疾患名など）
    pw = _POWER_KEYWORD_RE.search(title)
    if pw:
        return title[: pw.start()] + symbol + title[pw.end():]

    # ⑤ 「N選」「N個」「N食品」→ 数字前の語をマスク（「食べ物3選」→「○○3選」）
    # ひらがな・カタカナ・漢字の混在語（食べ物など）も対象にするため\u3040-\u9fffを使用
    m = re.search(
        r"([\u3040-\u9fff]{2,5})([2-9０-９][選個つ種])",
        title,
    )
    if m:
        return title[: m.start(1)] + symbol + title[m.end(1):]

    # ⑥ 適切なマスク対象が見つからない場合はマスクなしで返す
    # 主語・動詞・テーマのキーワードを無差別にマスクするのは逆効果
    return title


def _apply_variant_text(
    title: str,
    thumbnail_caption: str | None,
    variant: str,
) -> tuple[str, str | None]:
    """バリアントごとにテキストを調整する。
    マスク戦略: 「動画の核心となる答え・原因・方法」だけを隠す。
    適切な隠し対象がなければマスクなしで返す（無意味な伏せ字は逆効果）。
    疑問形タイトル（どう変わるのか等）は結果告知形に書き換えてからマスクする。
    """
    def _do_mask(title: str, symbols: list[str]) -> tuple[str, str | None]:
        if _MASK_SYMBOL_RE.search(title):
            return title, thumbnail_caption
        sym = random.choice(symbols)
        return _rewrite_for_mystery(title, sym), thumbnail_caption

    if variant == "A":
        return _do_mask(title, _MASK_SYMBOLS_A)
    elif variant == "B":
        return _do_mask(title, _MASK_SYMBOLS_B)
    elif variant == "C":
        return _do_mask(title, _MASK_SYMBOLS_C)

    return title, thumbnail_caption


# ── メイン処理 ───────────────────────────────────────────────────────────────

def make_thumbnail(
    title: str,
    output_path: Path,
    font_size: int = 0,
    bg_path: Path | None = None,
    narrative_style: str | None = None,
    variant: str = "A",
    thumbnail_caption: str | None = None,
    directive: dict | None = None,
    thumb_bg_path: Path | None = None,
    face_left_x: int | None = None,
) -> Path:
    """
    ゆっくり健康ラボ v2 スタイルのサムネイルを生成する。

    directive が渡された場合、AIアートディレクターの指示で全クリエイティブ判断を上書きする:
      - caption, emphasis_words, bg_top/bg_bottom, emphasis_color
      - marisa/reimu_expression, marisa/reimu_bubble

    バリアント:
      A: カラフルグラデ背景 + 極太テキスト + いらすとや + 饅頭（スタンダード）
      B: やや暗い背景 + ●●伏せ字 + 吹き出し（ミステリー強調）
      C: ツートーン背景 + テキスト超特大（インパクト重視）
    """
    # ── directive モード: AIアートディレクターの指示で全パラメータを上書き ──
    _directive_mode = directive is not None
    _dir_bubble: tuple[str, str] | None = None  # (魔理沙, 霊夢)

    # AI強調ワード・強調スケールをリセット
    global _DIRECTIVE_EMPH_WORDS, _EMPH_SCALE
    _DIRECTIVE_EMPH_WORDS = []
    _EMPH_SCALE = 1.7

    if _directive_mode:
        # AIの指示からパラメータを展開
        thumbnail_caption = directive["caption"]
        theme = directive.get("theme_category", "general")
        _dir_bg_top = tuple(directive.get("bg_top", (60, 190, 80)))
        _dir_bg_bottom = tuple(directive.get("bg_bottom", (25, 130, 45)))
        _dir_emph_color = tuple(directive.get("emphasis_color", (255, 240, 20)))
        _dir_bubble = (directive.get("marisa_bubble", ""), directive.get("reimu_bubble", ""))
        # AIが指定した強調ワードをセット（描画時に_segment_textが参照）
        _DIRECTIVE_EMPH_WORDS = directive.get("emphasis_words", [])
        # directiveモードはバリアント無視（AI指定の背景色を使う）
        variant = "A"
    # ─────────────────────────────────────────────────────────────

    # バリアント別〇〇カラー + 強調色をグローバルにセット（_draw_rich_line から参照）
    global _CURRENT_MASK_COLOR, _EMPH_COLOR
    if _directive_mode:
        _CURRENT_MASK_COLOR = _dir_emph_color
        _EMPH_COLOR = _dir_emph_color  # AI指定の強調色を適用
    else:
        _EMPH_COLOR = (255, 240, 20)  # デフォルト値にリセット（directiveモードの汚染防止）
        _CURRENT_MASK_COLOR = _MASK_EMPH_COLORS.get(variant, _EMPH_COLOR)

    display_title, display_caption = _apply_variant_text(title, thumbnail_caption, variant)

    # テーマ検出（タイトルから）
    if not _directive_mode:
        theme = _detect_theme(display_title)
    line1_color = _THEME_LINE1_COLORS.get(theme, (255, 240, 60))

    # バリアントC: テーマ別の〇〇カラーで上書き（背景色に対して最適なコントラストを確保）
    if variant == "C" and not _directive_mode:
        _palette_c = _THEME_PALETTES.get(theme, _THEME_PALETTES["general"])
        _CURRENT_MASK_COLOR = _palette_c.get("C_mask", _MASK_EMPH_COLORS["C"])

    # ① 背景生成
    if thumb_bg_path and Path(thumb_bg_path).exists():
        # AI生成サムネ背景画像を使用（暗めのオーバーレイでテキスト可読性を確保）
        import numpy as np
        _bg_img = Image.open(thumb_bg_path).convert("RGBA")
        _bg_img = _bg_img.resize(RESOLUTION, Image.LANCZOS)
        canvas = _bg_img
        # 暗めグラデーションオーバーレイ（左側を濃くしてテキスト視認性UP）
        W, H = RESOLUTION
        _xs = np.linspace(0, 1, W, dtype=np.float32)
        _ys = np.linspace(0, 1, H, dtype=np.float32)
        _xg, _yg = np.meshgrid(_xs, _ys)
        # 左側を濃く（テキスト可読性）、右半分はほぼ透明（被写体の顔を見せる）
        _left_fade = np.clip(1.0 - _xg / 0.45, 0, 1)
        _alpha = (15 + 130 * _left_fade).clip(0, 180).astype(np.uint8)
        _ov_arr = np.zeros((H, W, 4), dtype=np.uint8)
        _ov_arr[:, :, 3] = _alpha
        _overlay = Image.fromarray(_ov_arr, "RGBA")
        canvas = Image.alpha_composite(canvas, _overlay)
    elif _directive_mode:
        # AI指定のグラデーション背景
        canvas = Image.new("RGBA", RESOLUTION)
        _d_draw = ImageDraw.Draw(canvas)
        for y in range(RESOLUTION[1]):
            t = y / RESOLUTION[1]
            r = int(_dir_bg_top[0] + t * (_dir_bg_bottom[0] - _dir_bg_top[0]))
            g = int(_dir_bg_top[1] + t * (_dir_bg_bottom[1] - _dir_bg_top[1]))
            b = int(_dir_bg_top[2] + t * (_dir_bg_bottom[2] - _dir_bg_top[2]))
            _d_draw.line([(0, y), (RESOLUTION[0], y)], fill=(r, g, b, 255))
        del _d_draw
    elif variant == "A":
        canvas = _make_colorful_gradient_bg(theme, dark=False)
    elif variant == "B":
        canvas = _make_colorful_gradient_bg(theme, dark=True)   # やや暗め
    elif variant == "C":
        canvas = _make_twotone_bg(theme)                        # ツートーン
    else:
        canvas = _make_colorful_gradient_bg(theme, dark=False)

    # バリアントAでは中央霊夢モードをランダム決定（この時点で決めてirasutoya制御に使う）
    # いらすとやは「隙間埋め」目的のオプション。中央霊夢モード時は右ゾーンの隙間にのみ使用。
    use_center_reimu = (variant == "A") and (not _directive_mode) and (random.random() < 0.50)

    # ② いらすとや画像（中央霊夢モード時はスキップ。白背景除去済み・ドロップシャドウ付き）
    _ira_kws = directive.get("irasutoya_keywords") if _directive_mode else None
    topic_img = None if use_center_reimu else _get_topic_image(title, keywords=_ira_kws)  # AI指定 or タイトル解析
    if topic_img:
        print(f"  [THUMB] いらすとや取得成功: {topic_img.size}")
    else:
        print(f"  [THUMB] いらすとや取得失敗 (kws={_ira_kws})")
    if topic_img:
        # スケール: 幅最大350px・高さ最大320px に制限
        max_topic_w = 350
        max_topic_h = 320
        if topic_img.width > max_topic_w:
            scale = max_topic_w / topic_img.width
            topic_img = topic_img.resize(
                (max_topic_w, int(topic_img.height * scale)), Image.LANCZOS
            )
        if topic_img.height > max_topic_h:
            scale = max_topic_h / topic_img.height
            topic_img = topic_img.resize(
                (int(topic_img.width * scale), max_topic_h), Image.LANCZOS
            )

        if _directive_mode:
            # directiveモード: いらすとやはテキスト描画後に中央下部へ配置（後で処理）
            ix, iy = 0, 0
            text_max_w = TEXT_MAX_W
        elif variant == "C":
            # バリアントC: タイトル優先レイアウト
            # いらすとやはタイトル描画後に空きスペースへ配置（後続の else ブロックで処理）
            # text_max_w を 850 に制限して右側にいらすとや用スペースを確保
            ix, iy = 0, 0
            text_max_w = 850
        else:
            # バリアントA/B: 右上隅に配置（タイトルテキストは左側に収まるので水平に重ならない）
            ix = RESOLUTION[0] - topic_img.width - 10
            iy = 10  # 右上隅
            _paste_with_shadow(canvas, topic_img, (ix, iy), shadow_offset=5, shadow_alpha=90)
            text_max_w = max(730, ix - TEXT_LEFT - 20)
    else:
        ix, iy = 0, 0  # topic_imgなし時の初期値（_mystery_occupied計算用）
        # 中央霊夢モードまたはirasutoya未取得: テキストは全幅使用
        text_max_w = TEXT_MAX_W

    # 人物との重なり防止用: 人物左端から余白を引いた安全X座標
    _face_safe_x = (face_left_x - 40) if (face_left_x is not None and face_left_x > 0) else None

    # directiveモード: 行折り返し幅は780px固定（フォントサイズ最大化）
    # 人物との重なりは後段の _EMPH_SCALE 動的縮小で対応
    if _directive_mode:
        text_max_w = min(text_max_w, 780)

    draw = ImageDraw.Draw(canvas)

    # ミステリーオーバーレイの重複回避用: 既描画要素のバウンディングボックスを収集
    _mystery_occupied: list[tuple[int, int, int, int]] = []
    if topic_img and variant != "C":
        # バリアントCはタイトル後にix/iyを確定してから追加
        _mystery_occupied.append((ix, iy, ix + topic_img.width, iy + topic_img.height))

    # ③ バッジ（左上）— キャプション・タイトル両方に含まれる単語はバッジ化しない（重複防止）
    badge_force = "危険" if variant == "C" and re.search(r"危険|警告|リスク", display_title) else None
    _badge_full = (display_caption or "") + display_title
    badge_info  = _find_badge(_badge_full, force=badge_force, title=_badge_full)
    title_y = TEXT_TOP
    if badge_info:
        badge_word, badge_color = badge_info
        title_y = _draw_badge(draw, badge_word, badge_color, x=TEXT_LEFT, y=TEXT_TOP)

    # ④ タイトルテキスト（上部）
    if use_center_reimu and not display_caption and not font_size:
        # 中央霊夢モード: 1行化を優先するが、収まらない場合は _best_font で分割
        one_line_found = False
        for size in range(FONT_MAX, FONT_MIN - 1, -FONT_STEP):
            f = load_font(size)
            if _rendered_line_width(display_title, f) <= text_max_w:
                lines, fs = [display_title], size
                one_line_found = True
                break
        if not one_line_found:
            # 1行に収まらない → 通常の分割ロジックにフォールバック
            _, fs, lines = _best_font(display_title, text_max_w)
    else:
        lines, fs = _parse_caption(display_caption, display_title, text_max_w)
    if font_size:
        fs    = font_size
        lines = _split_text(display_title, load_font(fs), text_max_w)

    # directiveモード: テキストを上部42%に収める（下部はキャラ+吹き出し用）
    _text_zone_bottom = int(RESOLUTION[1] * 0.42)  # = 302px
    if _directive_mode:
        title_y_d = 45
        for _shrink in range(fs, FONT_MIN - 1, -2):
            _fnt_d = load_font(_shrink)
            _has_emph_d = any(_EMPHASIS_RE.search(ln) for ln in lines)
            if _has_emph_d:
                _emph_fs_d = min(FONT_MAX, int(_shrink * _EMPH_SCALE))
                _lh_d = load_font(_emph_fs_d).getbbox("あ")[3] + 6
            else:
                _lh_d = int(_shrink * 1.06)
            _th_d = _lh_d * len(lines)
            if title_y_d + _th_d <= _text_zone_bottom:
                fs = _shrink
                # 「|」区切りのキャプションは _parse_caption で正しく分割
                lines, fs = _parse_caption(display_caption, display_title, text_max_w)
                break
        title_y = title_y_d

    # バリアントCは文字を超特大に（通常の1.15倍）
    # ただしツートーン青ゾーン内に収める: split_y = 45% of height
    _twotone_split_y = int(RESOLUTION[1] * 0.45)  # = 324px
    if variant == "C" and not _directive_mode:
        # キャプションがあればキャプションを使う、なければタイトル
        if display_caption:
            lines, fs = _parse_caption(display_caption, display_title, text_max_w)
        else:
            fs = min(FONT_MAX, int(fs * 1.15))
            lines = _split_text(display_title, load_font(fs), text_max_w)
        # 青ゾーン（0〜split_y）に収まるようフォントを縮小
        title_y_c = 20  # Cバリアントは上端を詰めて青ゾーンをフル活用
        for _shrink in range(fs, FONT_MIN - 1, -2):
            _fnt_c = load_font(_shrink)
            _has_emph_c = any(_EMPHASIS_RE.search(ln) for ln in lines)
            if _has_emph_c:
                _emph_fs_c = min(FONT_MAX, int(_shrink * _EMPH_SCALE))
                _lh_c = load_font(_emph_fs_c).getbbox("あ")[3] + 6
            else:
                _lh_c = int(_shrink * 1.06)
            _th_c  = _lh_c * len(lines)
            if title_y_c + _th_c <= _twotone_split_y - 8:
                fs = _shrink
                break
        title_y = title_y_c

    font   = load_font(fs)
    _has_emph_in_lines = any(_EMPHASIS_RE.search(ln) for ln in lines)

    # 人物との重なり防止: _EMPH_SCALEを動的縮小
    # text_max_w(780)でフォントサイズを最大化した後、実描画幅が人物左端を超える行があれば
    # _EMPH_SCALEだけを縮小する（フォントサイズは変えない→テキストの大きさ維持）
    if _face_safe_x is not None and _has_emph_in_lines:
        _orig_emph_scale = _EMPH_SCALE
        for _try_scale in [1.7, 1.6, 1.5, 1.4, 1.3]:
            _EMPH_SCALE = _try_scale
            _max_line_w = max(_rendered_line_width(ln, font) for ln in lines)
            if _max_line_w <= _face_safe_x - TEXT_LEFT:
                break
        if _EMPH_SCALE != _orig_emph_scale:
            print(f"  [THUMB] 強調スケール: {_orig_emph_scale} -> {_EMPH_SCALE} (人物重なり防止)")

    # emphセグメント（〇〇・数字等）がある行では1.7x大のフォントが上方向に飛び出すため、
    # line_h を emph フォントの実測高さ基準に引き上げて行間の重なりを防ぐ
    if _has_emph_in_lines:
        _emph_fs = min(FONT_MAX, int(fs * _EMPH_SCALE))
        _emph_fnt = load_font(_emph_fs)
        line_h = _emph_fnt.getbbox("あ")[3] + 6  # 実測値 + 6px余白
    else:
        line_h = int(fs * 1.06)
    total_h = line_h * len(lines)

    # Cバリアント: テキストブロックを青ゾーン内で上下中央揃え（左寄せは維持）
    if variant == "C":
        _zone_top = 10
        _zone_bot = _twotone_split_y - 8
        # emph文字は下端を通常文字に揃えるため、最終行の占有高さは normal_h 分。
        # 視覚的ブロック高さ = (行数-1)*line_h + normal_h で計算する。
        _normal_h_c = font.getbbox("あ")[3]
        _visual_h_c = (len(lines) - 1) * line_h + _normal_h_c
        title_y = max(_zone_top, (_zone_top + _zone_bot - _visual_h_c) // 2)
        # 1行目に強調文字(○○/●●等)がある場合、_EMPH_SCALE倍の文字が上方向にはみ出す。
        # emph文字はbaseline基準で下端合わせのため top = title_y - (emph_h - normal_h)
        # → title_y を emph上方突き出し量だけ下げてオーバーフローを防ぐ
        if lines and _EMPHASIS_RE.search(lines[0]):
            _emph_h_c = int(fs * _EMPH_SCALE)
            _emph_top_overflow = max(0, _emph_h_c - _normal_h_c)
            title_y = max(title_y, _zone_top + _emph_top_overflow)
    else:
        max_text_bottom = _MYSTERY_Y - 20
        if title_y + total_h > max_text_bottom:
            title_y = max(TEXT_TOP, max_text_bottom - total_h)

    for i, line in enumerate(lines):
        _draw_rich_line(
            draw,
            (TEXT_LEFT, title_y + i * line_h),
            line, font,
            line_index=i,
            outline_w=14,
            font_size=fs,
        )

    # ⑤ バリアントB: 吹き出し追加（好奇心ギャップ強化）
    if variant == "B":
        _balloon_pool = [
            "アレを入れるだけ", "これって本当？", "知らないと損！", "実はヤバかった",
            "え、マジで!?", "試す価値あり!", "なぜか誰も教えない", "衝撃の事実…",
            "騙されてた…", "医師も驚いた!", "今すぐ確認して", "体に起きてた…",
            "99%が知らなかった", "実は簡単だった", "もっと早く知りたかった",
            "信じられない…", "これ本当に効く?", "やってみたら変わった",
        ]
        # reaction_pool で既出のものを除外して重複防止
        _react_pool = _REACTION_POOL.get(theme, _REACTION_POOL["general"])
        _balloon_candidates = [t for t in _balloon_pool if t not in _react_pool]
        balloon_text = random.choice(_balloon_candidates if _balloon_candidates else _balloon_pool)
        # 中央やや右寄りに配置
        bx = 600 if topic_img else 500
        by = _MYSTERY_Y - 80
        balloon_rect = _draw_balloon(canvas, balloon_text, bx, by, font_size=30)
        _mystery_occupied.append(balloon_rect)

    # ⑥ ミステリーボトムテキスト用テキストを生成（描画はキャラ配置後に行う）
    if _directive_mode and _dir_bubble and _dir_bubble[0] and _dir_bubble[1]:
        # AIアートディレクターの吹き出しテキストを使用
        mystery, _mystery_reimu_response = _dir_bubble
    else:
        # 魔理沙と霊夢の会話ペアを一括取得（AI生成→フォールバック）
        mystery, _mystery_reimu_response = _make_mystery_conversation(display_title)

    # ⑦ キャラクター配置（魔理沙は帽子分を補正して霊夢と顔サイズを揃える）
    # 表情はセリフから自動導出（Geminiの指定に依存しない → セリフと100%一致保証）
    if _directive_mode and mystery and _mystery_reimu_response:
        _marisa_expr = _expr_from_bubble(mystery, role="marisa")
        _reimu_expr = _expr_from_bubble(_mystery_reimu_response, role="reimu")
    elif _directive_mode:
        # セリフがない場合のみGeminiの指定を使用
        _marisa_expr = directive.get("marisa_expression", "serious")
        _reimu_expr = directive.get("reimu_expression", "surprised")
    else:
        _marisa_expr, _reimu_expr = _select_char_expressions(display_title, theme)
    print(f"  [THUMB] 表情: 魔理沙={_marisa_expr}, 霊夢={_reimu_expr}")
    marisa = _load_manju_expr("魔理沙", _MANJU_H_MARISA, _marisa_expr)
    reimu  = _load_manju_expr("霊夢",   _MANJU_H,        _reimu_expr)

    # 中央霊夢演出: タイトル下端を渡してテキストに被らないよう配置
    title_bottom_y = title_y + total_h

    # ミステリー重複回避: タイトルテキスト領域 + キャラクター配置領域を追加
    _mystery_occupied.append((0, title_y, RESOLUTION[0], title_bottom_y + 20))
    # 左下魔理沙・右下霊夢の実寸領域
    # 魔理沙 alpha_bbox right=390, canvas x=10 → 視覚右端 = 10+390 = 400 (+余裕10px)
    _mystery_occupied.append((0, RESOLUTION[1] - _MANJU_H_MARISA + 12, 410, RESOLUTION[1]))
    # 霊夢 alpha_bbox left=7, canvas x=(1280-330-10)=940 → 視覚左端 = 940+7 = 947 (-余裕20px)
    _mystery_occupied.append((920, RESOLUTION[1] - _MANJU_H + 12, RESOLUTION[0], RESOLUTION[1]))
    # 右下YouTubeバッジ保護ゾーン（競合分析: 右下には再生時間バッジが重なるため重要要素禁止）
    _mystery_occupied.append((900, 560, RESOLUTION[0], RESOLUTION[1]))
    reimu_center_placed = False

    # directiveモード: いらすとやを魔理沙・霊夢の間（中央下部）に配置
    # タイトル・ミステリーテキスト・キャラと重ならない安全ゾーン
    if _directive_mode and topic_img:
        _ira_center_x = (410 + 920) // 2  # 魔理沙右端〜霊夢左端の中央
        _ira_y = max(title_bottom_y + 15, int(RESOLUTION[1] * 0.45))
        _ira_max_h = RESOLUTION[1] - _ira_y - 40
        _ira_max_w = 550
        _scl = min(_ira_max_w / topic_img.width, _ira_max_h / topic_img.height, 1.0)
        if _scl < 1.0:
            topic_img = topic_img.resize(
                (max(60, int(topic_img.width * _scl)),
                 max(60, int(topic_img.height * _scl))), Image.LANCZOS)
        ix = _ira_center_x - topic_img.width // 2
        iy = _ira_y
        _paste_with_shadow(canvas, topic_img, (ix, iy), shadow_offset=5, shadow_alpha=90)
        _mystery_occupied.append((ix, iy, ix + topic_img.width, iy + topic_img.height))

    # ミニトピック・リアクションコメントのパラメータを事前計算（後で描画）
    _mini_topics_args: tuple | None = None
    _reaction_args: tuple | None = None

    if use_center_reimu:
        # いらすとや: 右ゾーンのみ配置（左ゾーンはミニトピックバッジ専用）
        _draw_scatter_irasutoya(canvas, display_title, title_bottom_y,
                                reimu_rx=10, reimu_rw=670, keywords=_ira_kws)
        reimu_center_placed = _draw_center_reimu(canvas, top_margin=title_bottom_y + 15)

        # ミニトピック: 左ゾーン（帽子の上に後で描画するためパラメータだけ保持）
        mini_topics = _make_mini_topics(display_title, theme)
        mini_x = 10
        mini_y_start = title_bottom_y + 20
        mini_max_h = _MYSTERY_Y - mini_y_start - 10
        _mini_topics_args = (mini_topics, mini_x, mini_y_start, mini_max_h, 250)

        # リアクションコメント: 右上のみ（_MYSTERY_Y付近はmysteryオーバーレイと重なるため除外）
        reaction_spots = [
            (820, title_bottom_y + 20),
        ]
        _reaction_args = (theme, reaction_spots)
    elif _directive_mode:
        # directiveモード: リアクションは右上隅・メインタイトルの高さ（40px間隔で重なり防止）
        reaction_spots = [
            (1050, 50),
            (1050, 90),
            (1050, 130),
        ]
        _reaction_args = (theme, reaction_spots)
    else:
        # 非中央霊夢モード: ミニトピック + リアクションコメント（後で描画）
        mini_topics = _make_mini_topics(display_title, theme)
        mini_x = TEXT_LEFT
        mini_y_start = title_bottom_y + 18
        mini_max_h = _MYSTERY_Y - mini_y_start - 15
        if topic_img and variant != "C":
            topic_left_x = RESOLUTION[0] - topic_img.width - 25
            badge_max_w = min(260, topic_left_x - mini_x - 15)
        else:
            badge_max_w = 260
        if mini_max_h > 60 and badge_max_w > 80:
            _mini_topics_args = (mini_topics, mini_x, mini_y_start, mini_max_h, badge_max_w)

        if topic_img and variant == "C":
            # バリアントC: タイトル優先レイアウト
            # 各行の実際の描画幅から右側の空きスペースを計算し、そこにいらすとやを配置
            _fnt_c = load_font(fs)
            _line_ws_c = [TEXT_LEFT + _rendered_line_width(ln, _fnt_c) for ln in lines]
            _ira_x_c = max(_line_ws_c) + 20  # 最も幅の広い行の右端 + マージン（全行と重ならない）
            _ira_w_c = RESOLUTION[0] - _ira_x_c - 10
            _ira_h_c = max(60, title_bottom_y - title_y)  # タイトル縦幅
            if _ira_w_c >= 100:
                # スペースに収まるようスケール（縮小のみ）
                _scl_c = min(_ira_w_c / topic_img.width, _ira_h_c / topic_img.height, 1.0)
                if _scl_c < 1.0:
                    topic_img = topic_img.resize(
                        (max(60, int(topic_img.width * _scl_c)),
                         max(60, int(topic_img.height * _scl_c))), Image.LANCZOS)
                ix = _ira_x_c
                iy = title_y + (_ira_h_c - topic_img.height) // 2
                _paste_with_shadow(canvas, topic_img, (ix, iy), shadow_offset=5, shadow_alpha=90)
                _mystery_occupied.append((ix, iy, ix + topic_img.width, iy + topic_img.height))
                # リアクション2個: irasutoyaの上部スパースエリアへ（タイトル・キャラを回避）
                _reaction_avoid_c = [
                    (0, title_y, ix - 5, title_bottom_y + 20),  # タイトルテキスト左側
                    (0, RESOLUTION[1] - _MANJU_H_MARISA + 12, 260, RESOLUTION[1]),  # 魔理沙
                    (RESOLUTION[0] - 260, RESOLUTION[1] - _MANJU_H + 12, RESOLUTION[0], RESOLUTION[1]),  # 霊夢
                ]
                _spots_c = _pick_sparse_comment_spots(topic_img, ix, iy, _reaction_avoid_c, n=2)
                if _spots_c:
                    _reaction_args = (theme, _spots_c)
        elif topic_img:
            # バリアントA/B: いらすとやのアルファ密度を分析してスポットを選択
            _reaction_avoid = [
                (0, title_y, ix - 5, title_bottom_y + 20),  # タイトルテキスト（irasutoya手前まで）
                (0, RESOLUTION[1] - _MANJU_H_MARISA + 12, 260, RESOLUTION[1]),  # 魔理沙
                (RESOLUTION[0] - 260, RESOLUTION[1] - _MANJU_H + 12, RESOLUTION[0], RESOLUTION[1]),  # 霊夢
            ]
            _spots = _pick_sparse_comment_spots(topic_img, ix, iy, _reaction_avoid, n=2)
            if _spots:
                _reaction_args = (theme, _spots)
            else:
                # スパースエリアが見つからない場合: タイトル下フォールバック
                react_x = TEXT_LEFT + 10
                react_y = title_bottom_y + 10
                if react_y < _MYSTERY_Y - 50:
                    _reaction_args = (theme, [(react_x, react_y)])
        else:
            react_x = TEXT_LEFT + 10
            react_y = title_bottom_y + 10
            if react_y < _MYSTERY_Y - 50:
                _reaction_args = (theme, [(react_x, react_y)])

    # リアクションコメントを先行選択（霊夢吹き出しとの類似回避に使用）
    _preselected_reactions: list[str] = []
    if _reaction_args:
        if _directive_mode and directive.get("reactions"):
            # AIアートディレクターが生成した2ch風リアクションを使用（3個未満ならプールから補充）
            _preselected_reactions = directive["reactions"][:3]
            if len(_preselected_reactions) < 3:
                _rt, _ = _reaction_args
                _rpool = _REACTION_POOL.get(_rt, _REACTION_POOL["general"])
                _extra = [r for r in _rpool if r not in _preselected_reactions]
                _preselected_reactions += random.sample(_extra, min(3 - len(_preselected_reactions), len(_extra)))
        else:
            _rt, _ = _reaction_args
            _rpool = _REACTION_POOL.get(_rt, _REACTION_POOL["general"])
            _preselected_reactions = random.sample(_rpool, min(2, len(_rpool)))

    # キャラクター描画（ミニトピックより先に描画して帽子が背景に）
    # ※ミステリーテキスト後に再合成してZオーダーを保証するため位置を保存
    _marisa_pos: tuple[int, int] | None = None
    if marisa:
        my = RESOLUTION[1] - marisa.height + 12  # 少し画面外にはみ出す（競合分析: キャラブリード効果）
        canvas.paste(marisa, (10, my), marisa)
        _marisa_pos = (10, my)

    # 中央に霊夢を配置した場合は右下霊夢をスキップ
    _reimu_char_pos: tuple[int, int] | None = None
    _reimu_bubble_text: str | None = None
    if reimu and not reimu_center_placed:
        ry = RESOLUTION[1] - reimu.height + 12  # 少し画面外にはみ出す（競合分析: キャラブリード効果）
        rx = RESOLUTION[0] - reimu.width - 10
        canvas.paste(reimu, (rx, ry), reimu)
        _reimu_char_pos = (rx, ry)
        # 霊夢頭上: 魔理沙のミステリーテキストとペアになった返しを使用
        _reimu_bubble_text = _mystery_reimu_response

    # ミニトピック・リアクションコメントをキャラクターの上に描画
    if _mini_topics_args:
        topics, mx, mys, mh, mbw = _mini_topics_args
        # キャラ上端より上に収まるよう高さを制限（重なり検知）
        char_top_y = RESOLUTION[1] - _MANJU_H_MARISA - 10
        mh = min(mh, char_top_y - mys - 8)
        if mh > 40:
            _draw_mini_topics(canvas, topics, mx, mys, mh, max_badge_w=mbw)
    # ⑧ ミステリーボトムテキスト: バリアントを事前選択して角度をリアクションコメントと共有
    _mystery_target_cy = ((_twotone_split_y + RESOLUTION[1]) // 2) if variant == "C" else None
    _mystery_v = _select_mystery_variant(mystery, _mystery_occupied)
    _mystery_angle = _mystery_v["angle"]

    if _reaction_args:
        t, spots = _reaction_args
        # ミステリーテキスト近傍のスポットを上方に退避（重複防止）
        _myst_rect = _mystery_approx_rect(_mystery_v, mystery)
        adjusted_spots = []
        for (sx, sy) in spots:
            if (_myst_rect[0] <= sx <= _myst_rect[2]
                    and _myst_rect[1] <= sy <= _myst_rect[3]):
                sy = _myst_rect[1] - 35
            adjusted_spots.append((sx, sy))
        _draw_reaction_comments(canvas, t, adjusted_spots, angle=_mystery_angle,
                                preselected=_preselected_reactions if _preselected_reactions else None)

    if _directive_mode:
        # directiveモード: ミステリーオーバーレイをスキップ（吹き出しで十分）
        pass
    else:
        _draw_mystery_overlay(canvas, mystery, occupied_rects=_mystery_occupied,
                              target_cy=_mystery_target_cy, preselected_v=_mystery_v)

    # キャラクター・吹き出しをミステリーテキスト前面に再合成（Zオーダー保証）
    # 初回描画でキャラが背景に溶け込み、ミステリー後に前面へ引き戻す
    # 吹き出しY座標を統一: 霊夢の実際の頭位置を基準にする
    # スプライトtop != 実際の頭。リボン・装飾分を30%オフセットして実際の頭位置に合わせる
    _sprite_top = _reimu_char_pos[1] if _reimu_char_pos else (RESOLUTION[1] - _MANJU_H + 12)
    _reimu_head_y = _sprite_top + int(_MANJU_H * 0.30)

    if marisa and _marisa_pos is not None:
        canvas.paste(marisa, _marisa_pos, marisa)
        # directiveモード: 魔理沙にも吹き出しを描画（ミステリーオーバーレイの代わり）
        if _directive_mode and mystery:
            _draw_marisa_speech_bubble(
                canvas, mystery,
                marisa_x=_marisa_pos[0], marisa_y=_marisa_pos[1],
                marisa_w=marisa.width,
                bubble_y=_reimu_head_y,
            )
    if reimu and not reimu_center_placed and _reimu_char_pos is not None:
        canvas.paste(reimu, _reimu_char_pos, reimu)
        if _reimu_bubble_text:
            _draw_reimu_speech_bubble(
                canvas, _reimu_bubble_text,
                reimu_rx=_reimu_char_pos[0], reimu_ry=_reimu_char_pos[1],
                reimu_w=reimu.width,
                bubble_y=_reimu_head_y,
            )

    # _EMPH_SCALEを元に戻す（グローバル変数のため次回生成に影響しないように）
    _EMPH_SCALE = 1.7

    # ⑨ 保存
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, "JPEG", quality=95)

    return output_path


def make_thumbnail_variants(
    title: str,
    base_output_path: Path,
    bg_path: Path | None = None,
    narrative_style: str | None = None,
    thumbnail_caption: str | None = None,
    directive: dict | None = None,
    thumb_bg_path: Path | None = None,
    face_left_x: int | None = None,
) -> dict[str, Path]:
    """サムネイルを生成して返す。

    directive が渡された場合はAIアートディレクターモードで生成。
    それ以外はバリアントC（ツートーン）で生成。
    後方互換のため "A" キーにも同じパスを格納する。

    thumb_bg_path: AI生成サムネ背景画像のパス（あればグラデーションの代わりに使用）
    """
    base = Path(base_output_path)
    out  = base
    try:
        make_thumbnail(
            title, out,
            bg_path=bg_path,
            narrative_style=narrative_style,
            variant="C",
            thumbnail_caption=thumbnail_caption,
            directive=directive,
            thumb_bg_path=thumb_bg_path,
            face_left_x=face_left_x,
        )
        return {"A": out, "C": out}
    except Exception as e:
        print(f"  [!] サムネイル生成失敗: {e}")
        return {}


# ── CLI ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("使い方: python thumbnail_maker.py <タイトル> <出力パス> [キャプション]")
        print("  キャプション例: '知らないと危険！|腸内環境の真実'")
        sys.exit(1)
    caption = sys.argv[3] if len(sys.argv) > 3 else None
    result  = make_thumbnail(sys.argv[1], Path(sys.argv[2]), thumbnail_caption=caption)
    print(f"保存しました: {result}")
