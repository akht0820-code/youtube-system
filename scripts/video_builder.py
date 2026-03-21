# 動画生成モジュール（16:9 / 1920×1080 / MP4）

import json
import os
import re
import textwrap
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
from dotenv import load_dotenv
from font_utils import load_font
from moviepy import (
    AudioFileClip,
    CompositeAudioClip,
    ImageClip,
    concatenate_videoclips,
)
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


ASSETS_DIR = Path(__file__).parent.parent / "assets"
CHAR_DIR   = ASSETS_DIR / "characters"
BG_DIR     = ASSETS_DIR / "backgrounds"
BGM_DIR    = ASSETS_DIR / "bgm"

# 字幕エリア
SUBTITLE_BAR_Y      = 860   # 字幕バーの上端Y座標
SUBTITLE_BAR_HEIGHT = 190   # 字幕バーの高さ
SUBTITLE_PADDING    = 24    # 字幕テキストの左右余白

# キャラクター画像の配置（画面底部からの高さで合わせる）
CHAR_CONFIG = {
    "魔理沙": {"x": 60,   "bottom": SUBTITLE_BAR_Y, "height": 500, "side": "left"},
    "霊夢":   {"x": 1380, "bottom": SUBTITLE_BAR_Y, "height": 500, "side": "right"},
}

# キャラクター名の表示色
NAME_COLORS = {
    "魔理沙": (255, 220, 80),   # 黄色
    "霊夢":   (255, 130, 180),  # ピンク
}

FONT_NAME     = load_font(36)   # キャラクター名
FONT_SUBTITLE = load_font(52)   # 字幕テキスト


# ── 素材読み込み ──────────────────────────────────────────

