# スキル: メタデータ生成（説明文・タグ・サムネイルキャプション・背景画像）

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from skills._common import (
    call_with_retry,
    check_prerequisites,
    ensure_scripts_path,
    get_llm,
    get_script_json,
    load_manifest,
    update_phase,
    SkillLogger,
)

ensure_scripts_path()

import model_config
from prompts import (
    build_description_prompt,
    build_tags_prompt,
    build_thumbnail_caption_prompt,
)
from image_generator import generate_background
from notifier import notify_error
from script_repair import extract_json_safe

# Step 3-δ.5c-3: OUTPUT_DIR module-level 定数は削除 (dead code).
# run_metadata は run_dir.parent を直接参照して bg_path を組み立てる.
# invariant: run_dir.parent == output_dir (generator._create_run_dir で保証).


# ── ヘルパー関数 ──────────────────────────────────────────


def _build_fallback_description(theme: str, title: str, sections: list) -> str:
    """説明文生成失敗・短すぎる場合のフォールバック説明文"""
    sec_lines = "\n".join(f"・{s['title']}" for s in sections[:6])
    return f"""{title}

■本動画について
{theme}について、ゆっくり霊夢・魔理沙がわかりやすく解説します。

■動画の構成
{sec_lines}

■BGM
Hanagoyomi / PeriTune (https://peritune.com/)
Harvest2 / PeriTune (https://peritune.com/)

#ゆっくり解説 #健康 #{theme[:8]}

─────────────────────────
本動画の台本・音声はAI（生成AIツール）を使用して制作しています。
情報の正確性には十分注意していますが、医療・健康に関する判断は必ず専門家にご相談ください。
─────────────────────────"""


# 構造タグ: 行頭の【...】で、中に構造指示語（ブロック/セクション/ステップ等）を含むもの
# 強調用の【腹の脂肪】等は残す
_STRUCT_TAG_RE = re.compile(
    r"^【(?:ブロック|セクション|ステップ|パート|AI生成|注意|補足)[^】]*】[ \t]*\n?",
    re.MULTILINE,
)
# フォールバック: 上記に引っかからないが「:」「（」を含む行頭の【...】も構造タグ
_STRUCT_TAG_FALLBACK_RE = re.compile(
    r"^【[^】]*[:：（(][^】]*】[ \t]*\n?",
    re.MULTILINE,
)


def _sanitize_description(desc: str) -> str:
    """概要欄テキストから内部構造タグを除去し、品質チェックを行う。

    除去対象:
    - 【ブロック1: 導入紹介文（約400字）】等の構造タグ（行頭・構造指示語含む）
    - 【AI生成コンテンツについて】等の見出しタグ
    - ＜導入紹介文＞等のプロンプト由来の指示タグ
    保持対象:
    - 【腹の脂肪】等のインライン強調（行中にあり、構造指示語を含まない）
    """
    # 構造タグを除去（2段階: 明示パターン → フォールバック）
    cleaned = _STRUCT_TAG_RE.sub("", desc)
    cleaned = _STRUCT_TAG_FALLBACK_RE.sub("", cleaned)
    # ＜...＞の指示タグも除去
    cleaned = re.sub(r"＜[^＞]*＞\n?", "", cleaned)
    # 3行以上の連続空行を2行に圧縮
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = cleaned.strip()

    # バリデーション: 導入文の長さチェック
    # 導入文 = ■目次 の前のテキスト（タイムスタンプより前の部分）
    intro_marker = cleaned.find("■目次")
    if intro_marker == -1:
        intro_marker = cleaned.find("■BGM")
    if intro_marker > 0:
        intro_text = cleaned[:intro_marker].strip()
        intro_len = len(intro_text)
        if intro_len > 300:
            print(f"  [!] 導入文が長すぎます({intro_len}字 > 300字上限)")

    # バリデーション: 残存構造タグチェック（行頭の【】で中に:を含むもの）
    remaining = re.findall(r"^【[^】]*[:：][^】]*】", cleaned, re.MULTILINE)
    if remaining:
        print(f"  [!] 構造タグ残存を検出・除去: {remaining}")
        for tag in remaining:
            cleaned = cleaned.replace(tag, "")
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return cleaned


