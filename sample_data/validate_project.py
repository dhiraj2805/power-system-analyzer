"""
Validate Sample Project
=======================
Runs all five analysis engines against the seeded sample project and
reports pass/fail for each.  Exits with code 0 on full success, 1 on
any failure.

Usage
-----
    python sample_data/validate_project.py          # from project root
    python validate_project.py                      # from sample_data/
"""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from models.database import init_db, get_session
from models.schema import Project

# Import seed helper
from seed_project import seed, PROJECT_NAME  # type: ignore  (same package)

from engine.load_flow          import run_load_flow
from engine.short_circuit      import run_short_circuit
from engine.transient_stability import run_transient_stability
from engine.protection          import check_coordination
from engine.grounding           import run_grounding_analysis


# ── ANSI colour helpers (Windows 10+) ────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
RESET  = "\033[0m"
BOLD   = "\033[1m"

def _ok(msg):   print(f"  {GREEN}✅ PASS{RESET}  {msg}")
def _fail(msg): print(f"  {RED}❌ FAIL{RESET}  {msg}")
def _warn(msg): print(f"  {YELLOW}⚠  WARN{RESET}  {msg}")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _check(result: dict, name: str, required_keys: list[str]) -> bool:
    """Generic result checker – returns True if no error and required keys present."""
    if "error" in result:
        _fail(f"{name}: {result['error']}")
        return False
    for key in required_keys:
        if key not in result:
            _fail(f"{name}: missing expected key '{key}' in result")
            return False
    _ok(f"{name}: completed successfully")
    # Print summary lines at one level of indent
    for s in result.get("summary", [])[:6]:
        print(f"         {s}")
    return True


# ── Main validation ───────────────────────────────────────────────────────────

def validate(pid: int) -> bool:
    print(f"\n{BOLD}Running all analysis engines on project id={pid}{RESET}\n")
    all_pass = True

    # 1. Load Flow ─────────────────────────────────────────────────────────────
    print(f"{BOLD}1. Load Flow (Newton-Raphson){RESET}")
    try:
        r = run_load_flow(pid, algorithm="nr")
        ok = _check(r, "Load Flow", ["bus_results", "converged"])
        if ok:
            converged = r.get("converged", False)
            if converged:
                _ok("Load flow converged")
            else:
                _warn("Load flow did NOT converge – check network data")
                ok = False
        all_pass = all_pass and ok
    except Exception as exc:
        _fail(f"Load Flow raised exception: {exc}")
        all_pass = False

    # 2. Short Circuit ─────────────────────────────────────────────────────────
    print(f"\n{BOLD}2. Short Circuit (IEC 60909 / 3-phase){RESET}")
    try:
        r = run_short_circuit(pid, fault_type="3ph", case="max")
        ok = _check(r, "Short Circuit", ["bus_results"])
        all_pass = all_pass and ok
    except Exception as exc:
        _fail(f"Short Circuit raised exception: {exc}")
        all_pass = False

    # 3. Transient Stability ───────────────────────────────────────────────────
    print(f"\n{BOLD}3. Transient Stability (Swing Equation){RESET}")
    try:
        # Look up the slack bus to use as fault location
        from models.schema import Bus as _Bus
        _s = get_session()
        try:
            _slack = _s.query(_Bus).filter_by(project_id=pid, bus_type=3).first()
            _fault_bus_id = _slack.id if _slack else None
        finally:
            _s.close()

        if _fault_bus_id is None:
            _fail("Transient Stability: no slack bus found for fault simulation")
            all_pass = False
        else:
            # fault_clear=0.25 s means fault duration ≈ 150 ms (start 0.1 → clear 0.25)
            r = run_transient_stability(
                pid,
                fault_bus_id=_fault_bus_id,
                fault_start=0.1,
                fault_clear=0.25,
                sim_time=2.0,
            )
            ok = _check(r, "Transient Stability", ["generators"])
            all_pass = all_pass and ok
    except Exception as exc:
        _fail(f"Transient Stability raised exception: {exc}")
        all_pass = False

    # 4. Protection Coordination ───────────────────────────────────────────────
    print(f"\n{BOLD}4. Protection Coordination (CTI check){RESET}")
    try:
        r = check_coordination(pid, cti=0.30)
        ok = _check(r, "Protection", ["pairs"])
        all_pass = all_pass and ok
    except Exception as exc:
        _fail(f"Protection Coordination raised exception: {exc}")
        all_pass = False

    # 5. Grounding ─────────────────────────────────────────────────────────────
    print(f"\n{BOLD}5. Grounding System (IEEE 80-2013){RESET}")
    try:
        r = run_grounding_analysis(pid)
        ok = _check(r, "Grounding", ["grid_results"])
        if ok:
            for gr in r.get("grid_results", []):
                status = "COMPLIANT ✅" if gr["compliant"] else "NON-COMPLIANT ❌"
                print(f"         Grid '{gr['name']}': {status}  "
                      f"(Rg={gr['grid_resistance_ohm']:.4f} Ω, "
                      f"Em={gr['mesh_voltage_v']:.0f} V / lim {gr['tolerable_touch_50kg_v']:.0f} V)")
        all_pass = all_pass and ok
    except Exception as exc:
        _fail(f"Grounding raised exception: {exc}")
        all_pass = False

    # ── PDF Report (smoke test only, no AI) ───────────────────────────────────
    print(f"\n{BOLD}6. PDF Report Generator (smoke test){RESET}")
    try:
        from reports.generator import generate_report, REPORTLAB_OK
        if not REPORTLAB_OK:
            _warn("reportlab not installed – PDF test skipped")
        else:
            session = get_session()
            try:
                proj = session.query(Project).filter_by(id=pid).first()
            finally:
                session.close()
            p_info = {
                "name": proj.name, "client": proj.client,
                "engineer": proj.engineer, "date": proj.date,
                "description": proj.description,
                "mva_base": proj.mva_base, "frequency": proj.frequency,
            }
            sample_results = {
                "load_flow":     run_load_flow(pid),
                "short_circuit": run_short_circuit(pid),
                "grounding":     run_grounding_analysis(pid),
            }
            pdf_bytes = generate_report(p_info, sample_results)
            size_kb = len(pdf_bytes) / 1024
            if size_kb > 5:
                _ok(f"PDF generated: {size_kb:.1f} KB")
            else:
                _fail(f"PDF too small ({size_kb:.1f} KB) – may be malformed")
                all_pass = False
    except Exception as exc:
        _fail(f"PDF report raised exception: {exc}")
        all_pass = False

    return all_pass


def main():
    print("=" * 60)
    print("Power System Analyzer – Validation Suite")
    print("=" * 60)

    init_db()

    # Seed (or re-use existing) project
    print("\n[1/2] Seeding sample project …")
    pid = seed()
    if pid is None:
        print(f"{RED}Seed failed – aborting validation.{RESET}")
        return False

    print("\n[2/2] Running validation …")
    passed = validate(pid)

    print("\n" + "=" * 60)
    if passed:
        print(f"{GREEN}{BOLD}ALL CHECKS PASSED ✅{RESET}")
    else:
        print(f"{RED}{BOLD}SOME CHECKS FAILED ❌  – review output above{RESET}")
    print("=" * 60 + "\n")
    return passed


if __name__ == "__main__":
    ok = main()
    sys.exit(0 if ok else 1)
