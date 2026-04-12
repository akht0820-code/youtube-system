"""Step 3-δ.5c-7 probe: AST hardcode guard + choices 現状ロック.

検証:
[1] 5c-1〜5c-6 で channel-aware 化された 7 ファイルに, 禁止ハードコード文字列
    ('output', 'credentials.json', 'token.json', 'themes.txt',
     'last_upload_date.txt') が Constant として残っていない
    (allow-list 例外: _common.py の legacy fallback のみ)
[2] 同 7 ファイルに `OUTPUT_DIR =` の module-level 定数が無い
[3] 全 CLI エントリポイント (7 箇所) が argparse choices=["health"] のままで
    creatures が silent に開放されていないこと (gating guard).
    creatures の choices 開放は 5c-8 (script char 閾値 + tags fallback の
    channel-aware 化) 完了後とする (Codex 対立レビュー 2026-04-12 指摘).
[4] creatures channel config (config/channels/creatures.json) が load 可能
    + output_subdir='output_creatures' + credentials='credentials_creatures.json'
    を解決できる (config ファイル自体の sanity, choices 未開放でも有効)

前提:
- Step 3-δ.5c-1〜5c-6 commit 済み, すべて regression zero.
- 本 Step は verification helper のみ. 既存 channel-aware ロジックは触らない.

なぜ [3] が「choices=['health'] のまま」を assert するのか:
- 5c-1〜5c-6 で channel-aware 化された範囲は paths/oauth/themes/output_dir のみ.
- skill_script_gen.py の _MIN/_HARD/_MAX_SCRIPT_CHARS は health 固定値
  (6000/5200/7500) で, creatures config (min_chars=8000/max_chars=10000) と不整合.
- skill_metadata.py (L305) と skill_upload.py (L170) の fallback tags が
  ['ゆっくり解説','健康'] で, creatures config (['生き物','動物','生態']) と不整合.
- この状態で creatures を choices に開放すると, 部分失敗 fallback 経路で
  creatures 動画が '健康' タグ付き silent success する危険がある.
- 本 probe は「まだ choices 開放していないか」を gating guard として守る.
"""
import ast
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SKILLS_DIR = SCRIPTS_DIR / "skills"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SKILLS_DIR))

errors = []


def expect(cond, msg):
    if cond:
        print(f"  [OK] {msg}")
    else:
        print(f"  [NG] {msg}")
        errors.append(msg)


# ── 対象ファイル ─────────────────────────────────────────────
# 5c-1〜5c-6 で channel-aware 化された 7 ファイル.
TARGET_FILES = [
    SCRIPTS_DIR / "generator.py",                   # 5c-1 呼び出し側
    SKILLS_DIR / "skill_script_gen.py",             # 5c-1
    SKILLS_DIR / "skill_video_build.py",            # 5c-2
    SKILLS_DIR / "skill_metadata.py",               # 5c-3
    SKILLS_DIR / "skill_upload.py",                 # 5c-4
    SKILLS_DIR / "self_healing.py",                 # 5c-5
    SKILLS_DIR / "_common.py",                      # 5c-6
]

# 禁止文字列リテラル (Constant.value として出現したら違反).
FORBIDDEN_LITERALS = {
    "output",
    "credentials.json",
    "token.json",
    "themes.txt",
    "last_upload_date.txt",
}

# Allow-list 例外: (file, value) で正当なケースを宣言.
# _common.py の legacy fallback のみ意図的に許可.
ALLOW_LIST = {
    ("_common.py", "output"): {"reason": "Step 3-δ.5c-6 legacy fallback (project_root/'output')"},
}


# ── [1] AST: 禁止ハードコード文字列の残存チェック ──────────────
print("[1] AST ハードコード guard (7 files)")
for target in TARGET_FILES:
    src = target.read_text(encoding="utf-8")
    tree = ast.parse(src)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value
            if v in FORBIDDEN_LITERALS:
                key = (target.name, v)
                if key in ALLOW_LIST:
                    continue  # 正当な例外
                hits.append((node.lineno, v))
    expect(
        len(hits) == 0,
        f"{target.name}: 禁止リテラル 0 件 (got: {hits})",
    )


# ── [2] AST: OUTPUT_DIR module-level 定数が無いこと ────────────
print("[2] AST: OUTPUT_DIR 定数残存なし")
for target in TARGET_FILES:
    src = target.read_text(encoding="utf-8")
    tree = ast.parse(src)
    found = []
    for node in tree.body:  # module-level のみ
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "OUTPUT_DIR":
                    found.append(node.lineno)
    expect(
        len(found) == 0,
        f"{target.name}: module-level OUTPUT_DIR 0 件 (got: {found})",
    )


# ── [3] argparse choices 現状ロック (creatures 未開放 guard) ───
print("[3] argparse choices=['health'] のまま (creatures 未開放 guard)")
# --channel の argparse 呼び出しがある 7 CLI エントリポイント.
CLI_FILES = [
    SCRIPTS_DIR / "preflight_runtime.py",
    SCRIPTS_DIR / "generator.py",
    SKILLS_DIR / "skill_script_gen.py",
    SKILLS_DIR / "skill_video_build.py",
    SKILLS_DIR / "skill_metadata.py",
    SKILLS_DIR / "skill_upload.py",
    SKILLS_DIR / "skill_cache_cleanup.py",
]

for cli in CLI_FILES:
    src = cli.read_text(encoding="utf-8")
    tree = ast.parse(src)
    # parser.add_argument("--channel", ..., choices=[...]) を探す
    found_choices = None
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "add_argument":
            continue
        # 第1引数が "--channel" か確認
        if not node.args:
            continue
        first = node.args[0]
        if not (isinstance(first, ast.Constant) and first.value == "--channel"):
            continue
        # choices kwarg を探す
        for kw in node.keywords:
            if kw.arg == "choices" and isinstance(kw.value, ast.List):
                found_choices = [
                    e.value for e in kw.value.elts
                    if isinstance(e, ast.Constant)
                ]
                break
        break
    expect(
        found_choices is not None and found_choices == ["health"],
        f"{cli.name}: --channel choices == ['health'] (got: {found_choices})",
    )


# ── [4] creatures channel config load sanity ──────────────────
# choices 未開放でも config ファイルと loader が壊れていないことを担保する.
# 5c-8 で choices を開放した瞬間に load 失敗しないための smoke test.
print("[4] creatures config load sanity")
try:
    from _channel import load_channel
    cfg = load_channel("creatures")
    expect(
        cfg.paths.output_subdir == "output_creatures",
        f"creatures output_subdir='output_creatures' (got: {cfg.paths.output_subdir!r})",
    )
    expect(
        cfg.oauth.credentials == "credentials_creatures.json",
        f"creatures credentials='credentials_creatures.json' (got: {cfg.oauth.credentials!r})",
    )
except Exception as e:
    expect(False, f"creatures config load 失敗: {type(e).__name__}: {e}")


# ── 結果 ──────────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK: Step 3-δ.5c-7 全項目合格")
    sys.exit(0)
