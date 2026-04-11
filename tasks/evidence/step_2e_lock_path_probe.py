"""Step 2-ε probe: 3 consumer (generator/skill_upload/preflight_runtime) が
cfg 由来 _lock_path を hardcoded と bit-identical に解決できるか検証.

Windows native Python + cwd=scripts/ で本番形態を実測.
"""
import sys
from pathlib import Path

EXPECTED_LOCK_REL = "logs/last_upload_date.txt"
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# scripts/ を sys.path 先頭に (本番 run.bat と同形態)
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

errors = []


def expect(cond, msg):
    if cond:
        print(f"  [OK] {msg}")
    else:
        print(f"  [NG] {msg}")
        errors.append(msg)


# ── 1. _channel から cfg 読込 ──────────────────────
print("[1] load_channel('health')")
from _channel import load_channel
cfg = load_channel("health")
expect(cfg.paths.lock_file == EXPECTED_LOCK_REL,
       f"cfg.paths.lock_file == {EXPECTED_LOCK_REL} (got {cfg.paths.lock_file})")

# ── 2. generator.py consumer と同じ解決 ─────────────
print("[2] generator.py _lock_path 相当")
gen_lock = PROJECT_ROOT / cfg.paths.lock_file
hardcoded_gen = PROJECT_ROOT / "logs" / "last_upload_date.txt"
expect(gen_lock.resolve() == hardcoded_gen.resolve(),
       f"generator: {gen_lock} == {hardcoded_gen}")

# ── 3. skill_upload.py consumer と同じ解決 ───────────
print("[3] skill_upload.run_upload _lock_path 相当")
# skill_upload.py は Path(__file__).parent.parent.parent / cfg.paths.lock_file
skill_upload_py = PROJECT_ROOT / "scripts" / "skills" / "skill_upload.py"
su_lock = skill_upload_py.parent.parent.parent / cfg.paths.lock_file
expect(su_lock.resolve() == hardcoded_gen.resolve(),
       f"skill_upload: {su_lock} == {hardcoded_gen}")

# ── 4. skill_upload の .lock 派生 ───────────────────
print("[4] _upload_lock_file .lock 派生")
su_dotlock = su_lock.with_suffix(".lock")
expected_dotlock = PROJECT_ROOT / "logs" / "last_upload_date.lock"
expect(su_dotlock.resolve() == expected_dotlock.resolve(),
       f".lock: {su_dotlock} == {expected_dotlock}")

# ── 5. preflight_runtime.py consumer と同じ解決 ──────
print("[5] preflight_runtime._check_duplicate_upload lock_file 相当")
# PROJECT_ROOT / cfg.paths.lock_file
pf_lock = PROJECT_ROOT / cfg.paths.lock_file
expect(pf_lock.resolve() == hardcoded_gen.resolve(),
       f"preflight: {pf_lock} == {hardcoded_gen}")

# ── 6. 3 consumers が同じ Path を指すこと ─────────────
print("[6] 3 consumers bit-identical")
expect(gen_lock.resolve() == su_lock.resolve() == pf_lock.resolve(),
       "generator == skill_upload == preflight")

# ── 7. import check: generator と skill_upload が壊れていないか ─
print("[7] import health")
try:
    import generator  # noqa: F401
    print("  [OK] generator import")
except Exception as e:
    print(f"  [NG] generator import failed: {e}")
    errors.append(f"generator import: {e}")

try:
    from skills import skill_upload  # noqa: F401
    print("  [OK] skills.skill_upload import")
except Exception as e:
    print(f"  [NG] skills.skill_upload import failed: {e}")
    errors.append(f"skill_upload import: {e}")

try:
    import preflight_runtime  # noqa: F401
    print("  [OK] preflight_runtime import")
except Exception as e:
    print(f"  [NG] preflight_runtime import failed: {e}")
    errors.append(f"preflight_runtime import: {e}")

# ── 結果 ──────────────────────────────────────────
if errors:
    print(f"\nPROBE_FAIL: {len(errors)} errors")
    for e in errors:
        print(f"  - {e}")
    sys.exit(1)
else:
    print("\nPROBE_OK_STEP_2E: all bit-identical, imports healthy")
    sys.exit(0)
