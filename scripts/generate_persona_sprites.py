# generate_persona_sprites.py
# fal.ai FLUX + IP-Adapter を使ってキャラクターの表情・ポーズバリエーションを生成する
#
# 使い方:
#   python scripts/generate_persona_sprites.py
#
# 生成物: assets/characters/persona_{marisa|reimu}_{pose}.png

from __future__ import annotations
import base64
import io
import os
import sys
import time
from pathlib import Path

import keyring
import fal_client
from PIL import Image

# ── 設定 ─────────────────────────────────────────────────────────────────────
ASSETS_DIR  = Path(__file__).resolve().parent.parent / "assets" / "characters"
OUTPUT_DIR  = ASSETS_DIR  # 同じディレクトリに保存

# キャラクター外見を保持しながらポーズを変えるモデル
MODEL = "fal-ai/instant-character"

# ── キャラクター定義 ──────────────────────────────────────────────────────────
CHARACTERS = {
    "marisa": {
        "base_image": ASSETS_DIR / "persona_marisa_base.png",
        "base_prompt": (
            "anime girl, witch hat with white bow, black and white outfit, "
            "blonde hair in braid, red bow tie, golden eyes, cute, "
            "touhou style, upper body, white background, "
            "high quality, detailed illustration"
        ),
        # 魔理沙: ツッコミ役・知識豊富・少しキツめ・頼れる
        "poses": {
            # ── 定番ツッコミ系 ──
            "arms_crossed": (
                "arms crossed over chest, smug confident expression, "
                "slight knowing smile, looking at viewer"
            ),
            "tsukkomi_point": (
                "one finger pointing forward accusingly, other hand on hip, "
                "exasperated expression, eyebrows raised, mouth open as if saying 'oi oi'"
            ),
            "facepalm": (
                "one hand covering face in exasperation, other arm at side, "
                "clearly tired of the situation, sighing expression"
            ),
            "head_shake": (
                "shaking head slightly, hand raised in dismissal, "
                "disappointed but fond expression, closed eyes, slight frown"
            ),
            "one_eyebrow_raised": (
                "arms crossed, one eyebrow raised skeptically, "
                "side-eye look, unimpressed smirk, looking sideways"
            ),
            # ── 解説・講義系 ──
            "explaining": (
                "index finger raised pointing up, other hand on hip, "
                "confident lecturing expression, slight proud smile"
            ),
            "lecture_serious": (
                "both hands gesturing forward as if presenting facts, "
                "serious focused expression, leaning slightly forward"
            ),
            "proud_explain": (
                "arms open wide as if presenting something impressive, "
                "proud confident smile, chest out, looking at viewer"
            ),
            "thinking": (
                "hand on chin, thoughtful expression, eyes looking up slightly, "
                "calm analytical pose"
            ),
            # ── 感情系 ──
            "surprised_good": (
                "eyes wide open in pleasant surprise, mouth open slightly, "
                "one hand raised, eyebrows up, genuinely impressed expression"
            ),
            "smug_grin": (
                "arms crossed, wide smug grin, eyes narrowed confidently, "
                "self-satisfied expression, head tilted slightly"
            ),
            "excited_discovery": (
                "leaning forward enthusiastically, both hands gesturing, "
                "bright excited eyes, open smile, sharing exciting information"
            ),
            "stern": (
                "arms at sides, stern serious face, direct eye contact, "
                "slightly furrowed brows, authoritative stance"
            ),
            "disappointed": (
                "arms crossed, disappointed frown, looking to the side, "
                "shaking head slightly, clearly unimpressed"
            ),
            "disbelief": (
                "hand on hip, other hand raised in disbelief, "
                "open mouth, wide eyes, looking shocked at something absurd"
            ),
            "tired_sigh": (
                "one hand on hip, other rubbing temple, tired expression, "
                "eyes slightly closed, worn out but amused sigh"
            ),
            "gentle_smile": (
                "arms relaxed at sides, warm gentle smile, soft eyes, "
                "kind approachable expression, looking at viewer warmly"
            ),
            "concerned": (
                "leaning slightly forward, worried furrowed brows, "
                "one hand partially raised in concern, genuine worried look"
            ),
            "impressed": (
                "arms crossed, nodding with impressed expression, "
                "raised eyebrows in approval, slight admiring smile"
            ),
            "wink": (
                "one eye winking playfully, finger gun gesture or v-sign, "
                "confident playful grin, cocky but charming"
            ),
            "angry_lecture": (
                "hands on hips, clearly agitated, brows furrowed deeply, "
                "leaning forward with intensity, scolding expression"
            ),
            "relieved": (
                "hand on chest in relief, eyes slightly closed, "
                "relieved exhale expression, small smile"
            ),
        },
    },
    "reimu": {
        "base_image": ASSETS_DIR / "persona_reimu_base.png",
        "base_prompt": (
            "anime girl, red hair bow ribbon, red and white miko outfit, "
            "brown hair, red eyes, cute, touhou style, upper body, "
            "white background, high quality, detailed illustration"
        ),
        # 霊夢: ボケ役・天然・おっちょこちょい・感情豊か・視聴者代表
        "poses": {
            # ── 定番ボケ・驚き系 ──
            "surprised_hands": (
                "both hands raised to mouth in surprise, wide eyes, "
                "shocked open mouth, eyebrows raised very high"
            ),
            "shocked_dramatic": (
                "hands on both cheeks, mouth wide open, eyes extremely wide, "
                "dramatically shocked expression, leaning back slightly"
            ),
            "jaw_drop": (
                "mouth hanging open in disbelief, eyes wide, "
                "both hands slightly raised, completely stunned look"
            ),
            "gasping": (
                "one hand over mouth gasping, other hand in front, "
                "eyes wide with realization, 'I didn't know that!' expression"
            ),
            # ── 天然・困惑系 ──
            "confused": (
                "head tilted to side, one finger on cheek, "
                "genuinely puzzled expression, big question mark energy"
            ),
            "thinking_hard": (
                "both hands on cheeks, eyes squeezed thinking hard, "
                "working very hard to understand, cute confused look"
            ),
            "clueless_smile": (
                "innocent wide smile, eyes slightly squinted happily, "
                "clearly has no idea what's happening, cheerful ignorance"
            ),
            "wrong_idea": (
                "confident pose with one finger raised, bright smile, "
                "completely wrong but certain expression, proudly mistaken"
            ),
            # ── 感情豊か系 ──
            "happy": (
                "arms slightly open, big happy smile, eyes curved upward, "
                "genuinely cheerful, pure joy expression"
            ),
            "excited_jump": (
                "both fists raised in excitement, big open smile, "
                "energetic bouncing energy, sparkling happy eyes"
            ),
            "delighted": (
                "hands clasped together in front of chest, bright smile, "
                "eyes sparkling, genuinely pleased and happy expression"
            ),
            "embarrassed": (
                "hands on cheeks, rosy blush, embarrassed smile, "
                "looking slightly away, adorably flustered"
            ),
            "crying_moved": (
                "tears in eyes, moved expression, hands clasped at chest, "
                "touched and emotional, happy crying"
            ),
            "scared": (
                "arms held close to body, wide scared eyes, "
                "leaning back slightly, nervous frightened expression"
            ),
            # ── 共感・リアクション系 ──
            "realization": (
                "sudden realization expression, one fist hitting palm, "
                "eyes lit up, open mouth in aha moment"
            ),
            "nodding": (
                "nodding enthusiastically, agreeing expression, "
                "both hands raised slightly, 'I see!' expression"
            ),
            "worried": (
                "hands clasped tightly, worried eyebrows, "
                "lips pressed together in concern, anxious look"
            ),
            "pouting": (
                "cheeks puffed out slightly, small pout, arms crossed loosely, "
                "mildly annoyed but cute expression"
            ),
            "sheepish_sorry": (
                "hand on back of head sheepishly, nervous smile, "
                "looking slightly away, apologetic expression"
            ),
            "determined": (
                "fist raised in front, determined expression, "
                "motivated energetic look, 'I'll try it!' expression"
            ),
            "relieved": (
                "hand on chest, eyes closed in relief, "
                "soft relieved smile, 'thank goodness' expression"
            ),
            "curious_lean": (
                "leaning forward slightly, curious bright eyes, "
                "one finger to lips, genuinely interested and attentive"
            ),
        },
    },
}

