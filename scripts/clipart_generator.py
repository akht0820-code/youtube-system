# clipart_generator.py — Gemini Proでイラストを生成するモジュール
# irasutoya_fetcher.py のドロップイン置換。visual_hintキーワードから
# かわいいフラットイラストを生成し、assets/clipart_gen/ にキャッシュする。

from __future__ import annotations
import hashlib
import io
import os
import re
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

_CACHE_DIR = Path(__file__).parent.parent / "assets" / "clipart_gen"
_IMAGE_MODEL = os.getenv("GEMINI_IMAGE_MODEL", "gemini-3-pro-image-preview")
_PROMPT_MODEL = os.getenv("GEMINI_MODEL_SIMPLE", "gemini-2.5-flash")


def _build_clipart_prompt(visual_hint: str) -> str:
    """visual_hintキーワードから英語のイラスト生成プロンプトを作成する。

    Gemini Flashで日本語→英語変換し、スタイルを固定する。
    LLM失敗時はテンプレートでフォールバック。
    """
    style_suffix = (
        "Japanese anime-style flat illustration, single subject centered on plain white background, "
        "bold black ink outlines, cel-shaded coloring with flat fills and minimal soft shading, "
        "bright clear colors, cute slightly chibi proportions, "
        "clean digital anime art style matching Touhou fan art aesthetic, "
        "no text, no watermark, no background elements, "
        "no UI, no menu, no toolbar, no interface elements, no editor window, no canvas border"
    )
    negative_suffix = (
        "Do NOT produce: photorealistic rendering, smooth airbrushed gradients, "
        "3D rendering, plastic shiny surfaces, watercolor texture, pencil sketch, "
        "stock photo style, dark moody atmosphere, neon colors, western cartoon style, "
        "illustration software interface, editing tool, paint application, software UI, screenshot"
    )

    try:
        from google import genai
        from google.genai import types
        from secrets import get_secret

        api_key = get_secret("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)

        system_prompt = (
            "You convert Japanese keywords into English image generation prompts. "
            "Output ONLY the English prompt (30-50 words). "
            "Describe the main subject concretely and visually. "
            "Do not include style instructions - just describe what to draw."
        )

        response = client.models.generate_content(
            model=_PROMPT_MODEL,
            contents=f"Japanese keyword: {visual_hint}",
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=0.3,
            ),
        )
        subject_desc = response.text.strip()
        return f"{subject_desc}. {style_suffix}. {negative_suffix}"

    except Exception as e:
        print(f"  プロンプト生成フォールバック: {e}")
        return f"cute simple illustration of {visual_hint}, {style_suffix}. {negative_suffix}"


def _generate_clipart_gemini(prompt: str, output_path: Path) -> Path:
    """Gemini Pro画像生成モデルでイラストを生成する。"""
    from google import genai
    from google.genai import types
    from PIL import Image
    from secrets import get_secret

    api_key = get_secret("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=_IMAGE_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_modalities=["IMAGE"],
        ),
    )

    image_data = None
    for part in response.candidates[0].content.parts:
        if hasattr(part, "inline_data") and part.inline_data is not None:
            image_data = part.inline_data.data
            break

    if not image_data:
        raise ValueError(f"Gemini APIから画像データが返されませんでした（{_IMAGE_MODEL}）")

    img = Image.open(io.BytesIO(image_data))
    # クロップなし（正方形のまま保存）。video_builderのパネルローダーがリサイズする
    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "PNG")
    return output_path


def _generate_clipart_imagen(prompt: str, output_path: Path) -> Path:
    """Imagen 4 Fast（1:1アスペクト比）でフォールバック生成する。"""
    from google import genai
    from google.genai import types
    from secrets import get_secret

    api_key = get_secret("GEMINI_API_KEY")
    client = genai.Client(api_key=api_key)

    response = client.models.generate_images(
        model="imagen-4.0-fast-generate-001",
        prompt=prompt + ", illustration style, clipart, white background",
        config=types.GenerateImagesConfig(
            number_of_images=1,
            aspect_ratio="1:1",
            safety_filter_level="block_low_and_above",
            person_generation="allow_adult",
        ),
    )

    img_bytes = response.generated_images[0].image.image_bytes
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(img_bytes)
    return output_path


def _make_cache_path(keyword: str) -> Path:
    """キーワードからキャッシュディレクトリパスを作成する。"""
    safe = re.sub(r"[^\w\-]", "_", keyword)[:30]
    return _CACHE_DIR / safe


