# TTSプロバイダの共通インターフェース
#
# 新しいプロバイダを追加する手順:
#   1. TTSClient を継承したクラスを作る（下の実装例を参考に）
#   2. providers.py の get_tts_client() に elif ブロックを追加する
#   3. .env の TTS_PROVIDER を新しいキー名に変更する

import json
from abc import ABC, abstractmethod


class TTSClient(ABC):
    """音声合成サービスの共通インターフェース"""

    @abstractmethod
    def synthesize(self, text: str, speaker_id: int, speed: float) -> bytes:
        """テキストをWAVバイナリに変換して返す"""


class VoicevoxTTSClient(TTSClient):
    """VOICEVOX を使ったTTSクライアント"""

    def __init__(self, base_url: str = "http://localhost:50021"):
        self._url = base_url

    def synthesize(self, text: str, speaker_id: int, speed: float) -> bytes:
        import requests

        query_res = requests.post(
            f"{self._url}/audio_query",
            params={"text": text, "speaker": speaker_id},
        )
        query_res.raise_for_status()
        query = query_res.json()
        query["speedScale"] = speed
        query["pauseLength"] = 0.3
        query["pauseLengthScale"] = 1.0

        synth_res = requests.post(
            f"{self._url}/synthesis",
            params={"speaker": speaker_id},
            data=json.dumps(query),
            headers={"Content-Type": "application/json"},
        )
        synth_res.raise_for_status()
        return synth_res.content


class AivisSpeechTTSClient(TTSClient):
    """AivisSpeech を使ったTTSクライアント（VOICEVOX互換API）

    AivisSpeech は VOICEVOX と完全に同じ HTTP API を持つため、
    URL を localhost:10101 に変えるだけで動作する。

    インストール: https://aivis-project.com/
    モデル配布:   https://hub.aivis-project.com/

    推奨モデル（AivisHub で公開されている無料モデル）:
      霊夢: "Anneli" または "つくよみちゃん" ノーマル
      魔理沙: "ずんだもん" ノーマル または "春日部つむぎ"

    スピーカーIDは AivisSpeech を起動後:
      python tts.py --list-speakers
    で確認できる。
    """

    def __init__(self, base_url: str = "http://localhost:10101"):
        self._url = base_url

    def synthesize(self, text: str, speaker_id: int, speed: float) -> bytes:
        import requests

        query_res = requests.post(
            f"{self._url}/audio_query",
            params={"text": text, "speaker": speaker_id},
        )
        query_res.raise_for_status()
        query = query_res.json()
        query["speedScale"] = speed
        query["pauseLength"] = 0.3
        query["pauseLengthScale"] = 1.0

        synth_res = requests.post(
            f"{self._url}/synthesis",
            params={"speaker": speaker_id},
            data=json.dumps(query),
            headers={"Content-Type": "application/json"},
        )
        synth_res.raise_for_status()
        return synth_res.content


# ── 将来の実装例（必要なときにコメントを外して使う）────────────────

# class OpenAITTSClient(TTSClient):
#     """OpenAI TTS API を使ったTTSクライアント"""
#     # speaker_id → OpenAIボイスのマッピング
#     VOICE_MAP = {0: "alloy", 1: "echo", 2: "fable", 3: "onyx", 4: "nova", 5: "shimmer"}
#
#     def __init__(self, api_key: str):
#         from openai import OpenAI
#         self._client = OpenAI(api_key=api_key)
#
#     def synthesize(self, text: str, speaker_id: int, speed: float) -> bytes:
#         voice = self.VOICE_MAP.get(speaker_id, "alloy")
#         response = self._client.audio.speech.create(
#             model="tts-1",
#             voice=voice,
#             input=text,
#             speed=max(0.25, min(4.0, speed)),
#             response_format="wav",
#         )
#         return response.content


# class GoogleCloudTTSClient(TTSClient):
#     """Google Cloud Text-to-Speech を使ったTTSクライアント"""
#     def __init__(self, credentials_path: str):
#         from google.cloud import texttospeech
#         self._client = texttospeech.TextToSpeechClient.from_service_account_file(credentials_path)
#
#     def synthesize(self, text: str, speaker_id: int, speed: float) -> bytes:
#         from google.cloud import texttospeech
#         synthesis_input = texttospeech.SynthesisInput(text=text)
#         voice = texttospeech.VoiceSelectionParams(
#             language_code="ja-JP",
#             name="ja-JP-Neural2-B",
#         )
#         audio_config = texttospeech.AudioConfig(
#             audio_encoding=texttospeech.AudioEncoding.LINEAR16,
#             speaking_rate=speed,
#         )
#         response = self._client.synthesize_speech(
#             input=synthesis_input, voice=voice, audio_config=audio_config
#         )
#         return response.audio_content