def generate_description(theme: str, title: str, sections: list) -> str:
    """YouTube説明文を生成する"""
    llm = get_llm()
    print("説明文を生成しています...")
    prompt = build_description_prompt(theme, title, sections)
    try:
        desc = call_with_retry(
            llm.generate, prompt, model_config.SIMPLE,
            label="説明文生成"
        ).strip()
        # 構造タグ除去+バリデーション
        desc = _sanitize_description(desc)
        print(f"  -> 説明文生成完了: {len(desc)}文字")
        if len(desc) < 200:
            print(f"  [!] 説明文が短すぎます({len(desc)}文字) -> フォールバックに切り替え")
            return _build_fallback_description(theme, title, sections)
        return desc
    except Exception as e:
        print(f"  -> 説明文生成失敗: {e}")
        return _build_fallback_description(theme, title, sections)


def generate_tags(theme: str, title: str) -> list[str]:
    """YouTubeタグを生成する"""
    llm = get_llm()
    print("タグを生成しています...")
    prompt = build_tags_prompt(theme, title)
    try:
        result = extract_json_safe(call_with_retry(
            llm.generate, prompt, model_config.SIMPLE,
            label="タグ生成"
        ))
        # リスト形式が期待されるが dict で返ることがある場合は中身を取り出す
        if isinstance(result, dict):
            for v in result.values():
                if isinstance(v, list):
                    return v
        return result if isinstance(result, list) else []
    except Exception as e:
        print(f"  → タグ生成失敗: {e}")
        return ["ゆっくり解説", "健康", theme]


def generate_thumbnail_caption(theme: str, title: str) -> str | None:
    """サムネイル画像専用のキャプション（「行1|行2」形式）を生成する。
    タイトルとは異なる短く視覚的に強いテキストをAIが生成する。
    失敗時は None を返す（呼び出し側でタイトル代用）。
    """
    llm = get_llm()
    print("サムネイルキャプションを生成しています...")
    prompt = build_thumbnail_caption_prompt(theme, title)
    try:
        raw = call_with_retry(
            llm.generate, prompt, model_config.SIMPLE,
            label="サムネイルキャプション生成"
        )
        # 「行1|行2」形式の1行のみを期待する
        lines = raw.strip().splitlines()
        if not lines:
            return None
        line = lines[0].strip()
        if not line:
            return None
        # 伏せ字セルフチェック
        line = _check_mask_quality(line, title, llm)
        return line
    except Exception as e:
        print(f"  → サムネイルキャプション生成失敗: {e}")
        return None


def _check_mask_quality(caption: str, title: str, llm) -> str:
    """伏せ字の品質チェック: 推測可能な伏せ字やタイトルとの矛盾を検出・修正する。

    チェック項目:
    1. ●●で隠した単語がタイトルに露出していないか
    2. ●●が文脈から2秒で推測できないか
    3. 推測可能な場合はAIに再生成させる
    """
    if "●" not in caption:
        return caption

    from script_repair import extract_json_safe

    prompt = (
        "あなたはYouTubeサムネイルの専門家です。\n"
        "以下のサムネイルキャプションとタイトルを見て、伏せ字（●●）の品質を判定してください。\n\n"
        f"サムネイル: {caption}\n"
        f"タイトル: {title}\n\n"
        "## チェック項目\n"
        "1. ●●で隠した単語がタイトルに書かれていないか？（タイトルでネタバレ→伏せ字が無意味）\n"
        "2. ●●の前後の文脈から、隠された単語を2秒で推測できないか？\n"
        "   NG例: 「エレ●●をやめたら」→エレベーターと分かる\n"
        "   NG例: 「脳が1●●若返る」→10歳と分かる\n"
        "   NG例: 「●●kg減」→数字は隠しても効果薄\n"
        "3. 主語・動詞・テーマのキーワードが隠されていないか？（隠すべきは答え・原因・方法）\n\n"
        "## 出力形式（JSONのみ・前置き不要）\n"
        '{"ok": true} または {"ok": false, "reason": "理由", "fixed": "修正後キャプション"}\n'
        "修正する場合: ●●を除去するか、位置を変えて答えが分からない形にする。\n"
        "伏せ字なしでも強いキャプションになるなら●●を除去してよい。"
    )

    try:
        raw = llm.generate(prompt, model_config.SIMPLE)
        result = extract_json_safe(raw)
        if isinstance(result, dict):
            if result.get("ok"):
                print(f"  [伏せ字チェック] OK")
                return caption
            fixed = result.get("fixed", "")
            reason = result.get("reason", "")
            if fixed and fixed.strip():
                fixed = fixed.strip()
                # フォーマットバリデーション: キャプション形式か確認
                # - 30文字以下（サムネに収まる長さ）
                # - 「|」区切りなら各パートも短い
                # - 長文説明や文章調のレスポンスは拒否
                parts = fixed.split("|")
                is_valid = (
                    len(fixed) <= 30
                    and all(len(p.strip()) <= 20 for p in parts)
                    and "。" not in fixed  # 文章調は不可
                )
                if is_valid:
                    print(f"  [伏せ字チェック] 修正: {reason}")
                    print(f"    旧: {caption}")
                    print(f"    新: {fixed}")
                    return fixed
                else:
                    # AIが文章調で返した→伏せ字を除去して元キャプションを使う
                    print(f"  [伏せ字チェック] 修正案が不正形式のため伏せ字除去: {fixed[:40]}...")
                    return caption.replace("●●", "").replace("●", "")
            else:
                # 修正案なし→伏せ字を除去
                print(f"  [伏せ字チェック] 伏せ字除去: {reason}")
                return caption.replace("●●", "").replace("●", "")
    except Exception as e:
        print(f"  [伏せ字チェック] スキップ: {e}")

    return caption


