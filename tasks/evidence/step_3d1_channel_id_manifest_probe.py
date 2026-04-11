"""Step 3-δ.1 probe: create_manifest が pipeline.json に channel_id を記録することを検証.

本 Step は no-op (consumer ゼロ). consumer は Step 3-δ.2 で skill_upload /
preflight_runtime が manifest.get('channel_id', 'health') で参照する予定.

Windows native Python + cwd=scripts/ で本番形態を実測する.
"""
import json
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

errors = []


def expect(cond, msg):
    if cond:
        print(f"  [OK] {msg}")
    else:
        print(f"  [NG] {msg}")
        errors.append(msg)


from skills._common import (
    PHASE_ORDER,
    create_manifest,
    load_manifest,
    save_manifest,
    update_phase,
)

# ── 1. create_manifest default (channel_id 省略) → 'health' ─────
print("[1] create_manifest default (後方互換)")
with tempfile.TemporaryDirectory(prefix="step3d1_default_") as _td:
    run_dir = Path(_td)
    manifest = create_manifest(run_dir, theme="test_theme", run_id="test_run_001")
    expect(manifest.get("channel_id") == "health",
           f"default manifest['channel_id'] == 'health' (got {manifest.get('channel_id')!r})")
    # pipeline.json file 実体も確認
    pj = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))
    expect(pj.get("channel_id") == "health",
           f"pipeline.json file channel_id == 'health' (got {pj.get('channel_id')!r})")

# ── 2. create_manifest channel_id='health' 明示 ─────────────────
print("[2] create_manifest channel_id='health' 明示")
with tempfile.TemporaryDirectory(prefix="step3d1_health_") as _td:
    run_dir = Path(_td)
    manifest = create_manifest(run_dir, theme="t", run_id="r", channel_id="health")
    expect(manifest.get("channel_id") == "health",
           "manifest['channel_id'] == 'health'")
    pj = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))
    expect(pj.get("channel_id") == "health",
           "pipeline.json file channel_id == 'health'")

# ── 3. create_manifest channel_id='creatures' ──────────────────
print("[3] create_manifest channel_id='creatures'")
with tempfile.TemporaryDirectory(prefix="step3d1_creatures_") as _td:
    run_dir = Path(_td)
    manifest = create_manifest(run_dir, theme="t", run_id="r", channel_id="creatures")
    expect(manifest.get("channel_id") == "creatures",
           "manifest['channel_id'] == 'creatures'")
    pj = json.loads((run_dir / "pipeline.json").read_text(encoding="utf-8"))
    expect(pj.get("channel_id") == "creatures",
           "pipeline.json file channel_id == 'creatures'")

# ── 4. dict キー順序: run_id → channel_id → theme → status → created_at → phases ─
print("[4] dict キー順序 (json.dump 出力順)")
with tempfile.TemporaryDirectory(prefix="step3d1_order_") as _td:
    run_dir = Path(_td)
    create_manifest(run_dir, theme="t", run_id="r", channel_id="health")
    raw = (run_dir / "pipeline.json").read_text(encoding="utf-8")
    pj_ordered = json.loads(raw)
    keys = list(pj_ordered.keys())
    expected_order = ["run_id", "channel_id", "theme", "status", "created_at", "phases"]
    expect(keys == expected_order,
           f"root keys order == {expected_order} (got {keys})")

# ── 5. update_phase round-trip で channel_id が消えない ─────────
print("[5] update_phase round-trip 保持")
with tempfile.TemporaryDirectory(prefix="step3d1_roundtrip_") as _td:
    run_dir = Path(_td)
    create_manifest(run_dir, theme="t", run_id="r", channel_id="creatures")
    # 各 phase を in_progress / completed に更新しても channel_id が消えないこと
    update_phase(run_dir, "script_gen", "in_progress")
    m1 = load_manifest(run_dir)
    expect(m1.get("channel_id") == "creatures",
           "update_phase(in_progress) 後も channel_id 保持")
    update_phase(run_dir, "script_gen", "completed", outputs=["x.json"])
    m2 = load_manifest(run_dir)
    expect(m2.get("channel_id") == "creatures",
           "update_phase(completed) 後も channel_id 保持")

