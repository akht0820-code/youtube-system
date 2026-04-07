# 自己修復パイプライン — フェーズ失敗時に原因診断→修正→再試行
#
# generator.py から run_phase_with_healing() を呼ぶだけで
# 「診断→修正→再試行」ループが自動的に行われる。

import os
import re
import subprocess
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from skills._common import (
    SkillLogger,
    load_manifest,
    save_manifest,
)
from notifier import notify_error


# ── エラーシグネチャ定義（上から順にマッチ、最初の一致で確定）─────

_SIGNATURES = [
    {
        "id": "FILE_LOCKED",
        "patterns": [r"WinError 32", r"別のプロセスが使用中", r"PermissionError.*_temp"],
        "cause": "ファイルロック（ゾンビプロセス）",
    },
    {
        "id": "VOICEVOX_DOWN",
        "patterns": [r"VOICEVOXに接続できません", r"VOICEVOXを起動できませんでした", r"起動がタイムアウトしました", r"実行ファイルが見つかりませんでした", r"ConnectionRefused.*1005", r"ConnectionRefused.*50021"],
        "cause": "VOICEVOX/AivisSpeech 未起動",
    },
    {
        "id": "API_RATE_LIMIT",
        "patterns": [r"429", r"RESOURCE_EXHAUSTED", r"quota"],
        "cause": "API レート制限",
    },
    {
        "id": "API_UNAVAILABLE",
        "patterns": [r"503", r"ServiceUnavailable", r"overloaded", r"high demand"],
        "cause": "API 一時的に利用不可",
    },
    {
        "id": "EMPTY_WAV",
        "patterns": [r"有効なクリップがありません", r"0 件の音声", r"WAVファイルが.*見つかりません"],
        "cause": "音声ファイルが空または欠損",
    },
    {
        "id": "SSL_EOF",
        "patterns": [r"SSLEOFError", r"SSLEOF", r"ConnectionReset"],
        "cause": "SSL接続切断",
    },
    {
        "id": "OAUTH_EXPIRED",
        "patterns": [r"invalid_grant", r"Token.*expired", r"RefreshError"],
        "cause": "OAuth認証トークン期限切れ",
    },
    {
        "id": "INVALID_JSON",
        "patterns": [r"JSONDecodeError", r"Expecting value", r"空のレスポンス"],
        "cause": "LLM不正JSON応答",
    },
    {
        "id": "MEMORY_ERROR",
        "patterns": [r"MemoryError", r"WinError 1455", r"ページファイル", r"Unable to allocate"],
        "cause": "メモリ不足（WSL/Windows仮想メモリ枯渇）",
    },
    {
        "id": "FFMPEG_ERROR",
        "patterns": [r"ffmpeg", r"CalledProcessError", r"returncode"],
        "cause": "ffmpegエンコード失敗",
    },
]


def _diagnose(error: Exception) -> dict:
    """例外を診断してシグネチャIDと原因を返す"""
    error_text = f"{type(error).__name__}: {error}\n{traceback.format_exc()}"
    for sig in _SIGNATURES:
        for pattern in sig["patterns"]:
            if re.search(pattern, error_text, re.IGNORECASE):
                return {"id": sig["id"], "cause": sig["cause"]}
    return {"id": "UNKNOWN", "cause": f"原因不明: {type(error).__name__}"}


# ── 修復関数群 ────────────────────────────────────────────

def _fix_kill_orphan_processes(run_dir, error, ctx):
    """ゾンビPython/ffmpegプロセスを管理者権限で終了する"""
    try:
        from skills._common import force_kill_pipeline_processes
        killed = force_kill_pipeline_processes()
        return f"{len(killed)} プロセスを終了: {', '.join(killed) if killed else 'なし'}"
    except Exception as e:
        return f"プロセス終了失敗: {e}"


