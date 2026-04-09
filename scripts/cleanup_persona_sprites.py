# cleanup_persona_sprites.py
# 生成済みペルソナスプライトの後処理:
#   rembg (U2Net) によるAI背景除去 → タイトクロップ
#
# フラッドフィル方式は「キャラが端に接触するポーズ」で失敗するため
# セグメンテーションモデル (U2Net) に切り替え

from __future__ import annotations
from pathlib import Path

import numpy as np
from PIL import Image

CHARS_DIR = Path(__file__).resolve().parent.parent / "assets" / "characters"


def remove_bg_rembg(img: Image.Image) -> Image.Image:
    """rembg (U2Net) でAI背景除去"""
    from rembg import remove
    result = remove(img)
    return result.convert("RGBA")


def tight_crop(img: Image.Image, pad: int = 8) -> Image.Image:
    """コンテンツ周囲の透明領域をトリムしてパディングを追加"""
    arr = np.array(img)
    mask = arr[:, :, 3] > 10
    if not mask.any():
        return img
    rows = np.any(mask, axis=1)
    cols = np.any(mask, axis=0)
    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]
    h, w = arr.shape[:2]
    rmin = max(0, rmin - pad)
    rmax = min(h - 1, rmax + pad)
    cmin = max(0, cmin - pad)
    cmax = min(w - 1, cmax + pad)
    return Image.fromarray(arr[rmin:rmax + 1, cmin:cmax + 1], "RGBA")


def process_sprite(path: Path) -> None:
    img = Image.open(path).convert("RGBA")
    cleaned = remove_bg_rembg(img)
    cropped = tight_crop(cleaned, pad=6)
    cropped.save(path, "PNG")


def main() -> None:
    sprites = sorted(CHARS_DIR.glob("persona_*.png"))
    print(f"{len(sprites)} 枚を処理します (rembg U2Net)...")

    for i, path in enumerate(sprites, 1):
        print(f"  [{i:02d}/{len(sprites)}] {path.name}...", end=" ", flush=True)
        try:
            process_sprite(path)
            print("OK")
        except Exception as e:
            print(f"NG ({e})")

    print(f"\n完了！保存先: {CHARS_DIR}")


if __name__ == "__main__":
    main()
