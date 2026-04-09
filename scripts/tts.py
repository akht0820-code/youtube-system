# 音声合成モジュール（AquesTalk専用）

import array as _array_mod
import io as _io_mod
import json
import os
import sys
import wave as _wave_mod
from pathlib import Path

from audio_processor import apply_pipeline, apply_prosody
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")


# ── 音声合成 ─────────────────────────────────────────────


def generate_audio_from_script(script: dict, output_dir: Path) -> list[Path]:
    """台本JSONから全セリフの音声をAquesTalk1で生成して保存する。"""
    return _generate_audio_aquestalk(script, output_dir)


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

        # AquesTalk合成（失敗時: 再補正リトライ → 最終手段として強制クリーニング）
        synth_ok = False
        for _attempt in range(3):
            try:
                if _attempt == 0:
                    aq_synthesize(text, character, output_path, speed=line_speed)
                elif _attempt == 1:
                    # リトライ1: check_synthesis経由で再補正
                    from check_synthesis import _run_pipeline
                    fixed_text = _run_pipeline(text)
                    if fixed_text and fixed_text != text:
                        print(f"  [{num:03d}] 再補正リトライ: {fixed_text[:30]}")
                    aq_synthesize(fixed_text or text, character, output_path, speed=line_speed)
                else:
                    # リトライ2: ひらがな・カタカナ・句読点のみに強制クリーニング
                    import re as _re_tts
                    stripped = _re_tts.sub(r"[^\u3041-\u3093\u30A1-\u30F6\u30FCー、。]", "", text)
                    if not stripped:
                        stripped = "。"
                    print(f"  [{num:03d}] 強制クリーニングリトライ: {stripped[:30]}")
                    aq_synthesize(stripped, character, output_path, speed=line_speed)
                synth_ok = True
                break
            except Exception as e:
                if _attempt < 2:
                    continue
                msg = f"  [!] [{num:03d}] {character} の音声生成に失敗(3回リトライ後): {e}"
                try:
                    print(msg)
                except UnicodeEncodeError:
                    print(msg.encode("cp932", errors="replace").decode("cp932"))

        if not synth_ok:
            continue

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
        retry_tag = f" [retry{_attempt}]" if _attempt > 0 else ""
        print(f"  [{num:03d}] {character}: {preview}{prosody_tag}{retry_tag}")
        saved_files.append(output_path)

    return sorted(saved_files)


# ── CLIエントリーポイント ────────────────────────────────

if __name__ == "__main__":
    args = sys.argv[1:]

    if not args or args[0] == "--help":
        print("使い方:")
        print("  python tts.py <台本.json> <出力ディレクトリ>  台本から音声生成")
    elif len(args) == 2:
        script_path = Path(args[0])
        out_dir = Path(args[1])
        script = json.loads(script_path.read_text(encoding="utf-8"))
        files = generate_audio_from_script(script, out_dir)
        print(f"\n{len(files)} 件の音声ファイルを生成しました")
    else:
        print("引数が正しくありません。--help で確認してください。")
