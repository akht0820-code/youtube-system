# フォント読み込みユーティリティ（Windows / Linux / WSL2 対応）

import os
import platform
from functools import lru_cache
from pathlib import Path
from PIL import ImageFont

# けいふぉんと（最優先）— assets/fonts/ に同梱
_KEIFONT_PATH = str(Path(__file__).parent.parent / "assets" / "fonts" / "keifont.ttf")

# Windows用フォント候補（けいふぉんとが読めない場合のフォールバック）
_WINDOWS_FONTS = [
    "C:/Windows/Fonts/meiryob.ttc",   # Meiryo UI Bold
    "C:/Windows/Fonts/yugothb.ttc",   # Yu Gothic Bold
    "C:/Windows/Fonts/YuGothB.ttc",
    "C:/Windows/Fonts/msgothic.ttc",  # MS Gothic
]

# WSL2から見たWindowsフォントパス（platform.system()=="Linux"になるため別途試す）
_WSL_WINDOWS_FONTS = [
    "/mnt/c/Windows/Fonts/meiryob.ttc",
    "/mnt/c/Windows/Fonts/yugothb.ttc",
    "/mnt/c/Windows/Fonts/YuGothB.ttc",
    "/mnt/c/Windows/Fonts/msgothic.ttc",
]

# Linux用フォント候補（GitHub Actions / VPS）
_LINUX_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJKjp-Bold.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
]


@lru_cache(maxsize=32)
def load_font(size: int) -> "ImageFont.FreeTypeFont | ImageFont.ImageFont":
    """けいふぉんとを最優先で読み込む。なければOS標準太ゴシックにフォールバック"""
    # けいふぉんとを最優先
    try:
        return ImageFont.truetype(_KEIFONT_PATH, size)
    except (IOError, OSError):
        pass

    # フォールバック
    if platform.system() == "Windows":
        candidates = _WINDOWS_FONTS
    else:
        candidates = _WSL_WINDOWS_FONTS + _LINUX_FONTS

    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()
