# スキル: AI自己レビュー — 各フェーズ出力の品質チェック + 自動修復

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from skills._common import (
    ensure_scripts_path,
    load_manifest,
    save_manifest,
    SkillLogger,
)



# キャラクター入替処理は削除済み。Geminiの出力をそのまま採用する。
# self_review ではキャラクター変更を行わない（品質チェックのみ）。


def review_script(run_dir: Path, logger: SkillLogger) -> tuple[list[dict], bool]:
    """台本の品質をチェックする。戻り値: (issues, needs_repair)"""
    issues = []
    needs_repair = False
    run_dir = Path(run_dir)

    # 台本JSONを探す
    manifest = load_manifest(run_dir)
    script_outputs = manifest["phases"]["script_gen"].get("outputs", [])
    script_path = None
    for out in script_outputs:
        p = run_dir.parent / out if not Path(out).is_absolute() else Path(out)
        if p.exists():
            script_path = p
            break
    if not script_path:
        issues.append({"type": "missing_file", "message": "台本JSONが見つかりません"})
        return issues, False

    script = json.loads(script_path.read_text(encoding="utf-8"))
    sections = script.get("sections", [])

    # 1. セリフ数チェック
    total_lines = sum(len(s.get("lines", [])) for s in sections)
    if total_lines < 30:
        issues.append({
            "type": "low_line_count",
            "message": f"セリフ数が少なすぎます: {total_lines}行（推奨: 60行以上）",
            "severity": "warning",
        })

    # 2. 文字数チェック
    total_chars = sum(
        len(line.get("text", ""))
        for s in sections
        for line in s.get("lines", [])
    )
    if total_chars < 4000:
        issues.append({
            "type": "low_char_count",
            "message": f"合計文字数が少なすぎます: {total_chars}文字（推奨: 6000文字以上）",
            "severity": "error",
        })

    # 3. キャラクター割り当ての読み取り専用チェック（修正はしない）
    #    キャラクター割り当てはGeminiの出力をそのまま使用。報告のみ。
    consec_count = 0
    for sec in sections:
        lines_list = sec.get("lines", [])
        for i in range(1, len(lines_list)):
            c_prev = lines_list[i - 1].get("character", "")
            c_curr = lines_list[i].get("character", "")
            if c_prev == c_curr and c_curr != "両者":
                consec_count += 1
    if consec_count > 0:
        issues.append({
            "type": "consecutive_speakers",
            "message": f"同一キャラ連続発言が {consec_count} 箇所あります（台本生成時のAI検証で未修正）",
            "severity": "warning",
        })

    return issues, needs_repair


def review_audio(run_dir: Path, logger: SkillLogger) -> list[dict]:
    """音声ファイルの品質をチェックする"""
    issues = []
    run_dir = Path(run_dir)

    wav_files = list(run_dir.glob("*.wav"))
    if not wav_files:
        issues.append({
            "type": "no_audio",
            "message": "WAVファイルが1つも生成されていません",
            "severity": "error",
        })
        return issues

    # 0バイトファイルチェック
    empty_count = sum(1 for f in wav_files if f.stat().st_size < 100)
    if empty_count > 0:
        issues.append({
            "type": "empty_audio",
            "message": f"空の音声ファイルが {empty_count} 件あります",
            "severity": "warning",
        })

    return issues


def review_video(run_dir: Path, logger: SkillLogger) -> list[dict]:
    """動画ファイルの品質をチェックする"""
    issues = []
    run_dir = Path(run_dir)

    manifest = load_manifest(run_dir)
    video_outputs = manifest["phases"]["video_build"].get("outputs", [])
    if not video_outputs:
        issues.append({
            "type": "no_video",
            "message": "動画が生成されていません",
            "severity": "error",
        })
        return issues

    for out in video_outputs:
        p = run_dir.parent / out if not Path(out).is_absolute() else Path(out)
        if p.exists():
            size_mb = p.stat().st_size / (1024 * 1024)
            if size_mb < 5:
                issues.append({
                    "type": "small_video",
                    "message": f"動画ファイルが小さすぎます: {size_mb:.1f}MB",
                    "severity": "warning",
                })
            break
    else:
        issues.append({
            "type": "missing_video",
            "message": "動画ファイルが見つかりません",
            "severity": "error",
        })

    return issues


def run_self_review(run_dir: str | Path) -> dict:
    """全フェーズの出力を品質チェックし、レビューレポートを生成する"""
    run_dir = Path(run_dir)
    logger = SkillLogger(run_dir, "self_review")
    logger.log("=== 自己レビュー開始 ===")

    report = {
        "reviewed_at": __import__("datetime").datetime.now().isoformat(),
        "checks": {},
        "total_issues": 0,
        "errors": 0,
        "warnings": 0,
        "passed": True,
        "needs_repair": False,
    }

    manifest = load_manifest(run_dir)

    # 台本チェック
    if manifest["phases"]["script_gen"]["status"] == "completed":
        issues, needs_repair = review_script(run_dir, logger)
        report["checks"]["script"] = issues
        report["needs_repair"] = needs_repair
        for issue in issues:
            logger.log(f"  [台本] {issue['message']}")

    # 音声チェック（修復が必要な場合はスキップ — 再生成されるため）
    if not report["needs_repair"] and manifest["phases"]["tts"]["status"] == "completed":
        issues = review_audio(run_dir, logger)
        report["checks"]["audio"] = issues
        for issue in issues:
            logger.log(f"  [音声] {issue['message']}")

    # 動画チェック（同上）
    if not report["needs_repair"] and manifest["phases"]["video_build"]["status"] == "completed":
        issues = review_video(run_dir, logger)
        report["checks"]["video"] = issues
        for issue in issues:
            logger.log(f"  [動画] {issue['message']}")

    # 集計
    all_issues = []
    for check_issues in report["checks"].values():
        all_issues.extend(check_issues)
    report["total_issues"] = len(all_issues)
    report["errors"] = sum(1 for i in all_issues if i.get("severity") == "error")
    report["warnings"] = sum(1 for i in all_issues if i.get("severity") == "warning")
    report["passed"] = report["errors"] == 0

    # レポート保存
    review_dir = run_dir / "review"
    review_dir.mkdir(exist_ok=True)
    report_path = review_dir / "review_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if report["needs_repair"]:
        logger.log("=== 自己レビュー完了: 台本修復あり → TTS以降を再実行します ===")
    elif report["passed"]:
        logger.log(f"=== 自己レビュー完了: 合格 (警告{report['warnings']}件) ===")
    else:
        logger.log(f"=== 自己レビュー完了: 不合格 (エラー{report['errors']}件, 警告{report['warnings']}件) ===")

    return report


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="AI自己レビュー")
    parser.add_argument("--run-dir", required=True, help="実行ディレクトリ")
    args = parser.parse_args()
    report = run_self_review(args.run_dir)
    sys.exit(0 if report["passed"] else 1)
