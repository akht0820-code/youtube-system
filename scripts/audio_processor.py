# 音声後処理パイプライン
# VOICEVOXが生成したWAVの品質を向上させる（標準ライブラリのみ使用）
#
# 処理フロー（apply_pipeline で一括適用）:
#   1. 無音トリミング   — 先頭・末尾の余分な無音を除去してテンポを上げる
#   2. RMS正規化       — 全キャラの音量を共通目標値に揃える
#   3. キャラ別ゲイン   — キャラごとの音量微調整（+dB で声の小さいキャラをブースト）
#   4. フェードイン     — クリックノイズ防止（15ms）
#   5. フェードアウト   — 語尾の自然な余韻（80ms）
#   6. ソフトリミッター — 正規化後のクリッピングを防止
#
# .env で設定可能:
#   AUDIO_TARGET_DBFS=-20.0      # RMS正規化の目標音量（dBFS）
#   AUDIO_TRIM_SILENCE=true      # 無音トリム（true/false）
#   AUDIO_TRIM_THRESHOLD=400     # 無音とみなすサンプル絶対値（0〜32767）
#   AUDIO_TRIM_MARGIN_MS=30      # トリム後に残す余白（ms）
#   AUDIO_FADE_IN_MS=15          # フェードイン長さ（ms）
#   AUDIO_FADE_OUT_MS=80         # フェードアウト長さ（ms）
#   AUDIO_GAIN_霊夢=2.0          # 霊夢の追加ゲイン（dB）
#   AUDIO_GAIN_魔理沙=0.0        # 魔理沙の追加ゲイン（dB）

import array
import io
import math
import os
import wave
from pathlib import Path

import numpy as np

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

# ── 設定値（.env で上書き可能）──────────────────────────────────

TARGET_DBFS    = float(os.getenv("AUDIO_TARGET_DBFS",    "-20.0"))
TRIM_SILENCE   = os.getenv("AUDIO_TRIM_SILENCE",   "true").lower() == "true"
TRIM_THRESHOLD = int(os.getenv("AUDIO_TRIM_THRESHOLD",   "400"))   # 0〜32767
TRIM_MARGIN_MS = int(os.getenv("AUDIO_TRIM_MARGIN_MS",   "30"))
FADE_IN_MS     = int(os.getenv("AUDIO_FADE_IN_MS",       "15"))
FADE_OUT_MS    = int(os.getenv("AUDIO_FADE_OUT_MS",      "80"))

# キャラクター別の追加ゲイン（dB）
# 正の値で音量アップ、負の値で音量ダウン
_CHAR_GAIN_DB: dict[str, float] = {
    "霊夢":  float(os.getenv("AUDIO_GAIN_霊夢",  "2.0")),  # 霊夢はやや小声なので+2dB
    "魔理沙": float(os.getenv("AUDIO_GAIN_魔理沙", "0.0")),
}


# ── 内部ユーティリティ ────────────────────────────────────────

def _load_wav(wav_bytes: bytes) -> tuple[array.array, int, int, int]:
    """WAVバイナリを読み込み (samples, framerate, channels, sampwidth) を返す"""
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        channels  = w.getnchannels()
        sampwidth = w.getsampwidth()
        framerate = w.getframerate()
        frames    = w.readframes(w.getnframes())
    samples = array.array("h", frames)
    return samples, framerate, channels, sampwidth


