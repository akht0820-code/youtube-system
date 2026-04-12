"""09:55 起動前ヘルスチェック — 10:00定時タスクの実行条件を事前検証

Windows Task Schedulerで09:55に実行。
異常検知時はnotifier経由でスマホ+Discordに即時通知。

チェック内容:
  1. ネットワーク接続（Gemini API / Google API socket到達性）
  2. token.json存在+有効期限（API呼び出しなし、ファイルベース確認のみ）
  3. credentials.json存在
  4. ディスク空き容量（5GB以上）
  5. 本日のlast_upload_date.txt重複チェック
"""

import json
import os
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# パス設定
PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
LOGS_DIR = PROJECT_ROOT / "logs"

sys.path.insert(0, str(SCRIPTS_DIR))


def _check_network() -> list[str]:
    """socket接続でネットワーク到達性を確認"""
    from network_check import check
    if not check():
        return ["[NG] Gemini/Google APIにネットワーク接続できません"]
    return []


def _check_token_json(token_path: Path) -> list[str]:
    """token.jsonの存在と有効期限をファイルベースで確認（API呼び出しなし）"""
    errors = []
    if not token_path.exists():
        errors.append("[NG] token.jsonが存在しません")
        return errors

    try:
        data = json.loads(token_path.read_text(encoding="utf-8"))
        expiry_str = data.get("expiry", "")
        if expiry_str:
            # "2026-04-09T10:30:00.000000Z" 形式
            expiry_str_clean = expiry_str.replace("Z", "+00:00")
            expiry = datetime.fromisoformat(expiry_str_clean)
            now = datetime.now(timezone.utc)
            # refresh_tokenがあれば期限切れでも自動更新される
            if "refresh_token" not in data or not data["refresh_token"]:
                if expiry < now:
                    errors.append(
                        f"[NG] token.jsonの有効期限切れ({expiry_str})かつrefresh_tokenなし"
                    )
    except (json.JSONDecodeError, ValueError) as e:
        errors.append(f"[NG] token.jsonの読み取りエラー: {e}")

    return errors


def _check_credentials(cred_path: Path) -> list[str]:
    """credentials.jsonの存在確認"""
    if not cred_path.exists():
        return ["[NG] credentials.jsonが存在しません"]
    return []


def _check_disk_space() -> list[str]:
    """ディスク空き容量チェック（最低5GB）"""
    try:
        usage = shutil.disk_usage(str(PROJECT_ROOT))
        free_gb = usage.free / (1024 ** 3)
        if free_gb < 5.0:
            return [f"[NG] ディスク空き容量不足: {free_gb:.1f}GB (最低5GB必要)"]
    except OSError as e:
        return [f"[NG] ディスク容量チェック失敗: {e}"]
    return []


def _check_duplicate_upload(lock_path: Path) -> list[str]:
    """本日のアップロード済み確認"""
    # Step 3-δ.5b: lock_path は main() から channel config 経由で受け取る
    if not lock_path.exists():
        return []

    try:
        content = lock_path.read_text(encoding="utf-8").strip()
        today = datetime.now().strftime("%Y-%m-%d")
        if content.startswith(today):
            return [
                f"[NG] 本日({today})は既にアップロード済み: {content}"
            ]
    except OSError:
        pass
    return []


def main():
    # Step 3-δ.5b: --channel 追加 + channel config から paths 解決.
    # channel config load 失敗時も channel 非依存チェック (network/disk) は
    # 継続実行して診断力を維持する (Codex Round 1 指摘対応).
    import argparse
    parser = argparse.ArgumentParser(description="起動前ヘルスチェック")
    parser.add_argument("--channel", default="health", choices=["health"],
                        help="チャンネルID (creatures は 5c-8 完了後に開放)")
    args = parser.parse_args()

    print(f"=== 起動前ヘルスチェック ({datetime.now().strftime('%Y-%m-%d %H:%M:%S')}) ===")
    print(f"  [channel] {args.channel}")

    all_errors = []

    def _run_check(name: str, func):
        try:
            errors = func()
            if errors:
                all_errors.extend(errors)
                for e in errors:
                    print(f"  {e}")
            else:
                print(f"  [OK] {name}")
        except Exception as e:
            msg = f"[NG] {name}チェックでクラッシュ: {e}"
            all_errors.append(msg)
            print(f"  {msg}")

    # ── channel 非依存チェック (channel config の成否に関わらず常に実行) ──
    _run_check("ネットワーク接続", _check_network)
    _run_check("ディスク容量", _check_disk_space)

    # ── channel config load (失敗時は all_errors に積んで通知経路を温存) ──
    cfg = None
    try:
        from _channel import load_channel, ChannelLoadError
        cfg = load_channel(args.channel)
    except Exception as _ce:
        msg = f"[NG] channel config 読込失敗 ({args.channel}): {_ce}"
        all_errors.append(msg)
        print(f"  {msg}")

    # ── channel 依存チェック (cfg がある時のみ実行) ──
    if cfg is not None:
        token_path = PROJECT_ROOT / cfg.oauth.token
        cred_path = PROJECT_ROOT / cfg.oauth.credentials
        lock_path = PROJECT_ROOT / cfg.paths.lock_file
        _run_check("OAuth2トークン", lambda: _check_token_json(token_path))
        _run_check("認証ファイル", lambda: _check_credentials(cred_path))
        _run_check("重複アップロード", lambda: _check_duplicate_upload(lock_path))

    if all_errors:
        print(f"\n[NG] {len(all_errors)}件の問題を検出 - 10:00タスクに影響する可能性があります")
        # 即時通知
        try:
            from notifier import notify_report
            body = "\n".join(all_errors)
            notify_report(
                "[NG] 起動前ヘルスチェック失敗",
                f"10:00定時タスクに影響する可能性があります:\n{body}",
                priority="high",
            )
        except Exception as e:
            print(f"  通知送信失敗: {e}")
        sys.exit(1)
    else:
        print("\n[OK] 全チェック合格 - 10:00タスクの実行条件を満たしています")
        sys.exit(0)


if __name__ == "__main__":
    main()
