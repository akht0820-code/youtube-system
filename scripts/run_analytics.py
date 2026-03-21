# 分析バッチのオーケストレーター
# 毎日9:00にタスクスケジューラから実行される
#
# .env で使用実装を切り替えられる:
#   ANALYTICS_COLLECTOR=youtube   # youtube
#   ANALYTICS_STORE=sheets        # sheets | json
#   ANALYTICS_MODEL=gemini        # gemini
#
# 新しい実装を追加する場合:
#   1. analytics_base.py の StatsCollector / StatsStore / AnalysisModel を継承したクラスを作る
#   2. 下の _COLLECTORS / _STORES / _MODELS に登録する
#   3. .env のキーを変更する

import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

from analytics_base import AnalysisModel, StatsCollector, StatsStore
from analyzer import GeminiAnalysisModel, save_suggestions
from analytics_collector import YouTubeStatsCollector
from analytics_store_json import JsonFileStore
from sheets_writer import GoogleSheetsStore
from notifier import notify_error

# ── ファクトリ登録テーブル ────────────────────────────────────────
# 新しい実装を追加するときはここにキーと型を追加するだけ

_COLLECTORS: dict[str, type[StatsCollector]] = {
    "youtube": YouTubeStatsCollector,
}

_STORES: dict[str, type[StatsStore]] = {
    "sheets": GoogleSheetsStore,
    "json":   JsonFileStore,
}

_MODELS: dict[str, type[AnalysisModel]] = {
    "gemini": GeminiAnalysisModel,
}


def _build_pipeline() -> tuple[StatsCollector, StatsStore, AnalysisModel]:
    """.env の設定値から各コンポーネントをインスタンス化して返す"""
    collector_key = os.getenv("ANALYTICS_COLLECTOR", "youtube")
    store_key     = os.getenv("ANALYTICS_STORE", "sheets")
    model_key     = os.getenv("ANALYTICS_MODEL", "gemini")

    if collector_key not in _COLLECTORS:
        raise ValueError(f"ANALYTICS_COLLECTOR に未登録のキー: {collector_key!r}  使用可能: {list(_COLLECTORS)}")
    if store_key not in _STORES:
        raise ValueError(f"ANALYTICS_STORE に未登録のキー: {store_key!r}  使用可能: {list(_STORES)}")
    if model_key not in _MODELS:
        raise ValueError(f"ANALYTICS_MODEL に未登録のキー: {model_key!r}  使用可能: {list(_MODELS)}")

    return (
        _COLLECTORS[collector_key](),
        _STORES[store_key](),
        _MODELS[model_key](),
    )


def main():
    print("=== 動画統計分析バッチ 開始 ===\n")

    try:
        collector, store, model = _build_pipeline()
        print(
            f"  コレクター : {collector.__class__.__name__}\n"
            f"  ストア     : {store.__class__.__name__}\n"
            f"  分析モデル : {model.__class__.__name__}\n"
        )
    except ValueError as e:
        print(f"[エラー] 設定: {e}")
        sys.exit(1)

    # ── ステップ1: 統計収集 ──────────────────────────────────
    try:
        print("動画統計を収集しています...")
        stats = collector.collect()
        print(f"  → {len(stats)} 本のデータを取得しました\n")
    except Exception as e:
        notify_error("動画統計収集", e)
        print(f"[エラー] 動画統計収集: {e}")
        sys.exit(1)

    if not stats:
        print("動画が見つかりませんでした。処理を終了します。")
        sys.exit(0)

    # ── ステップ2: 統計保存 ──────────────────────────────────
    try:
        print("統計データを保存しています...")
        store.write(stats)
        print()
    except Exception as e:
        notify_error("統計データ保存", e)
        print(f"[エラー] 統計データ保存: {e}")
        # 保存が失敗しても分析は続行

    # ── ステップ3: AI分析・提案生成 ─────────────────────────
    try:
        result = model.analyze(stats)
        save_suggestions(result)
        print()
        print("【分析サマリー】")
        print(result.get("analysis", ""))
        print("\n【改善提案】")
        for i, s in enumerate(result.get("suggestions", []), 1):
            print(f"  {i}. {s}")
        print("\n【おすすめテーマ】")
        for theme in result.get("recommended_themes", []):
            print(f"  ・{theme}")
    except Exception as e:
        notify_error("AI分析", e)
        print(f"[エラー] AI分析: {e}")

    print("\n=== 動画統計分析バッチ 完了 ===")


if __name__ == "__main__":
    main()
