# VOICEVOX音声合成モジュール

import array as _array_mod
import io as _io_mod
import json
import os
import platform
import subprocess
import sys
import time
import wave as _wave_mod
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from audio_processor import apply_pipeline, apply_prosody
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

def _get_tts_base_url() -> str:
    """TTS_PROVIDER に応じた接続先 URL を返す"""
    provider = os.getenv("TTS_PROVIDER", "aquestalk").lower()
    if provider == "aivis":
        return os.getenv("AIVIS_URL", "http://localhost:10101")
    return os.getenv("VOICEVOX_URL", "http://localhost:50021")

VOICEVOX_URL = _get_tts_base_url()

# VOICEVOXの一般的なインストール先候補（Windows）
VOICEVOX_CANDIDATES = [
    Path(r"C:\Users") / Path.home().name / "AppData/Local/Programs/VOICEVOX/VOICEVOX.exe",
    Path(r"C:\Program Files\VOICEVOX\VOICEVOX.exe"),
    Path(r"C:\Program Files (x86)\VOICEVOX\VOICEVOX.exe"),
]

# 読み方辞書ファイルのパス
READING_DICT_PATH = Path(__file__).parent / "reading_dict.json"

# ── キャラクター設定 ──────────────────────────────────────────
# スピーカーIDと話速は .env で変更できる
#
# スピーカーIDを確認するには:
#   python tts.py --list-speakers
#
# ── VOICEVOX 推奨スピーカー（バージョンによって変わることあり）──
#   ID  名前
#    0  四国めたん (ノーマル)   ← 霊夢向き（明るい女声）
#    1  四国めたん (あまあま)
#    2  四国めたん (ツンツン)
#    3  四国めたん (セクシー)
#    4  ずんだもん (ノーマル)   ← 魔理沙向き（元気な声）
#    5  ずんだもん (あまあま)
#   13  白上虎太郎 (ふつう)     ← 男声が欲しい場合
#
# ── AivisSpeech 推奨モデル（hub.aivis-project.com で配布）────
#   霊夢向き: Anneli (ノーマル) / つくよみちゃん
#   魔理沙向き: ずんだもん (ノーマル) / 春日部つむぎ
#   ※ AivisSpeech ではスピーカーIDが VOICEVOX と異なるため要確認
#
# .env 設定例（AivisSpeech 使用時）:
#   TTS_PROVIDER=aivis
#   VOICEVOX_SPEAKER_霊夢=<AivisSpeechで確認したID>
#   VOICEVOX_SPEAKER_魔理沙=<AivisSpeechで確認したID>
#   TTS_SPEED_霊夢=1.05
#   TTS_SPEED_魔理沙=1.10

def _build_character_settings() -> dict:
    """キャラクター設定を .env の値で上書きして返す"""
    return {
        "霊夢": {
            "speaker_id": int(os.getenv("VOICEVOX_SPEAKER_霊夢",  "2")),
            "speed":     float(os.getenv("TTS_SPEED_霊夢",        "1.05")),
        },
        "魔理沙": {
            "speaker_id": int(os.getenv("VOICEVOX_SPEAKER_魔理沙", "3")),
            "speed":     float(os.getenv("TTS_SPEED_魔理沙",       "1.10")),
        },
    }

CHARACTER_SETTINGS = _build_character_settings()


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

# TTSクライアントはプロバイダ設定に応じて初期化（起動時に1回だけ生成）
def _get_tts_client():
    from providers import get_tts_client
    return get_tts_client()


def synthesize(text: str, speaker_id: int, speed: float) -> bytes:
    """テキストをWAVバイナリに変換する（TTSプロバイダに委譲）"""
    return _get_tts_client().synthesize(text, speaker_id, speed)


def generate_audio_from_script(script: dict, output_dir: Path) -> list[Path]:
    """
    台本JSONから全セリフの音声を並列生成して保存する。

    TTS_PROVIDER=aquestalk の場合は AquesTalk1 (霊夢=f1/魔理沙=f2) を使う。
    それ以外は VOICEVOX / AivisSpeech を使う。
    """
    provider = os.getenv("TTS_PROVIDER", "aquestalk").lower()

    # AquesTalk1 プロバイダー分岐
    if provider == "aquestalk":
        return _generate_audio_aquestalk(script, output_dir)

    if not ensure_voicevox():
        raise ConnectionError("VOICEVOXを起動できませんでした。")

    output_dir.mkdir(parents=True, exist_ok=True)
    max_workers = int(os.getenv("TTS_WORKERS", "3"))

    # セリフリストを (line_num, character, synthesis_text, prosody) として収集
    # synthesis_text が設定されている場合はそちらを優先（発音補正済み）
    # text は字幕表示用に残しているため変更しない
    all_lines: list[tuple[int, str, str, dict | None]] = []
    line_num = 1
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            # synthesis_text があれば使う（pronunciation.py が設定）
            synth_text = line.get("synthesis_text") or line["text"]
            prosody = line.get("prosody")
            all_lines.append((line_num, line["character"], synth_text, prosody))
            line_num += 1

    total = len(all_lines)
    print(f"  {total} 件の音声を並列生成します（workers={max_workers}）")

    def process_one(args: tuple[int, str, str, dict | None]) -> Path | None:
        num, character, text, prosody = args
        settings = CHARACTER_SETTINGS.get(character)
        if settings is None:
            print(f"  [!] [{num:03d}] 「{character}」の設定が未定義。スキップします。")
            return None

        output_path = output_dir / f"{num:03d}_{character}.wav"
        try:
            # プロソディのspeedをVOICEVOX speedScaleに反映
            speed = settings["speed"]
            if prosody and prosody.get("speed", 1.0) != 1.0:
                speed = speed * prosody["speed"]
            wav_data = synthesize(text, settings["speaker_id"], speed)
            wav_data = apply_pipeline(wav_data, character)   # 後処理パイプライン
            # プロソディのピッチ・音量を適用
            if prosody:
                wav_data = apply_prosody(wav_data, prosody)
            output_path.write_bytes(wav_data)
            preview = text[:20] + ("..." if len(text) > 20 else "")
            print(f"  [{num:03d}] {character}: {preview}")
            return output_path
        except requests.HTTPError as e:
            print(f"  [!] [{num:03d}] {character} の音声生成に失敗: {e}")
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


