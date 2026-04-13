# ゆっくり解説動画 台本自動生成システム — オーケストレーター
#
# 各フェーズは scripts/skills/ の独立スキルとして実行される。
# このファイルはスキルの呼び出し順序を制御するだけの薄いオーケストレーター。

import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

from notifier import notify_error, notify_start, notify_success
from skills.self_healing import run_phase_with_healing

# Step 3-δ.4: OUTPUT_DIR の module-level 定数は削除.
# main() で channel.paths.output_subdir から動的に解決し, 3 helper に引数で渡す.


def _pick_theme_from_file(themes_path: Path, output_dir: Path) -> str:
    """themes.txt からランダムにテーマを1つ選ぶ（使用済みテーマを除外）

    themes_path / output_dir は呼び出し元 (main) が channel config から解決して渡す。
    """
    import random
    if not themes_path.exists():
        raise FileNotFoundError(f"themes.txt が見つかりません: {themes_path}")
    lines = [l.strip() for l in themes_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if not lines:
        raise ValueError("themes.txt にテーマが入っていません")

    used: set[str] = set()
    try:
        for d in output_dir.iterdir():
            if d.is_dir() and re.match(r"\d{8}_\d{6}_", d.name):
                used.add(d.name[16:])
    except Exception:
        pass

    unused = [t for t in lines if re.sub(r'[\\/:*?"<>|]', "", t)[:30] not in used]
    candidates = unused if unused else lines
    if unused and len(unused) < len(lines):
        print(f"[テーマ] 残り未使用: {len(unused)}/{len(lines)} 件")
    return random.choice(candidates)


def _create_run_dir(theme: str, output_dir: Path) -> tuple[Path, str, str]:
    """実行ディレクトリを作成し、(run_dir, run_id, safe_theme) を返す"""
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_theme = re.sub(r'[\\/:*?"<>|]', "", theme)[:30]
    run_dir = output_dir / f"{run_id}_{safe_theme}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return run_dir, run_id, safe_theme


def _find_resumable_run(output_dir: Path) -> Path | None:
    """当日の最新の未完了（in_progress / failed）run_dir を返す。なければ None"""
    if not output_dir.exists():
        return None
    today_prefix = datetime.now().strftime("%Y%m%d")
    candidates = []
    for d in output_dir.iterdir():
        if not d.is_dir() or not re.match(r"\d{8}_\d{6}_", d.name):
            continue
        # 当日のrun_dirのみ対象
        if not d.name.startswith(today_prefix):
            continue
        pj = d / "pipeline.json"
        if not pj.exists():
            continue
        try:
            m = json.loads(pj.read_text(encoding="utf-8"))
            if m.get("status") in ("in_progress", "failed"):
                candidates.append(d)
        except Exception:
            continue
    if not candidates:
        return None
    # 最新のディレクトリ名（タイムスタンプ順）を返す
    candidates.sort(key=lambda p: p.name, reverse=True)
    return candidates[0]


def _phase_completed(manifest: dict, phase: str) -> bool:
    """指定フェーズが完了済みかどうか"""
    return manifest.get("phases", {}).get(phase, {}).get("status") == "completed"


def main():
    import argparse
    # Step 3-γ: allow_abbrev=False で --ch / --auto_ 等の省略形 prefix match を禁止
    # (Codex レビュー 2026-04-11 指摘). 既存 consumer (run.bat / run_preflight.bat /
    # .github/workflows) は全て完全形のみ使用しているため副作用なし.
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--auto",          action="store_true", help="自動実行モード")
    parser.add_argument("--theme",         type=str, default="", help="テーマを直接指定")
    parser.add_argument("--publish-hours", type=int, default=0,  help="N時間後に予約投稿")
    parser.add_argument("--publish-time",  type=str, default="", help="指定時刻に予約投稿（例: 18:00）")
    parser.add_argument("--no-upload",     action="store_true",  help="アップロードをスキップ")
    parser.add_argument("--script-file",   type=str, default="", help="外部台本JSONファイルのパス")
    parser.add_argument("--resume",        action="store_true",  help="当日の失敗/未完了run_dirから再開（対象なしは失敗終了）")
    # Step 3-γ: --channel で読み込むチャンネル設定を選択. default='health' で
    # 既存の 10時タスク (run.bat) と bit-identical.
    # Step 3-δ.5c-8: script char 閾値 + tags fallback の channel-aware 化完了.
    # creatures を choices に開放.
    parser.add_argument("--channel",       type=str, default="health",
                        choices=["health", "creatures"],
                        help="チャンネルID (default: health)")
    args = parser.parse_args()

    # 注: --auto と --resume の併用は run.bat のリトライフローで使用される。
    # ただし成立条件は「初回実行が run_dir と pipeline.json を作成した後に失敗した場合」のみ。
    # run_dir 作成前（テーマ選定/プリフライト/notify_start 等）で落ちた場合は2回目以降も対象なし即死する。
    # 事故の根本原因は併用そのものではなく、--resume 対象なし時のサイレントフォールバック。
    # 後段（L126付近）で対象なし時に sys.exit(1) する対策を取る。

    # ── チャンネル設定を読み込む (fail-closed; import / load 両方通知付き) ──
    # Step 2-ε: 1日1本ガードの _lock_path も cfg 由来にしたため, load_channel を
    # 1日1本ガードの **前** に移動した (Step 2-γ では後ろに置いていた).
    # 運用意味の変化: config 破損時は 1日1本ガード skip 経路も fail-closed で
    # 死ぬ. 静かに壊れるより fail-closed で Discord 通知の方が安全という意図仕様.
    # except Exception は ImportError/ModuleNotFoundError/SyntaxError 等を
    # 網羅するが, SystemExit と KeyboardInterrupt は意図的に捕捉しない
    # (BaseException まで広げない)。
    try:
        from _channel import load_channel, ChannelLoadError
    except Exception as _ce_imp:
        print(f"[致命的] _channel モジュール import 失敗: {_ce_imp}")
        try:
            notify_error("チャンネル設定モジュール import失敗", _ce_imp)
        except Exception:
            pass
        sys.exit(1)

    try:
        channel = load_channel(args.channel)
    except ChannelLoadError as _ce_load:
        print(f"[致命的] チャンネル設定読込失敗 ({args.channel}): {_ce_load}")
        try:
            notify_error(f"チャンネル設定読込失敗 ({args.channel})", _ce_load)
        except Exception:
            pass
        sys.exit(1)

    _project_root = Path(__file__).parent.parent
    _themes_path = _project_root / channel.paths.themes_file
    _lock_path = _project_root / channel.paths.lock_file
    # Step 3-δ.4: output_dir を channel config から解決.
    # health.json: output_subdir="output" → 旧 OUTPUT_DIR と文字列同一 (bit-identical).
    _output_dir = _project_root / channel.paths.output_subdir

    # ── 1日1本ガード ──────────────────────────────────────
    if args.auto:
        _today = datetime.now().strftime("%Y-%m-%d")
        if _lock_path.exists():
            _lock_content = _lock_path.read_text(encoding="utf-8").strip()
            _lock_date = _lock_content.split("|", 1)[0]
            if _lock_date == _today:
                print(f"[スキップ] 本日({_today})は既に動画を投稿済みです。")
                sys.exit(0)

    print("=== ゆっくり解説動画 台本生成システム ===\n")

    # ── --resume: 最新の失敗/未完了run_dirから再開 ────────
    _resuming = False
    _resume_manifest = None
    if args.resume:
        _resume_dir = _find_resumable_run(_output_dir)
        if _resume_dir:
            from skills._common import load_manifest
            _resume_manifest = load_manifest(_resume_dir)
            print(f"[再開モード] 未完了のrun_dirを検出: {_resume_dir.name}")
            # 完了済みフェーズを表示
            for _ph, _info in _resume_manifest.get("phases", {}).items():
                if _info.get("status") == "completed":
                    print(f"  スキップ: {_ph} (完了済み)")
            _resuming = True
        else:
            # Step1: サイレントフォールバック禁止。
            # 以前は「新規実行します」と表示して新テーマ生成に進んでいたが、
            # 2026-04-09に『壊れた動画の差し替え目的で --resume 指定 → 完了済みrunのため
            # 対象なし判定 → 新テーマで全く無関係な動画を生成開始』という重大事故が発生。
            # --resume は意図が明確な操作なので、対象なしは必ず失敗終了する。
            # 注意: _find_resumable_run() は『当日』かつ status=in_progress/failed のみ対象。
            #       完了済みrun や前日以前のrun は候補にならない。
            print("エラー: --resume 対象の未完了run_dirが見つかりません。")
            print("  条件: 当日(YYYYMMDD)作成 かつ status in ('in_progress','failed')")
            print("  完了済みrunや前日以前のrunはこの条件では対象外です。")
            print("  新規生成したい場合: --resume を外して実行してください。")
            print("  既存runの特定フェーズを個別実行したい場合:")
            print("    scripts/skills/skill_video_build.py --run-dir <path> などの")
            print("    個別スキルを直接実行してください。")
            sys.exit(1)

    # ── テーマ決定 ────────────────────────────────────────
    _external_script = None
    if _resuming:
        theme = _resume_manifest["theme"]
    elif args.script_file:
        # fail-closed: 読込失敗/schema不備は exit(1)
        # 2026-04-09事故対策: 以前は失敗時にAI新規生成へサイレントフォールバックしていた
        # が、typo/破損/エンコーディング違い/schema崩れで別テーマの動画が作られる穴
        # だったため撤去。明示指定された入力の失敗は必ず失敗終了する。
        try:
            with open(args.script_file, encoding="utf-8") as f:
                _external_script = json.load(f)
        except FileNotFoundError:
            print(f"エラー: 外部台本JSONが見つかりません: {args.script_file}")
            sys.exit(1)
        except json.JSONDecodeError as e:
            print(f"エラー: 外部台本JSONのパース失敗: {args.script_file}")
            print(f"  {e}")
            sys.exit(1)
        except Exception as e:
            print(f"エラー: 外部台本JSON読込失敗: {args.script_file}")
            print(f"  {e}")
            sys.exit(1)
        # 最低限のschema検証
        _errs = []
        if not isinstance(_external_script, dict):
            _errs.append("ルートがdictでない")
        else:
            if not (_external_script.get("title") or _external_script.get("youtube_title")):
                _errs.append("title または youtube_title がない")
            _sections = _external_script.get("sections")
            if not isinstance(_sections, list) or not _sections:
                _errs.append("sections が list でないか空")
            else:
                for _i, _sec in enumerate(_sections):
                    _lines = _sec.get("lines") if isinstance(_sec, dict) else None
                    if not isinstance(_lines, list) or not _lines:
                        _errs.append(f"sections[{_i}].lines が list でないか空")
                        break
        if _errs:
            print(f"エラー: 外部台本JSONのschema不備: {args.script_file}")
            for _e in _errs:
                print(f"  - {_e}")
            sys.exit(1)
        print(f"外部台本JSONを読み込みました: {args.script_file}")

    if not _resuming:
        if _external_script:
            # schema検証で title or youtube_title の存在は保証済み
            theme = _external_script.get("title") or _external_script.get("youtube_title")
        elif args.theme:
            theme = args.theme
        elif args.auto:
            try:
                theme = _pick_theme_from_file(_themes_path, _output_dir)
            except Exception as e:
                notify_error("テーマ取得", e)
                print(f"エラー: {e}")
                sys.exit(1)
            print(f"本日のテーマ: 「{theme}」")
        else:
            theme = input("テーマを入力してください: ").strip()

    if not theme:
        print("エラー: テーマが入力されていません")
        sys.exit(1)

    print(f"\nテーマ: 「{theme}」\n")
    notify_start(theme)

    # ── 起動時メモリチェック（不要プロセスを自動解放）──
    try:
        from skills._common import ensure_memory
        ensure_memory("起動時")
    except Exception as e:
        print(f"  [警告] メモリチェック失敗（無視して続行）: {e}")

    # ── 起動時クリーンアップ（temp files・古いWAVディレクトリ・失敗パイプライン）──
    # 失敗しても動画生成は必ず続行する（再開モード時はクリーンアップしない）
    if not _resuming:
        try:
            from skills.skill_cache_cleanup import run_cache_cleanup
            # Step 3-δ.5a: channel-aware cleanup (output_dir を明示的に渡す)
            _cleanup = run_cache_cleanup(output_dir=_output_dir)
            _cleanup_total = sum(len(v) for v in _cleanup.values())
            if _cleanup_total:
                print(f"  [起動時クリーンアップ] {_cleanup_total} 件削除しました")
        except Exception as e:
            print(f"  [警告] 起動時クリーンアップ失敗（無視して続行）: {e}")

    # ── 実行ディレクトリ作成 or 再開 + パイプライン初期化 ─────────
    if _resuming:
        run_dir = _resume_dir
        manifest = _resume_manifest
        run_id = manifest["run_id"]
    else:
        run_dir, run_id, safe_theme = _create_run_dir(theme, _output_dir)
        from skills._common import create_manifest
        # Step 3-δ.1: channel_id を pipeline.json に記録 (no-op; consumer は Step 3-δ.2)
        manifest = create_manifest(run_dir, theme, run_id, channel_id=args.channel)
    global _current_run_dir
    _current_run_dir = run_dir
    print(f"実行ディレクトリ: {run_dir}\n")

    _t0 = time.perf_counter()
    def _elapsed():
        return f"{time.perf_counter() - _t0:.0f}s"

    # ── フェーズ1+2: 台本生成 ─────────────────────────────
    if _phase_completed(manifest, "script_gen"):
        # 再開時: 完了済み台本の文字数を検証（不良台本での無駄走り防止）
        # 2026-04-09事故対策:
        #   - 旧実装は run_dir.glob("*.json") + startswith("2026") で台本を探していた
        #     (無関係なJSONを掴む / 2027年以降動作しない問題あり)
        #   - manifest script_gen.outputs を唯一の真実とする
        # Codex Round3指摘: outputs欠損 or JSON破損を except: pass で握りつぶさず
        # script_gen を failed 扱いにしてリジェネに回す (fail-closed)
        _script_path = None
        _script_invalid = False
        _script_invalid_reason = ""
        _sg_outputs = manifest.get("phases", {}).get("script_gen", {}).get("outputs", [])
        if not _sg_outputs:
            _script_invalid = True
            _script_invalid_reason = "script_gen.outputs が manifest に無い"
        else:
            # Codex Round5: run_dir 相対 / run_dir.parent 相対 / 絶対を全て試す
            for _out in _sg_outputs:
                try:
                    _out_p = Path(_out)
                    if _out_p.is_absolute():
                        _candidates = [_out_p]
                    else:
                        _candidates = [run_dir / _out_p, run_dir.parent / _out_p]
                except Exception as _pe:
                    _script_invalid = True
                    _script_invalid_reason = f"outputs path 解釈失敗: {_pe}"
                    break
                _found = None
                for _c in _candidates:
                    if _c.exists() and _c.suffix == ".json":
                        _found = _c
                        break
                if _found is not None:
                    _script_path = _found
                    break
            if _script_path is None and not _script_invalid:
                _script_invalid = True
                _script_invalid_reason = f"outputs に実体のあるJSONなし: {_sg_outputs}"

        _chars = None
        if _script_path is not None:
            try:
                import json as _j
                _sc = _j.loads(_script_path.read_text(encoding="utf-8"))
                _chars = sum(len(l.get("text","")) for s in _sc.get("sections",[]) for l in s.get("lines",[]))
            except Exception as _je:
                _script_invalid = True
                _script_invalid_reason = f"台本JSON読込/パース失敗: {_je}"

        # Step 3-δ.5c-8: channel config から resume 判定用ハード下限を取得.
        # 旧: from skills.skill_script_gen import _HARD_MIN_SCRIPT_CHARS
        # 新: channel config の hard_min_chars を使用 (channel 間で閾値が異なるため).
        _RESUME_MIN_CHARS = channel.script.hard_min_chars
        if _script_invalid or (_chars is not None and _chars < _RESUME_MIN_CHARS):
            _reason = _script_invalid_reason if _script_invalid else f"文字数不足: {_chars}文字 (<{_RESUME_MIN_CHARS})"
            print(f"[再開モード] 台本が無効 ({_reason}) → フェーズ1からやり直します")
            from skills._common import update_phase
            update_phase(run_dir, "script_gen", "failed", error=_reason)
            # Codex Round5: self_review は PHASE_ORDER に無いので除外
            for _ph in ["metadata", "pronunciation", "se_assign", "prosody", "tts", "video_build", "thumbnail", "upload"]:
                try:
                    update_phase(run_dir, _ph, "pending")
                except Exception:
                    pass
            manifest = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))

        if _phase_completed(manifest, "script_gen"):
            print("【フェーズ1+2】台本生成 → スキップ（完了済み）")
    else:
        print("【フェーズ1+2】台本を生成しています...")
        from skills.skill_script_gen import run_script_gen
        sg_result = run_script_gen(run_dir, theme, external_script=_external_script)
        if not sg_result:
            print("[致命的エラー] 台本生成に失敗しました。処理を中断します。")
            sys.exit(1)
        print(f"  → フェーズ1+2完了 ({_elapsed()})\n")

    # ── フェーズ3: メタデータ生成 ─────────────────────────
    if _phase_completed(manifest, "metadata"):
        print("【フェーズ3】メタデータ生成 → スキップ（完了済み）")
    else:
        print("【フェーズ3】メタデータを生成しています...")
        from skills.skill_metadata import run_metadata
        run_metadata(run_dir)
        print(f"  → フェーズ3完了 ({_elapsed()})\n")

    # ── 発音補正 ──────────────────────────────────────────
    if _phase_completed(manifest, "pronunciation"):
        print("【発音補正】→ スキップ（完了済み）")
    else:
        print("【発音補正】静的辞書＋AI読みチェックを実行しています...")
        from skills.skill_pronunciation import run_pronunciation
        run_pronunciation(run_dir)
        print(f"  → 発音補正完了 ({_elapsed()})\n")

    # ── SE（効果音）割り当て ─────────────────────────────
    if _phase_completed(manifest, "se_assign"):
        print("【SE割り当て】→ スキップ（完了済み）")
    else:
        print("【SE割り当て】Gemini ProがSEを判定しています...")
        from skills.skill_se_assign import run_se_assign
        se_result = run_se_assign(run_dir)
        print(f"  → SE割り当て完了: {se_result.get('se_count', 0)}件 ({_elapsed()})\n")

    # ── プロソディ（抑揚）割り当て ──────────────────────
    if _phase_completed(manifest, "prosody"):
        print("【プロソディ】→ スキップ（完了済み）")
    else:
        print("【プロソディ】Gemini Proが抑揚を判定しています...")
        from skills.skill_prosody import run_prosody
        prosody_result = run_prosody(run_dir)
        print(f"  → プロソディ完了: {prosody_result.get('prosody_count', 0)}件 ({_elapsed()})\n")

    # ── キャッシュクリーンアップ（TTS前: 発音変更で古いWAVを無効化）──
    from skills.skill_cache_cleanup import run_cache_cleanup
    cleanup_result = run_cache_cleanup(run_dir=run_dir)
    if cleanup_result.get("stale_wav"):
        print(f"  [キャッシュ] 発音変更により {len(cleanup_result['stale_wav'])} WAVを削除しました")
        # クリーンアップがphaseをpendingに戻した場合、manifestを再読み込み
        manifest = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))

    # ── フェーズ4: 音声合成（自己修復付き）─────────────────
    if _phase_completed(manifest, "tts"):
        print("【フェーズ4】音声合成 → スキップ（完了済み）")
    else:
        print("【フェーズ4】音声を合成しています...")
        from skills.skill_tts import run_tts
        run_phase_with_healing("tts", run_tts, run_dir)
        print(f"  → フェーズ4完了 ({_elapsed()})\n")

    # ── フェーズ5: 動画生成（自己修復付き）─────────────────
    if _phase_completed(manifest, "video_build"):
        print("【フェーズ5】動画生成 → スキップ（完了済み）")
    else:
        print("【フェーズ5】動画を生成しています...")
        try:
            ensure_memory("video_build前")
        except Exception:
            pass
        from skills.skill_video_build import run_video_build
        run_phase_with_healing("video_build", run_video_build, run_dir)
        print(f"  → フェーズ5完了 ({_elapsed()})\n")

    # ── フェーズ6: サムネイル生成 ─────────────────────────
    if _phase_completed(manifest, "thumbnail"):
        print("【フェーズ6】サムネイル生成 → スキップ（完了済み）")
    else:
        print("【フェーズ6】サムネイルを生成しています...")
        from skills.skill_thumbnail import run_thumbnail
        run_thumbnail(run_dir)
        print(f"  → フェーズ6完了 ({_elapsed()})\n")

    # ── 自己レビュー ─────────────────────────────────────
    from skills.skill_self_review import run_self_review
    review = run_self_review(run_dir)

    if review.get("needs_repair"):
        # キャラクターロール逸脱を自動修復 → 発音+TTS+動画のみ再実行
        # SE/プロソディはテキスト修復の影響を受けないためスキップ
        print("[自動修復] 台本修復済み → 発音補正・音声・動画を再生成します...")
        from skills.skill_pronunciation import run_pronunciation
        from skills.skill_tts import run_tts
        from skills.skill_video_build import run_video_build
        run_pronunciation(run_dir)
        run_phase_with_healing("tts", run_tts, run_dir)
        run_phase_with_healing("video_build", run_video_build, run_dir)
        print(f"  → 再生成完了 ({_elapsed()})\n")

    elif not review["passed"] and review.get("errors", 0) > 0:
        print(f"[致命的] 自己レビューでエラー {review['errors']} 件 → アップロードをブロックします")
        notify_error("自己レビュー不合格 → アップロード中止", ValueError(
            f"エラー{review['errors']}件, 警告{review['warnings']}件。手動確認が必要です。"
        ))
        sys.exit(1)

    elif not review["passed"]:
        # 警告のみ（エラーなし）の場合は続行
        print(f"[警告] 自己レビューで警告 {review['warnings']} 件（エラーなし → 続行）")

    # ── アップロード前の最終安全チェック ────────────────────
    # manifestを再読込（video_build完了後のoutputsを取得するため）
    from skills._common import load_manifest
    manifest = load_manifest(run_dir)
    _mp4 = None
    _vb_outputs = manifest["phases"]["video_build"].get("outputs", [])
    for _out in _vb_outputs:
        if _out.endswith(".mp4"):
            _candidate = run_dir.parent / _out if not Path(_out).is_absolute() else Path(_out)
            if _candidate.exists():
                _mp4 = _candidate
                break
    if _mp4 and args.auto:
        import subprocess as _sp
        try:
            from imageio_ffmpeg import get_ffmpeg_exe as _get_ffmpeg_exe
            _ffmpeg_path = _get_ffmpeg_exe()
            _ffprobe_path = _ffmpeg_path.replace("ffmpeg", "ffprobe")
            _probe = _sp.run(
                [_ffprobe_path,
                 "-v", "error", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(_mp4)],
                capture_output=True, text=True, timeout=10,
            )
            _dur = float(_probe.stdout.strip()) if _probe.stdout.strip() else 0
        except Exception:
            # ffprobeが使えない場合はファイルサイズで判定
            _dur = _mp4.stat().st_size / (200 * 1024)  # 概算: 200KB/秒
        _MIN_DURATION = 180  # 最低3分
        if _dur < _MIN_DURATION:
            print(f"[致命的] 動画が短すぎます: {_dur:.0f}秒（最低{_MIN_DURATION}秒）→ アップロード中止")
            notify_error("動画尺不足 → アップロード中止", ValueError(
                f"動画 {_dur:.0f}秒 < 最低{_MIN_DURATION}秒。台本生成に失敗した可能性があります。"
            ))
            sys.exit(1)

    # ── フェーズ7: アップロード ───────────────────────────
    if args.no_upload:
        print("アップロードをスキップしました。")
    elif args.auto:
        import random
        wait_sec = random.randint(60, 300)
        print(f"自動モード: アップロード前に {wait_sec} 秒待機しています（ボット判定回避）...")
        time.sleep(wait_sec)

        from skills.skill_upload import run_upload
        run_upload(
            run_dir,
            publish_time=args.publish_time or None,
            publish_hours=args.publish_hours,
            skip_wait=True,  # 既に待機済み
        )
    else:
        try:
            do_upload = input("YouTubeにアップロードしますか？ [y/N]: ").strip().lower()
        except EOFError:
            do_upload = "n"

        if do_upload == "y":
            from skills.skill_upload import run_upload

            publish_input = ""
            if not args.publish_time:
                try:
                    publish_input = input(
                        "予約投稿の日時を入力してください（例: 2026/03/25 18:00）\n"
                        "即公開の場合はEnterを押してください: "
                    ).strip()
                except EOFError:
                    pass

            run_upload(
                run_dir,
                publish_time=args.publish_time or publish_input or None,
                publish_hours=args.publish_hours,
            )
        else:
            print("アップロードをスキップしました。")

    # ── 完了サマリ ───────────────────────────────────────
    from skills._common import load_manifest
    manifest = load_manifest(run_dir)
    print(f"\n=== 処理完了 ({_elapsed()}) ===")
    print(f"テーマ    : {theme}")
    print(f"run_dir   : {run_dir}")

    # 主要出力ファイルを表示
    for phase_name in ["script_gen", "video_build", "thumbnail", "upload"]:
        phase = manifest["phases"].get(phase_name, {})
        for out in phase.get("outputs", []):
            print(f"  {out}")

    url = manifest["phases"].get("upload", {}).get("outputs", [None])
    if isinstance(url, list):
        for item in url:
            if isinstance(item, str) and item.startswith("http"):
                print(f"URL       : {item}")


_current_run_dir = None  # main()内で設定、未捕捉例外時にpipeline.json更新に使用


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as _uncaught:
        # pipeline.json にエラーを記録（run_dir確定後のクラッシュの場合）
        import traceback as _tb
        _err_msg = f"{type(_uncaught).__name__}: {_uncaught}"
        _err_detail = _tb.format_exc()
        print(f"\n[致命的エラー] 未捕捉例外:\n{_err_detail}")
        if _current_run_dir is not None:
            try:
                from skills._common import load_manifest as _lm, update_phase as _up, save_manifest as _sm
                _m = _lm(_current_run_dir)
                _updated = False
                for _ph_name, _ph_data in _m.get("phases", {}).items():
                    if _ph_data.get("status") == "in_progress":
                        _up(_current_run_dir, _ph_name, "failed", error=_err_msg)
                        _updated = True
                        break
                if not _updated:
                    _m["status"] = "failed"
                    _m["uncaught_error"] = _err_msg
                    _sm(_current_run_dir, _m)
            except Exception:
                pass
        try:
            notify_error("パイプライン未捕捉例外", _uncaught)
        except Exception:
            pass
        sys.exit(1)
