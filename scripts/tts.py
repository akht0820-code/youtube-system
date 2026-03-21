# VOICEVOX音声合成モジュール

import array
import io
import json
import math
import os
import platform
import subprocess
import sys
import time
import wave
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

VOICEVOX_URL = "http://localhost:50021"

# VOICEVOXの一般的なインストール先候補（Windows）
VOICEVOX_CANDIDATES = [
    Path(r"C:\Users") / Path.home().name / "AppData/Local/Programs/VOICEVOX/VOICEVOX.exe",
    Path(r"C:\Program Files\VOICEVOX\VOICEVOX.exe"),
    Path(r"C:\Program Files (x86)\VOICEVOX\VOICEVOX.exe"),
]

# 読み方辞書ファイルのパス
READING_DICT_PATH = Path(__file__).parent / "reading_dict.json"

# 目標音量（dBFS）。全キャラの音量をこの値に統一する
TARGET_DBFS = -20.0

# キャラクター設定: スピーカーID と 話速（speedScale）
# speedScale: 1.0=普通 / 1.2=早口 / 0.9=ゆっくり
CHARACTER_SETTINGS = {
    "霊夢": {"speaker_id": 2,  "speed": 1.05},  # 四国めたん: リアクション役・明るめ
    "魔理沙": {"speaker_id": 3, "speed": 1.1},  # ずんだもん: 解説役・やや早口
}


# ── VOICEVOX起動管理 ─────────────────────────────────────

def is_voicevox_running() -> bool:
    try:
        res = requests.get(f"{VOICEVOX_URL}/version", timeout=3)
        return res.status_code == 200
    except requests.ConnectionError:
        return False


def find_voicevox_exe() -> Path | None:
    for path in VOICEVOX_CANDIDATES:
        if path.exists():
            return path
    return None


def launch_voicevox() -> bool:
    # Linux（GitHub Actions / VPS）ではDockerサービスとして起動済みのため自動起動不要
    if platform.system() != "Windows":
        print("Linux環境: VOICEVOXはDockerサービスとして起動済みのはずです。")
        return False

    exe = find_voicevox_exe()
    if exe is None:
        print("VOICEVOXの実行ファイルが見つかりませんでした。手動で起動してください。")
        return False

    print(f"VOICEVOXを起動しています: {exe}")
    subprocess.Popen([str(exe)], creationflags=subprocess.DETACHED_PROCESS)

    for i in range(30):
        time.sleep(1)
        if is_voicevox_running():
            print("VOICEVOXの起動を確認しました。")
            return True
        print(f"  待機中... ({i + 1}/30秒)", end="\r")

    print("\nVOICEVOXの起動がタイムアウトしました。手動で確認してください。")
    return False


def ensure_voicevox() -> bool:
    if is_voicevox_running():
        return True
    # Linux環境ではDockerの起動を少し待ってリトライ
    if platform.system() != "Windows":
        print("VOICEVOXの起動を待っています...")
        for i in range(20):
            time.sleep(3)
            if is_voicevox_running():
                print("VOICEVOXの起動を確認しました。")
                return True
            print(f"  待機中... ({(i+1)*3}/60秒)", end="\r")
        print("\nVOICEVOXに接続できませんでした。")
        return False
    print("VOICEVOXが起動していません。自動起動します...")
    return launch_voicevox()


# ── 音量正規化 ───────────────────────────────────────────

def normalize_wav(wav_bytes: bytes, target_dbfs: float = TARGET_DBFS) -> bytes:
    """WAVデータの音量を target_dbfs に統一する（標準ライブラリのみ使用）"""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        n_channels = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        frames = w.readframes(w.getnframes())

    # 16bit PCMとして読み込む
    samples = array.array("h", frames)
    if not samples:
        return wav_bytes

    # 現在のRMSを計算
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    if rms == 0:
        return wav_bytes

    # 目標RMSに合わせてゲインを計算
    target_rms = 32767 * (10 ** (target_dbfs / 20))
    gain = target_rms / rms

    # クリッピング防止付きでスケーリング
    normalized = array.array(
        "h", [max(-32768, min(32767, int(s * gain))) for s in samples]
    )

    # WAVとして書き直す
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(n_channels)
        w.setsampwidth(sampwidth)
        w.setframerate(framerate)
        w.writeframes(normalized.tobytes())

    return buf.getvalue()