def _mix_wav_bytes(wav1: bytes, wav2: bytes) -> bytes:
    """2つの16bit mono WAVバイト列を重ねてミックスして返す"""
    def read_samples(data: bytes):
        with _wave_mod.open(_io_mod.BytesIO(data)) as wf:
            params = wf.getparams()
            raw = wf.readframes(wf.getnframes())
        return params, _array_mod.array("h", raw)

    params, s1 = read_samples(wav1)
    _,      s2 = read_samples(wav2)

    # 短い方をゼロパディングして長さを揃える
    max_len = max(len(s1), len(s2))
    s1.extend([0] * (max_len - len(s1)))
    s2.extend([0] * (max_len - len(s2)))

    # 各チャンネル0.65倍で加算してクリッピング防止
    mixed = _array_mod.array("h", [
        max(-32768, min(32767, int(a * 0.65 + b * 0.65)))
        for a, b in zip(s1, s2)
    ])

    buf = _io_mod.BytesIO()
    with _wave_mod.open(buf, "wb") as wf:
        wf.setparams(params)
        wf.writeframes(mixed.tobytes())
    return buf.getvalue()


def _generate_audio_aquestalk(script: dict, output_dir: Path) -> list[Path]:
    """AquesTalk1 (霊夢=f1/魔理沙=f2) で台本全セリフの音声を生成する（逐次処理）"""
    from tts_aquestalk import synthesize as aq_synthesize, _SPEED_MAP
    output_dir.mkdir(parents=True, exist_ok=True)

    all_lines: list[tuple[int, str, str, dict | None]] = []
    line_num = 1
    for section in script.get("sections", []):
        for line in section.get("lines", []):
            synth_text = line.get("synthesis_text") or line["text"]
            prosody = line.get("prosody")  # {"speed": 1.08, "pitch": 1.5, "volume": 2.0}
            all_lines.append((line_num, line["character"], synth_text, prosody))
            line_num += 1

    total = len(all_lines)
    print(f"  {total} 件の音声を AquesTalk1 で生成します（逐次処理）")

    saved_files: list[Path] = []
    for num, character, text, prosody in all_lines:
        output_path = output_dir / f"{num:03d}_{character}.wav"
        if output_path.exists():
            # キャッシュ済みはスキップ
            saved_files.append(output_path)
            continue

        # 両者ハモり: 霊夢・魔理沙を同じ速さ(118)で生成してWAVミックス（プロソディ無効）
        if character == "両者":
            try:
                tmp_r = output_dir / f"{num:03d}_両者_r_tmp.wav"
                tmp_m = output_dir / f"{num:03d}_両者_m_tmp.wav"
                aq_synthesize(text, "霊夢",   tmp_r, speed=118)
                aq_synthesize(text, "魔理沙", tmp_m, speed=118)
                mixed = _mix_wav_bytes(tmp_r.read_bytes(), tmp_m.read_bytes())
                output_path.write_bytes(mixed)
                tmp_r.unlink(missing_ok=True)
                tmp_m.unlink(missing_ok=True)
                preview = text[:20] + ("..." if len(text) > 20 else "")
                print(f"  [{num:03d}] 両者(ハモり): {preview}")
                saved_files.append(output_path)
            except Exception as e:
                print(f"  [!] [{num:03d}] 両者ハモり生成失敗: {e}")
            continue

        # プロソディ: speed変動を計算（AquesTalkのspeedパラメータに反映）
        line_speed = None
        if prosody and prosody.get("speed", 1.0) != 1.0:
            voice_key = "reimu" if character == "霊夢" else "marisa"
            base_speed = _SPEED_MAP.get(voice_key, 100)
            line_speed = int(base_speed * prosody["speed"])

        try:
            aq_synthesize(text, character, output_path, speed=line_speed)
            # 後処理パイプライン（WAVバイト読み取り→処理→上書き）
            try:
                wav_data = apply_pipeline(output_path.read_bytes(), character)
                # プロソディのピッチ・音量を適用（speed以外）
                if prosody:
                    wav_data = apply_prosody(wav_data, prosody)
                output_path.write_bytes(wav_data)
            except Exception:
                pass  # パイプライン失敗は無視して生成済み WAV をそのまま使う
            preview = text[:20] + ("..." if len(text) > 20 else "")
            prosody_tag = ""
            if prosody:
                parts = []
                if prosody.get("speed", 1.0) != 1.0:
                    parts.append(f"spd={prosody['speed']}")
                if abs(prosody.get("pitch", 0)) >= 0.1:
                    parts.append(f"pit={prosody['pitch']:+.1f}")
                if abs(prosody.get("volume", 0)) >= 0.5:
                    parts.append(f"vol={prosody['volume']:+.1f}")
                if parts:
                    prosody_tag = f" [{','.join(parts)}]"
            print(f"  [{num:03d}] {character}: {preview}{prosody_tag}")
            saved_files.append(output_path)
        except Exception as e:
            msg = f"  [!] [{num:03d}] {character} の音声生成に失敗: {e}"
            try:
                print(msg)
            except UnicodeEncodeError:
                print(msg.encode("cp932", errors="replace").decode("cp932"))

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
