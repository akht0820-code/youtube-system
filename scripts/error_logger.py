# エラーログモジュール
# logs/YYYYMMDD.log にスタックトレース付きで記録する

import logging
import traceback
from datetime import datetime
from pathlib import Path

LOG_DIR = Path(__file__).parent.parent / "logs"

_logger: logging.Logger | None = None


def _get_logger() -> logging.Logger:
    global _logger
    if _logger is not None:
        return _logger

    LOG_DIR.mkdir(exist_ok=True)
    log_file = LOG_DIR / f"{datetime.now().strftime('%Y%m%d')}.log"

    logger = logging.getLogger("youtube-system")
    logger.setLevel(logging.DEBUG)

    # ── ファイルハンドラ（DEBUG以上を全記録）──────────────
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))
    logger.addHandler(fh)

    _logger = logger
    return logger


def log_info(message: str):
    """通常ログ（処理の節目など）を記録する"""
    _get_logger().info(message)


def log_error(step: str, error: Exception, context: dict | None = None):
    """エラーをスタックトレース付きでログファイルに記録する"""
    tb = traceback.format_exc()
    lines = [f"[{step}] {type(error).__name__}: {error}"]
    if context:
        lines.append("コンテキスト:")
        for k, v in context.items():
            lines.append(f"  {k}: {v}")
    # スタックトレースが取れているときだけ付加
    if "NoneType: None" not in tb:
        lines.append(tb.rstrip())
    _get_logger().error("\n".join(lines))


def get_log_path() -> Path:
    """今日のログファイルパスを返す"""
    return LOG_DIR / f"{datetime.now().strftime('%Y%m%d')}.log"
