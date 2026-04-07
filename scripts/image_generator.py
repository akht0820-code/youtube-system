# AI背景画像生成モジュール
# 動画のテーマに合った背景画像をAIで自動生成する
#
# .envで切り替えられる:
#   IMAGE_PROVIDER=irasutoya    （デフォルト: いらすとや背景、Pollinationsフォールバック）
#   IMAGE_PROVIDER=pollinations （無料・APIキー不要・FLUXモデル）
#   IMAGE_PROVIDER=gemini       （Gemini画像生成モデル・要課金）
#   IMAGE_PROVIDER=local_sd     （ローカルStable Diffusion: GPU必要）
#
#   GEMINI_IMAGE_MODEL=gemini-3-pro-image-preview  （デフォルト）

import io
import os
import random
import urllib.parse
import urllib.request
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

_PROVIDER            = os.getenv("IMAGE_PROVIDER",         "imagen").lower()
_SECTION_PROVIDER    = os.getenv("SECTION_IMAGE_PROVIDER", "imagen").lower()
_IMAGE_MODEL         = os.getenv("GEMINI_IMAGE_MODEL",     "gemini-3-pro-image-preview")
_PROMPT_BUILD_MODEL  = os.getenv("GEMINI_MODEL_SIMPLE",    "gemini-2.5-flash")


# ── Gemini 画像生成 ──────────────────────────────────────────────

def _build_image_prompt(theme: str) -> str:
    """
    テーマから「君の名は。」風アニメ背景の英語画像プロンプトを生成する。
    テーマに合った場所・時間帯・小物を自動推論し、構図も指定する。
    """
    from google import genai
    from google.genai import types
    from secrets import get_secret

    api_key = get_secret("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    system = (
        "あなたはゆっくり解説動画の背景イラストのプロンプトを作るアシスタントです。\n"
        "動画のテーマを受け取り、そのテーマに合った日本の室内シーンの背景を英語で描写してください。\n\n"
        "重要な構図ルール:\n"
        "- テーマのメイン題材（食べ物・物体・シチュエーション）は画面の中央下部に配置する\n"
        "- 画面の左右はキャラクターで隠れるので重要なものを置かない\n"
        "- 画面の上部はUIで隠れるので背景（壁、窓、棚など）だけにする\n"
        "- 俯瞰気味のアングルで見下ろす構図\n\n"
        "その他ルール:\n"
        "- テーマの内容から最も自然な時間帯・シチュエーションを推論する\n"
        "  例: 焼き鮭・味噌汁・納豆→朝食→早朝の柔らかい光\n"
        "  例: ビール・焼肉・おつまみ→夕食/晩酌→夕暮れ～夜の温かい室内灯\n"
        "  例: コーヒー・サンドイッチ→昼食/カフェ→昼の明るい光\n"
        "  例: 睡眠・リラックス→寝室→夜の静かな月明かり\n"
        "  例: 運動・ストレッチ→リビング→朝～午前の爽やかな光\n"
        "- テーマに合った場所を選ぶ（台所、リビング、和室、寝室、書斎、浴室など）\n"
        "- テーマに合った小物を自然に配置する\n"
        "- 推論した時間帯に合った自然光を必ず描写する\n"
        "- 温かみのある生活感のある空間にする\n"
        "- 人物は絶対に描かない\n"
        "- 出力は英語のみ、50-80語\n"
        "- スタイル指示は含めない、シーンの描写だけ"
    )
    response = client.models.generate_content(
        model=_PROMPT_BUILD_MODEL,
        contents=f"テーマ: {theme}",
        config=types.GenerateContentConfig(
            system_instruction=system,
            temperature=0.7,
        ),
    )
    scene_desc = response.text.strip()

    style = (
        'Background art in the style of the anime film "Your Name" (Kimi no Na wa) by CoMix Wave Films. '
        "Breathtakingly beautiful photorealistic anime painting with extraordinary attention to light. "
        "Magical golden hour sunlight pouring through windows, creating dramatic god rays and long warm shadows. "
        "Shimmering dust particles dancing in beams of light. "
        "Every surface rendered with obsessive detail — reflections on polished wood, "
        "condensation on glass, subtle scratches on old furniture, steam rising from hot food. "
        "Vivid jewel-tone colors, painterly yet hyper-real. "
        "Cinematic wide 16:9 composition with natural depth of field. "
        "No characters, no people, no text, no watermark, no UI elements."
    )
    return f"{scene_desc}. {style}"


def _crop_to_16_9(img: "Image.Image") -> "Image.Image":
    """画像を16:9のアスペクト比に中央クロップする"""
    w, h = img.size
    target_ratio = 16 / 9
    current_ratio = w / h

    if abs(current_ratio - target_ratio) < 0.01:
        return img  # すでに16:9

    if current_ratio > target_ratio:
        # 横長すぎる → 左右をクロップ
        new_w = int(h * target_ratio)
        left = (w - new_w) // 2
        return img.crop((left, 0, left + new_w, h))
    else:
        # 縦長すぎる → 上下をクロップ
        new_h = int(w / target_ratio)
        top = (h - new_h) // 2
        return img.crop((0, top, w, top + new_h))


