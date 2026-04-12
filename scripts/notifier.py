# スマホ通知モジュール（ntfy.sh）＋ Discord転送 ＋ エラーログ統合

import json
import os
import time
import traceback
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

NTFY_TOPIC = os.getenv("NTFY_TOPIC", "")
NTFY_URL   = f"https://ntfy.sh/{NTFY_TOPIC}"

# Discord連携用のerror feedファイル（outbox.jsonとは別で競合回避）
_ERROR_FEED = Path(__file__).parent.parent / "tmp_discord" / "error_feed.json"
_DEBOUNCE_SEC = 300  # 同一stepのエラーは5分以内の再発を集約
_last_error_times: dict[str, float] = {}  # step名 → 最終通知時刻


def _send_to_discord(title: str, message: str, priority: str = "default"):
    """error_feed.jsonにエラーを書き込む（Discord Botが監視して送信）"""
    try:
        _ERROR_FEED.parent.mkdir(exist_ok=True)
        entry = {
            "timestamp": time.time(),
            "title": title,
            "message": message[:1500],
            "priority": priority,
        }
        # 既存のfeedに追記（リスト形式）
        feed = []
        if _ERROR_FEED.exists():
            try:
                feed = json.loads(_ERROR_FEED.read_text(encoding="utf-8"))
                if not isinstance(feed, list):
                    feed = []
            except Exception:
                feed = []
        feed.append(entry)
        # 最大20件まで保持（古いものは捨てる）
        _ERROR_FEED.write_text(
            json.dumps(feed[-20:], ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:
        pass  # Discord転送失敗はシステムを止めない


def _send(title: str, message: str, priority: str = "default", tags: list[str] | None = None):
    """ntfy.sh に通知を送る"""
    if not NTFY_TOPIC:
        return
    try:
        requests.post(
            NTFY_URL,
            data=message.encode("utf-8"),
            headers={
                "Title":    title.encode("utf-8"),
                "Priority": priority,
                "Tags":     ",".join(tags or []),
            },
            timeout=10,
        )
    except Exception:
        pass  # 通知失敗はシステムを止めない


def notify_error(step: str, error: Exception, context: dict | None = None):
    """エラー発生をログに記録し、スマホに通知する"""
    # ── ログファイルに記録 ──────────────────────────────
    try:
        from error_logger import log_error
        log_error(step, error, context)
    except Exception:
        pass  # ログ書き込み失敗でもシステムを止めない

    # ── リトライで解決する一時的エラーは通知しない ─────────
    err_str = str(error)
    _transient_keywords = [
        "429", "RESOURCE_EXHAUSTED", "rate limit",
        "quota exceeded", "Too Many Requests",
        "503", "UNAVAILABLE", "temporarily",
    ]
    if any(kw.lower() in err_str.lower() for kw in _transient_keywords):
        return  # ログには記録済み、通知は不要

    # ── スマホ通知 ────────────────────────────────────
    # 通知本文: エラー種別 + メッセージ + スタックトレース末尾
    error_type = type(error).__name__
    tb_lines = traceback.format_exc().strip().splitlines()
    # トレースバックの最後の2行（エラー発生箇所と内容）を抜粋
    tb_snippet = ""
    useful = [l for l in tb_lines if l.strip() and "NoneType: None" not in l]
    if useful:
        tb_snippet = "\n" + "\n".join(useful[-2:])

    ctx_str = ""
    if context:
        ctx_str = "\n" + "\n".join(f"{k}: {v}" for k, v in context.items())

    # 2026-04-12: 150文字では台本品質ゲートの違反詳細が切り捨てられ
    # Discord 側で即診断不能だったため 500 文字に拡大.
    # 最終的には L108/L120 の [:500]/[:1500] で各チャネル上限に収まる.
    message = f"{error_type}: {str(error)[:500]}{tb_snippet}{ctx_str}"

    _send(
        title=f"エラー: {step}",
        message=message[:500],  # ntfy.shの実用上限
        priority="high",
        tags=["warning"],
    )

    # ── Discord転送（デバウンス付き） ──────────────────
    now = time.time()
    last_time = _last_error_times.get(step, 0)
    if now - last_time >= _DEBOUNCE_SEC:
        _last_error_times[step] = now
        _send_to_discord(
            title=f"[システム通知] エラー: {step}",
            message=message[:1500],
            priority="high",
        )


def notify_success(theme: str, url: str = ""):
    """動画アップロード完了を通知"""
    # ── ログファイルに記録 ──────────────────────────────
    try:
        from error_logger import log_info
        log_info(f"動画アップロード完了: theme={theme} url={url}")
    except Exception:
        pass

    msg = f"テーマ: {theme}"
    if url:
        msg += f"\n{url}"
    _send(
        title="動画アップロード完了",
        message=msg,
        priority="default",
        tags=["tada"],
    )


def notify_start(theme: str):
    """処理開始を通知"""
    # ── ログファイルに記録 ──────────────────────────────
    try:
        from error_logger import log_info
        log_info(f"動画生成を開始: theme={theme}")
    except Exception:
        pass

    _send(
        title="動画生成を開始",
        message=f"テーマ: {theme}",
        priority="low",
        tags=["arrow_forward"],
    )


def notify_report(title: str, body: str, priority: str = "default"):
    """汎用レポート通知（run_monitor 等から使う公開ラッパー）"""
    _send(title, body, priority=priority)
    # urgent/high 優先度のレポートはDiscordにも転送
    if priority in ("urgent", "high"):
        _send_to_discord(
            title=f"[システム通知] {title}",
            message=body[:1500],
            priority=priority,
        )


def notify_analytics_report(
    video_count: int,
    analysis: str,
    suggestions: list[str],
    recommended_themes: list[str],
):
    """分析レポートをスマホに送信する"""
    # ── ログファイルに記録 ──────────────────────────────
    try:
        from error_logger import log_info
        log_info("分析レポート送信")
    except Exception:
        pass

    # 本文を組み立て（ntfy.sh の実用上限 500字 に収める）
    lines = [f"{video_count} 本を分析"]

    if analysis:
        # 分析サマリーは最初の150字
        lines.append(analysis[:150] + ("…" if len(analysis) > 150 else ""))

    if suggestions:
        lines.append("\n【改善提案】")
        for i, s in enumerate(suggestions[:3], 1):   # 上位3件だけ
            lines.append(f"{i}. {s[:60]}")

    if recommended_themes:
        lines.append("\n【おすすめテーマ】")
        for t in recommended_themes[:3]:              # 上位3件だけ
            lines.append(f"・{t}")

    message = "\n".join(lines)

    _send(
        title="週次チャンネル分析レポート",
        message=message[:500],
        priority="default",
        tags=["chart_with_upwards_trend"],
    )
