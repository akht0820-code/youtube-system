"""チャンネル設定 JSON の load entry point.

`load_channel(channel_id)` は config/channels/{channel_id}.json を読み、
_channel_schema.validate_and_build に委譲して ChannelConfig を返す。

設計方針:
- sys.path を一切触らない (scripts/secrets.py shadow 回避の必須条件)
- _channel_schema からの import は通常の `from _channel_schema import ...` で良い
  (scripts/ は PYTHONPATH に入らないが、本モジュールは scripts/ 内に置かれ、
   呼び出し元 (generator.py など) は sys.path[0]=project_root の状態で
   `from scripts._channel import load_channel` のような形で使われる想定ではなく、
   将来の Phase 2 で generator.py 自身が scripts/ 内から動く場合は
   相対 import / importlib 経由に差し替える)
- 本 Step では誰も load_channel() を呼ばないため no-op (既存コードパス無影響)

注: 本 Step のスコープでは load_channel は既存実行経路から呼ばれない。
    10:00 定時タスク (run.bat -> generator.py --auto) に影響ゼロ。
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from _channel_schema import ChannelConfig, ChannelSchemaError, validate_and_build


# channel_id の厳格パターン: 小文字英字始まり, 英数字と _ のみ
_CHANNEL_ID_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")

# project_root/config/channels/ を正規化して固定
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CONFIG_DIR = (_PROJECT_ROOT / "config" / "channels").resolve()


class ChannelLoadError(Exception):
    """load_channel が失敗した時の wrapper.

    - 設定ファイル不在
    - JSON パース失敗
    - channel_id 異常 (regex / containment)
    - schema validation 失敗 (ChannelSchemaError を wrap)
    """


def load_channel(channel_id: str) -> ChannelConfig:
    """channel_id から config/channels/{channel_id}.json を読み strict validate.

    失敗時は ChannelLoadError のみを raise する (silent failure 禁止).
    ChannelSchemaError は ChannelLoadError で wrap して再送出する。
    """
    if not isinstance(channel_id, str):
        raise ChannelLoadError(
            f"channel_id: str 必須 (got {type(channel_id).__name__})"
        )
    if not _CHANNEL_ID_PATTERN.match(channel_id):
        raise ChannelLoadError(
            f"channel_id: 許容パターン ^[a-z][a-z0-9_]*$ 違反: {channel_id!r}"
        )

    # containment check: CONFIG_DIR の外に出ないこと (防御的)
    candidate = (_CONFIG_DIR / f"{channel_id}.json").resolve()
    try:
        candidate.relative_to(_CONFIG_DIR)
    except ValueError:
        raise ChannelLoadError(
            f"channel_id: config dir 外参照: {candidate}"
        )

    if not candidate.is_file():
        raise ChannelLoadError(f"channel 設定ファイル不在: {candidate}")

    try:
        # utf-8-sig: BOM 付きの JSON も許容 (Windows 製エディタ対策)
        text = candidate.read_text(encoding="utf-8-sig")
    except OSError as e:
        raise ChannelLoadError(f"channel 設定ファイル読込失敗: {candidate}: {e}")

    try:
        raw: Any = json.loads(text)
    except json.JSONDecodeError as e:
        raise ChannelLoadError(
            f"channel 設定 JSON パース失敗: {candidate}: {e}"
        )

    try:
        return validate_and_build(raw, file_stem=channel_id)
    except ChannelSchemaError as e:
        raise ChannelLoadError(
            f"channel 設定 schema violation: {candidate}: {e}"
        ) from e
