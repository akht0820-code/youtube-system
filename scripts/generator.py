# ゆっくり解説動画 台本自動生成システム

import json
import random
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from google import genai

from characters import get_character_names
from prompts import (
    build_description_prompt,
    build_script_prompt,
    build_script_prompt_with_suggestions,
    build_structure_prompt,
    build_tags_prompt,
    build_title_prompt,
)
from analyzer import load_suggestions
import model_config
from notifier import notify_error, notify_start, notify_success
from secrets import get_secret
from thumbnail_maker import make_thumbnail
from tts import ensure_voicevox, generate_audio_from_script
from video_builder import build_video
from youtube_uploader import _parse_publish_at, get_video_url, upload_video

try:
    client = genai.Client(api_key=get_secret("GEMINI_API_KEY"))
except RuntimeError as e:
    print(f"エラー: {e}")
    sys.exit(1)

OUTPUT_DIR = Path(__file__).parent.parent / "output"


def extract_json(text: str) -> dict:
    """Geminiの応答からJSONを抽出してパースする"""
    # コードブロックを除去
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*", "", text)
    text = text.strip()
    return json.loads(text)


def generate_title(theme: str) -> str:
    """テーマからYouTubeタイトルを生成する"""
    print("タイトルを生成しています...")
    prompt = build_title_prompt(theme)
    response = client.models.generate_content(model=model_config.STANDARD, contents=prompt)
    title = response.text.strip().strip("「」")
    print(f"  → {title}")
    return title


def generate_structure(theme: str) -> dict:
    """ステップ1: テーマから動画構成を生成"""
    print(f"構成を考えています...")
    prompt = build_structure_prompt(theme)
    response = client.models.generate_content(model=model_config.STANDARD, contents=prompt)
    structure = extract_json(response.text)
    print(f"  → {len(structure.get('sections', []))} セクション構成が決まりました")
    return structure


def fix_consecutive_speakers(script: dict) -> tuple[dict, int]:
    """同じキャラクターが連続して発言している箇所を修正する"""
    all_names = get_character_names()
    fixed_count = 0

    for section in script.get("sections", []):
        lines = section.get("lines", [])
        i = 1
        while i < len(lines):
            if lines[i]["character"] == lines[i - 1]["character"]:
                # 前後で使われていないキャラを選んで差し込む
                used = {lines[i - 1]["character"]}
                if i + 1 < len(lines):
                    used.add(lines[i + 1]["character"])
                candidates = [n for n in all_names if n not in used]
                if not candidates:
                    candidates = [n for n in all_names if n != lines[i - 1]["character"]]

                # 直後の行のキャラを別のキャラに差し替える
                lines[i]["character"] = random.choice(candidates)
                fixed_count += 1
            i += 1

    return script, fixed_count


def generate_script(theme: str, structure: dict) -> dict:
    """ステップ2: 構成から台本を生成（改善提案があれば反映）"""
    print("台本を生成しています...")
    suggestions = load_suggestions()
    if suggestions.get("suggestions"):
        print(f"  → 改善提案 {len(suggestions['suggestions'])} 件を反映します")
        prompt = build_script_prompt_with_suggestions(theme, structure, suggestions)
    else:
        prompt = build_script_prompt(theme, structure)
    response = client.models.generate_content(model=model_config.QUALITY, contents=prompt)
    script = extract_json(response.text)

    total_lines = sum(len(s.get("lines", [])) for s in script.get("sections", []))
    print(f"  → {total_lines} 行の台本が生成されました")

    # 連続発言の修正
    script, fixed_count = fix_consecutive_speakers(script)
    if fixed_count > 0:
        print(f"  → 連続発言を {fixed_count} 箇所修正しました")

    return script


def save_script(theme: str, script: dict) -> Path:
    """台本をJSONファイルとして保存"""
    OUTPUT_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    # ファイル名に使えない文字を除去
    safe_theme = re.sub(r'[\\/:*?"<>|]', "", theme)[:30]
    filename = f"{timestamp}_{safe_theme}.json"

    output_path = OUTPUT_DIR / filename
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(script, f, ensure_ascii=False, indent=2)

    return output_path