def _load_background() -> Image.Image:
    """背景画像を読み込む。なければグラデーションで生成する"""
    for ext in ("png", "jpg", "jpeg"):
        path = BG_DIR / f"bg.{ext}"
        if path.exists():
            img = Image.open(path).convert("RGBA")
            return img.resize(RESOLUTION, Image.LANCZOS)

    # 背景画像がない場合: 黒→ダークグレーのグラデーション
    bg = Image.new("RGBA", RESOLUTION, (0, 0, 0, 255))
    draw = ImageDraw.Draw(bg)
    for y in range(RESOLUTION[1]):
        gray = int(20 + (y / RESOLUTION[1]) * 30)
        draw.line([(0, y), (RESOLUTION[0], y)], fill=(gray, gray, gray, 255))
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

    # 画像がない場合: 名前入りのプレースホルダーを生成
    w, h = 280, height
    placeholder = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(placeholder)
    color = NAME_COLORS.get(name, (180, 180, 180))
    draw.rounded_rectangle([10, 10, w - 10, h - 10], radius=20,
                            fill=(*color, 120), outline=(*color, 200), width=3)
    font = _load_font(32)
    draw.text((w // 2, h // 2), name, font=font, fill=(255, 255, 255, 230), anchor="mm")
    return placeholder


# ── フレーム合成 ──────────────────────────────────────────

def _draw_text_with_outline(draw: ImageDraw.Draw, pos: tuple, text: str,
                             font, fill, outline=(0, 0, 0), outline_width=3):
    """縁取り付きテキストを描画する"""
    x, y = pos
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx != 0 or dy != 0:
                draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text(pos, text, font=font, fill=fill)


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


def compose_frame(character: str, text: str,
                  bg: Image.Image,
                  char_images: dict[str, Image.Image | None]) -> np.ndarray:
    """1フレームの画像を合成してnumpy配列で返す"""
    frame = bg.copy()

    # キャラクター画像を配置（話していないキャラは暗くする）
    for name, cfg in CHAR_CONFIG.items():
        img = char_images.get(name)
        if img is None:
            continue
        x = cfg["x"]
        y = cfg["bottom"] - img.height

        if name != character:
            # 話していないキャラは少し暗く・小さく
            dimmed = img.copy()
            overlay = Image.new("RGBA", dimmed.size, (0, 0, 0, 100))
            dimmed = Image.alpha_composite(dimmed, overlay)
            small_h = int(img.height * 0.88)
            small_w = int(img.width * 0.88)
            dimmed = dimmed.resize((small_w, small_h), Image.LANCZOS)
            y_offset = img.height - small_h
            frame.paste(dimmed, (x, y + y_offset), dimmed)
        else:
            frame.paste(img, (x, y), img)

    # 字幕バー（半透明の黒帯）
    overlay = Image.new("RGBA", RESOLUTION, (0, 0, 0, 0))
    draw_overlay = ImageDraw.Draw(overlay)
    draw_overlay.rectangle(
        [0, SUBTITLE_BAR_Y, RESOLUTION[0], RESOLUTION[1]],
        fill=(0, 0, 0, 185)
    )
    frame = Image.alpha_composite(frame, overlay)

    draw = ImageDraw.Draw(frame)

    # キャラクター名
    name_color = NAME_COLORS.get(character, (255, 255, 255))
    _draw_text_with_outline(
        draw,
        (SUBTITLE_PADDING, SUBTITLE_BAR_Y + 12),
        f"【{character}】",
        font=FONT_NAME,
        fill=(*name_color, 255),
        outline_width=2,
    )

    # 字幕テキスト（折り返し対応）
    max_w = RESOLUTION[0] - SUBTITLE_PADDING * 2
    wrapped = _wrap_subtitle(text, FONT_SUBTITLE, max_w)
    text_y = SUBTITLE_BAR_Y + 58
    for line in wrapped[:2]:  # 最大2行
        _draw_text_with_outline(
            draw,
            (SUBTITLE_PADDING, text_y),
            line,
            font=FONT_SUBTITLE,
            fill=(255, 255, 255, 255),
            outline_width=3,
        )
        text_y += 62

    return np.array(frame.convert("RGB"))


# ── BGM合成 ───────────────────────────────────────────────

def _load_bgm(total_duration: float) -> AudioFileClip | None:
    """BGMを読み込んで全体の尺に合わせてループさせる"""
    bgm_files = list(BGM_DIR.glob("*.mp3")) + list(BGM_DIR.glob("*.wav"))
    if not bgm_files:
        return None

    bgm = AudioFileClip(str(bgm_files[0])).with_volume_scaled(BGM_VOLUME)

    # 必要な長さまでループ
    if bgm.duration < total_duration:
        loops = int(total_duration / bgm.duration) + 1
        from moviepy import concatenate_audioclips
        bgm = concatenate_audioclips([bgm] * loops)

    bgm = bgm.subclipped(0, total_duration)
    bgm = bgm.audio_fadein(BGM_FADEIN).audio_fadeout(BGM_FADEOUT)
    return bgm


# ── メイン処理 ────────────────────────────────────────────

def build_video(script: dict, audio_dir: Path, output_path: Path) -> Path:
    """台本JSONと音声ファイルから動画を生成する"""
    print("動画を生成しています...")
    print(f"  エンコード設定: preset={ENCODE_PRESET}, threads={ENCODE_THREADS or 'auto'}")

    # 素材を読み込む
    bg = _load_background()
    char_images = {}
    for name, cfg in CHAR_CONFIG.items():
        char_images[name] = _load_character(name, cfg["height"])
        status = "読み込み済み" if char_images[name] else "プレースホルダー使用"
        print(f"  キャラ画像 {name}: {status}")

    # セリフリストを事前に収集（音声ファイルが存在するものだけ）
    line_entries = []  # [(line_num, character, text, audio_path), ...]
    line_num = 1
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            audio_path = audio_dir / f"{line_num:03d}_{line['character']}.wav"
            if audio_path.exists():
                line_entries.append((line_num, line["character"], line["text"], audio_path))
            line_num += 1

    if not line_entries:
        raise ValueError("有効なクリップがありません。音声ファイルを確認してください。")

    # フレームを並列レンダリング（CPU処理なのでスレッドが有効）
    print(f"  {len(line_entries)} フレームを並列レンダリングしています...")
    def render_frame(entry):
        _, character, text, _ = entry
        return compose_frame(character, text, bg, char_images)

    with ThreadPoolExecutor(max_workers=4) as executor:
        frames = list(executor.map(render_frame, line_entries))

    # クリップを組み立てる
    clips = []
    for frame, (_, character, text, audio_path) in zip(frames, line_entries):
        audio_clip = AudioFileClip(str(audio_path))
        clip = ImageClip(frame, duration=audio_clip.duration).with_fps(FPS)
        clip = clip.with_audio(audio_clip)
        clips.append(clip)

    print(f"  {len(clips)} クリップを結合しています...")
    video = concatenate_videoclips(clips, method="compose")

    # BGMを合成
    bgm = _load_bgm(video.duration)
    if bgm:
        mixed = CompositeAudioClip([video.audio, bgm])
        video = video.with_audio(mixed)
        print("  BGMを合成しました")
    else:
        print("  BGMファイルが見つかりません（assets/bgm/ に配置してください）")

    # MP4書き出し（高速プリセット＋マルチスレッド）
    output_path.parent.mkdir(parents=True, exist_ok=True)
    print(f"  MP4を書き出しています → {output_path}")
    video.write_videofile(
        str(output_path),
        fps=FPS,
        codec="libx264",
        audio_codec="aac",
        preset=ENCODE_PRESET,
        threads=ENCODE_THREADS,
        temp_audiofile=str(output_path.parent / "_temp_audio.m4a"),
        remove_temp=True,
        logger=None,
    )

    print(f"完了！動画を保存しました: {output_path}")
    return output_path


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