# ── 6. 旧 manifest (channel_id 無し) を update_phase しても壊れない ──
#    Codex レビュー改善点: 旧 run 互換を事前検証
print("[6] 旧 manifest (channel_id 無し) update_phase 互換性")
with tempfile.TemporaryDirectory(prefix="step3d1_legacy_") as _td:
    run_dir = Path(_td)
    # 旧形式の pipeline.json を手動で作る (channel_id フィールド無し).
    # phases は PHASE_ORDER から動的生成 (Codex 非ブロッキング改善 2026-04-11).
    legacy = {
        "run_id": "legacy_run",
        "theme": "legacy_theme",
        "status": "in_progress",
        "created_at": "2026-04-01T10:00:00",
        "phases": {
            phase: {
                "status": "pending",
                "started_at": None,
                "completed_at": None,
                "outputs": [],
                "error": None,
                "retries": 0,
                "healing_log": [],
            }
            for phase in PHASE_ORDER
        },
    }
    save_manifest(run_dir, legacy)

    # load してみる (壊れないこと)
    m_legacy = load_manifest(run_dir)
    expect("channel_id" not in m_legacy,
           "旧 manifest には channel_id が無い (baseline)")
    expect(m_legacy.get("channel_id", "health") == "health",
           "旧 manifest でも .get('channel_id', 'health') → 'health' (Step 3-δ.2 申し送りフォールバック)")

    # update_phase で壊れないこと (チャンネル consumer ゼロなので channel_id 無しのままで OK)
    try:
        update_phase(run_dir, "script_gen", "in_progress")
        expect(True, "旧 manifest update_phase(in_progress) 例外なし")
    except Exception as e:
        expect(False, f"旧 manifest update_phase で例外: {e}")

    m_legacy_after = load_manifest(run_dir)
    expect(m_legacy_after["phases"]["script_gen"]["status"] == "in_progress",
           "旧 manifest 経由でも phase 状態は更新される")
    # channel_id フィールドは update_phase では追加されない (Step 3-δ.1 範囲)
    expect("channel_id" not in m_legacy_after,
           "update_phase は channel_id フィールドを勝手に追加しない (範囲外)")

# ── 7. 既存 key (run_id/theme/status/phases) に副作用がないこと ─────
print("[7] 既存 key の値に副作用なし (bit-identical w.r.t. 他キー)")
with tempfile.TemporaryDirectory(prefix="step3d1_sideeffect_") as _td:
    run_dir = Path(_td)
    manifest = create_manifest(run_dir, theme="A_theme", run_id="A_id",
                               channel_id="health")
    expect(manifest["run_id"] == "A_id", "run_id 非改変")
    expect(manifest["theme"] == "A_theme", "theme 非改変")
    expect(manifest["status"] == "in_progress", "status 非改変")
    expect(isinstance(manifest["created_at"], str) and len(manifest["created_at"]) > 10,
           "created_at timestamp still present")
    # phases: PHASE_ORDER と一致, 各々 status=pending, retries=0 等
    # (Codex 非ブロッキング改善: PHASE_ORDER 動的追随)
    phases = manifest["phases"]
    expect(len(phases) == len(PHASE_ORDER),
           f"phases count == {len(PHASE_ORDER)} (got {len(phases)})")
    expect(set(phases.keys()) == set(PHASE_ORDER),
           f"phases keys == PHASE_ORDER set")
    for phase_name, phase in phases.items():
        if phase["status"] != "pending":
            errors.append(f"phase[{phase_name}].status != 'pending'")
        if phase["retries"] != 0:
            errors.append(f"phase[{phase_name}].retries != 0")
    if not any("phase[" in e for e in errors):
        print("  [OK] 全 phase が pending/retries=0 の初期状態")

# ── 結果 ──────────────────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_3D1: create_manifest が channel_id を記録, no-op として成立")
    sys.exit(0)
