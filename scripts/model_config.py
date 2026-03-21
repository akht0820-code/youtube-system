# Geminiモデルのティア設定
#
# .env で各ティアのモデルを変更できる。
#
# 推奨モデル候補:
#   SIMPLE   : gemini-2.0-flash-lite  （最安値・機械的な作業向け）
#   STANDARD : gemini-2.5-flash       （バランス型・デフォルト）
#   QUALITY  : gemini-2.5-pro         （最高品質・コスト高）
#
# タスクとティアの対応:
#   SIMPLE   → 説明文生成、タグ生成
#   STANDARD → タイトル生成、構成生成、動画分析
#   QUALITY  → 台本生成（動画の核心）

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

SIMPLE   = os.getenv("GEMINI_MODEL_SIMPLE",   "gemini-2.0-flash-lite")
STANDARD = os.getenv("GEMINI_MODEL_STANDARD", "gemini-2.5-flash")
QUALITY  = os.getenv("GEMINI_MODEL_QUALITY",  "gemini-2.5-flash")
