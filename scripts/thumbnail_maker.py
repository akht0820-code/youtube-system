# サムネイル自動生成モジュール（1280×720）

import sys
import textwrap
from pathlib import Path

from font_utils import load_font
from PIL import Image, ImageDraw

RESOLUTION = (1280, 720)

ASSETS_DIR = Path(__file__).parent.parent / "assets"
CHAR_DIR   = ASSETS_DIR / "characters"
BG_DIR     = ASSETS_DIR / "backgrounds"


# キャラクターの配置設定
CHAR_CONFIG = {
    "魔理沙": {"side": "left",  "x_ratio": 0.02, "height": 400},
    "霊夢":   {"side": "right", "x_ratio": 0.62, "height": 400},
}

# テキストエリア（中央寄せ）
TEXT_AREA_LEFT   = 60
TEXT_AREA_RIGHT  = 1220
TEXT_CENTER_X    = RESOLUTION[0] // 2
TEXT_START_Y     = 60   # 最初の行のY座標



def _load_background() -> Image.Image:
    """背景画像を読み込む。なければグラデーション背景を生成する"""
    for name in ("thumbnail_bg", "bg"):
        for ext in ("png", "jpg", "jpeg"):
            path = BG_DIR / f"{name}.{ext}"
            if path.exists():
                img = Image.open(path).convert("RGBA")
                return img.resize(RESOLUTION, Image.LANCZOS)

    # 背景がない場合: 黒→ダークネイビーのグラデーション
    bg = Image.new("RGBA", RESOLUTION, (0, 0, 0, 255))
    draw = ImageDraw.Draw(bg)
    for y in range(RESOLUTION[1]):
        ratio = y / RESOLUTION[1]
        r = int(5  + ratio * 10)
        g = int(5  + ratio * 15)
        b = int(20 + ratio * 40)
        draw.line([(0, y), (RESOLUTION[0], y)], fill=(r, g, b, 255))
    return bg


def _load_character(name: str, height: int) -> Image.Image | None:
    """キャラクター画像を読み込んでリサイズする"""
    for ext in ("png", "webp", "jpg"):
        path = CHAR_DIR / f"{name}.{ext}"
        if path.exists():
            img = Image.open(path).convert("RGBA")
            ratio = height / img.height
            new_w = int(img.width * ratio)
            return img.resize((new_w, height), Image.LANCZOS)
    return None


def _draw_outlined_text(draw: ImageDraw.Draw, xy: tuple, text: str,
                         font, fill=(255, 255, 255),
                         outline=(0, 0, 0), outline_width=6,
                         anchor="mm"):
    """縁取り付きテキストを描画する"""
    x, y = xy
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font,
                          fill=outline, anchor=anchor)
    draw.text(xy, text, font=font, fill=fill, anchor=anchor)


def _split_title(title: str, font, max_width: int) -> list[str]:
    """タイトルを描画幅に合わせて2行に分割する"""
    # 句読点・読点・記号で分割を試みる
    for sep in ("、", "。", "，", "！", "？", "、実は", "すると", "を"):
        idx = title.find(sep)
        if 0 < idx < len(title) - 1:
            line1 = title[:idx + (1 if sep in ("、", "。") else 0)]
            line2 = title[idx + (1 if sep in ("、", "。") else 0):]
            # 両行が収まるか確認
            w1 = font.getbbox(line1)[2]
            w2 = font.getbbox(line2)[2]
            if w1 <= max_width and w2 <= max_width:
                return [line1, line2]

    # 句読点で分割できない場合は文字数で等分
    mid = len(title) // 2
    return [title[:mid], title[mid:]]


def make_thumbnail(title: str, output_path: Path,
                   font_size: int = 88) -> Path:
    """
    サムネイル画像を生成して保存する

    Args:
        title: サムネイルに表示するタイトル文字列
        output_path: 出力先パス（.png または .jpg）
        font_size: フォントサイズ（デフォルト88px）
    """
    canvas = _load_background().convert("RGBA")
    font   = load_font(font_size)

    # ── キャラクター画像を配置 ──────────────────────────
    for name, cfg in CHAR_CONFIG.items():
        img = _load_character(name, cfg["height"])
        if img is None:
            continue
        x = int(RESOLUTION[0] * cfg["x_ratio"])
        y = RESOLUTION[1] - img.height  # 底辺に合わせる
        canvas.paste(img, (x, y), img)

    # ── テキスト描画 ────────────────────────────────────
    draw = ImageDraw.Draw(canvas)
    max_text_width = TEXT_AREA_RIGHT - TEXT_AREA_LEFT

    lines = _split_title(title, font, max_text_width)

    # フォントサイズが大きすぎる場合は自動縮小
    while font_size > 40:
        font = load_font(font_size)
        widths = [font.getbbox(line)[2] for line in lines]
        if max(widths) <= max_text_width:
            break
        font_size -= 4

    line_height = font_size + 20
    total_text_height = line_height * len(lines)

    # テキストエリアの垂直中央に配置（上半分寄り）
    start_y = max(TEXT_START_Y + font_size, RESOLUTION[1] // 2 - total_text_height)

    for i, line in enumerate(lines):
        y = start_y + i * line_height
        _draw_outlined_text(
            draw,
            (TEXT_CENTER_X, y),
            line,
            font=font,
            fill=(255, 255, 255),
            outline=(0, 0, 0),
            outline_width=7,
            anchor="mt",  # 上中央基準
        )

    # ── 保存 ────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    rgb = canvas.convert("RGB")

    if output_path.suffix.lower() in (".jpg", ".jpeg"):
        rgb.save(output_path, "JPEG", quality=95)
    else:
        canvas.save(output_path, "PNG")

    return output_path


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("使い方: python thumbnail_maker.py <タイトル> <出力パス>")
        print('例: python thumbnail_maker.py "納豆を毎日食べると実は体に変化が起きます" ../output/test.png')
        sys.exit(1)

    title_text  = sys.argv[1]
    output_file = Path(sys.argv[2])
    result = make_thumbnail(title_text, output_file)
    print(f"保存しました: {result}")
