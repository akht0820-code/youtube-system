# スキル: サムネイル生成（3バリアント A/B/C 生成）

import json
import sys
from pathlib import Path

from skills._common import (
    check_prerequisites,
    ensure_scripts_path,
    get_script_json,
    load_manifest,
    update_phase,
    SkillLogger,
)

ensure_scripts_path()

from thumbnail_maker import make_thumbnail_variants
from thumbnail_director import generate_directive
from notifier import notify_error


# ── メインエントリポイント ──────────────────────────────────


def run_thumbnail(run_dir: str | Path) -> dict:
    """サムネイル生成スキルを実行する。

    Args:
        run_dir: パイプラインの実行ディレクトリ

    Returns:
        {"thumbnail_path": str, "variants": dict[str, str]}
    """
    run_dir = Path(run_dir)
    logger = SkillLogger(run_dir, "thumbnail")
    update_phase(run_dir, "thumbnail", "in_progress")

    try:
        # 前提チェック: metadata が完了していること（bg_path, thumbnail_caption が必要）
        if not check_prerequisites(run_dir, "thumbnail", ["metadata"]):
            raise RuntimeError("前提フェーズ 'metadata' が未完了です")

        # 台本JSONを読み込む
        script = get_script_json(run_dir)

        # metadata.json を読み込む
        metadata_path = run_dir / "metadata.json"
        if not metadata_path.exists():
            raise FileNotFoundError(f"metadata.json が見つかりません: {metadata_path}")
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))

        youtube_title = metadata.get("youtube_title", script.get("youtube_title", script.get("title", "")))
        thumbnail_caption = metadata.get("thumbnail_caption")
        narrative_style = script.get("_narrative_style")

        # 背景画像パスの取得（metadata フェーズの出力から）
        manifest = load_manifest(run_dir)
        bg_path = None
        meta_outputs = manifest["phases"]["metadata"].get("outputs", [])
        for out in meta_outputs:
            if out.endswith("_bg.jpg") or out.endswith("_bg.png"):
                candidate = run_dir.parent / out if not Path(out).is_absolute() else Path(out)
                if candidate.exists():
                    bg_path = candidate
                    break

        # サムネイル出力パスの決定（台本JSONファイル名ベース）
        script_outputs = manifest["phases"]["script_gen"].get("outputs", [])
        script_json_path = None
        for out in script_outputs:
            p = Path(run_dir).parent / out if not Path(out).is_absolute() else Path(out)
            if p.exists():
                script_json_path = p
                break
        if script_json_path is None:
            # サイレントフォールバック禁止（2026-04-09事故対策）
            raise FileNotFoundError(
                f"台本JSONが manifest outputs で見つかりません: {run_dir} "
                f"outputs={script_outputs}"
            )

        # サムネイルパス: 台本JSONの名前から _thumbnail.png を作る
        thumbnail_path = script_json_path.with_name(
            script_json_path.stem + "_thumbnail.png"
        )

        # サムネ背景画像をAI生成（3枚→AI選定）
        thumb_bg_path = None
        _face_left_x = None
        try:
            from image_generator import generate_thumbnail_background
            _thumb_bg_out = script_json_path.with_name(
                script_json_path.stem + "_thumb_bg.jpg"
            )
            theme = script.get("title", youtube_title)
            _bg_result = generate_thumbnail_background(
                theme, youtube_title, script, _thumb_bg_out,
            )
            # 戻り値: (Path, face_left_x) or Path or None
            if isinstance(_bg_result, tuple):
                thumb_bg_path, _face_left_x = _bg_result
            else:
                thumb_bg_path = _bg_result
            if thumb_bg_path:
                logger.log(f"  サムネ背景画像: {thumb_bg_path}")
        except Exception as e:
            logger.log(f"  [!] サムネ背景生成失敗: {e} → グラデーション背景で続行")

        logger.log("【サムネイル生成】AIアートディレクター + 描画を実行しています...")
        logger.log(f"  タイトル: {youtube_title}")

        # AIアートディレクター: Gemini 2.5 Proでクリエイティブ判断を一括生成
        # 台本・メタデータを丸ごと渡して最適なクリエイティブ判断を引き出す
        theme = script.get("title", youtube_title)
        directive = generate_directive(theme, youtube_title,
                                       script=script, metadata=metadata)
        if directive:
            # AIアートディレクターがタイトルも生成した場合、metadata/台本を更新
            if directive.get("youtube_title"):
                new_title = directive["youtube_title"]
                logger.log(f"  [AD] タイトル更新: {youtube_title} → {new_title}")
                youtube_title = new_title
                # metadata.json を更新
                metadata["youtube_title"] = youtube_title
                metadata_path.write_text(
                    json.dumps(metadata, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
                # 台本JSONも更新
                script["youtube_title"] = youtube_title
                script_json_path.write_text(
                    json.dumps(script, ensure_ascii=False, indent=2),
                    encoding="utf-8"
                )
            logger.log(f"  [AD] キャプション: {directive['caption']}")
            logger.log(f"  [AD] 配色: {directive['bg_top']} → {directive['bg_bottom']}")
        else:
            logger.log(f"  [AD] フォールバック: 従来ロジックで生成")
            if thumbnail_caption:
                logger.log(f"  キャプション: {thumbnail_caption}")

        # サムネイル生成（directive有→AIモード、無→従来Cバリアント）
        thumb_variants = make_thumbnail_variants(
            youtube_title, thumbnail_path,
            bg_path=bg_path,
            narrative_style=narrative_style,
            thumbnail_caption=thumbnail_caption,
            directive=directive,
            thumb_bg_path=thumb_bg_path,
            face_left_x=_face_left_x,
        )

        # C(2トーン)を優先採用、なければA
        primary = thumb_variants.get("C", thumb_variants.get("A", thumbnail_path))
        logger.log(f"サムネイルを保存しました: {primary}")

        if len(thumb_variants) > 1:
            others = [str(p) for k, p in thumb_variants.items() if k != "C"]
            logger.log(f"  A/Bテスト用バリアント: {', '.join(others)}")
            logger.log("  ※ YouTubeスタジオの「テストと比較」でB/Cを手動アップロードしてください")

        # パイプライン状態を更新
        output_files = [str(Path(v).name) for v in thumb_variants.values()]
        update_phase(run_dir, "thumbnail", "completed", outputs=output_files)

        result = {
            "thumbnail_path": str(primary),
            "variants": {k: str(v) for k, v in thumb_variants.items()},
        }
        logger.log("サムネイル生成スキル完了")
        return result

    except Exception as e:
        update_phase(run_dir, "thumbnail", "failed", error=str(e))
        notify_error("サムネイル生成", e)
        raise


# ── CLI ──────────────────────────────────────────────────


def main():
    import argparse
    parser = argparse.ArgumentParser(description="サムネイル生成スキル")
    parser.add_argument("--run-dir", required=True, help="パイプラインの実行ディレクトリ")
    args = parser.parse_args()

    result = run_thumbnail(args.run_dir)
    print(f"\nサムネイル: {result['thumbnail_path']}")
    for k, v in result["variants"].items():
        print(f"  バリアント{k}: {v}")


if __name__ == "__main__":
    main()
