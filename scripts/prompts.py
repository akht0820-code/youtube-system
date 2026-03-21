# Geminiへのプロンプトテンプレート（健康ゆっくり解説チャンネル特化）

from characters import get_characters_description, get_character_names


def build_title_prompt(theme: str) -> str:
    """サムネイル用YouTubeタイトルを生成するプロンプト"""
    return f"""
あなたは健康ゆっくり解説YouTubeチャンネルのタイトルコピーライターです。

テーマ「{theme}」に対して、クリックされやすいYouTubeタイトルを1つ生成してください。

## タイトルのパターン（いずれかを使う）
- 「〇〇すると、実は●●になります」
- 「〇〇な人、実は●●でした」
- 「〇〇を食べ続けると、●●になります」
- 数字＋「選」形式（例：「本当に摂るべき食品11選」）

## ルール
- 「●●」の部分は答えを伏せて好奇心を煽る（サムネには赤丸で隠す想定）
- 40〜60代が反応するワードを使う（白髪・老化・疲労・血糖値・睡眠など）
- 「実は」「意外と」などの意外性ワードを入れる
- 20〜35文字以内
- タイトル1行のみ出力。説明文は不要。

テーマ: {theme}
"""


def build_description_prompt(theme: str, title: str, sections: list) -> str:
    """YouTube動画の説明文を生成するプロンプト"""
    section_titles = "\n".join(f"・{s['title']}" for s in sections)
    return f"""
あなたは健康ゆっくり解説YouTubeチャンネルの説明文ライターです。

以下の情報をもとに、YouTube動画の説明文を生成してください。

タイトル: {title}
テーマ: {theme}
動画の構成:
{section_titles}

## 説明文のフォーマット（必ずこの順番・形式で）

1行目: 動画の内容を1〜2文で要約（視聴者に「見る価値がある」と思わせる）

（空行）

■本日の動画構成
（各セクションを「0:00 セクション名」の形式でタイムスタンプ付きで記載。時間は仮で構わない）

（空行）

■BGM
Hanagoyomi / PeriTune (https://peritune.com/)
Harvest2 / PeriTune (https://peritune.com/)
伝承の丘 / 秋山裕和 (https://www.bgmchannel.com/)

（空行）

#ゆっくり解説 #健康

## ルール
- タイムスタンプは「0:00 導入」から始め、等間隔で仮の時間を入れる
- 全体200〜400文字程度
- 説明文のみ出力。前置きや補足は不要
"""


def build_tags_prompt(theme: str, title: str) -> str:
    """YouTube動画のタグを生成するプロンプト"""
    return f"""
以下のYouTube動画に適したタグを生成してください。

タイトル: {title}
テーマ: {theme}

## ルール
- 15〜20個のタグを生成する
- 健康・食・ゆっくり解説に関連するキーワード
- 視聴者が検索しそうな具体的なワード（「納豆 効果」「血糖値 下げる」など）
- 1タグは1〜10文字程度
- JSONの配列形式のみで出力（例: ["タグ1", "タグ2", ...]）
- 前置きや説明は不要
"""


def build_structure_prompt(theme: str) -> str:
    """1回目: テーマから動画構成を生成"""
    return f"""
あなたは健康・食・雑学ゆっくり解説YouTubeチャンネルの構成作家です。

テーマ「{theme}」について、16〜17分の動画構成を作ってください。

ターゲット視聴者: 40〜60代の健康に関心がある日本人

## 構成のルール
- 「導入」は短め（30秒〜1分）。最初のセリフは必ず「え、マジで！？」と思わせるような衝撃的な事実か問いかけにする
- 本編は「サブチャプター」を3〜8個に分けてランキング・箇条書き形式で展開する
- 最後は「まとめ」で要点を3点以内に整理する
- 全体のセリフ数が200〜250行になるよう、各サブチャプターの情報量を設定する

## 含めるべき要素
- 40〜60代が気になるワード（白髪・疲労・老化防止・睡眠・体重・血糖値など）を自然に盛り込む
- 「実は〜」「意外と知られていないが〜」という意外性の表現を多用する
- 数字・データ・研究結果を含める（「〜倍」「〜%」「〜万人の研究で」など）

以下の形式でJSONのみを出力してください。

{{
  "theme": "テーマ名",
  "hook": "最初のセリフ（衝撃的な事実・問いかけ）",
  "summary": "この動画で視聴者が得られること（100字）",
  "sections": [
    {{
      "title": "セクションタイトル",
      "type": "intro | chapter | summary",
      "key_points": ["具体的な情報1", "具体的な情報2"]
    }}
  ]
}}
"""


