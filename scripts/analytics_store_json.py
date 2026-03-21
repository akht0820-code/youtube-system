# JSONファイルへの動画統計保存モジュール（シンプルなローカル代替）

import json
from datetime import datetime
from pathlib import Path

from analytics_base import StatsStore

_DEFAULT_PATH = Path(__file__).parent.parent / "stats.json"


class JsonFileStore(StatsStore):
    """ローカルのJSONファイルに動画統計を保存・読み込む（Google Sheets不要）"""

    def __init__(self, path: Path = _DEFAULT_PATH):
        self._path = path

    def write(self, stats: list[dict]) -> None:
        now_str = datetime.now().strftime("%Y-%m-%d %H:%M")
        data = {
            "updated_at": now_str,
            "videos": stats,
        }
        self._path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"統計データをJSONに保存しました: {self._path}（{len(stats)} 件）")

    def read(self) -> list[dict]:
        if not self._path.exists():
            return []
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            return data.get("videos", [])
        except Exception:
            return []
