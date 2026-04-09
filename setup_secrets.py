# 秘密情報をWindows Credential Managerに登録するセットアップスクリプト
#
# 使い方:
#   python setup_secrets.py          # 対話形式で全キーを登録
#   python setup_secrets.py --list   # 登録済みキーの一覧を表示
#   python setup_secrets.py --delete GEMINI_API_KEY  # 特定のキーを削除

import argparse
import sys

try:
    import keyring
except ImportError:
    print("エラー: keyring がインストールされていません。")
    print("  pip install keyring")
    sys.exit(1)

SERVICE = "youtube-system"

SECRETS = {
    "GEMINI_API_KEY": {
        "label": "Google Gemini API キー",
        "hint":  "Google AI Studio (aistudio.google.com) で取得",
    },
    "ANTHROPIC_API_KEY": {
        "label": "Anthropic Claude API キー（Gemini制限時フォールバック用）",
        "hint":  "console.anthropic.com で取得 — 登録しておくとGemini制限時に自動でClaudeへ切り替わる",
    },
}


def _mask(value: str) -> str:
    """値の先頭6文字だけ表示してマスクする"""
    if len(value) <= 6:
        return "*" * len(value)
    return value[:6] + "*" * (len(value) - 6)


def cmd_list():
    """登録済みキーの一覧を表示する"""
    print("=== 登録済みの秘密情報 ===\n")
    found = False
    for key, meta in SECRETS.items():
        value = keyring.get_password(SERVICE, key)
        if value:
            print(f"  ✓ {key:<20}  {_mask(value)}  （{meta['label']}）")
            found = True
        else:
            print(f"  ✗ {key:<20}  未登録               （{meta['label']}）")
    if not found:
        print("  登録済みのキーはありません。")
    print()


def cmd_set(key: str | None = None):
    """対話形式で秘密情報を登録する"""
    targets = {key: SECRETS[key]} if key else SECRETS

    print("=== 秘密情報の登録 ===")
    print("Credential Manager に暗号化して保存されます。\n")

    for key, meta in targets.items():
        existing = keyring.get_password(SERVICE, key)
        if existing:
            print(f"【{meta['label']}】")
            print(f"  現在の値: {_mask(existing)}")
            overwrite = input("  上書きしますか？ [y/N]: ").strip().lower()
            if overwrite != "y":
                print("  スキップしました。\n")
                continue

        print(f"【{meta['label']}】")
        print(f"  ヒント: {meta['hint']}")
        value = input("  値を入力してください: ").strip()
        if not value:
            print("  空のため登録をスキップしました。\n")
            continue

        keyring.set_password(SERVICE, key, value)
        print(f"  ✓ 登録完了: {_mask(value)}\n")

    print("完了！登録内容を確認するには --list オプションを使ってください。")


def cmd_delete(key: str):
    """指定したキーをCredential Managerから削除する"""
    if key not in SECRETS:
        print(f"エラー: 不明なキー {key!r}")
        print(f"  登録可能なキー: {list(SECRETS.keys())}")
        sys.exit(1)

    existing = keyring.get_password(SERVICE, key)
    if not existing:
        print(f"{key} は登録されていません。")
        return

    keyring.delete_password(SERVICE, key)
    print(f"✓ {key} を削除しました。")


def main():
    parser = argparse.ArgumentParser(description="秘密情報をCredential Managerに登録する")
    parser.add_argument("--list",   action="store_true", help="登録済みキーの一覧を表示")
    parser.add_argument("--delete", metavar="KEY",       help="指定したキーを削除")
    args = parser.parse_args()

    if args.list:
        cmd_list()
    elif args.delete:
        cmd_delete(args.delete)
    else:
        cmd_set()


if __name__ == "__main__":
    main()