def _generate_gemini(
    image_prompt: str, width: int, height: int, output_path: Path
) -> Path:
    """
    Gemini 画像生成モデルで背景画像を生成する。
    APIキーは GEMINI_API_KEY（台本生成と共用）。
    モデルは GEMINI_IMAGE_MODEL（デフォルト: gemini-3-pro-image-preview）。
    """
    from google import genai
    from google.genai import types
    from PIL import Image

    from secrets import get_secret
    api_key = get_secret("GEMINI_API_KEY")

    client = genai.Client(api_key=api_key)
    print(f"  Gemini ({_IMAGE_MODEL}) で画像を生成しています...")

    response = client.models.generate_content(
        model=_IMAGE_MODEL,
        contents=image_prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
        ),
    )

    # レスポンスから画像バイナリを取得
    image_data = None
    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data is not None:
            image_data = part.inline_data.data
            break

    if not image_data:
        raise ValueError(
            f"Gemini APIから画像データが返されませんでした "
            f"（モデル: {_IMAGE_MODEL}）"
        )

    # 16:9クロップ → target解像度にリサイズ → 保存
    img = Image.open(io.BytesIO(image_data))
    img = _crop_to_16_9(img)
    img = img.resize((width, height), Image.LANCZOS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() in (".jpg", ".jpeg"):
        img.convert("RGB").save(output_path, "JPEG", quality=95)
    else:
        img.save(output_path)

    print(f"  → 背景画像を保存: {output_path.name}")
    return output_path


# ── Pollinations.ai（無料フォールバック）────────────────────────

# テーマキーワード → 英語プロンプト（Pollinations用: LLM呼び出し不要）
_THEME_MAP = [
    (["歯", "歯みがき", "歯磨き", "歯周病", "フロス", "口腔", "虫歯", "歯茎", "口臭", "歯科", "歯ブラシ"],
     "close-up of dental hygiene essentials: soft toothbrush, white toothpaste tube, "
     "fresh mint leaves on clean white marble surface, cool mint green and ivory tones"),
    (["納豆", "豆腐", "豆"],
     "japanese fermented soybeans bowl on wooden table, natural morning light"),
    (["緑茶", "お茶", "ルイボス", "ミルク"],
     "japanese green tea ceremony, zen garden, stone and bamboo, soft bokeh"),
    (["睡眠", "眠れ", "目が覚", "いびき"],
     "peaceful bedroom at night, moonlight through sheer curtains, dark blue tones"),
    (["ブロッコリー", "野菜", "トマト", "玉ねぎ", "わかめ"],
     "fresh colorful vegetables on rustic wooden table, natural sunlight"),
    (["果物", "りんご", "バナナ", "アボカド"],
     "tropical fresh fruits arrangement, white marble background, vibrant food photography"),
    (["魚", "サバ"],
     "fresh fish fillet on clean plate, ocean blue background, healthy seafood"),
    (["オイル", "油", "亜麻仁", "オリーブ"],
     "premium olive oil in glass bottle, mediterranean herbs rosemary, warm light"),
    (["コーヒー"],
     "morning coffee cup on rustic wooden table, warm bokeh, cozy atmosphere"),
    (["ヨーグルト", "キムチ", "腸"],
     "probiotic yogurt bowl with fresh berries, soft light, clean kitchen background"),
    (["血糖", "血圧", "コレステロール", "尿酸"],
     "medical wellness concept, clean white blue tones, health monitoring"),
    (["老化", "白髪", "抜け毛", "若く"],
     "anti-aging natural skincare herbs and botanicals, warm golden tones, spa aesthetic"),
    (["筋力", "ウォーキング", "階段", "ストレッチ", "歩"],
     "serene morning park path, sunlight through green trees, healthy lifestyle"),
    (["疲労", "疲れ", "だるい"],
     "calming chamomile herbal tea on wooden table, warm cozy lighting"),
    (["認知", "物忘れ", "脳", "頭"],
     "ginkgo biloba leaves autumn golden colors, brain health concept, soft light"),
    (["ストレス", "メンタル", "孤独"],
     "zen meditation bamboo garden, peaceful japanese atmosphere, soft morning light"),
    (["骨", "筋"],
     "calcium rich foods milk cheese, clean kitchen, health and strength concept"),
    (["肝臓"],
     "green detox vegetables and herbs, fresh juice, natural health concept"),
    (["免疫", "花粉"],
     "citrus fruits and vitamin C concept, fresh herbs, clean white background"),
    (["日光", "太陽"],
     "golden morning sunlight through forest trees, nature wellness, bright warm tones"),
    (["水", "炭酸"],
     "clear pure water splash on blue background, refreshing health concept"),
]
_DEFAULT_PROMPT = (
    "serene japanese wellness background, green nature, soft sunlight, "
    "health concept, calm atmosphere"
)
_STYLE_SUFFIX = (
    "cinematic background photography, no text, no people, no characters, "
    "soft focus bokeh, 4k quality, wellness aesthetic"
)

# ── アニメ調ボカシ背景（動画メイン背景用）────────────────────────
# テーマカテゴリ → アニメ調ボカシ背景プロンプト
# 共通要素: animation-style illustration, soft bokeh blur, no characters, no text
_ANIME_BG_COMMON = (
    "animation-style illustration, soft bokeh blur depth of field, "
    "warm soft lighting, no characters, no people, no text, no watermarks, "
    "1920x1080 widescreen"
)
_ANIME_BG_MAP = [
    # 歯・口腔ケア → 清潔感のあるバスルーム
    (["歯", "歯みがき", "歯磨き", "歯周病", "フロス", "口腔", "虫歯", "歯茎", "口臭", "歯科"],
     "a clean anime-style Japanese bathroom interior, bright white tiles, "
     "soft natural window light, toothbrush holder on sink edge, "
     "fresh mint-white color palette"),
    # 食事・栄養・腸 → 温かいキッチン
    (["食事", "食べ", "栄養", "腸", "消化", "胃", "発酵", "ヨーグルト",
      "納豆", "腸活", "野菜", "果物", "魚", "肉", "料理"],
     "a cozy anime-style Japanese kitchen interior, warm morning light, "
     "wooden counter with fresh vegetables, steam rising from pot, "
     "warm amber and cream color palette"),
    # 睡眠・リラックス → 寝室
    (["睡眠", "眠れ", "目が覚", "いびき", "夜", "不眠", "疲労", "疲れ", "だるい"],
     "a peaceful anime-style Japanese bedroom at night, soft moonlight "
     "through sheer curtains, warm bedside lamp glow, "
     "calming blue-purple and warm cream color palette"),
    # 運動・ダイエット → 朝の和室/リビング
    (["運動", "ウォーキング", "散歩", "ジョギング", "筋力", "体操",
      "ストレッチ", "ダイエット", "体重", "肥満"],
     "a bright anime-style Japanese living room, morning sunlight streaming "
     "through large windows, yoga mat on wooden floor, "
     "fresh green and white color palette"),
    # メンタル・ストレス → 縁側・茶室
    (["ストレス", "メンタル", "心", "孤独", "うつ", "呼吸", "瞑想",
      "リラックス", "自律神経"],
     "a serene anime-style Japanese tea room, tatami floor, "
     "zen garden visible through sliding doors, afternoon sunlight, "
     "peaceful warm golden and green color palette"),
    # 医療・血液 → 明るい和室
    (["血圧", "血糖", "コレステロール", "心臓", "血管", "糖尿病",
      "検査", "健診", "医師", "病院"],
     "a bright and clean anime-style Japanese room, white walls, "
     "soft diffused light, simple wooden furniture, "
     "clean white and light blue color palette"),
    # 老化・美容・肌
    (["老化", "白髪", "抜け毛", "若く", "肌", "美容", "アンチエイジング"],
     "a cozy anime-style Japanese dressing room, warm vanity mirror lights, "
     "elegant wooden dresser with plants, "
     "soft rose gold and cream color palette"),
    # 認知・脳・頭
    (["認知", "物忘れ", "脳", "頭", "記憶"],
     "a peaceful anime-style Japanese study room, bookshelves, "
     "warm desk lamp light, autumn leaves outside window, "
     "warm amber and deep green color palette"),
]
# デフォルト（一般的な健康テーマ）
_ANIME_BG_DEFAULT = (
    "a cozy anime-style Japanese tatami room interior, low wooden table, "
    "sliding shoji doors with soft light, small indoor plant, "
    "warm color palette with cream and natural wood tones"
)


def _build_anime_bg_prompt(theme: str) -> str:
    """
    テーマからアニメ調ボカシ背景の英語プロンプトを生成する。
    LLM呼び出しなし（静的テーブルマッチング）。
    """
    for keywords, scene in _ANIME_BG_MAP:
        if any(kw in theme for kw in keywords):
            return f"{scene}, {_ANIME_BG_COMMON}"
    return f"{_ANIME_BG_DEFAULT}, {_ANIME_BG_COMMON}"


def _build_anime_bg_prompt_llm(theme: str) -> str:
    """
    LLMを使ってテーマに合ったアニメ調背景プロンプトを生成する。
    静的テーブルと違い、テーマの具体的な内容（食材・症状等）を反映できる。
    失敗時は静的テーブルにフォールバック。
    """
    from google import genai
    from secrets import get_secret

    api_key = get_secret("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    request = f"""You are an expert at crafting image generation prompts for AI image models.

Generate an anime-style background illustration prompt for a Japanese health YouTube video.

Japanese theme: {theme}

## Requirements:
- Anime-style illustration (アニメ調) with soft bokeh blur
- A specific Japanese interior scene (kitchen, bedroom, living room, study, etc.) that fits the health topic
- Include 2-3 specific objects/props directly related to the health topic (e.g. for "blood sugar foods": wooden table with broccoli, cinnamon sticks, berries in bowls)
- Specify a color palette (2-3 colors that match the mood)
- NO characters, people, faces, text, watermarks, logos
- Warm, inviting, cozy atmosphere

## Output format:
Output the English prompt text only. No explanation. 50-70 words max.
End with: ", {_ANIME_BG_COMMON}"

## Good example (for theme "納豆を毎日食べると体に起きる変化"):
"a cozy anime-style Japanese kitchen interior, morning sunlight, wooden cutting board with fresh soybeans and steaming natto bowl, small ceramic dish with mustard and soy sauce, warm amber and cream color palette, {_ANIME_BG_COMMON}"

Japanese theme: {theme}
"""
    try:
        response = client.models.generate_content(
            model=_PROMPT_BUILD_MODEL, contents=request
        )
        result = response.text.strip().strip('"').strip("'")
        # _ANIME_BG_COMMON が含まれていなければ付加する
        if _ANIME_BG_COMMON not in result:
            result = f"{result}, {_ANIME_BG_COMMON}"
        return result
    except Exception as e:
        print(f"  [!] アニメ背景プロンプトLLM生成失敗 → 静的テーブルにフォールバック: {e}")
        return _build_anime_bg_prompt(theme)


def _build_section_prompt_llm(section_content: str) -> str:
    """
    LLMを使ってセクション内容に合った画像プロンプトを生成する。
    静的テーブルと違い、セリフの具体的な内容（食材・数値・効果）を反映できる。
    失敗時は静的テーブルにフォールバック。
    """
    from google import genai
    from secrets import get_secret

    api_key = get_secret("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    # セクション内容は長い場合があるので300文字に抑える
    content_preview = section_content[:300]

    request = f"""You are an expert at crafting image generation prompts for AI image models.

Generate a photo-realistic lifestyle or health concept image prompt for a Japanese health YouTube video section.

Japanese section content: {content_preview}

## Requirements:
- Photo-realistic style (NOT anime)
- Focus ONLY on the SINGLE main food/drink/activity that is the central subject of the section — ignore other foods briefly mentioned
- PREFER lifestyle scenes: a person's hands holding a cup of tea, someone drinking from a mug, a person preparing healthy food, etc.
  - If showing a person: use only hands, silhouette, or a cozy lifestyle scene — NO close-up faces
- If lifestyle scene is not natural, use a clean close-up of only the main food/drink item
- Specify a color palette (2-3 warm, inviting colors)
- NO close-up faces, no text, no watermarks, no logos
- Clean composition, soft natural light, 16:9 widescreen

## Output format:
Output the English prompt text only. No explanation. 50-70 words max.
End with: ", no faces, no text, soft natural light, 16:9 widescreen, 4k quality"

## Good examples:
- (for green tea content): "Japanese woman's hands wrapping around a warm ceramic green tea cup, steam rising gently, wooden table with scattered dried green tea leaves, soft morning light through window, warm sage green and cream tones, no faces, no text, soft natural light, 16:9 widescreen, 4k quality"
- (for blood pressure content): "A person's hand placing a blood pressure monitor on a wooden table beside a glass of water and fresh vegetables, calm teal and white tones, no faces, no text, soft natural light, 16:9 widescreen, 4k quality"

Japanese section content: {content_preview}
"""
    try:
        response = client.models.generate_content(
            model=_PROMPT_BUILD_MODEL, contents=request
        )
        return response.text.strip().strip('"').strip("'")
    except Exception as e:
        print(f"  [!] セクション画像プロンプトLLM生成失敗 → 静的テーブルにフォールバック: {e}")
        return _build_prompt_static(section_content)


def _build_prompt_static(theme: str) -> str:
    """テーマに合った背景画像プロンプトを静的テーブルから返す（LLM呼び出し不要）"""
    for keywords, desc in _THEME_MAP:
        if any(kw in theme for kw in keywords):
            return f"{desc}, {_STYLE_SUFFIX}"
    return f"{_DEFAULT_PROMPT}, {_STYLE_SUFFIX}"


def _generate_pollinations(
    prompt: str, width: int, height: int, output_path: Path
) -> Path:
    """Pollinations.ai のFLUX APIで画像を生成する（完全無料・APIキー不要）"""
    seed = random.randint(1, 999999)
    encoded = urllib.parse.quote(prompt)
    url = (
        f"https://image.pollinations.ai/prompt/{encoded}"
        f"?width={width}&height={height}&seed={seed}&nologo=true&model=flux"
    )
    print(f"  Pollinations.ai（無料）で背景を生成中... seed={seed}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(url, output_path)
    print(f"  → 背景画像を保存: {output_path.name}")
    return output_path


# ── いらすとや 背景画像 ──────────────────────────────────────────

# テーマキーワード → いらすとや検索語（シーン系の背景画像を狙う）
_IRA_BG_MAP = [
    (["睡眠", "眠れ", "いびき", "夜", "不眠"],         "和室"),
    (["食事", "食べ", "栄養", "腸", "消化", "胃",
      "発酵", "ヨーグルト", "納豆", "腸活"],            "台所"),
    (["運動", "ウォーキング", "散歩", "ジョギング",
      "筋力", "体操", "ストレッチ"],                    "公園"),
    (["ストレス", "メンタル", "心", "孤独", "うつ",
      "呼吸", "瞑想", "リラックス"],                    "自然"),
    (["老化", "アンチエイジング", "若", "肌", "美容"],  "和室"),
    (["医師", "病院", "検査", "薬", "治療"],            "病院"),
    (["血圧", "血糖", "コレステロール", "心臓"],        "病院"),
    (["秋", "秋バテ"],                                  "自然"),
    (["冬", "寒"],                                      "和室"),
    (["春", "春バテ", "花粉"],                          "公園"),
    (["夏", "熱中症", "水分"],                          "海"),
    (["温泉", "入浴", "お風呂"],                        "温泉"),
    (["免疫", "風邪", "インフルエンザ"],                "和室"),
]
_IRA_BG_DEFAULT = "和室"


def _generate_irasutoya(
    theme: str, width: int, height: int, output_path: Path
) -> "Path | None":
    """
    いらすとやのシーン系背景画像をテーマに合わせて取得・加工する。
    取得失敗時は None を返す（呼び出し元が Pollinations にフォールバック）。

    処理:
      1. テーマ → 背景キーワード（和室/台所/公園/自然/病院等）
      2. irasutoya_fetcher.fetch() でキャッシュ/ダウンロード
      3. カバーリサイズ → 中央クロップ → ぼかし → 明るさ調整 → 保存
    """
    from PIL import Image, ImageEnhance, ImageFilter

    # 1. テーマに対応する背景キーワードを選ぶ
    bg_kw = _IRA_BG_DEFAULT
    for keywords, kw in _IRA_BG_MAP:
        if any(k in theme for k in keywords):
            bg_kw = kw
            break

    print(f"  いらすとや背景を取得中... キーワード: {bg_kw}")

    # 2. いらすとや画像を取得（キャッシュ優先）
    try:
        from irasutoya_fetcher import fetch as ira_fetch
        images = ira_fetch(bg_kw, max_count=5)
    except Exception as e:
        print(f"  [!] いらすとや取得エラー: {e}")
        return None

    if not images:
        print(f"  いらすとや: {bg_kw} の画像が見つかりません")
        return None

    img_path = random.choice(images)

    # 3. 画像処理
    try:
        img = Image.open(img_path).convert("RGBA")

        # 白背景に合成（透過PNG対応）
        base = Image.new("RGBA", img.size, (255, 255, 255, 255))
        base.paste(img, mask=img.split()[3])
        img = base.convert("RGB")

        # カバーリサイズ（アスペクト比維持で全面を覆う）
        img_ratio = img.width / img.height
        tgt_ratio = width / height
        if img_ratio > tgt_ratio:
            new_h = height
            new_w = int(height * img_ratio)
        else:
            new_w = width
            new_h = int(width / img_ratio)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        # 中央クロップ
        left = (new_w - width) // 2
        top  = (new_h - height) // 2
        img = img.crop((left, top, left + width, top + height))

        # 優しいタッチに: ソフトぼかし + 明るさ微増 + 彩度微減
        img = img.filter(ImageFilter.GaussianBlur(radius=3))
        img = ImageEnhance.Brightness(img).enhance(1.25)
        img = ImageEnhance.Color(img).enhance(0.80)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, "JPEG", quality=90)
        print(f"  → いらすとや背景を保存: {output_path.name} ({bg_kw})")
        return output_path

    except Exception as e:
        print(f"  [!] いらすとや画像処理エラー: {e}")
        return None


# ── ローカル Stable Diffusion（AUTOMATIC1111 WebUI API）─────────

def _generate_local_sd(
    prompt: str, width: int, height: int, output_path: Path
) -> Path:
    """ローカルのStable Diffusion WebUI APIで画像を生成する（GPU必要）"""
    import base64
    import json
    import urllib.request as req
    from PIL import Image

    sd_url = os.getenv("SD_WEBUI_URL", "http://127.0.0.1:7860")
    payload = json.dumps({
        "prompt": prompt,
        "negative_prompt": (
            "text, watermark, logo, nsfw, blurry, low quality, "
            "anime, cartoon, illustration, people, face"
        ),
        "width": width,
        "height": height,
        "steps": 20,
        "cfg_scale": 7,
        "sampler_name": "DPM++ 2M Karras",
    }).encode()

    request = req.Request(
        f"{sd_url}/sdapi/v1/txt2img",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    print(f"  ローカルSD（{sd_url}）で背景を生成中...")
    with req.urlopen(request, timeout=120) as resp:
        result = json.loads(resp.read())

    img_data = base64.b64decode(result["images"][0])
    img = Image.open(io.BytesIO(img_data))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path)
    print(f"  → 背景画像を保存: {output_path.name}")
    return output_path


# ── サムネイル背景画像（3枚生成→AI選定）────────────────────────


def _build_thumbnail_bg_prompt(theme: str, youtube_title: str, script: dict) -> str:
    """台本の内容からサムネ背景用のフォトリアル画像プロンプトを生成する。

    Gemini Proがテーマ・台本内容を分析し、YouTubeでクリックしたくなる
    フォトリアルな人物入り背景画像のプロンプトを生成する。
    """
    from google import genai
    from secrets import get_secret

    api_key = get_secret("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    # 台本の冒頭セリフ（内容理解用）
    preview_lines = []
    for sec in script.get("sections", [])[:3]:
        for line in sec.get("lines", [])[:5]:
            preview_lines.append(f'{line.get("character","")}: {line.get("text","")[:50]}')
    script_preview = "\n".join(preview_lines[:10])

    request = f"""You are a YouTube thumbnail image director. Create an English prompt for generating a photo-realistic background image for a Japanese health YouTube thumbnail.

## Video Info
- Theme (Japanese): {theme}
- YouTube Title: {youtube_title}
- Script Preview:
{script_preview}

## Your Task
Generate a prompt for a photo-realistic image that would make viewers CLICK on this thumbnail when browsing YouTube recommendations.

## Rules
1. **MUST include a person** fitting the video content:
   - Decide age, gender, ethnicity based on video content (e.g. health topic for elderly → middle-aged/elderly person)
   - Use diverse, photogenic people (Western, Asian, etc. - your choice based on what fits best)
   - The person's facial expression MUST match the video's emotional tone:
     - Dangerous/warning content → shocked, worried, holding head in disbelief
     - Positive/health benefit content → bright smile, energetic, confident
     - Surprising facts → wide eyes, open mouth, astonished
     - Sad/serious content → concerned, furrowed brows, pensive
   - Person should be in a relevant setting/location

2. **Setting must match video content**:
   - "Stairs vs elevator" → dramatic staircase in beautiful building
   - "Brain damage from bad habits" → office/home setting
   - "Dangerous food" → kitchen or dining setting

3. **Photography style**: Professional editorial/lifestyle photography, high contrast, vivid colors, shallow depth of field, dramatic lighting

4. **Composition**: 16:9 widescreen. Person positioned in the RIGHT THIRD of the frame (X: 60-90% from left). LEFT 60% of frame must be clean/blurred background for text overlay. Person's FACE must be FULLY VISIBLE — facing camera or at 3/4 angle, well-lit, no shadows hiding eyes. NEVER place person in center or left half.

5. **Output**: English only, 60-80 words, prompt text only, no labels or explanations

## Example:
"Professional lifestyle photography, dramatic natural lighting, middle-aged Caucasian woman with shocked expression holding her head in disbelief, facing camera at slight angle, standing in a modern bright kitchen, warm amber and cool blue contrast tones, 16:9 widescreen, shallow depth of field, high contrast editorial style, face clearly visible in right half of frame"
"""
    response = client.models.generate_content(model=_PROMPT_BUILD_MODEL, contents=request)
    return response.text.strip().strip('"').strip("'")


def _generate_imagen_thumbnail_candidates(
    prompt: str, width: int, height: int, output_dir: Path, count: int = 3,
) -> list[Path]:
    """Imagen 4 Fastでサムネ背景候補を複数枚生成する。"""
    from google import genai
    from google.genai import types
    from PIL import Image

    from secrets import get_secret
    api_key = get_secret("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    output_dir.mkdir(parents=True, exist_ok=True)
    candidates = []

    for i in range(count):
        try:
            response = client.models.generate_images(
                model="imagen-4.0-fast-generate-001",
                prompt=prompt,
                config=types.GenerateImagesConfig(
                    number_of_images=1,
                    aspect_ratio="16:9",
                    safety_filter_level="block_low_and_above",
                    person_generation="allow_adult",
                ),
            )
            if response.generated_images:
                img_bytes = response.generated_images[0].image.image_bytes
                img = Image.open(io.BytesIO(img_bytes))
                img = img.resize((width, height), Image.LANCZOS)
                path = output_dir / f"thumb_bg_candidate_{i}.jpg"
                img.convert("RGB").save(path, "JPEG", quality=95)
                candidates.append(path)
                print(f"    候補{i+1}/{count} 生成完了")
        except Exception as e:
            print(f"    候補{i+1}/{count} 生成失敗: {e}")

    return candidates


def _ai_select_best_thumbnail_bg(
    candidates: list[Path], theme: str, youtube_title: str,
) -> tuple[Path, int | None]:
    """Gemini Proに3枚の候補画像を見せて最適な1枚を選ばせる。

    戻り値: (選定画像パス, 人物左端X座標 or None)
    """
    if len(candidates) == 1:
        return candidates[0], None

    from google import genai
    from google.genai import types
    from PIL import Image

    from secrets import get_secret
    api_key = get_secret("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    # 画像をGemini Proに渡す
    parts = [
        f"あなたはYouTubeサムネイルの専門家です。\n"
        f"以下の{len(candidates)}枚のサムネイル背景候補画像から、最もクリック率が高くなりそうな1枚を選んでください。\n\n"
        f"動画テーマ: {theme}\n"
        f"YouTubeタイトル: {youtube_title}\n\n"
        f"## 評価基準\n"
        f"1. テーマとの関連性（内容に合っているか）\n"
        f"2. 視覚的インパクト（スマホの小さい画面でも目を引くか）\n"
        f"3. 感情表現（人物の表情が視聴者の興味を引くか）\n"
        f"4. テキスト配置スペース（左側60%以上にテキストを重ねる余地があるか。人物が左寄りすぎる画像は低評価）\n"
        f"5. 全体の品質（不自然なAI生成感がないか）\n\n"
        f"## 回答形式（厳守）\n"
        f"1行目: 選んだ候補番号（1, 2, または 3）\n"
        f"2行目: 選んだ画像内の人物の顔・体の左端がキャンバス左端から何ピクセルの位置にあるか（画像幅は1280px）\n\n"
        f"例:\n2\n850"
    ]

    image_parts = []
    for i, path in enumerate(candidates):
        img = Image.open(path)
        image_parts.append(f"\n--- 候補{i+1} ---")
        image_parts.append(img)

    face_left_x = None
    try:
        response = client.models.generate_content(
            model=_PROMPT_BUILD_MODEL,
            contents=[parts[0]] + [item for p in zip(image_parts[::2], image_parts[1::2]) for item in p],
        )
        answer = response.text.strip()
        # 回答をパース: 1行目=候補番号、2行目=人物左端X座標
        lines = [ln.strip() for ln in answer.splitlines() if ln.strip()]
        chosen_idx = None
        for ch in (lines[0] if lines else ""):
            if ch.isdigit():
                idx = int(ch) - 1
                if 0 <= idx < len(candidates):
                    chosen_idx = idx
                    break
        # 2行目から人物左端X座標を取得
        if len(lines) >= 2:
            import re
            _nums = re.findall(r'\d+', lines[1])
            if _nums:
                _fx = int(_nums[0])
                if 0 < _fx < 1280:
                    face_left_x = _fx
                    print(f"    人物左端X: {face_left_x}px")

        if chosen_idx is not None:
            print(f"    AI選定: 候補{chosen_idx+1}を選択")
            return candidates[chosen_idx], face_left_x
    except Exception as e:
        print(f"    AI選定失敗: {e}")

    # フォールバック: 最初の画像
    print(f"    フォールバック: 候補1を使用")
    return candidates[0], None


def generate_thumbnail_background(
    theme: str,
    youtube_title: str,
    script: dict,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
) -> "Path | None":
    """サムネイル用の背景画像を生成する。

    1. Gemini Proが台本内容からプロンプトを生成
    2. Imagen 4 Fastで3枚生成
    3. Gemini Proが最適な1枚を選定

    Args:
        theme: 動画テーマ（日本語）
        youtube_title: YouTubeタイトル
        script: 台本JSON
        output_path: 保存先パス
        width: 画像幅
        height: 画像高さ

    Returns:
        保存したファイルのパス。失敗時は None。
    """
    print(f"  サムネ背景画像を生成しています [Imagen 4 Fast × 3枚 → AI選定]")

    try:
        # Step 1: プロンプト生成
        prompt = _build_thumbnail_bg_prompt(theme, youtube_title, script)
        print(f"    プロンプト: {prompt[:80]}...")

        # Step 2: 3枚生成
        tmp_dir = output_path.parent / "_thumb_bg_candidates"
        candidates = _generate_imagen_thumbnail_candidates(
            prompt, width, height, tmp_dir, count=3,
        )
        if not candidates:
            print(f"    候補画像が1枚も生成できませんでした")
            return None

        # Step 3: AI選定（人物左端X座標も取得）
        best, face_left_x = _ai_select_best_thumbnail_bg(candidates, theme, youtube_title)

        # 選定画像を最終パスにコピー
        import shutil
        output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(best, output_path)
        print(f"  → サムネ背景画像を保存: {output_path.name}")

        # 候補画像を削除
        import shutil as _shutil
        _shutil.rmtree(tmp_dir, ignore_errors=True)

        return output_path, face_left_x

    except Exception as e:
        print(f"  [!] サムネ背景画像生成失敗: {e}")
        return None


# ── Imagen 4 Fast（セクション画像専用）─────────────────────────

def _generate_imagen_fast(
    prompt: str, width: int, height: int, output_path: Path
) -> Path:
    """
    Imagen 4 Fast でセクション画像を生成する。
    モデル: imagen-4.0-fast-generate-001
    コスト: 約$0.02/枚
    プロンプト: 英語のみ（日本語は受け付けない）
    """
    from google import genai
    from google.genai import types
    from PIL import Image

    from secrets import get_secret
    api_key = get_secret("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    print(f"  Imagen 4 Fast でセクション画像を生成しています...")

    response = client.models.generate_images(
        model="imagen-4.0-fast-generate-001",
        prompt=prompt,
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="16:9",
            safety_filter_level="block_low_and_above",
            person_generation="dont_allow",  # 人物不要
        ),
    )

    if not response.generated_images:
        raise ValueError("Imagen 4 Fastから画像が返されませんでした")

    img_bytes = response.generated_images[0].image.image_bytes
    img = Image.open(io.BytesIO(img_bytes))
    img = img.resize((width, height), Image.LANCZOS)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.suffix.lower() in (".jpg", ".jpeg"):
        img.convert("RGB").save(output_path, "JPEG", quality=92)
    else:
        img.save(output_path)

    print(f"  → セクション画像を保存: {output_path.name}")
    return output_path


# ── パブリック API ──────────────────────────────────────────────

def generate_section_image(
    section_content: str,
    output_path: Path,
    width: int = 1280,
    height: int = 720,
) -> "Path | None":
    """
    台本セクションのセリフ内容に合った画像を生成して保存する。

    既にファイルが存在する場合はスキップ（セッション内キャッシュ）。

    Args:
        section_content: セクションの全セリフをつなげたテキスト（日本語）
        output_path: 保存先パス（.jpg 推奨）
        width: 画像幅（デフォルト 1280）
        height: 画像高さ（デフォルト 720）

    Returns:
        保存したファイルのパス。失敗時は None。

    .env 設定:
        SECTION_IMAGE_PROVIDER=imagen      （デフォルト: Imagen 4 Fast）
        SECTION_IMAGE_PROVIDER=gemini      （Gemini画像生成モデル・GEMINI_API_KEY共用）
        SECTION_IMAGE_PROVIDER=pollinations （フォールバック: 無料・APIキー不要）
        SECTION_IMAGE_PROVIDER=off          （セクション画像生成を無効化）
    """
    if _SECTION_PROVIDER == "off":
        return None

    # 既存ファイルがあればスキップ（セッション内再利用）
    if output_path.exists():
        return output_path

    # LLMでセクション内容に合った具体的なプロンプトを生成
    if _SECTION_PROVIDER in ("imagen", "gemini"):
        prompt = _build_section_prompt_llm(section_content)
    else:
        prompt = _build_prompt_static(section_content)

    try:
        if _SECTION_PROVIDER == "imagen":
            return _generate_imagen_fast(prompt, width, height, output_path)
        elif _SECTION_PROVIDER == "gemini":
            return _generate_gemini(prompt, width, height, output_path)
        elif _SECTION_PROVIDER == "pollinations":
            return _generate_pollinations(prompt, width, height, output_path)
        else:
            print(f"  [!] 未対応のSECTION_IMAGE_PROVIDER: {_SECTION_PROVIDER!r}")
            return None
    except Exception as e:
        print(f"  [!] セクション画像生成失敗 ({_SECTION_PROVIDER}): {e}")
        return None


def generate_background(
    theme: str,
    output_path: Path,
    width: int = 1920,
    height: int = 1080,
) -> "Path | None":
    """
    テーマに合った背景画像をAIで生成して保存する。

    Args:
        theme:       動画テーマ（日本語）
        output_path: 保存先パス（.png または .jpg）
        width:       画像幅（デフォルト 1920）
        height:      画像高さ（デフォルト 1080）

    Returns:
        保存したファイルのパス。失敗した場合は None を返す
        （呼び出し元でグラデーション背景にフォールバックする）。

    .env 設定:
        IMAGE_PROVIDER=imagen       （デフォルト: Imagen 4 Fast・アニメ調ボカシ背景）
        IMAGE_PROVIDER=gemini       （Gemini画像生成モデル・LLMプロンプト生成）
        IMAGE_PROVIDER=pollinations （フォールバック: 無料・APIキー不要）
        IMAGE_PROVIDER=local_sd     （ローカルSD: GPU必要）
        GEMINI_IMAGE_MODEL=gemini-3-pro-image-preview  （gemini使用時のモデル名）
    """
    print(f"  背景画像を生成しています [{_PROVIDER}]")

    try:
        if _PROVIDER == "imagen":
            # LLMでテーマに合ったアニメ調背景プロンプトを生成（静的テーブルより具体的）
            prompt = _build_anime_bg_prompt_llm(theme)
            print(f"  背景プロンプト: {prompt[:70]}...")
            return _generate_imagen_fast(prompt, width, height, output_path)

        elif _PROVIDER == "irasutoya":
            # いらすとやシーン背景（失敗時はPollinationsにフォールバック）
            result = _generate_irasutoya(theme, width, height, output_path)
            if result:
                return result
            print("  いらすとや取得失敗 → Pollinationsにフォールバック")
            prompt = _build_prompt_static(theme)
            return _generate_pollinations(prompt, width, height, output_path)

        elif _PROVIDER == "gemini":
            # Step1: テーマ → 英語画像プロンプトをLLMで生成
            print(f"  画像プロンプトを生成しています...")
            image_prompt = _build_image_prompt(theme)
            print(f"  プロンプト: {image_prompt[:70]}...")
            # Step2: Gemini画像モデルで生成
            return _generate_gemini(image_prompt, width, height, output_path)

        elif _PROVIDER == "pollinations":
            prompt = _build_prompt_static(theme)
            return _generate_pollinations(prompt, width, height, output_path)

        elif _PROVIDER == "local_sd":
            prompt = _build_prompt_static(theme)
            return _generate_local_sd(prompt, width, height, output_path)

        else:
            raise ValueError(
                f"未対応のIMAGE_PROVIDER: {_PROVIDER!r}  "
                f"使用可能: gemini, pollinations, local_sd"
            )

    except Exception as e:
        print(f"  [!] 背景画像生成失敗: {e}")
        print(f"  -> グラデーション背景で続行します")
        return None
