# LLMプロバイダの共通インターフェース
#
# 新しいプロバイダを追加する手順:
#   1. LLMClient を継承したクラスを作る（下の実装例を参考に）
#   2. providers.py の get_llm_client() に elif ブロックを追加する
#   3. .env の LLM_PROVIDER を新しいキー名に変更する

from abc import ABC, abstractmethod


class LLMClient(ABC):
    """テキスト生成AIの共通インターフェース"""

    @abstractmethod
    def generate(self, prompt: str, model: str, *, temperature: float | None = None) -> str:
        """プロンプトを送り、テキストレスポンスを返す

        Args:
            temperature: 生成の創造性（0.0〜2.0）。Noneならモデルのデフォルト値を使用
        """


class GeminiLLMClient(LLMClient):
    """Google Gemini API を使ったLLMクライアント"""

    def __init__(self, api_key: str):
        from google import genai
        self._client = genai.Client(api_key=api_key)

    def generate(self, prompt: str, model: str, *, temperature: float | None = None) -> str:
        kwargs: dict = {"model": model, "contents": prompt}
        if temperature is not None:
            from google.genai import types
            kwargs["config"] = types.GenerateContentConfig(temperature=temperature)
        response = self._client.models.generate_content(**kwargs)
        return response.text


class ClaudeLLMClient(LLMClient):
    """Anthropic Claude API を使ったLLMクライアント"""

    def __init__(self, api_key: str):
        import anthropic
        self._client = anthropic.Anthropic(api_key=api_key)

    def generate(self, prompt: str, model: str, *, temperature: float | None = None) -> str:
        kwargs: dict = {
            "model": model,
            "max_tokens": 8192,
            "messages": [{"role": "user", "content": prompt}],
        }
        if temperature is not None:
            kwargs["temperature"] = temperature
        response = self._client.messages.create(**kwargs)
        return response.content[0].text


class GeminiWithClaudeFallbackLLMClient(LLMClient):
    """Gemini を主、Claude を従としたフォールバック対応LLMクライアント。

    Gemini がレート制限（429）やクォータ超過エラーを返した場合に
    自動で Claude へ切り替える。ユーザー側の操作は一切不要。

    Gemini モデル → Claude モデル の対応表:
        gemini-2.0-flash       →  claude-sonnet-4-6            （標準）
        gemini-2.5-flash       →  claude-sonnet-4-6            （標準・高品質）
        gemini-*-pro           →  claude-opus-4-6              （最高品質）
        その他                 →  claude-sonnet-4-6            （デフォルト）
    """

    # Gemini モデル名 → Claude モデル名のマッピング
    _MODEL_MAP: dict[str, str] = {
        "gemini-2.0-flash-lite":   "claude-haiku-4-5-20251001",
        "gemini-2.0-flash":        "claude-sonnet-4-6",
        "gemini-2.5-flash-lite":   "claude-haiku-4-5-20251001",
        "gemini-2.5-flash":        "claude-sonnet-4-6",
        "gemini-2.5-pro":          "claude-opus-4-6",
        "gemini-1.5-flash":        "claude-sonnet-4-6",
        "gemini-1.5-pro":          "claude-opus-4-6",
    }
    _DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-6"

    def __init__(self, gemini_key: str, claude_key: str):
        self._gemini = GeminiLLMClient(api_key=gemini_key)
        self._claude = ClaudeLLMClient(api_key=claude_key)

    @staticmethod
    def _should_fallback(exc: Exception) -> bool:
        """Claudeへフォールバックすべきエラーか判定する（レート制限・モデル廃止等）"""
        msg = str(exc).lower()
        return any(kw in msg for kw in (
            "429",
            "quota",
            "resource_exhausted",
            "rate_limit",
            "ratelimit",
            "too_many_requests",
            "toomanyrequests",
            "exhausted",
            "limit exceeded",
            "404",
            "not_found",
            "not found",
            "no longer available",
            "deprecated",
            "decommissioned",
        ))

    def generate(self, prompt: str, model: str, *, temperature: float | None = None) -> str:
        """Gemini で生成を試み、制限/廃止エラー時は Claude に自動切り替えする"""
        try:
            return self._gemini.generate(prompt, model, temperature=temperature)
        except Exception as e:
            if self._should_fallback(e):
                claude_model = self._MODEL_MAP.get(model, self._DEFAULT_CLAUDE_MODEL)
                reason = "モデル廃止" if any(k in str(e).lower() for k in ("404", "not_found", "not found", "no longer")) else "制限検知"
                print(f"  [フォールバック] Gemini {reason} → Claude ({claude_model}) に切り替えます")
                return self._claude.generate(prompt, claude_model, temperature=temperature)
            raise


# class OpenAILLMClient(LLMClient):
#     """OpenAI API を使ったLLMクライアント"""
#     def __init__(self, api_key: str):
#         from openai import OpenAI
#         self._client = OpenAI(api_key=api_key)
#
#     def generate(self, prompt: str, model: str) -> str:
#         response = self._client.chat.completions.create(
#             model=model,
#             messages=[{"role": "user", "content": prompt}],
#         )
#         return response.choices[0].message.content
