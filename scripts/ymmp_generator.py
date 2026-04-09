# ゆっくりMovieMaker4 (.ymmp) プロジェクトファイル生成モジュール
#
# 台本JSON + 生成済み音声WAVから YMM4 プロジェクトファイルを生成する。
# 生成したファイルを YMM4 で開くと、タイムライン・セリフ・立ち絵が
# 自動配置された状態になる。
#
# 使い方:
#   from ymmp_generator import build_ymmp
#   ymmp_path = build_ymmp(script, wav_map, output_dir)
#
# wav_map: {line_index: wav_bytes} または {line_index: wav_path}
#
# 参考:
#   - .ymmp は UTF-8 JSON（BOMなし）
#   - Timelines[0].Items にタイムラインアイテムを格納
#   - VoiceItem の Frame はタイムライン先頭からのフレーム数（30fps）
#   - キャラクター立ち絵は ImageItem で別レイヤーに配置

import io
import json
import math
import uuid
import wave
from pathlib import Path
from typing import Any

# BudouX（日本語の自然な改行位置を検出するライブラリ）
# pip install budoux でインストール済み
try:
    import budoux as _budoux
    _BUDOUX_PARSER = _budoux.load_default_japanese_parser()
except Exception:
    _BUDOUX_PARSER = None

# ── 定数 ───────────────────────────────────────────────────────────

FPS = 30                    # タイムラインのフレームレート
SAMPLE_RATE = 44100         # 音声サンプルレート（Hz）
WIDTH  = 1920               # 動画の横幅
HEIGHT = 1080               # 動画の高さ

# セリフとセリフの間に挟む無音フレーム数（0.5秒）
GAP_FRAMES = 15

# キャラクターレイヤー設定
LAYER_VOICE   = 1           # 音声アイテムのレイヤー
LAYER_FACE    = 2           # 表情（立ち絵）のレイヤー
LAYER_BG      = 0           # 背景のレイヤー

# キャラクターごとの立ち絵X座標（画面を左右に分ける）
CHARACTER_X = {
    "霊夢":  480,    # 画面左側
    "魔理沙": 1440,  # 画面右側
}

# YMM4内部の型識別子
_TYPE_VOICE = (
    "YukkuriMovieMaker.Project.Items.VoiceItem, YukkuriMovieMaker"
)
_TYPE_IMAGE = (
    "YukkuriMovieMaker.Project.Items.ImageItem, YukkuriMovieMaker"
)
_TYPE_TEXT = (
    "YukkuriMovieMaker.Project.Items.TextItem, YukkuriMovieMaker"
)


# ── テロップ改行（BudouX）────────────────────────────────────────

_TELOP_MAX_LINE = 20    # 1行の最大文字数
_TELOP_MAX_LINES = 2    # 最大行数

def _smart_line_break(text: str, max_chars: int = _TELOP_MAX_LINE) -> str:
    """
    日本語テキストを意味のまとまりで改行する（BudouX使用）。
    1行 max_chars 文字以内、最大 _TELOP_MAX_LINES 行に収める。
    BudouX未インストール時は単純な文字数折り返しにフォールバック。
    """
    if len(text) <= max_chars:
        return text

    if _BUDOUX_PARSER is not None:
        try:
            chunks = _BUDOUX_PARSER.parse(text)
            lines: list[str] = []
            current = ""
            for chunk in chunks:
                if len(current) + len(chunk) > max_chars and current:
                    lines.append(current)
                    current = chunk
                    if len(lines) >= _TELOP_MAX_LINES - 1:
                        # 残りは全てまとめる
                        remaining = "".join(chunks[chunks.index(chunk):])
                        lines.append(remaining[:max_chars * 2])
                        return "\n".join(lines[:_TELOP_MAX_LINES])
                else:
                    current += chunk
            if current:
                lines.append(current)
            return "\n".join(lines[:_TELOP_MAX_LINES])
        except Exception:
            pass

    # フォールバック: 文字数で単純折り返し
    return "\n".join([
        text[i:i + max_chars]
        for i in range(0, min(len(text), max_chars * _TELOP_MAX_LINES), max_chars)
    ])


# ── 音声長さの計算 ────────────────────────────────────────────────

