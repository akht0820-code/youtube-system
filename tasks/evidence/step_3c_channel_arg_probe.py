"""Step 3-γ probe: generator.py の --channel CLI 引数が期待通り動作することを検証.

設計:
- `import generator` は notifier → dotenv 依存で環境によって import-time で赤くなる
  (Codex レビュー 2026-04-11 指摘). よって probe は generator.py の argparse
  定義部分だけを本番形態で再現する.
- 「probe 側で再構築した parser」と「本番 generator.py の argparse 定義」が
  逐語一致している保証は, generator.py のソースを AST で読み取り, 期待される
  add_argument 呼び出しセットと一致するかで担保する.
- Windows native Python + cwd=scripts/ で実行すること.
"""
import ast
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
GENERATOR_PY = SCRIPTS_DIR / "generator.py"

errors = []


def expect(cond, msg):
    if cond:
        print(f"  [OK] {msg}")
    else:
        print(f"  [NG] {msg}")
        errors.append(msg)


# ── 1. generator.py AST 解析: ArgumentParser(allow_abbrev=False) と ──────
#     add_argument の set を抽出
print("[1] generator.py AST 解析")
src = GENERATOR_PY.read_text(encoding="utf-8")
tree = ast.parse(src)

allow_abbrev_false_found = False
channel_arg_found = False
channel_default = None
channel_choices = None
add_arg_names = []

for node in ast.walk(tree):
    # ArgumentParser(allow_abbrev=False)
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        if node.func.attr == "ArgumentParser":
            for kw in node.keywords:
                if kw.arg == "allow_abbrev" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                    allow_abbrev_false_found = True

    # parser.add_argument("--xxx", ...)
    if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument" and node.args):
        first = node.args[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            name = first.value
            add_arg_names.append(name)
            if name == "--channel":
                channel_arg_found = True
                for kw in node.keywords:
                    if kw.arg == "default" and isinstance(kw.value, ast.Constant):
                        channel_default = kw.value.value
                    if kw.arg == "choices":
                        if isinstance(kw.value, (ast.List, ast.Tuple)):
                            channel_choices = [
                                elt.value for elt in kw.value.elts
                                if isinstance(elt, ast.Constant)
                            ]

expect(allow_abbrev_false_found,
       "ArgumentParser(allow_abbrev=False) が定義されている")
expect(channel_arg_found, "--channel 引数が定義されている")
expect(channel_default == "health",
       f"--channel default == 'health' (got {channel_default!r})")
expect(channel_choices == ["health"],
       f"--channel choices == ['health'] only (got {channel_choices})")

# 既存引数の消失がないこと (regression)
EXPECTED_ARGS = {
    "--auto", "--theme", "--publish-hours", "--publish-time",
    "--no-upload", "--script-file", "--resume", "--channel",
}
missing = EXPECTED_ARGS - set(add_arg_names)
expect(not missing,
       f"expected args all present (missing: {sorted(missing)})")

# ── 2. load_channel(args.channel) 呼び出しが存在すること ─────────────
print("[2] load_channel(args.channel) 呼び出し")
# 愚直に文字列で確認 (AST 正規化不要)
expect("load_channel(args.channel)" in src,
       "load_channel(args.channel) が generator.py に存在")
expect('load_channel("health")' not in src,
       'load_channel("health") ハードコードが消えている')
expect("load_channel('health')" not in src,
       "load_channel('health') ハードコードが消えている")

# ── 3. 本番と同じ ArgumentParser を probe 側で再構築して動作実測 ─────
print("[3] 本番形態 ArgumentParser 動作実測")
import argparse

parser = argparse.ArgumentParser(allow_abbrev=False)
parser.add_argument("--auto",          action="store_true")
parser.add_argument("--theme",         type=str, default="")
parser.add_argument("--publish-hours", type=int, default=0)
parser.add_argument("--publish-time",  type=str, default="")
parser.add_argument("--no-upload",     action="store_true")
parser.add_argument("--script-file",   type=str, default="")
parser.add_argument("--resume",        action="store_true")
parser.add_argument("--channel",       type=str, default="health",
                    choices=["health"])

# 3-a: run.bat と同じ呼び出し → args.channel == 'health' (default)
args = parser.parse_args(["--auto", "--publish-time", "18:00"])
expect(args.channel == "health",
       f"run.bat 相当 → args.channel == 'health' (got {args.channel!r})")
expect(args.auto is True, "run.bat 相当 → args.auto is True")
expect(args.publish_time == "18:00", "run.bat 相当 → publish_time == '18:00'")

# 3-b: --channel health 明示
args = parser.parse_args(["--auto", "--channel", "health"])
expect(args.channel == "health",
       f"--channel health → 'health' (got {args.channel!r})")

# 3-c: --channel creatures → argparse レベルで SystemExit
#      Codex adversarial 指摘: creatures を先行露出すると混成実行 silent success
#      リスクが生じるため, Step 3-γ では choices に creatures を含めない.
try:
    parser.parse_args(["--auto", "--channel", "creatures"])
    expect(False, "--channel creatures → choices で SystemExit reject (got: 通過)")
except SystemExit:
    expect(True, "--channel creatures → choices で SystemExit reject (混成実行遮断)")

# 3-d: --channel foo → SystemExit (argparse choices reject)
try:
    parser.parse_args(["--auto", "--channel", "foo"])
    expect(False, "--channel foo → SystemExit で reject (got: 通過)")
except SystemExit:
    expect(True, "--channel foo → SystemExit で reject")

# 3-e: --ch creatures → allow_abbrev=False で SystemExit (prefix match 禁止)
#      Codex 前回指摘の防止確認
try:
    parser.parse_args(["--auto", "--ch", "creatures"])
    expect(False, "--ch creatures → allow_abbrev=False で SystemExit reject (got: 通過)")
except SystemExit:
    expect(True, "--ch creatures → allow_abbrev=False で SystemExit reject")

# 3-f: 他の既存引数 prefix match も禁止されていること (例: --pub → --publish-time)
try:
    parser.parse_args(["--auto", "--pub", "18:00"])
    expect(False, "--pub 18:00 → allow_abbrev=False で SystemExit (got: 通過)")
except SystemExit:
    expect(True, "--pub → allow_abbrev=False で prefix match 禁止")

# ── 4. load_channel('health') が bit-identical に動くこと ───────────
#    creatures の regression 保護は tests.test_channel.TestCreaturesLoad
#    (Step 3-β) に委譲済み. 本 probe では default 経路のみを検証する.
print("[4] load_channel('health') default 経路 bit-identical")
sys.path.insert(0, str(SCRIPTS_DIR))
from _channel import load_channel

health = load_channel("health")
expect(health.id == "health", "load_channel('health').id == 'health'")

# default 経路 (run.bat 実行経路) が health と bit-identical になることの確認
expect(health.paths.lock_file == "logs/last_upload_date.txt",
       "health.paths.lock_file unchanged (bit-identical guard)")
expect(health.paths.themes_file == "themes.txt",
       "health.paths.themes_file unchanged (bit-identical guard)")

# ── 5. notify_error 文言にチャンネル名が入ること (source grep) ────────
print("[5] notify_error 文言のチャンネル名埋め込み")
expect("チャンネル設定読込失敗 ({args.channel})" in src,
       "notify_error 文言に args.channel が埋め込まれている")

# ── 結果 ─────────────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3C: --channel CLI 引数が本番形態で期待通り動作")
    sys.exit(0)
