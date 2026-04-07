# プロバイダファクトリ
#
# .env で切り替えるキー:
#   LLM_PROVIDER       = gemini          # gemini / openai / claude
#   TTS_PROVIDER       = voicevox        # voicevox / aivis / openai / google
#   THUMBNAIL_PROVIDER = local           # local / dalle / stable_diffusion
#
# 新しいプロバイダを追加する場合:
#   1. 対応する *_client.py に実装クラスを追加する
#   2. 下の各関数に elif ブロックを追加する
#   3. .env のキーを変更する

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from llm_client import LLMClient
from tts_client import TTSClient
from thumbnail_client import ThumbnailGenerator


def get_llm_client() -> LLMClient:
    """環境変数 LLM_PROVIDER に応じたLLMクライアントを返す。

    LLM_PROVIDER=gemini（デフォルト）の場合、ANTHROPIC_API_KEY が
    Credential Manager に登録されていれば自動的に Claude フォールバック付き
    クライアントを返す。Gemini が制限に達したときも作業が止まらない。
    """
    provider = os.getenv("LLM_PROVIDER", "gemini").lower()

    if provider == "gemini":
        from llm_client import GeminiLLMClient, GeminiWithClaudeFallbackLLMClient
        from secrets import get_secret
        gemini_key = get_secret("GEMINI_API_KEY")

        # ANTHROPIC_API_KEY が登録済みなら自動フォールバック付きクライアントを使用
        try:
            claude_key = get_secret("ANTHROPIC_API_KEY")
            if claude_key:
                print("  LLM: Gemini（Claude自動フォールバック付き）")
                return GeminiWithClaudeFallbackLLMClient(
                    gemini_key=gemini_key, claude_key=claude_key
                )
        except Exception:
            pass  # キー未登録の場合はフォールバックなしで続行

        return GeminiLLMClient(api_key=gemini_key)

    elif provider == "claude":
        from llm_client import ClaudeLLMClient
        from secrets import get_secret
        print("  LLM: Claude")
        return ClaudeLLMClient(api_key=get_secret("ANTHROPIC_API_KEY"))

    # elif provider == "openai":
    #     from llm_client import OpenAILLMClient
    #     from secrets import get_secret
    #     return OpenAILLMClient(api_key=get_secret("OPENAI_API_KEY"))

    raise ValueError(
        f"未対応のLLMプロバイダ: {provider!r}\n"
        ".env の LLM_PROVIDER に 'gemini' を設定してください"
    )


def get_tts_client() -> TTSClient:
    """環境変数 TTS_PROVIDER に応じたTTSクライアントを返す"""
    provider = os.getenv("TTS_PROVIDER", "aquestalk").lower()

    if provider == "voicevox":
        from tts_client import VoicevoxTTSClient
        url = os.getenv("VOICEVOX_URL", "http://localhost:50021")
        return VoicevoxTTSClient(base_url=url)

    elif provider == "aivis":
        from tts_client import AivisSpeechTTSClient
        url = os.getenv("AIVIS_URL", "http://localhost:10101")
        return AivisSpeechTTSClient(base_url=url)

    # elif provider == "openai":
    #     from tts_client import OpenAITTSClient
    #     from secrets import get_secret
    #     return OpenAITTSClient(api_key=get_secret("OPENAI_API_KEY"))

    # elif provider == "google":
    #     from tts_client import GoogleCloudTTSClient
    #     return GoogleCloudTTSClient(credentials_path=os.getenv("GOOGLE_CREDENTIALS", "credentials.json"))

    raise ValueError(
        f"未対応のTTSプロバイダ: {provider!r}\n"
        ".env の TTS_PROVIDER に 'voicevox' を設定してください"
    )


def get_thumbnail_generator() -> ThumbnailGenerator:
    """環境変数 THUMBNAIL_PROVIDER に応じたサムネイル生成器を返す"""
    provider = os.getenv("THUMBNAIL_PROVIDER", "local").lower()

    if provider == "local":
        from thumbnail_client import LocalThumbnailGenerator
        return LocalThumbnailGenerator()

    # elif provider == "dalle":
    #     from thumbnail_client import DalleThumbnailGenerator
    #     from secrets import get_secret
    #     return DalleThumbnailGenerator(api_key=get_secret("OPENAI_API_KEY"))

    # elif provider == "stable_diffusion":
    #     from thumbnail_client import StableDiffusionThumbnailGenerator
    #     url = os.getenv("STABLE_DIFFUSION_URL", "http://localhost:7860")
    #     return StableDiffusionThumbnailGenerator(base_url=url)

    raise ValueError(
        f"未対応のサムネイルプロバイダ: {provider!r}\n"
        ".env の THUMBNAIL_PROVIDER に 'local' を設定してください"
    )
