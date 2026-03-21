# キャラクター定義（霊夢・魔理沙の2キャラ固定）

CHARACTERS = [
    {
        "id": "reimu",
        "name": "霊夢",
        "role": "リアクション・質問役",
        "style": "驚きやすい、素直に疑問を投げかける。「え、マジで！？」「それ知らなかった！」「どういうこと？」など。視聴者目線の代弁者。",
    },
    {
        "id": "marisa",
        "name": "魔理沙",
        "role": "解説・進行役",
        "style": "自信満々、断定的に話す。「実はな〜」「これがすごいんだぜ」「知ってるか？」「〜なんだぜ」など。情報を楽しく伝える。",
    },
]


def get_character_names() -> list[str]:
    return [c["name"] for c in CHARACTERS]


def get_characters_description() -> str:
    lines = []
    for c in CHARACTERS:
        lines.append(f"・{c['name']}（{c['role']}）: {c['style']}")
    return "\n".join(lines)