def _validate_clipart(image_path: Path) -> bool:
    """生成画像にUI要素やエディタ画面が含まれていないか検証する。

    Returns:
        True: 問題なし, False: UI要素が検出された
    """
    try:
        from google import genai
        from google.genai import types
        from secrets import get_secret
        import base64

        api_key = get_secret("GEMINI_API_KEY")
        client = genai.Client(api_key=api_key)

        img_bytes = image_path.read_bytes()
        img_b64 = base64.b64encode(img_bytes).decode()

        response = client.models.generate_content(
            model=_PROMPT_MODEL,
            contents=[
                types.Part.from_bytes(data=img_bytes, mime_type="image/png"),
                "Does this image contain any software UI elements, editor windows, toolbars, "
                "menus, canvas borders, or application interfaces? "
                "Answer ONLY 'YES' or 'NO'.",
            ],
            config=types.GenerateContentConfig(temperature=0.0),
        )
        answer = response.text.strip().upper()
        if "YES" in answer:
            print(f"  [品質チェック] UI要素を検出: {image_path.name}")
            return False
        return True
    except Exception as e:
        print(f"  [品質チェック] 検証スキップ: {e}")
        return True  # 検証失敗時は通過させる


def fetch(keyword: str, max_count: int = 1) -> list[Path]:
    """キーワードからイラストを生成して返す。irasutoya_fetcher.fetch()と同じシグネチャ。

    フォールバック: Gemini Pro → Imagen 4 → irasutoya
    """
    if not keyword or not keyword.strip():
        return []

    cache_dir = _make_cache_path(keyword)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # キャッシュ確認
    cached = sorted(cache_dir.glob("*.png"))
    if cached:
        return cached[:max_count]

    # プロンプト生成
    prompt = _build_clipart_prompt(keyword)
    output_path = cache_dir / "001.png"

    # Gemini Pro で生成（UI検出時は最大2回リトライ）
    _MAX_VALIDATION_RETRIES = 2
    for _attempt in range(_MAX_VALIDATION_RETRIES + 1):
        try:
            print(f"  Gemini Pro でイラスト生成: {keyword}" + (f" (リトライ{_attempt})" if _attempt > 0 else ""))
            _generate_clipart_gemini(prompt, output_path)
            if _validate_clipart(output_path):
                print(f"  → {output_path.name}")
                return [output_path]
            # バリデーション失敗: リトライ前にファイル削除
            output_path.unlink(missing_ok=True)
        except Exception as e:
            print(f"  Gemini Pro失敗: {e}")
            break  # 生成自体が失敗したらリトライせずフォールバックへ

    # Imagen 4 フォールバック
    try:
        print(f"  Imagen 4 でイラスト生成: {keyword}")
        _generate_clipart_imagen(prompt, output_path)
        print(f"  → {output_path.name}")
        return [output_path]
    except Exception as e:
        print(f"  Imagen 4失敗: {e}")

    # いらすとやフォールバック
    try:
        from irasutoya_fetcher import fetch as ira_fetch
        print(f"  いらすとやフォールバック: {keyword}")
        return ira_fetch(keyword, max_count=max_count)
    except Exception as e:
        print(f"  いらすとやも失敗: {e}")

    return []


def prefetch_for_lines(lines: list[dict],
                       section_breaks: "list[int] | None" = None) -> dict[int, "Path | None"]:
    """台本の全セリフに対してイラスト画像を事前取得する。

    irasutoya_fetcher.prefetch_for_lines()と同じシグネチャ・同じロジック。
    visual_hintがあればそれを優先し、話題が変わったタイミングでのみ画像を切り替える。
    """
    _MIN_HOLD_LINES = 3
    _section_set = set(section_breaks or [])

    result: dict[int, "Path | None"] = {}
    cur_img: "Path | None" = None
    cur_kw = ""
    lines_since_change = 0
    used_imgs: set[str] = set()

    for i, line in enumerate(lines):
        # キーワード抽出（visual_hint優先）
        hint = (line.get("visual_hint") or "").strip()
        if hint:
            kw = hint
        else:
            # visual_hintなし: テキストからキーワード抽出
            # irasutoya_fetcherの_extract_keywordsを借りる
            try:
                from irasutoya_fetcher import _extract_keywords
                text = line.get("text", "")
                keywords = _extract_keywords(text)
                kw = keywords[0] if keywords else ""
            except ImportError:
                kw = ""

        is_section_break = i in _section_set
        kw_changed = kw and kw != cur_kw
        held_enough = lines_since_change >= _MIN_HOLD_LINES

        should_change = False
        if is_section_break and kw:
            should_change = True
        elif kw_changed and held_enough:
            should_change = True

        if should_change:
            imgs = fetch(kw, max_count=2)
            if imgs:
                new_img = None
                for img in imgs:
                    if str(img) not in used_imgs:
                        new_img = img
                        break
                if new_img is None:
                    new_img = imgs[0]
                cur_img = new_img
                cur_kw = kw
                used_imgs.add(str(cur_img))
                lines_since_change = 0

        result[i] = cur_img
        lines_since_change += 1

    return result


if __name__ == "__main__":
    import sys
    kw = sys.argv[1] if len(sys.argv) > 1 else "バナナ"
    print(f"生成: {kw}")
    paths = fetch(kw, max_count=1)
    for p in paths:
        print(f"  {p} ({p.stat().st_size} bytes)")