def _fix_delete_temp_files(run_dir, error, ctx):
    """ロック対象のtempファイルを強制削除（プロセス終了後）"""
    # まずロックしているプロセスを終了
    _fix_kill_orphan_processes(run_dir, error, ctx)
    time.sleep(5)  # プロセス終了を待つ
    deleted = 0
    # run_dir内とoutput/直下の両方を掃除
    search_dirs = [Path(run_dir)]
    output_dir = Path(run_dir).parent
    if output_dir.exists():
        search_dirs.append(output_dir)
    from skills._common import TEMP_FILE_GLOBS, TEMP_DIR_GLOBS, _safe_unlink, _safe_rmtree
    for d in search_dirs:
        for pattern in TEMP_FILE_GLOBS:
            for f in d.glob(pattern):
                if _safe_unlink(f):
                    deleted += 1
        for pattern in TEMP_DIR_GLOBS:
            for dd in d.glob(pattern):
                if dd.is_dir() and _safe_rmtree(dd):
                    deleted += 1
    return f"{deleted} ファイル/ディレクトリを削除"


def _fix_cleanup_and_wait(run_dir, error, ctx):
    """キャッシュクリーンアップ + 30秒待機"""
    try:
        from skills.skill_cache_cleanup import run_cache_cleanup
        run_cache_cleanup(run_dir=run_dir)
    except Exception:
        pass
    time.sleep(30)
    return "クリーンアップ + 30秒待機"


def _fix_wait(seconds):
    """指定秒数待機する修復関数ファクトリ"""
    def _wait(run_dir, error, ctx):
        time.sleep(seconds)
        return f"{seconds}秒待機"
    return _wait


def _fix_delete_wavs_rerun_tts(run_dir, error, ctx):
    """WAVファイルを全削除（再実行は外側のリトライループが担当）"""
    deleted = 0
    for f in Path(run_dir).glob("*.wav"):
        try:
            f.unlink()
            deleted += 1
        except Exception:
            pass
    return f"WAV {deleted} 件削除（リトライループで再実行される）"


def _fix_delete_token_reauth(run_dir, error, ctx):
    """token.jsonを削除して再認証"""
    token_path = Path(__file__).parent.parent.parent / "token.json"
    try:
        if token_path.exists():
            token_path.unlink()
    except Exception:
        pass
    return "token.json を削除（次回APIアクセスで再認証される）"


def _fix_memory_cleanup(run_dir, error, ctx):
    """WSL側の不要プロセスを終了 + GC でメモリを解放"""
    import gc
    gc.collect()
    try:
        from skills._common import ensure_memory
        result = ensure_memory("self_healing")
        killed = result.get("killed", [])
        after = result.get("after_mb", 0)
        return f"GC実行 + {len(killed)}プロセス終了 → 空き{after}MB"
    except Exception as e:
        return f"メモリ解放試行（一部失敗: {e}）"


def _fix_memory_deep_cleanup(run_dir, error, ctx):
    """video_builderのキャッシュ全クリア + 残留プロセス強制終了 + tempファイル削除"""
    import gc
    # video_builderのモジュールキャッシュをクリア
    try:
        from video_builder import (
            _wb_cache, _irasutoya_cache, _kai_char_cache,
            _overlay_cache, _base_frame_cache, _subtitle_overlay_cache,
        )
        _wb_cache.clear()
        _irasutoya_cache.clear()
        _kai_char_cache.clear()
        _overlay_cache.clear()
        _base_frame_cache[0] = None
        _base_frame_cache[1] = None
        _subtitle_overlay_cache[0] = None
        _subtitle_overlay_cache[1] = None
    except Exception:
        pass
    gc.collect()
    # 残留プロセスを管理者権限で強制終了
    kill_result = _fix_kill_orphan_processes(run_dir, error, ctx)
    time.sleep(5)
    # tempファイルも掃除（プロセス終了後ならロック解除されている）
    temp_result = _fix_delete_temp_files(run_dir, error, ctx)
    # output/直下の大きいtempも削除
    try:
        from skills._common import _cleanup_temp_files
        _cleanup_temp_files()
    except Exception:
        pass
    return f"キャッシュ全クリア + GC + {kill_result} + {temp_result}"


