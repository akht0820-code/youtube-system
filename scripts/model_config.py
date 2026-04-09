# モデルティア設定（LLM_PROVIDER に応じてモデル名を切り替える）
#
# .env でプロバイダとモデルを指定:
#   LLM_PROVIDER           = gemini          # gemini / openai / claude
#
#   # Gemini
#   GEMINI_MODEL_SIMPLE    = gemini-2.5-flash
#   GEMINI_MODEL_STANDARD  = gemini-2.5-flash
#   GEMINI_MODEL_QUALITY   = gemini-2.5-flash
#
#   # OpenAI（LLM_PROVIDER=openai のとき）
#   OPENAI_MODEL_SIMPLE    = gpt-4o-mini
#   OPENAI_MODEL_STANDARD  = gpt-4o
#   OPENAI_MODEL_QUALITY   = gpt-4o
#
#   # Claude（LLM_PROVIDER=claude のとき）
#   CLAUDE_MODEL_SIMPLE    = claude-haiku-4-5-20251001
#   CLAUDE_MODEL_STANDARD  = claude-sonnet-4-6
#   CLAUDE_MODEL_QUALITY   = claude-opus-4-6

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

_PROVIDER = os.getenv("LLM_PROVIDER", "gemini").lower()

if _PROVIDER == "gemini":
    SIMPLE   = os.getenv("GEMINI_MODEL_SIMPLE",   "gemini-2.5-flash")
    STANDARD = os.getenv("GEMINI_MODEL_STANDARD", "gemini-2.5-flash")
    QUALITY  = os.getenv("GEMINI_MODEL_QUALITY",  "gemini-2.5-flash")
    CREATIVE = os.getenv("GEMINI_MODEL_CREATIVE", "gemini-2.5-pro")

elif _PROVIDER == "openai":
    SIMPLE   = os.getenv("OPENAI_MODEL_SIMPLE",   "gpt-4o-mini")
    STANDARD = os.getenv("OPENAI_MODEL_STANDARD", "gpt-4o")
    QUALITY  = os.getenv("OPENAI_MODEL_QUALITY",  "gpt-4o")
    CREATIVE = os.getenv("OPENAI_MODEL_CREATIVE", "gpt-4o")

elif _PROVIDER == "claude":
    SIMPLE   = os.getenv("CLAUDE_MODEL_SIMPLE",   "claude-haiku-4-5-20251001")
    STANDARD = os.getenv("CLAUDE_MODEL_STANDARD", "claude-sonnet-4-6")
    QUALITY  = os.getenv("CLAUDE_MODEL_QUALITY",  "claude-opus-4-6")
    CREATIVE = os.getenv("CLAUDE_MODEL_CREATIVE", "claude-sonnet-4-6")

else:
    # 未知のプロバイダ: 環境変数で明示的に指定する
    SIMPLE   = os.getenv("LLM_MODEL_SIMPLE",   "")
    STANDARD = os.getenv("LLM_MODEL_STANDARD", "")
    QUALITY  = os.getenv("LLM_MODEL_QUALITY",  "")
    CREATIVE = os.getenv("LLM_MODEL_CREATIVE", "")