def _export_wav(samples: array.array, framerate: int,
                channels: int, sampwidth: int) -> bytes:
    """サンプル配列を WAVバイナリに変換して返す"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(sampwidth)
        w.setframerate(framerate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()


def _ms_to_samples(ms: int, framerate: int, channels: int) -> int:
    """ミリ秒をサンプル数に変換する（ステレオ考慮）"""
    return int(framerate * ms / 1000) * channels


# ── 処理ステップ ──────────────────────────────────────────────

def _trim_silence(samples: array.array, framerate: int, channels: int,
                  threshold: int, margin_ms: int) -> array.array:
    """
    先頭・末尾の無音（絶対値 < threshold のサンプルが続く区間）を除去する。
    margin_ms 分だけ余白を残すことで語頭の「ポップ」を防ぐ。
    """
    margin = _ms_to_samples(margin_ms, framerate, channels)
    total  = len(samples)

    # 先頭の無音を検索
    start = 0
    for i, s in enumerate(samples):
        if abs(s) > threshold:
            start = max(0, i - margin)
            break

    # 末尾の無音を検索
    end = total
    for i in range(total - 1, -1, -1):
        if abs(samples[i]) > threshold:
            end = min(total, i + margin + 1)
            break

    if start >= end:
        return samples  # 全体が無音 → そのまま返す
    return samples[start:end]


def _normalize_rms(samples: array.array, target_dbfs: float) -> array.array:
    """
    RMS（二乗平均平方根）ベースの音量正規化。
    全サンプルが0の場合はそのまま返す。
    """
    if not samples:
        return samples
    rms = math.sqrt(sum(s * s for s in samples) / len(samples))
    if rms == 0:
        return samples

    target_rms = 32767.0 * (10 ** (target_dbfs / 20.0))
    gain = target_rms / rms

    # クリッピング前にソフトリミットで丸める
    return array.array("h", [
        max(-32768, min(32767, int(s * gain))) for s in samples
    ])


def _apply_gain_db(samples: array.array, gain_db: float) -> array.array:
    """
    dB 単位のゲインを適用する（正 = 音量アップ、負 = 音量ダウン）。
    0 dB のときはコピーせずそのまま返す。
    """
    if gain_db == 0.0:
        return samples
    factor = 10 ** (gain_db / 20.0)
    return array.array("h", [
        max(-32768, min(32767, int(s * factor))) for s in samples
    ])


def _fade_inout(samples: array.array, framerate: int, channels: int,
                fade_in_ms: int, fade_out_ms: int) -> array.array:
    """
    先頭にフェードイン・末尾にフェードアウトを適用する。
    クリックノイズの防止と語尾の自然な余韻のため。
    """
    result = array.array("h", samples)  # コピー
    total  = len(result)

    fi = min(_ms_to_samples(fade_in_ms,  framerate, channels), total)
    fo = min(_ms_to_samples(fade_out_ms, framerate, channels), total)

    for i in range(fi):
        result[i] = int(result[i] * i / fi)
    for i in range(fo):
        idx = total - 1 - i
        result[idx] = int(result[idx] * i / fo)

    return result


def _soft_limit(samples: array.array, knee_ratio: float = 0.92) -> array.array:
    """
    ソフトリミッター：knee 以上のサンプルを滑らかに圧縮してクリッピングを防ぐ。
    knee_ratio=0.92 → 約 -0.7dBFS でニーが始まる。
    """
    knee = int(32767 * knee_ratio)
    result = array.array("h")
    for s in samples:
        a = abs(s)
        if a <= knee:
            result.append(s)
        else:
            sign = 1 if s >= 0 else -1
            over = a - knee
            # 超過分を対数的に圧縮（簡易版）
            compressed = knee + int(over / (1.0 + over / (32767 - knee)))
            result.append(sign * min(32767, compressed))
    return result


# ── ピッチシフト（プロソディ用）──────────────────────────────────


def _pitch_shift(samples: array.array, framerate: int,
                 semitones: float) -> array.array:
    """半音単位でピッチシフトする（numpy リサンプリング）。

    方式: サンプルレートを変えてピッチを変更し、元の長さにリサンプリングして
    再生速度（尺）を維持する。
    """
    if abs(semitones) < 0.1:
        return samples

    factor = 2.0 ** (semitones / 12.0)
    src = np.array(samples, dtype=np.float64)
    orig_len = len(src)
    # factor > 1 → 高い声: 短縮してから元の長さに引き延ばす
    # factor < 1 → 低い声: 伸張してから元の長さに縮める
    new_len = int(orig_len / factor)
    if new_len < 2:
        return samples

    # Step1: 元音声をnew_lenにリサンプリング（ピッチ変更+尺変化）
    indices_1 = np.linspace(0, orig_len - 1, new_len)
    stretched = np.interp(indices_1, np.arange(orig_len), src)

    # Step2: new_lenの音声を元の長さに戻す（尺を復元、ピッチは維持）
    indices_2 = np.linspace(0, new_len - 1, orig_len)
    resampled = np.interp(indices_2, np.arange(new_len), stretched)

    # クリッピング
    resampled = np.clip(resampled, -32768, 32767).astype(np.int16)
    return array.array("h", resampled.tobytes())


# ── パブリック API ──────────────────────────────────────────────

def apply_prosody(wav_bytes: bytes, prosody: dict) -> bytes:
    """プロソディ（抑揚）のピッチ・音量調整を適用する。

    speed は TTS エンジン側で適用済みのため、ここでは pitch と volume のみ。

    Args:
        wav_bytes: TTS生成済みWAVバイナリ
        prosody: {"speed": float, "pitch": float, "volume": float}
    """
    if not wav_bytes or not prosody:
        return wav_bytes

    pitch = prosody.get("pitch", 0.0)
    volume = prosody.get("volume", 0.0)

    if abs(pitch) < 0.1 and abs(volume) < 0.5:
        return wav_bytes

    try:
        samples, framerate, channels, sampwidth = _load_wav(wav_bytes)

        # ピッチシフト
        if abs(pitch) >= 0.1:
            samples = _pitch_shift(samples, framerate, pitch)

        # 音量調整
        if abs(volume) >= 0.5:
            samples = _apply_gain_db(samples, volume)

        # クリッピング防止
        samples = _soft_limit(samples)

        return _export_wav(samples, framerate, channels, sampwidth)
    except Exception as e:
        print(f"  [!] プロソディ適用失敗: {e} -> 元音声をそのまま使用")
        return wav_bytes


def apply_pipeline(wav_bytes: bytes, character: str = "") -> bytes:
    """
    音声後処理パイプラインを適用して品質向上したWAVバイナリを返す。

    処理順:
      1. 無音トリミング（AUDIO_TRIM_SILENCE=true のとき）
      2. RMS正規化（AUDIO_TARGET_DBFS に合わせる）
      3. キャラ別ゲイン（AUDIO_GAIN_{character} dB）
      4. フェードイン/アウト
      5. ソフトリミッター

    Args:
        wav_bytes: VOICEVOXが生成した生のWAVバイナリ
        character: キャラクター名（キャラ別ゲイン適用に使う）
    """
    if not wav_bytes:
        return wav_bytes

    try:
        samples, framerate, channels, sampwidth = _load_wav(wav_bytes)

        # Step1: 無音トリミング
        if TRIM_SILENCE:
            samples = _trim_silence(
                samples, framerate, channels,
                TRIM_THRESHOLD, TRIM_MARGIN_MS,
            )

        # Step2: RMS正規化（全キャラ共通の音量目標に揃える）
        samples = _normalize_rms(samples, TARGET_DBFS)

        # Step3: キャラ別ゲイン（声の小さいキャラをブースト）
        gain_db = _CHAR_GAIN_DB.get(character, 0.0)
        if gain_db != 0.0:
            samples = _apply_gain_db(samples, gain_db)

        # Step4: フェードイン/アウト
        samples = _fade_inout(samples, framerate, channels, FADE_IN_MS, FADE_OUT_MS)

        # Step5: ソフトリミッター（クリッピング防止）
        samples = _soft_limit(samples)

        return _export_wav(samples, framerate, channels, sampwidth)

    except Exception as e:
        # 後処理に失敗しても音声生成は止めない
        print(f"  [!] 音声後処理失敗（{character}）: {e} -> 元音声をそのまま使用")
        return wav_bytes


# ── 診断ツール ────────────────────────────────────────────────

def measure_dbfs(wav_bytes: bytes) -> float:
    """WAVのRMSをdBFSで返す（診断用）"""
    try:
        samples, _, _, _ = _load_wav(wav_bytes)
        if not samples:
            return -math.inf
        rms = math.sqrt(sum(s * s for s in samples) / len(samples))
        if rms == 0:
            return -math.inf
        return 20 * math.log10(rms / 32767.0)
    except Exception:
        return -math.inf


def measure_duration_ms(wav_bytes: bytes) -> float:
    """WAVの長さをミリ秒で返す（診断用）"""
    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as w:
            return w.getnframes() / w.getframerate() * 1000
    except Exception:
        return 0.0


# ── CLI（診断・単体テスト用）────────────────────────────────────

if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("使い方:")
        print("  python audio_processor.py check <wavファイル>    音量・長さを表示")
        print("  python audio_processor.py process <入力wav> <出力wav> [キャラ名]")
        print('  例: python audio_processor.py process in.wav out.wav 霊夢')
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "check" and len(sys.argv) >= 3:
        path = Path(sys.argv[2])
        data = path.read_bytes()
        dbfs = measure_dbfs(data)
        dur  = measure_duration_ms(data)
        print(f"ファイル : {path.name}")
        print(f"音量     : {dbfs:.1f} dBFS")
        print(f"長さ     : {dur:.0f} ms")

    elif cmd == "process" and len(sys.argv) >= 4:
        in_path  = Path(sys.argv[2])
        out_path = Path(sys.argv[3])
        char     = sys.argv[4] if len(sys.argv) > 4 else ""

        raw  = in_path.read_bytes()
        print(f"処理前: {measure_dbfs(raw):.1f} dBFS  {measure_duration_ms(raw):.0f} ms")

        processed = apply_pipeline(raw, char)
        out_path.write_bytes(processed)
        print(f"処理後: {measure_dbfs(processed):.1f} dBFS  {measure_duration_ms(processed):.0f} ms")
        print(f"保存  : {out_path}")

    else:
        print("引数が正しくありません。引数なしで実行してヘルプを確認してください。")