def _fix_ffmpeg_cleanup(run_dir, error, ctx):
    """ffmpeg関連のプロセス終了 + tempを掃除してリトライ"""
    # まずffmpegプロセスを終了
    kill_result = _fix_kill_orphan_processes(run_dir, error, ctx)
    time.sleep(5)
    temp_result = _fix_delete_temp_files(run_dir, error, ctx)
    return f"{kill_result} + {temp_result}"


# ── エスカレーション定義 ──────────────────────────────────

# 各シグネチャIDに対する修復戦略リスト（順番に試行）
_ESCALATION = {
    "FILE_LOCKED": [
        ("ゾンビプロセス終了", _fix_kill_orphan_processes),
        ("tempファイル強制削除", _fix_delete_temp_files),
        ("クリーンアップ+待機", _fix_cleanup_and_wait),
    ],
    "VOICEVOX_DOWN": [
        ("15秒待機（起動待ち）", _fix_wait(15)),
        ("30秒待機（再起動待ち）", _fix_wait(30)),
        ("60秒待機（最終待機）", _fix_wait(60)),
    ],
    "API_RATE_LIMIT": [
        ("60秒待機", _fix_wait(60)),
        ("5分待機", _fix_wait(300)),
        ("15分待機", _fix_wait(900)),
    ],
    "API_UNAVAILABLE": [
        ("30秒待機", _fix_wait(30)),
        ("2分待機", _fix_wait(120)),
        ("5分待機", _fix_wait(300)),
    ],
    "EMPTY_WAV": [
        ("WAV全削除", _fix_delete_wavs_rerun_tts),
        ("クリーンアップ+待機", _fix_cleanup_and_wait),
    ],
    "SSL_EOF": [
        ("30秒待機", _fix_wait(30)),
        ("2分待機", _fix_wait(120)),
        ("5分待機", _fix_wait(300)),
    ],
    "OAUTH_EXPIRED": [
        ("token.json削除+再認証", _fix_delete_token_reauth),
        ("60秒待機+再試行", _fix_wait(60)),
    ],
    "INVALID_JSON": [
        ("30秒待機+再試行", _fix_wait(30)),
        ("60秒待機+再試行", _fix_wait(60)),
    ],
    "MEMORY_ERROR": [
        ("メモリ解放（WSLプロセス終了+GC）", _fix_memory_cleanup),
        ("深層クリーンアップ（キャッシュ+ゾンビ終了）", _fix_memory_deep_cleanup),
    ],
    "FFMPEG_ERROR": [
        ("ffmpeg temp掃除", _fix_ffmpeg_cleanup),
        ("クリーンアップ+待機", _fix_cleanup_and_wait),
    ],
    "UNKNOWN": [
        ("30秒待機+再試行", _fix_wait(30)),
        ("60秒待機+再試行", _fix_wait(60)),
    ],
}


# ── 自己修復オーケストレーター ────────────────────────────

