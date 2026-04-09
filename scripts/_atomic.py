"""原子的ファイル書き込みヘルパ（Discord連携系共通）

設計方針:
- .tmp → rename 必須（部分書き込みを他プロセスに読まれない）
- cp932対策: encoding は必ず utf-8 明示
- /mnt/c 上のrename は WSL/Windows 境界で挙動差異の可能性あり → 実測検証対象
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path | str, data: str, encoding: str = "utf-8") -> None:
    """文字列を原子的に書き込む。

    - 同じディレクトリに .tmp ファイルを作り、fsync 後 rename する
    - 親ディレクトリが無ければ作る
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f".{p.name}.", suffix=".tmp", dir=str(p.parent)
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(data)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # /mnt/c などで fsync 未サポートの場合は無視
                pass
        os.replace(tmp_path, p)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def atomic_write_json(path: Path | str, obj: Any) -> None:
    """JSON を原子的に書き込む（ensure_ascii=Falseで日本語OK）"""
    data = json.dumps(obj, ensure_ascii=False, indent=2)
    atomic_write_text(path, data)


def safe_read_json(path: Path | str, default: Any = None) -> Any:
    """JSON を安全に読む。壊れてたら default 返す"""
    try:
        p = Path(path)
        if not p.exists():
            return default
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return default