def _wav_duration_frames(wav_bytes: bytes) -> int:
    """WAVバイナリの長さをフレーム数（30fps換算）で返す"""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            duration_sec = w.getnframes() / w.getframerate()
        return max(1, math.ceil(duration_sec * FPS))
    except Exception:
        return FPS * 3  # 読み込み失敗時は3秒と仮定


# ── アイテム生成ヘルパー ─────────────────────────────────────────

def _make_voice_item(
    serif: str,
    character_name: str,
    frame: int,
    length: int,
    layer: int = LAYER_VOICE,
    wav_path: str = "",
) -> dict[str, Any]:
    """VoiceItem（セリフアイテム）を生成して返す"""
    return {
        "$type": _TYPE_VOICE,
        "Serif": serif,
        "CharacterName": character_name,
        "Frame": frame,
        "Length": length,
        "Layer": layer,
        "IsLocked": False,
        "IsHidden": False,
        "FilePath": wav_path,
        "VoiceParameter": {
            "Speed": 1.0,
            "Volume": 1.0,
            "Pitch": 0.0,
        },
        "Hatsuon": None,
        "Decorations": [],
    }


def _make_image_item(
    file_path: str,
    frame: int,
    length: int,
    x: int,
    y: int,
    layer: int = LAYER_FACE,
    scale: float = 1.0,
) -> dict[str, Any]:
    """ImageItem（画像アイテム）を生成して返す"""
    return {
        "$type": _TYPE_IMAGE,
        "FilePath": file_path,
        "Frame": frame,
        "Length": length,
        "Layer": layer,
        "IsLocked": False,
        "IsHidden": False,
        "X": x,
        "Y": HEIGHT // 2,   # 縦は中央
        "Zoom": scale,
        "Alpha": 1.0,
    }


# ── キャラクター設定生成 ─────────────────────────────────────────