def run_phase_with_healing(
    phase_name: str,
    phase_fn,
    run_dir: Path,
    *args,
    **kwargs,
):
    """フェーズを実行し、失敗時は診断→修正→再試行を繰り返す。

    Args:
        phase_name: フェーズ名（ログ・通知用）
        phase_fn: フェーズ関数（run_dir を第1引数に取る）
        run_dir: 実行ディレクトリ
        *args, **kwargs: phase_fn に渡す追加引数

    Returns:
        phase_fn の戻り値（成功時）

    Raises:
        RuntimeError: 全修復戦略を使い果たしても失敗した場合
    """
    run_dir = Path(run_dir)
    logger = SkillLogger(run_dir, "self_healing")
    healing_log = []

    # 最初の試行
    try:
        result = phase_fn(run_dir, *args, **kwargs)
        if result is not False and result is not None:
            return result
        # False/None は失敗扱い
        error = RuntimeError(f"{phase_name} が失敗を返しました（戻り値: {result}）")
    except Exception as e:
        error = e

    # 失敗 → 診断・修復ループ
    diagnosis = _diagnose(error)
    sig_id = diagnosis["id"]
    strategies = _ESCALATION.get(sig_id, _ESCALATION["UNKNOWN"])

    logger.log(f"=== 自己修復開始: {phase_name} ===")
    logger.log(f"  エラー: {type(error).__name__}: {error}")
    logger.log(f"  診断: [{sig_id}] {diagnosis['cause']}")

    for i, (fix_name, fix_fn) in enumerate(strategies):
        attempt = i + 1
        total = len(strategies)

        logger.log(f"  修復戦略 {attempt}/{total}: {fix_name}")

        # 修復を実行
        try:
            fix_result = fix_fn(run_dir, error, {"phase": phase_name, "attempt": attempt})
            logger.log(f"    結果: {fix_result}")
        except Exception as fix_err:
            logger.log(f"    修復自体が失敗: {fix_err}")
            fix_result = f"修復失敗: {fix_err}"

        # 修復履歴を記録
        entry = {
            "attempt": attempt,
            "error": f"{type(error).__name__}: {str(error)[:200]}",
            "diagnosis": sig_id,
            "cause": diagnosis["cause"],
            "fix_applied": fix_name,
            "fix_result": str(fix_result),
            "timestamp": datetime.now().isoformat(),
        }
        healing_log.append(entry)

        # 修復後にフェーズを再試行
        logger.log(f"  [{phase_name}] 再試行中...")
        try:
            result = phase_fn(run_dir, *args, **kwargs)
            if result is not False and result is not None:
                logger.log(f"=== 自己修復成功: {phase_name} (戦略{attempt}: {fix_name}) ===")
                _save_healing_log(run_dir, phase_name, healing_log)
                return result
            # False/None は失敗
            error = RuntimeError(f"{phase_name} が失敗を返しました（戻り値: {result}）")
        except Exception as e:
            error = e
            logger.log(f"    再試行失敗: {type(e).__name__}: {e}")

        # 再診断（新しいエラーかもしれない）
        new_diag = _diagnose(error)
        if new_diag["id"] != sig_id:
            logger.log(f"  エラーが変化: [{sig_id}] → [{new_diag['id']}] {new_diag['cause']}")
            sig_id = new_diag["id"]
            diagnosis = new_diag
            # 新しいシグネチャの戦略に切り替え（残りを取得）
            new_strategies = _ESCALATION.get(sig_id, _ESCALATION["UNKNOWN"])
            # 現在のループの残りを新しい戦略で上書き
            remaining = list(enumerate(new_strategies))
            for j, (new_fix_name, new_fix_fn) in remaining:
                if j >= attempt:
                    continue  # 既に試した分をスキップ
                strategies = new_strategies
                break

    # 全戦略を使い果たした
    logger.log(f"=== 自己修復失敗: {phase_name} — 全{len(strategies)}戦略を試行済み ===")
    _save_healing_log(run_dir, phase_name, healing_log)

    # 詳細な診断情報をntfy通知
    diag_summary = "\n".join(
        f"  {e['attempt']}. [{e['diagnosis']}] {e['fix_applied']} → {e['fix_result']}"
        for e in healing_log
    )
    notify_error(
        f"{phase_name}(自己修復失敗)",
        RuntimeError(
            f"全{len(strategies)}戦略を試行後も失敗\n"
            f"最終エラー: {error}\n"
            f"修復履歴:\n{diag_summary}"
        ),
    )
    raise RuntimeError(
        f"{phase_name}: 自己修復失敗（{len(strategies)}戦略試行済み）: {error}"
    ) from error


def _save_healing_log(run_dir: Path, phase_name: str, healing_log: list):
    """修復履歴を pipeline.json に書き込む"""
    try:
        manifest = load_manifest(run_dir)
        if phase_name in manifest.get("phases", {}):
            manifest["phases"][phase_name]["healing_log"] = healing_log
        save_manifest(run_dir, manifest)
    except Exception:
        pass  # パイプライン記録失敗でも止めない
