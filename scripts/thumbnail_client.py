# サムネイル生成プロバイダの共通インターフェース
#
# 新しいプロバイダを追加する手順:
#   1. ThumbnailGenerator を継承したクラスを作る（下の実装例を参考に）
#   2. providers.py の get_thumbnail_generator() に elif ブロックを追加する
#   3. .env の THUMBNAIL_PROVIDER を新しいキー名に変更する

from abc import ABC, abstractmethod
from pathlib import Path


class ThumbnailGenerator(ABC):
    """サムネイル生成サービスの共通インターフェース"""

    @abstractmethod
    def generate(self, title: str, output_path: Path,
                 bg_path: "Path | None" = None,
                 narrative_style: "str | None" = None) -> Path:
        """
        サムネイルを生成して output_path に保存し、パスを返す。

        Args:
            title:           動画タイトル（テキストオーバーレイ用）
            output_path:     保存先パス
            bg_path:         AI生成背景画像のパス（省略時はデフォルト背景）
            narrative_style: ナラティブスタイルキー（感情選択に使用）
        """


class LocalThumbnailGenerator(ThumbnailGenerator):
    """PIL/Pillow を使ったローカルサムネイル生成（外部サービス不要）"""

    def generate(self, title: str, output_path: Path,
                 bg_path: "Path | None" = None,
                 narrative_style: "str | None" = None) -> Path:
        from thumbnail_maker import make_thumbnail
        return make_thumbnail(
            title, output_path,
            bg_path=bg_path,
            narrative_style=narrative_style,
        )


# ── 将来の実装例（必要なときにコメントを外して使う）────────────────

# class DalleThumbnailGenerator(ThumbnailGenerator):
#     """OpenAI DALL-E でサムネイル背景画像を生成し、タイトルをオーバーレイする"""
#     def __init__(self, api_key: str):
#         from openai import OpenAI
#         self._client = OpenAI(api_key=api_key)
#
#     def generate(self, title: str, output_path: Path) -> Path:
#         import requests
#         from PIL import Image, ImageDraw
#         from io import BytesIO
#         from font_utils import load_font
#
#         # DALL-E で背景生成
#         prompt = f"YouTube thumbnail background, health topic, clean minimal design, no text, 16:9"
#         response = self._client.images.generate(
#             model="dall-e-3", prompt=prompt, size="1792x1024", quality="standard", n=1,
#         )
#         img_bytes = requests.get(response.data[0].url).content
#         bg = Image.open(BytesIO(img_bytes)).resize((1280, 720))
#
#         # タイトルをオーバーレイ
#         draw = ImageDraw.Draw(bg)
#         font = load_font(80)
#         draw.text((640, 360), title, font=font, fill="white", anchor="mm")
#
#         output_path.parent.mkdir(parents=True, exist_ok=True)
#         bg.save(output_path)
#         return output_path


# class StableDiffusionThumbnailGenerator(ThumbnailGenerator):
#     """Stable Diffusion WebUI API でサムネイルを生成する"""
#     def __init__(self, base_url: str = "http://localhost:7860"):
#         self._url = base_url
#
#     def generate(self, title: str, output_path: Path) -> Path:
#         import requests, base64
#         from PIL import Image
#         from io import BytesIO
#
#         payload = {
#             "prompt": f"youtube thumbnail, health channel, {title}, clean design",
#             "width": 1280, "height": 720, "steps": 20,
#         }
#         response = requests.post(f"{self._url}/sdapi/v1/txt2img", json=payload)
#         img_data = base64.b64decode(response.json()["images"][0])
#         output_path.parent.mkdir(parents=True, exist_ok=True)
#         Image.open(BytesIO(img_data)).save(output_path)
#         return output_path