def _make_character_entry(
    name: str,
    image_path: str = "",
) -> dict[str, Any]:
    """Characters[] に入れるキャラクター設定を生成して返す"""
    return {
        "Name": name,
        "CastName": name,
        "Image": image_path,
        "X": CHARACTER_X.get(name, WIDTH // 2),
        "Y": HEIGHT // 2,
        "Zoom": 1.0,
        "Flip": name == "魔理沙",   # 魔理沙は右向きに反転
    }


# ── メイン生成関数 ────────────────────────────────────────────────

def build_wav_map_from_dir(audio_dir: Path) -> dict[int, Path]:
    """
    tts.py が生成した音声ディレクトリから {0始まりインデックス: WAVパス} を構築する。
    ファイル名形式: {num:03d}_{character}.wav （numは1始まり）
    """
    wav_map: dict[int, Path] = {}
    for wav_file in sorted(audio_dir.glob("*.wav")):
        try:
            # "001_霊夢.wav" → num=1 → index=0
            num = int(wav_file.name.split("_")[0])
            wav_map[num - 1] = wav_file
        except (ValueError, IndexError):
            continue
    return wav_map


def build_ymmp(
    script: dict,
    wav_map: dict[int, bytes | str | Path] | None = None,
    output_dir: Path | str = ".",
    assets_dir: Path | str | None = None,
    audio_dir: Path | str | None = None,
) -> Path:
    """
    台本JSONからYMM4プロジェクトファイル（.ymmp）を生成する。

    Args:
        script:     generator.py が生成した台本JSON
                    {"sections": [{"section": str, "lines": [...]}]}
        wav_map:    {グローバル行インデックス（0始まり）: WAVバイナリ or WAVファイルパス}
                    None かつ audio_dir 指定の場合は audio_dir から自動構築する
        output_dir: .ymmp ファイルの出力先ディレクトリ
        assets_dir: characters/ や bgm/ の親ディレクトリ
                    None の場合は output_dir/../assets を使う
        audio_dir:  tts.py の出力ディレクトリ（wav_map が None のときに使う）

    Returns:
        生成した .ymmp ファイルのパス
    """
    # audio_dir が指定されていれば wav_map を自動構築
    if wav_map is None and audio_dir is not None:
        wav_map = build_wav_map_from_dir(Path(audio_dir))
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if assets_dir is None:
        # scripts/ から実行される場合は ../assets を参照
        assets_dir = Path(__file__).parent.parent / "assets"
    assets_dir = Path(assets_dir)

    # キャラクター立ち絵パス
    char_images: dict[str, str] = {}
    for char in ["霊夢", "魔理沙"]:
        img = assets_dir / "characters" / f"{char}.png"
        if img.exists():
            char_images[char] = str(img)
        else:
            char_images[char] = ""

    items: list[dict] = []
    current_frame = 0
    global_line_idx = 0

    for section in script.get("sections", []):
        for line in section.get("lines", []):
            # 字幕表示は元の漢字テキスト、WAV生成は synthesis_text で行われている
            display_text = line.get("text", "")
            character    = line.get("character", "霊夢")

            # WAV長さの推定用にも display_text を使う
            text = display_text

            # WAV長さを取得
            if wav_map is not None and global_line_idx in wav_map:
                wav_data = wav_map[global_line_idx]
                if isinstance(wav_data, (str, Path)):
                    wav_path_str = str(wav_data)
                    try:
                        length = _wav_duration_frames(Path(wav_data).read_bytes())
                    except Exception:
                        length = FPS * 3
                else:
                    wav_path_str = ""
                    length = _wav_duration_frames(wav_data)
            else:
                wav_path_str = ""
                # テキスト長さから推定（1文字 ≒ 0.1秒）
                length = max(FPS, math.ceil(len(text) * 0.1 * FPS))

            # 音声アイテム（Serif=字幕表示用テキスト・BudouX改行適用済み）
            telop_text = _smart_line_break(display_text)
            voice_item = _make_voice_item(
                serif=telop_text,
                character_name=character,
                frame=current_frame,
                length=length,
                layer=LAYER_VOICE,
                wav_path=wav_path_str,
            )
            items.append(voice_item)

            # 立ち絵アイテム（音声と同じ長さで配置）
            img_path = char_images.get(character, "")
            if img_path:
                x = CHARACTER_X.get(character, WIDTH // 2)
                face_item = _make_image_item(
                    file_path=img_path,
                    frame=current_frame,
                    length=length,
                    x=x,
                    y=HEIGHT // 2,
                    layer=LAYER_FACE,
                )
                items.append(face_item)

            current_frame += length + GAP_FRAMES
            global_line_idx += 1

    total_length = max(current_frame, 1)

    # ── Characters 定義 ────────────────────────────────────────
    characters = [
        _make_character_entry("霊夢",  char_images.get("霊夢",  "")),
        _make_character_entry("魔理沙", char_images.get("魔理沙", "")),
    ]

    # ── プロジェクトJSON組み立て ────────────────────────────────
    project: dict[str, Any] = {
        "Timelines": [
            {
                "VideoInfo": {
                    "FPS": FPS,
                    "Hz":  SAMPLE_RATE,
                    "Width":  WIDTH,
                    "Height": HEIGHT,
                },
                "Items": items,
                "LayerVisibilities": [],
                "CurrentFrame": 0,
                "Length": total_length,
                "MaxLayer": 10,
            }
        ],
        "Characters": characters,
        "YmmVersion": "4.14.0.0",
    }

    # ── ファイル出力 ────────────────────────────────────────────
    title = script.get("title", "動画")
    # ファイル名に使えない文字を除去
    safe_title = "".join(
        c for c in title if c not in r'\/:*?"<>|'
    )[:50] or "project"

    out_path = output_dir / f"{safe_title}.ymmp"
    out_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    total_lines = global_line_idx
    duration_sec = total_length / FPS
    print(f"  YMM4プロジェクト生成完了: {out_path.name}")
    print(f"    セリフ数: {total_lines} 行 / 総尺: {duration_sec:.1f} 秒")

    return out_path


# ── CLIツール ─────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("使い方:")
        print("  python ymmp_generator.py <台本JSONファイル> [出力ディレクトリ]")
        print('  例: python ymmp_generator.py output/script.json output/')
        sys.exit(0)

    script_path = Path(sys.argv[1])
    out_dir     = Path(sys.argv[2]) if len(sys.argv) > 2 else script_path.parent

    with open(script_path, encoding="utf-8") as f:
        script_data = json.load(f)

    result = build_ymmp(script_data, wav_map=None, output_dir=out_dir)
    print(f"生成完了: {result}")
