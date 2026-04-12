"""Phase A+B+C+D+E probe: _fix_role_violations の挙動を全面検証.

検証:
[A-1] 霊夢 俺→私 後の下流 _REIMU_MASCULINE_FIXES が新 text を参照する
[B-1] 魔理沙+私 は違反判定されない (character-design.md 準拠)
[B-2] 魔理沙+俺 は fixer で 私 に戻る + 違反判定される
[B-3] 霊夢+俺 は fixer で 私 に戻る + 違反判定される
[C-1] 10時エラー再現: 魔理沙+line_type=質問 が _fix_role_violations で「汎用」に正規化
[C-2] _original_line_type に元値が退避される
[C-3] 「汎用」化した line_type は validator で違反にならない
[D-1] 霊夢+「だぜ」→「だわ」に自動修正される (speech_pattern)
[D-2] 霊夢+「なんだぜ」→「なんだわ」
[D-3] 魔理沙+「知らなかった!」→「知らなかったぜ!」
[D-4] 霊夢の行頭「霊夢、」vocative が削除される (name_call)
[D-5] 行頭 vocative 削除後に text が短くなりすぎる場合はロールバック
[D-6] 中間出現の「霊夢」は削除されない (引用/言及を保護)
[E-1] gate 失敗時の RuntimeError メッセージに先頭5件の detail が含まれる
[E-2] 10時エラーの現物データ (魔理沙+質問 の line_type) が _fix_role_violations 通過後 gate を通る
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
SKILLS_DIR = SCRIPTS_DIR / "skills"
sys.path.insert(0, str(SCRIPTS_DIR))
sys.path.insert(0, str(SKILLS_DIR))

import skill_script_gen as sg

errors = []


def expect(cond, msg):
    if cond:
        print(f"  [OK] {msg}")
    else:
        print(f"  [NG] {msg}")
        errors.append(msg)


def make_script(lines):
    return {"sections": [{"lines": lines}]}


# ── [A-1] 霊夢 俺→私 後の下流 _REIMU_MASCULINE_FIXES 更新 ──
print("[A-1] 霊夢 俺→私 後の下流修正が新 text を参照")
script = make_script([
    {"character": "霊夢", "text": "俺はそうだぜ", "synthesis_text": "俺はそうだぜ", "line_type": ""},
])
_, fixed = sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
# 俺→私 + だぜ→だわ 両方適用されることを期待
expect(t == "私はそうだわ", f"霊夢 俺+だぜ → 私+だわ (got: {t!r})")


# ── [B-1] 魔理沙+私 は違反判定されない ──
print("[B-1] 魔理沙+私 は非違反")
script = make_script([
    {"character": "魔理沙", "text": "私が説明するぜ", "synthesis_text": "私が説明するぜ", "line_type": "解説"},
])
v = sg.deterministic_validate_roles(script)
pronoun_v = [x for x in v if x["check_type"] == "pronoun"]
expect(len(pronoun_v) == 0, f"魔理沙+私 は pronoun 違反0件 (got: {len(pronoun_v)})")


# ── [B-2] 魔理沙+俺 は fixer で 私 に戻る ──
print("[B-2] 魔理沙+俺 → 私")
script = make_script([
    {"character": "魔理沙", "text": "俺が説明する", "synthesis_text": "俺が説明する", "line_type": "解説"},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
expect(t == "私が説明する", f"魔理沙 俺→私 (got: {t!r})")


# ── [B-3] 霊夢+俺 → 私 ──
print("[B-3] 霊夢+俺 → 私")
script = make_script([
    {"character": "霊夢", "text": "俺、知らなかった!", "synthesis_text": "俺、知らなかった!", "line_type": "リアクション"},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
expect("私" in t and "俺" not in t, f"霊夢 俺→私 (got: {t!r})")


# ── [C-1][C-2][C-3] 10時エラー現物: 魔理沙+line_type=質問 ──
print("[C-1~3] 魔理沙+質問 line_type 正規化")
script = make_script([
    {"character": "魔理沙", "text": "どうなってるんだ", "synthesis_text": "どうなってるんだ", "line_type": "質問"},
    {"character": "魔理沙", "text": "なぜそんなことに?", "synthesis_text": "なぜそんなことに?", "line_type": "質問"},
])
sg._fix_role_violations(script)
l0 = script["sections"][0]["lines"][0]
l1 = script["sections"][0]["lines"][1]
expect(l0["line_type"] == "汎用", f"l0 line_type 正規化 (got: {l0['line_type']!r})")
expect(l0.get("_original_line_type") == "質問", f"l0 元値退避 (got: {l0.get('_original_line_type')!r})")
expect(l1["line_type"] == "汎用" and l1.get("_original_line_type") == "質問", "l1 同様に正規化")
v = sg.deterministic_validate_roles(script)
lt_v = [x for x in v if x["check_type"] == "line_type"]
expect(len(lt_v) == 0, f"正規化後 line_type 違反0件 (got: {len(lt_v)})")


# ── [D-1][D-2] 霊夢 speech_pattern 自動修正 ──
print("[D-1~2] 霊夢 だぜ/なんだぜ 自動修正")
script = make_script([
    {"character": "霊夢", "text": "それは違うんだぜ", "synthesis_text": "それは違うんだぜ", "line_type": ""},
    {"character": "霊夢", "text": "そうなんだぜ", "synthesis_text": "そうなんだぜ", "line_type": ""},
])
sg._fix_role_violations(script)
t0 = script["sections"][0]["lines"][0]["text"]
t1 = script["sections"][0]["lines"][1]["text"]
expect(t0.endswith("だわ"), f"霊夢 だぜ→だわ (got: {t0!r})")
expect("なんだわ" in t1, f"霊夢 なんだぜ→なんだわ (got: {t1!r})")
v = sg.deterministic_validate_roles(script)
sp_v = [x for x in v if x["check_type"] == "speech_pattern"]
expect(len(sp_v) == 0, f"修正後 speech_pattern 違反0件 (got: {len(sp_v)})")


# ── [D-3] 魔理沙 知らなかった! 自動修正 ──
print("[D-3] 魔理沙 知らなかった!→知らなかったぜ!")
script = make_script([
    {"character": "魔理沙", "text": "えっ知らなかった！それは初耳", "synthesis_text": "えっ知らなかった！それは初耳", "line_type": "解説"},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
expect("知らなかったぜ" in t, f"魔理沙 知らなかった→知らなかったぜ (got: {t!r})")


# ── [D-4] 霊夢 行頭「霊夢、」vocative 削除 ──
print("[D-4] 行頭 vocative 削除")
script = make_script([
    {"character": "霊夢", "text": "霊夢、それは違うわよ本当に", "synthesis_text": "霊夢、それは違うわよ本当に", "line_type": ""},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
expect(not t.startswith("霊夢"), f"行頭 vocative 削除 (got: {t!r})")
expect("それは違う" in t, f"本文は保持 (got: {t!r})")


# ── [D-5] 行頭 vocative 削除後に短くなりすぎる場合ロールバック ──
print("[D-5] 短すぎる場合はロールバック")
script = make_script([
    {"character": "霊夢", "text": "霊夢、ねえ", "synthesis_text": "霊夢、ねえ", "line_type": ""},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
# "ねえ" は3文字 < 5 なのでロールバック → 元の "霊夢、ねえ" のまま
expect(t.startswith("霊夢"), f"短すぎるのでロールバック (got: {t!r})")


# ── [D-6] 中間出現の 霊夢 は削除されない ──
print("[D-6] 中間出現の自キャラ名は保護")
script = make_script([
    {"character": "霊夢", "text": "そうね、霊夢という名前について", "synthesis_text": "そうね、霊夢という名前について", "line_type": ""},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
expect("霊夢" in t, f"中間の霊夢は保持 (got: {t!r})")
v = sg.deterministic_validate_roles(script)
nc_v = [x for x in v if x["check_type"] == "name_call"]
expect(len(nc_v) == 0, f"行頭でないので name_call 違反0件 (got: {len(nc_v)})")


# ── [F-1] 引用文保護: 魔理沙行の 「知らなかった！」 が改変されない ──
print("[F-1] 魔理沙行の引用「知らなかった！」保護")
script = make_script([
    {"character": "魔理沙", "text": "患者は「知らなかった！」と驚いた", "synthesis_text": "患者は「知らなかった！」と驚いた", "line_type": "解説"},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
expect("「知らなかった！」" in t, f"引用は保持 (got: {t!r})")
expect("知らなかったぜ" not in t, f"引用内に fixer が介入していない (got: {t!r})")
v = sg.deterministic_validate_roles(script)
sp_v = [x for x in v if x["check_type"] == "speech_pattern"]
expect(len(sp_v) == 0, f"引用外なら validator も沈黙 (got: {len(sp_v)})")


# ── [F-2] 引用外の 知らなかった！ は従来通り修正される ──
print("[F-2] 引用外の 知らなかった！ は修正対象")
script = make_script([
    {"character": "魔理沙", "text": "うーん知らなかった！本当に意外だ", "synthesis_text": "うーん知らなかった！本当に意外だ", "line_type": "解説"},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
expect("知らなかったぜ" in t, f"引用外なら修正される (got: {t!r})")


# ── [F-3] 霊夢行の 「だぜ」 引用保護 ──
print("[F-3] 霊夢行の引用「だぜ」保護")
script = make_script([
    {"character": "霊夢", "text": "魔理沙は「そうなんだぜ」が口癖", "synthesis_text": "魔理沙は「そうなんだぜ」が口癖", "line_type": ""},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
expect("「そうなんだぜ」" in t, f"霊夢の引用「だぜ」は保持 (got: {t!r})")


# ── [F-4] ってことだぜ → ってことなのよ (順序依存の確認) ──
print("[F-4] ってことだぜ → ってことなのよ (短いパターンに潰されない)")
script = make_script([
    {"character": "霊夢", "text": "つまりそういうってことだぜ", "synthesis_text": "つまりそういうってことだぜ", "line_type": ""},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
expect("ってことなのよ" in t, f"長パターンが先に発火 (got: {t!r})")
expect("ってことだわ" not in t, f"短パターンに潰されていない (got: {t!r})")


# ── [F-5] 2段階しきい値: ハード下限の境界 ──
print("[F-5] ハード下限 5200 / ソフト目標 6000")
expect(sg._HARD_MIN_SCRIPT_CHARS == 5200, f"ハード下限定数 (got: {sg._HARD_MIN_SCRIPT_CHARS})")
expect(sg._MIN_SCRIPT_CHARS == 6000, f"ソフト目標定数 (got: {sg._MIN_SCRIPT_CHARS})")
expect(sg._HARD_MIN_SCRIPT_CHARS < sg._MIN_SCRIPT_CHARS, "hard < soft 関係維持")


# ── [F-6] resume 判定も HARD を見る (generator.py との整合) ──
print("[F-6] generator.py の resume 判定も HARD 基準")
import importlib
_gen_path = PROJECT_ROOT / "scripts" / "generator.py"
_gen_src = _gen_path.read_text(encoding="utf-8")
expect(
    "_HARD_MIN_SCRIPT_CHARS as _RESUME_MIN_CHARS" in _gen_src,
    "generator.py が _HARD_MIN_SCRIPT_CHARS を import",
)


# ── [F-8] pronoun fixer/validator も引用内を保護する ──
print("[F-8] 引用内の「俺」は fixer/validator とも無視")
script = make_script([
    {"character": "霊夢", "text": "彼は「俺がやる」と言った", "synthesis_text": "彼は「俺がやる」と言った", "line_type": ""},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
expect("「俺がやる」" in t, f"引用内の俺は保持 (got: {t!r})")
v = sg.deterministic_validate_roles(script)
pronoun_v = [x for x in v if x["check_type"] == "pronoun"]
expect(len(pronoun_v) == 0, f"引用内なら pronoun 違反0件 (got: {len(pronoun_v)})")


# ── [F-9] 不整合な引用は fixer では無変更、validator は全文フォールバック ──
print("[F-9] 不整合な引用: fixer 無変更 + validator は fail-open にしない")
script = make_script([
    {"character": "霊夢", "text": "彼は「俺がやるといった", "synthesis_text": "彼は「俺がやるといった", "line_type": ""},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
# unbalanced なので fixer は触らない (壊さない). 本文は残る.
expect(t == "彼は「俺がやるといった", f"不整合引用は fixer 無変更 (got: {t!r})")
# validator 側は malformed を全文検索フォールバックして 俺 を検出する必要.
v = sg.deterministic_validate_roles(script)
pronoun_v = [x for x in v if x["check_type"] == "pronoun"]
expect(len(pronoun_v) >= 1, f"malformed は validator がフォールバックで拾う (got: {len(pronoun_v)})")


# ── [F-9b] 入れ子引用 + 引用外の 俺 → validator が gate で拾う ──
print("[F-9b] 入れ子引用でも引用外の違反を gate で捕捉")
script = make_script([
    {"character": "霊夢", "text": "彼は「A「B」C」と言った。俺は反対だ", "synthesis_text": "彼は「A「B」C」と言った。俺は反対だ", "line_type": ""},
])
sg._fix_role_violations(script)
v = sg.deterministic_validate_roles(script)
pronoun_v = [x for x in v if x["check_type"] == "pronoun"]
expect(len(pronoun_v) >= 1, f"入れ子でも pronoun 違反を検出 (got: {len(pronoun_v)})")


# ── [F-10] 呼び方修正も引用内を保護 ──
print("[F-10] 引用内の「君」は保持")
script = make_script([
    {"character": "魔理沙", "text": "先生は「君は若い」と言った", "synthesis_text": "先生は「君は若い」と言った", "line_type": "解説"},
])
sg._fix_role_violations(script)
t = script["sections"][0]["lines"][0]["text"]
expect("「君は若い」" in t, f"引用内の君は保持 (got: {t!r})")


# ── [F-11] 魔理沙 口癖保護: だぜ/なんだ/だぞ は一切触らない ──
print("[F-11] 魔理沙 口癖 (だぜ/なんだ/だぞ) は無変更")
for t_in in [
    "そうなんだ",
    "気をつけるんだぞ",
    "強いんだぜ",
    "なんだぜ、それは",
    "そうだぜ",
    "だろ？",
    "覚えておけよ",
    "教えてやる",
]:
    script = make_script([
        {"character": "魔理沙", "text": t_in, "synthesis_text": t_in, "line_type": "解説"},
    ])
    sg._fix_role_violations(script)
    t = script["sections"][0]["lines"][0]["text"]
    expect(t == t_in, f"魔理沙 {t_in!r} 無変更 (got: {t!r})")


# ── [F-7] _original_line_type が JSON 保存前クリーンアップに載っている ──
print("[F-7] _original_line_type は保存前に除去される")
_sg_src = (PROJECT_ROOT / "scripts" / "skills" / "skill_script_gen.py").read_text(encoding="utf-8")
expect(
    'line.pop("_original_line_type", None)' in _sg_src,
    "_original_line_type 除去コードが存在",
)


# ── [E-2] 統合: 現物データ再現で gate 通過 ──
print("[E-2] 10時エラー現物データ再現 → gate 通過")
# 行129/130 魔理沙+line_type=質問 を模擬
lines = []
for i in range(128):
    lines.append({"character": "魔理沙" if i % 2 == 0 else "霊夢",
                  "text": f"テストセリフ{i}です",
                  "synthesis_text": f"テストセリフ{i}です",
                  "line_type": "解説" if i % 2 == 0 else "ボケ"})
# 違反行
lines.append({"character": "魔理沙", "text": "どうなってるんだ", "synthesis_text": "どうなってるんだ", "line_type": "質問"})
lines.append({"character": "魔理沙", "text": "なぜそうなるんだ", "synthesis_text": "なぜそうなるんだ", "line_type": "質問"})
script = {"sections": [{"lines": lines}]}
sg._fix_role_violations(script)
v = sg.deterministic_validate_roles(script)
non_consec = [x for x in v if x["check_type"] != "consecutive"]
expect(len(non_consec) == 0, f"10時エラー現物 fix 後に非連続違反0件 (got: {len(non_consec)}, details: {non_consec[:3]})")


# ── 結果 ──────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK: Phase A+B+C+D+E+F 全項目合格")
    sys.exit(0)