def build_script_prompt_with_suggestions(
    theme: str, structure: dict, suggestions: dict
) -> str:
    """改善提案を反映した台本生成プロンプト（suggestions.jsonがある場合に使用）"""
    base_prompt = build_script_prompt(theme, structure)

    suggestion_lines = suggestions.get("suggestions", [])
    title_patterns   = suggestions.get("title_patterns", [])
    if not suggestion_lines:
        return base_prompt

    suggestions_text = "\n".join(f"  - {s}" for s in suggestion_lines[:5])
    title_text = "\n".join(f"  - {p}" for p in title_patterns[:3]) if title_patterns else ""

    extra = f"""
## 前回の分析による改善指示（必ず反映すること）
{suggestions_text}
"""
    if title_text:
        extra += f"""
## 効果的なタイトルパターン（参考）
{title_text}
"""

    # JSONのみ出力という指示の直前に挿入
    return base_prompt.replace(
        "以下の形式でJSONのみを出力してください。",
        extra + "\n以下の形式でJSONのみを出力してください。",
    )


def build_script_prompt(theme: str, structure: dict) -> str:
    """2回目: 構成から台本を生成"""
    characters_desc = get_characters_description()

    sections_desc = ""
    for i, section in enumerate(structure.get("sections", []), 1):
        sections_desc += f"\n【{section['title']}】（タイプ: {section.get('type', 'chapter')}）\n"
        for point in section.get("key_points", []):
            sections_desc += f"  - {point}\n"

    hook = structure.get("hook", "")

    return f"""
あなたはゆっくり解説動画の台本ライターです。
霊夢と魔理沙の2キャラが会話する形式で台本を書いてください。

## テーマ
{theme}

## 動画の概要
{structure.get("summary", "")}

## キャラクター
{characters_desc}

## 構成と含める情報
{sections_desc}

## 台本のルール

【会話スタイル】
- ゆっくり解説らしい軽快なテンポで進める
- 魔理沙が情報を話し、霊夢が「え、本当に？」「それすごい！」とリアクションする流れを基本とする
- 1セリフは1〜2文（短め）。長い説明は魔理沙が2〜3回に分けて話す
- 相槌や驚きの短いセリフを適度に挟む（「マジか！」「なるほど〜」「それ知らなかった！」など）

【導入の必須ルール】
- 最初のセリフは必ず魔理沙がこのフックで始める:
  「{hook}」
- 冒頭5〜6セリフで「なぜこれを見るべきか」を視聴者に感じさせる

【テンポのルール】
- 同じキャラクターを2回以上連続で発言させない
- 5〜6セリフに1回は霊夢が魔理沙に直接質問し、魔理沙が答える「やりとり」を入れる

【全体の分量】
- 合計200〜250行のセリフを生成する
- 各セクションを丁寧に展開し、情報を細かく分けて伝える

- emotion は "normal", "surprised", "happy", "serious" のいずれか

以下の形式でJSONのみを出力してください。

{{
  "theme": "{theme}",
  "characters": ["霊夢", "魔理沙"],
  "sections": [
    {{
      "section": "セクションタイトル",
      "lines": [
        {{
          "character": "霊夢 または 魔理沙",
          "text": "セリフ",
          "emotion": "感情"
        }}
      ]
    }}
  ]
}}
"""
