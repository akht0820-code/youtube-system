# フォント読み込みユーティリティ（Windows / Linux 対応）

import platform
from PIL import ImageFont

# Windows用フォント候補
_WINDOWS_FONTS = [
    "C:/Windows/Fonts/meiryob.ttc",
    "C:/Windows/Fonts/yugothb.ttc",
    "C:/Windows/Fonts/msgothic.ttc",
]

# Linux用フォント候補（GitHub Actions / VPS）
_LINUX_FONTS = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJKjp-Bold.otf",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Bold.otf",
]


def load_font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    """OS に応じた日本語フォントを読み込む"""
    candidates = _WINDOWS_FONTS if platform.system() == "Windows" else _LINUX_FONTS
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except (IOError, OSError):
            continue
    return ImageFont.load_default()
