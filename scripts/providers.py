# プロバイダファクトリ
#
# .env で切り替えるキー:
#   LLM_PROVIDER       = gemini          # gemini / openai / claude
#   TTS_PROVIDER       = aquestalk       # aquestalk（tts.py で直接処理）
#   THUMBNAIL_PROVIDER = local           # local / dalle / stable_diffusion

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from llm_client import LLMClient
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