# ── ヘルパー関数 ──────────────────────────────────────────────────────────────

def get_api_key() -> str:
    key = keyring.get_password("youtube-system", "FAL_API_KEY")
    if not key:
        raise RuntimeError("FAL_API_KEY が登録されていません。setup_secrets.py で登録してください。")
    return key


def image_to_data_url(path: Path) -> str:
    """PNG画像をdata URLに変換（fal.ai API用）"""
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode()
    return f"data:image/png;base64,{data}"


def remove_bg(img: Image.Image, tolerance: int = 35) -> Image.Image:
    """白背景をフラッドフィルで除去して透過PNGにする"""
    from collections import deque
    import numpy as np

    arr = img.convert("RGBA")
    np_arr = __import__("numpy").array(arr).copy()
    h, w = np_arr.shape[:2]
    visited = __import__("numpy").zeros((h, w), dtype=bool)

    corners = [(0, 0), (0, w - 1), (h - 1, 0), (h - 1, w - 1)]
    bg = __import__("numpy").mean([np_arr[r, c, :3] for r, c in corners], axis=0)

    queue = deque(corners)
    for r, c in corners:
        visited[r, c] = True

    while queue:
        r, c = queue.popleft()
        np_arr[r, c, 3] = 0
        for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nr, nc = r + dr, c + dc
            if 0 <= nr < h and 0 <= nc < w and not visited[nr, nc]:
                dist = float(__import__("numpy").sqrt(
                    __import__("numpy").sum((np_arr[nr, nc, :3].astype(float) - bg) ** 2)
                ))
                if dist < tolerance:
                    visited[nr, nc] = True
                    queue.append((nr, nc))

    return Image.fromarray(np_arr, "RGBA")


