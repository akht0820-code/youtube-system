# 分析パイプラインのインターフェース定義

from abc import ABC, abstractmethod


class StatsCollector(ABC):
    """動画統計を収集するインターフェース"""

    @abstractmethod
    def collect(self) -> list[dict]:
        """
        Returns:
            [
              {
                "video_id": str,
                "title": str,
                "published_at": str,  # "YYYY-MM-DD"
                "views": int,
                "likes": int,
                "comments": int,
                "url": str,
              }, ...
            ]
        """


class StatsStore(ABC):
    """統計データを保存・読み込むインターフェース"""

    @abstractmethod
    def write(self, stats: list[dict]) -> None:
        """統計データを書き込む（既存データは上書き更新）"""

    @abstractmethod
    def read(self) -> list[dict]:
        """保存済みの統計データを読み込む"""


class AnalysisModel(ABC):
    """統計データを分析して改善提案を生成するインターフェース"""

    @abstractmethod
    def analyze(self, stats: list[dict]) -> dict:
        """
        Args:
            stats: StatsCollector.collect() の戻り値

        Returns:
            {
              "analysis": str,
              "suggestions": list[str],
              "recommended_themes": list[str],
              "title_patterns": list[str],
            }
        """