# ── 読み方辞書 ───────────────────────────────────────────

def _load_reading_dict() -> dict:
    if READING_DICT_PATH.exists():
        return json.loads(READING_DICT_PATH.read_text(encoding="utf-8"))
    return {}


def _save_reading_dict(data: dict):
    READING_DICT_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def add_reading(surface: str, reading: str):
    """単語と読み方をVOICEVOXユーザー辞書に登録する"""
    if not ensure_voicevox():
        print("VOICEVOXに接続できないため登録できません。")
        return

    # VOICEVOX APIに登録（reading はカタカナ）
    res = requests.post(
        f"{VOICEVOX_URL}/user_dict_word",
        params={
            "surface": surface,
            "pronunciation": reading,
            "accent_type": 0,
            "word_type": "PROPER_NOUN",
            "priority": 10,
        },
    )
    res.raise_for_status()
    uuid = res.text.strip('"')

    # ローカルJSONにも保存
    data = _load_reading_dict()
    data[surface] = {"reading": reading, "uuid": uuid}
    _save_reading_dict(data)

    print(f"登録しました: 「{surface}」→「{reading}」（UUID: {uuid[:8]}...）")


def remove_reading(surface: str):
    """単語をVOICEVOXユーザー辞書から削除する"""
    data = _load_reading_dict()
    entry = data.get(surface)
    if not entry:
        print(f"「{surface}」は辞書に登録されていません。")
        return

    if ensure_voicevox():
        try:
            res = requests.delete(f"{VOICEVOX_URL}/user_dict_word/{entry['uuid']}")
            res.raise_for_status()
        except requests.HTTPError:
            print("VOICEVOXからの削除に失敗しました（ローカルからは削除します）。")

    del data[surface]
    _save_reading_dict(data)
    print(f"削除しました: 「{surface}」")


def sync_readings():
    """ローカルJSONの内容をVOICEVOXに一括登録する（再インストール後などに使用）"""
    data = _load_reading_dict()
    if not data:
        print("辞書が空です。")
        return

    if not ensure_voicevox():
        print("VOICEVOXに接続できません。")
        return

    print(f"{len(data)} 件を同期します...")
    for surface, entry in data.items():
        res = requests.post(
            f"{VOICEVOX_URL}/user_dict_word",
            params={
                "surface": surface,
                "pronunciation": entry["reading"],
                "accent_type": 0,
                "word_type": "PROPER_NOUN",
                "priority": 10,
            },
        )
        if res.ok:
            new_uuid = res.text.strip('"')
            entry["uuid"] = new_uuid
            print(f"  登録: 「{surface}」→「{entry['reading']}」")
        else:
            print(f"  失敗: 「{surface}」")

    _save_reading_dict(data)
    print("同期完了。")


def list_readings():
    """登録済みの読み方一覧を表示"""
    data = _load_reading_dict()
    if not data:
        print("登録された読み方はありません。")
        return
    print(f"{'単語':<20} 読み方")
    print("-" * 40)
    for surface, entry in data.items():
        print(f"{surface:<20} {entry['reading']}")


# ── スピーカー一覧 ───────────────────────────────────────

def list_speakers():
    if not is_voicevox_running():
        print("エラー: VOICEVOXが起動していません")
        return
    res = requests.get(f"{VOICEVOX_URL}/speakers")
    speakers = res.json()
    print(f"{'スピーカー名':<25} {'スタイル':<20} {'ID'}")
    print("-" * 55)
    for speaker in speakers:
        for style in speaker["styles"]:
            print(f"{speaker['name']:<25} {style['name']:<20} {style['id']}")