# ── メインエントリポイント ──────────────────────────────────


def run_metadata(
    run_dir: str | Path,
    youtube_title: str | None = None,
    structure: dict | None = None,
) -> dict:
    """メタデータ生成スキルを実行する。

    Args:
        run_dir: パイプラインの実行ディレクトリ
        youtube_title: YouTubeタイトル（未指定時は台本JSONから取得）
        structure: 動画構成（未指定時は台本JSONのセクションから構築）

    Returns:
        {"description": str, "tags": list, "thumbnail_caption": str|None, "bg_path": Path|None}
    """
    run_dir = Path(run_dir)
    logger = SkillLogger(run_dir, "metadata")
    update_phase(run_dir, "metadata", "in_progress")

    try:
        # 前提チェック
        if not check_prerequisites(run_dir, "metadata", ["script_gen"]):
            raise RuntimeError("前提フェーズ 'script_gen' が未完了です")

        # 台本JSONを読み込む
        script = get_script_json(run_dir)
        theme = script.get("title", "")

        # タイトル・構成が渡されていなければ台本から取得
        if not youtube_title:
            youtube_title = script.get("youtube_title") or theme
        if structure is None:
            # 台本のセクション情報から構成を構築
            sections = [{"title": s.get("section", s.get("title", ""))} for s in script.get("sections", [])]
        else:
            sections = structure.get("sections", [{"title": s.get("section", "")} for s in script.get("sections", [])])

        # run_dir の親ディレクトリに bg.jpg を保存
        bg_path = run_dir.parent / f"{run_dir.name}_bg.jpg"

        logger.log("【メタデータ生成】説明文・タグ・サムネイルキャプション・背景画像を並列生成しています...")

        description = theme
        tags = ["ゆっくり解説", "健康"]
        thumbnail_caption = None
        bg_result = None

        with ThreadPoolExecutor(max_workers=4) as ex:
            fd = ex.submit(generate_description, theme, youtube_title, sections)
            fg = ex.submit(generate_tags, theme, youtube_title)
            fbg = ex.submit(generate_background, theme, bg_path, 1920, 1080)
            fcap = ex.submit(generate_thumbnail_caption, theme, youtube_title)

            try:
                description = fd.result()
            except Exception as e:
                notify_error("説明文生成", e)
                logger.error(f"説明文生成: {e} → 空欄で続行")

            try:
                tags = fg.result()
            except Exception as e:
                notify_error("タグ生成", e)
                logger.error(f"タグ生成: {e} → デフォルトタグで続行")

            try:
                bg_result = fbg.result()
            except Exception as e:
                notify_error("背景画像生成", e)
                logger.error(f"背景画像生成: {e} → グラデーション背景で続行")

            try:
                thumbnail_caption = fcap.result()
                logger.log(f"  サムネイルキャプション: {thumbnail_caption}")
            except Exception as e:
                logger.log(f"  [!] サムネイルキャプション生成失敗: {e} → タイトルで代用")

        # metadata.json を保存
        metadata = {
            "youtube_title": youtube_title,
            "description": description,
            "tags": tags,
            "thumbnail_caption": thumbnail_caption,
        }
        metadata_path = run_dir / "metadata.json"
        with open(metadata_path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, ensure_ascii=False, indent=2)
        logger.log(f"メタデータを保存しました: {metadata_path}")

        # 後方互換性のために台本JSONにもメタデータを書き込む
        try:
            manifest = load_manifest(run_dir)
            outputs = manifest["phases"]["script_gen"].get("outputs", [])
            for out in outputs:
                script_path = run_dir.parent / out if not Path(out).is_absolute() else Path(out)
                if script_path.exists():
                    script_data = json.loads(script_path.read_text(encoding="utf-8"))
                    script_data["youtube_title"] = youtube_title
                    script_data["description"] = description
                    script_data["tags"] = tags
                    with open(script_path, "w", encoding="utf-8") as f:
                        json.dump(script_data, f, ensure_ascii=False, indent=2)
                    logger.log(f"台本JSONにメタデータを追記しました: {script_path}")
                    break
        except Exception as e:
            logger.log(f"  [!] 台本JSONへのメタデータ追記スキップ: {e}")

        # パイプライン状態を更新
        output_files = ["metadata.json"]
        if bg_result:
            output_files.append(str(Path(bg_result).name) if hasattr(bg_result, 'name') else str(bg_result))
        update_phase(run_dir, "metadata", "completed", outputs=output_files)

        result = {
            "description": description,
            "tags": tags,
            "thumbnail_caption": thumbnail_caption,
            "bg_path": bg_result,
        }
        logger.log("メタデータ生成スキル完了")
        return result

    except Exception as e:
        update_phase(run_dir, "metadata", "failed", error=str(e))
        raise