def generate_pose(
    char_name: str,
    pose_name: str,
    base_image_path: Path,
    base_prompt: str,
    pose_prompt: str,
    output_path: Path,
) -> bool:
    """1ポーズを生成して保存する"""
    print(f"  生成中: {char_name}_{pose_name}...", end=" ", flush=True)

    full_prompt = f"{base_prompt}, {pose_prompt}"
    image_url = image_to_data_url(base_image_path)

    try:
        result = fal_client.subscribe(
            MODEL,
            arguments={
                "image_url": image_url,
                "prompt": full_prompt,
                "negative_prompt": (
                    "bad anatomy, extra fingers, deformed, ugly, low quality, "
                    "blurry, multiple characters, text, watermark, signature"
                ),
                "scale": 1.2,           # キャラクター同一性（0-2、高いほど元キャラに近い）
                "guidance_scale": 5.0,
                "num_inference_steps": 28,
                "num_images": 1,
                "image_size": "portrait_4_3",
                "output_format": "png",
            },
            with_logs=False,
        )

        images = result.get("images", [])
        if not images:
            print("NG (画像なし)")
            return False

        # URLまたはbase64で返ってくる
        img_data = images[0]
        if isinstance(img_data, dict):
            img_url = img_data.get("url", "")
            if img_url.startswith("data:"):
                # base64
                b64 = img_url.split(",", 1)[1]
                img = Image.open(io.BytesIO(base64.b64decode(b64)))
            else:
                import urllib.request
                with urllib.request.urlopen(img_url) as resp:
                    img = Image.open(io.BytesIO(resp.read()))
        else:
            img = Image.open(io.BytesIO(base64.b64decode(img_data)))

        # 背景除去して保存
        img_clean = remove_bg(img.convert("RGBA"))
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img_clean.save(output_path, "PNG")
        print(f"OK → {output_path.name}")
        return True

    except Exception as e:
        print(f"NG ({e})")
        return False


# ── メイン ────────────────────────────────────────────────────────────────────

def main() -> None:
    api_key = get_api_key()
    os.environ["FAL_KEY"] = api_key

    print("=" * 60)
    print("キャラクターペルソナ スプライト生成")
    print(f"モデル: {MODEL}")
    print("=" * 60)

    total = sum(len(c["poses"]) for c in CHARACTERS.values())
    done = 0
    failed = 0

    for char_name, char_cfg in CHARACTERS.items():
        base_img = char_cfg["base_image"]
        if not base_img.exists():
            print(f"[スキップ] ベース画像が見つかりません: {base_img}")
            continue

        print(f"\n【{char_name}】 ({len(char_cfg['poses'])}ポーズ)")
        for pose_name, pose_prompt in char_cfg["poses"].items():
            out_path = OUTPUT_DIR / f"persona_{char_name}_{pose_name}.png"

            # instant-character で全ポーズ再生成（旧ファイルは上書き）

            ok = generate_pose(
                char_name=char_name,
                pose_name=pose_name,
                base_image_path=base_img,
                base_prompt=char_cfg["base_prompt"],
                pose_prompt=pose_prompt,
                output_path=out_path,
            )
            if ok:
                done += 1
            else:
                failed += 1

            time.sleep(1)  # API負荷対策

    print(f"\n完了: {done}/{total} 成功, {failed} 失敗")
    print(f"保存先: {OUTPUT_DIR}")

    # 生成されたファイル一覧
    generated = sorted(OUTPUT_DIR.glob("persona_*.png"))
    print("\n生成済みスプライト:")
    for f in generated:
        size_kb = f.stat().st_size // 1024
        print(f"  {f.name} ({size_kb}KB)")


if __name__ == "__main__":
    main()