# ── 音声合成 ─────────────────────────────────────────────

def synthesize(text: str, speaker_id: int, speed: float) -> bytes:
    """テキストをWAVバイナリに変換する"""
    query_res = requests.post(
        f"{VOICEVOX_URL}/audio_query",
        params={"text": text, "speaker": speaker_id},
    )
    query_res.raise_for_status()
    query = query_res.json()

    # キャラクターごとの話速を適用
    query["speedScale"] = speed
    query["pauseLength"] = 0.3
    query["pauseLengthScale"] = 1.0

    synth_res = requests.post(
        f"{VOICEVOX_URL}/synthesis",
        params={"speaker": speaker_id},
        data=json.dumps(query),
        headers={"Content-Type": "application/json"},
    )
    synth_res.raise_for_status()
    return synth_res.content


def generate_audio_from_script(script: dict, output_dir: Path) -> list[Path]:
    """
    台本JSONから全セリフの音声を並列生成して保存する。

    VOICEVOX の synthesis エンドポイントはサーバー側で逐次処理されるが、
    audio_query・normalize_wav・ファイル書き込みは並列化できる。
    TTS_WORKERS=3 が概ねバランスの良い値（増やしすぎると VOICEVOX が詰まる）。
    """
    if not ensure_voicevox():
        raise ConnectionError("VOICEVOXを起動できませんでした。")

    output_dir.mkdir(parents=True, exist_ok=True)
    max_workers = int(os.getenv("TTS_WORKERS", "3"))

    # セリフリストを (line_num, character, text) として収集
    all_lines: list[tuple[int, str, str]] = []
    line_num = 1
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            all_lines.append((line_num, line["character"], line["text"]))
            line_num += 1

    total = len(all_lines)
    print(f"  {total} 件の音声を並列生成します（workers={max_workers}）")

    def process_one(args: tuple[int, str, str]) -> Path | None:
        num, character, text = args
        settings = CHARACTER_SETTINGS.get(character)
        if settings is None:
            print(f"  ⚠ [{num:03d}] 「{character}」の設定が未定義。スキップします。")
            return None

        output_path = output_dir / f"{num:03d}_{character}.wav"
        try:
            wav_data = synthesize(text, settings["speaker_id"], settings["speed"])
            wav_data = normalize_wav(wav_data)
            output_path.write_bytes(wav_data)
            preview = text[:20] + ("..." if len(text) > 20 else "")
            print(f"  [{num:03d}] {character}: {preview}")
            return output_path
        except requests.HTTPError as e:
            print(f"  ⚠ [{num:03d}] {character} の音声生成に失敗: {e}")
            return None

    saved_files: list[Path] = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(process_one, args): args[0] for args in all_lines}
        for future in as_completed(futures):
            result = future.result()
            if result:
                saved_files.append(result)

    # ファイル名順（= セリフ順）にソートして返す
    return sorted(saved_files)


# ── CLIエントリーポイント ────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "--help":
        print("使い方:")
        print("  python tts.py --list-speakers              スピーカー一覧を表示")
        print("  python tts.py --list-readings              登録済み読み方を表示")
        print("  python tts.py --add-reading <単語> <読み>  読み方を登録（読みはカタカナ）")
        print("  python tts.py --remove-reading <単語>      読み方を削除")
        print("  python tts.py --sync-readings              辞書をVOICEVOXに一括同期")
    elif args[0] == "--list-speakers":
        list_speakers()
    elif args[0] == "--list-readings":
        list_readings()
    elif args[0] == "--add-reading" and len(args) == 3:
        add_reading(args[1], args[2])
    elif args[0] == "--remove-reading" and len(args) == 2:
        remove_reading(args[1])
    elif args[0] == "--sync-readings":
        sync_readings()
    else:
        print("引数が正しくありません。--help で確認してください。")