def generate_description(theme: str, title: str, sections: list) -> str:
    """YouTube説明文を生成する"""
    print("説明文を生成しています...")
    prompt = build_description_prompt(theme, title, sections)
    response = client.models.generate_content(model=model_config.SIMPLE, contents=prompt)
    return response.text.strip()


def generate_tags(theme: str, title: str) -> list[str]:
    """YouTubeタグを生成する"""
    print("タグを生成しています...")
    prompt = build_tags_prompt(theme, title)
    response = client.models.generate_content(model=model_config.SIMPLE, contents=prompt)
    return extract_json(response.text)


def _pick_theme_from_file() -> str:
    """themes.txt からランダムにテーマを1つ選ぶ"""
    themes_path = Path(__file__).parent.parent / "themes.txt"
    if not themes_path.exists():
        raise FileNotFoundError("themes.txt が見つかりません")
    lines = [l.strip() for l in themes_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        raise ValueError("themes.txt にテーマが入っていません")
    import random
    return random.choice(lines)


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--auto",          action="store_true", help="自動実行モード（対話なし・自動アップロード）")
    parser.add_argument("--theme",         type=str, default="", help="テーマを直接指定")
    parser.add_argument("--publish-hours", type=int, default=0,  help="N時間後に予約投稿（0=即公開）")
    parser.add_argument("--no-upload",     action="store_true",  help="アップロードをスキップ")
    args = parser.parse_args()

    print("=== ゆっくり解説動画 台本生成システム ===\n")

    if args.theme:
        theme = args.theme
    elif args.auto:
        theme = _pick_theme_from_file()
        print(f"本日のテーマ: 「{theme}」")
    else:
        theme = input("テーマを入力してください: ").strip()

    if not theme:
        print("エラー: テーマが入力されていません")
        sys.exit(1)

    print(f"\nテーマ: 「{theme}」\n")
    notify_start(theme)

    youtube_title  = ""
    output_path    = None
    thumbnail_path = None
    video_path     = None
    url            = ""
    _t0 = time.perf_counter()

    def _elapsed():
        return f"{time.perf_counter() - _t0:.0f}s"

    # ── フェーズ1: タイトル + 構成を並列生成 ─────────────
    # 互いに独立しているので同時に投げる
    print("【フェーズ1】タイトル・構成を並列生成しています...")
    structure = None
    with ThreadPoolExecutor(max_workers=2) as ex:
        ft = ex.submit(generate_title, theme)
        fs = ex.submit(generate_structure, theme)

        try:
            youtube_title = ft.result()
        except Exception as e:
            notify_error("タイトル生成", e)
            print(f"[エラー] タイトル生成: {e}")
            youtube_title = theme

        try:
            structure = fs.result()
        except Exception as e:
            notify_error("構成生成", e)
            print(f"[エラー] 構成生成: {e} → 処理を中断します")
            sys.exit(1)

    print(f"  → フェーズ1完了 ({_elapsed()})\n")

    # ── フェーズ2: 台本生成（構成が必要なので単独） ──────
    try:
        script = generate_script(theme, structure)
    except Exception as e:
        notify_error("台本生成", e)
        print(f"[エラー] 台本生成: {e} → 処理を中断します")
        sys.exit(1)

    print(f"  → フェーズ2完了 ({_elapsed()})\n")

    # 台本を先に保存してパス情報を確定させる
    try:
        output_path = save_script(theme, script)
        print(f"台本を保存しました: {output_path}")
        safe_theme = re.sub(r'[\\/:*?"<>|]', "", theme)[:30]
        timestamp  = output_path.stem.split("_")[0]
    except Exception as e:
        notify_error("台本保存", e)
        print(f"[エラー] 台本保存: {e} → 処理を中断します")
        sys.exit(1)

    # ── フェーズ3: 説明文 + タグ + サムネイルを並列生成 ──
    # すべて台本・タイトルが揃えば互いに独立して生成できる
    print("\n【フェーズ3】説明文・タグ・サムネイルを並列生成しています...")
    sections       = [{"title": s["section"]} for s in script.get("sections", [])]
    thumbnail_path = OUTPUT_DIR / f"{timestamp}_{safe_theme}_thumbnail.png"
    description    = theme
    tags           = ["ゆっくり解説", "健康"]

    with ThreadPoolExecutor(max_workers=3) as ex:
        fd = ex.submit(generate_description, theme, youtube_title, sections)
        fg = ex.submit(generate_tags, theme, youtube_title)
        fth = ex.submit(make_thumbnail, youtube_title, thumbnail_path)

        try:
            description = fd.result()
        except Exception as e:
            notify_error("説明文生成", e)
            print(f"[エラー] 説明文生成: {e} → 空欄で続行")

        try:
            tags = fg.result()
        except Exception as e:
            notify_error("タグ生成", e)
            print(f"[エラー] タグ生成: {e} → デフォルトタグで続行")

        try:
            fth.result()
            print(f"サムネイルを保存しました: {thumbnail_path}")
        except Exception as e:
            notify_error("サムネイル生成", e)
            print(f"[エラー] サムネイル生成: {e} → スキップして続行")
            thumbnail_path = None

    print(f"  → フェーズ3完了 ({_elapsed()})\n")

    # ── フェーズ4: 音声合成 ───────────────────────────────
    print("【フェーズ4】音声合成・動画生成を開始します...")
    try:
        audio_dir  = OUTPUT_DIR / f"{timestamp}_{safe_theme}"
        video_path = output_path.with_suffix(".mp4")
        print(f"音声を生成しています → {audio_dir}")
        if ensure_voicevox():
            saved = generate_audio_from_script(script, audio_dir)
            print(f"\n{len(saved)} 件の音声ファイルを保存しました ({_elapsed()})\n")
            build_video(script, audio_dir, video_path)
            print(f"  → フェーズ4完了 ({_elapsed()})\n")
        else:
            raise RuntimeError("VOICEVOXに接続できませんでした")
    except Exception as e:
        notify_error("音声・動画生成", e)
        print(f"[エラー] 音声・動画生成: {e} → アップロードをスキップします")
        video_path = None

    # ── ステップ7: YouTubeアップロード ───────────────────
    if args.auto and not args.no_upload:
        do_upload = "y"
    else:
        print("\n" + "=" * 50)
        do_upload = input("YouTubeにアップロードしますか？ [y/N]: ").strip().lower()

    if do_upload == "y" and video_path and video_path.exists():
        try:
            if args.auto and args.publish_hours > 0:
                from datetime import timedelta
                publish_at = datetime.now() + timedelta(hours=args.publish_hours)
            elif args.auto:
                publish_at = None
            else:
                publish_input = input(
                    "予約投稿の日時を入力してください（例: 2026/03/25 18:00）\n"
                    "即公開の場合はEnterを押してください: "
                ).strip()
                publish_at = _parse_publish_at(publish_input) if publish_input else None

            video_id = upload_video(
                video_path=video_path,
                title=youtube_title,
                description=description,
                tags=tags,
                thumbnail_path=thumbnail_path,
                publish_at=publish_at,
            )
            url = get_video_url(video_id)
            if publish_at:
                print(f"\n予約投稿完了！ {publish_at.strftime('%Y/%m/%d %H:%M')} に公開されます")
            else:
                print(f"\n公開完了！")
            print(f"URL: {url}")
            notify_success(theme, url)
        except Exception as e:
            notify_error("YouTubeアップロード", e)
            print(f"[エラー] アップロード: {e}")
    else:
        print("アップロードをスキップしました。")

    print(f"\n=== 処理完了 ===")
    print(f"タイトル  : {youtube_title}")
    if output_path:   print(f"台本      : {output_path}")
    if thumbnail_path: print(f"サムネイル: {thumbnail_path}")
    if video_path:    print(f"動画      : {video_path}")
    if url:           print(f"URL       : {url}")


if __name__ == "__main__":
    main()
