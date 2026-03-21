#!/usr/bin/env python3
"""
GitHub リポジトリへのデプロイ準備スクリプト

必要なシークレットを GitHub に登録する。
gh CLI がインストール済みであれば自動登録、なければ手動設定用の値を表示する。

使い方:
  python setup_github.py
"""

import base64
import os
import subprocess
import sys
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).parent
load_dotenv(PROJECT_ROOT / ".env")


# ── ヘルパー ─────────────────────────────────────────────

def _encode_file(path: Path) -> str | None:
    """ファイルをbase64エンコードして返す（存在しなければ None）"""
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode()


def _get_from_keyring(key: str) -> str:
    """Windows Credential Manager からシークレットを取得する"""
    try:
        import keyring
        return keyring.get_password("youtube-system", key) or ""
    except Exception:
        return ""


def _has_gh_cli() -> bool:
    try:
        subprocess.run(["gh", "--version"], capture_output=True, check=True)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError):
        return False


def _gh_set_secret(repo: str, name: str, value: str) -> bool:
    result = subprocess.run(
        ["gh", "secret", "set", name, "--body", value, "--repo", repo],
        capture_output=True, text=True,
    )
    return result.returncode == 0


# ── シークレット収集 ─────────────────────────────────────

def collect_secrets() -> dict[str, str | None]:
    """登録すべきシークレットをすべて収集して返す"""
    return {
        "GEMINI_API_KEY":      _get_from_keyring("GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY", "") or None,
        "GOOGLE_TOKEN":        _encode_file(PROJECT_ROOT / "token.json"),
        "GOOGLE_CREDENTIALS":  _encode_file(PROJECT_ROOT / "credentials.json"),
        "NTFY_TOPIC":          os.getenv("NTFY_TOPIC") or None,
        "SPREADSHEET_ID":      os.getenv("SPREADSHEET_ID") or None,
    }


# ── 自動登録（gh CLI） ────────────────────────────────────

def register_with_gh(repo: str, secrets: dict):
    print(f"\ngh CLI でシークレットを登録しています → {repo}\n")
    for name, value in secrets.items():
        if not value:
            print(f"  -  {name:<25} スキップ（値が未設定）")
            continue
        ok = _gh_set_secret(repo, name, value)
        mark = "✓" if ok else "✗"
        print(f"  {mark}  {name}")
    print("\n完了！")


# ── 手動設定ガイド ────────────────────────────────────────

def print_manual_guide(secrets: dict):
    print("""
手動設定の手順:
  1. GitHub リポジトリを開く
  2. Settings > Secrets and variables > Actions を開く
  3. 「New repository secret」をクリック
  4. 下記の名前と値をコピー&ペーストして登録する
""")
    for name, value in secrets.items():
        print(f"{'─' * 50}")
        print(f"名前: {name}")
        if not value:
            print("値:  ⚠ 未設定 — 手動で入力してください")
        else:
            # 長い値（base64）はファイルに書き出す
            if len(value) > 100:
                out = PROJECT_ROOT / f"_secret_{name}.txt"
                out.write_text(value, encoding="utf-8")
                print(f"値:  （長いため {out.name} に書き出しました。ファイルの中身を貼り付けてください）")
            else:
                print(f"値:  {value}")
        print()

    print("─" * 50)
    print("\n登録後に _secret_*.txt ファイルは削除してください。")


# ── メイン ───────────────────────────────────────────────

def main():
    print("=== GitHub デプロイ準備 ===\n")

    secrets = collect_secrets()

    # 問題のある項目を先に表示
    missing = [k for k, v in secrets.items() if not v]
    if missing:
        print("⚠ 以下のシークレットが未設定です:")
        for k in missing:
            print(f"  - {k}")
        print()

    if _has_gh_cli():
        print("gh CLI を検出しました。自動登録モードで実行します。")
        repo = input("リポジトリ名を入力してください（例: username/youtube-system）: ").strip()
        if not repo:
            print("キャンセルしました。")
            sys.exit(0)
        register_with_gh(repo, secrets)
    else:
        print("gh CLI が見つかりません。手動設定ガイドを表示します。")
        print("（gh CLI は https://cli.github.com/ からインストールできます）")
        print_manual_guide(secrets)

    print("""
次のステップ:
  1. 上記のシークレットを GitHub に登録する
  2. コードを GitHub にプッシュする（下記コマンドを参照）
  3. Actions > 動画自動生成・投稿 > Run workflow で手動実行してテストする
  4. 問題なければ毎日 18:00 JST に自動実行される

コードのプッシュ（初回）:
  cd C:\\Users\\user\\Desktop\\youtube-system
  git init
  git add .
  git commit -m "Initial commit"
  git branch -M main
  git remote add origin https://github.com/[ユーザー名]/[リポジトリ名].git
  git push -u origin main
""")


if __name__ == "__main__":
    main()