# ── CLI ──────────────────────────────────────────────────

def main():
    import argparse
    import sys as _sys
    parser = argparse.ArgumentParser(description="メタデータ生成スキル")
    parser.add_argument("--run-dir", required=True, help="パイプラインの実行ディレクトリ")
    parser.add_argument("--channel", default="health", choices=["health"],
                        help="チャンネルID (creatures は 5c-8 完了後に開放)")
    args = parser.parse_args()

    # Step 3-δ.5c-3: channel config 読込 (fail-closed, generator.py と同形の二段 try).
    try:
        from _channel import load_channel, ChannelLoadError
    except Exception as _ce_imp:
        print(f"エラー: _channel モジュール import 失敗: {_ce_imp}")
        _sys.exit(1)
    try:
        channel = load_channel(args.channel)
    except ChannelLoadError as _ce_load:
        print(f"エラー: channel config 読込失敗 ({args.channel}): {_ce_load}")
        _sys.exit(1)

    _project_root = Path(__file__).parent.parent.parent
    _output_dir = _project_root / channel.paths.output_subdir

    # Step 3-δ.5c-3: invariant guard (Codex 対立レビュー指摘).
    _run_dir_resolved = Path(args.run_dir).resolve()
    _output_dir_resolved = _output_dir.resolve()
    if _run_dir_resolved.parent != _output_dir_resolved:
        print(f"エラー: --run-dir の親 ({_run_dir_resolved.parent}) が")
        print(f"       channel '{args.channel}' の output_dir ({_output_dir_resolved}) と一致しません")
        print(f"       --run-dir は output_dir 直下の run ディレクトリを指定してください")
        _sys.exit(1)

    # Step 3-δ.5c-3: canonicalization 整合 (guard と同じ resolved path を渡す).
    result = run_metadata(_run_dir_resolved)
    print(f"\n説明文: {result['description'][:100]}...")
    print(f"タグ: {result['tags']}")
    print(f"サムネイルキャプション: {result['thumbnail_caption']}")
    print(f"背景画像: {result['bg_path']}")


if __name__ == "__main__":
    main()
