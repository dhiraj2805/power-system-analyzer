"""
Grounding System Analysis Engine
Implements IEEE Std 80-2013 "Guide for Safety in AC Substation Grounding".

Calculates:
  - Ground grid resistance (Sverak formula, Eq. 57)
  - Ground potential rise (GPR)
  - Mesh voltage (Em)
  - Step voltage (Es)
  - Tolerable touch and step voltages for 50 kg and 70 kg body weights
  - Surface layer reduction factor (Cs)
  - Conductor size adequacy
"""
import math
import traceback
import numpy as np

from models.database import get_session
from models.schema import GroundingGrid


# Physical constants
COPPER_RESISTIVITY   = 1.72e-8    # Ω·m at 20°C
ALUMINUM_RESISTIVITY = 2.82e-8    # Ω·m at 20°C
EARTH_SURFACE_LAYER_DEFAULT_DEPTH = 0.1   # m


def run_grounding_analysis(project_id: int) -> dict:
    """Run grounding analysis for all grounding grids in a project."""
    session = get_session()
    try:
        grids = session.query(GroundingGrid).filter_by(project_id=project_id).all()
        if not grids:
            return {"error": "No grounding grids defined. Add a grounding grid first."}

        grid_results = [_analyze_grid(g) for g in grids]

        all_compliant = all(r.get("compliant", False) for r in grid_results)
        return dict(
            num_grids=len(grids),
            grid_results=grid_results,
            all_compliant=all_compliant,
            summary=_build_grounding_summary(grid_results),
        )
    except Exception as exc:
        return {"error": str(exc), "traceback": traceback.format_exc()}
    finally:
        session.close()


def analyze_single_grid(
    grid_length_m: float,
    grid_width_m: float,
    conductor_spacing_m: float,
    burial_depth_m: float,
    conductor_diameter_m: float,
    soil_resistivity_ohm_m: float,
    surface_resistivity_ohm_m: float,
    surface_layer_depth_m: float,
    fault_current_ka: float,
    fault_duration_s: float,
    decrement_factor: float = 1.0,
    num_rods: int = 0,
    rod_length_m: float = 3.0,
    rod_diameter_m: float = 0.016,
    name: str = "Grid",
) -> dict:
    """
    Run IEEE 80-2013 grounding calculations without requiring a database record.
    All length parameters in metres, current in kA.
    """
    class _Grid:
        pass

    g = _Grid()
    g.name = name
    g.grid_length_m = grid_length_m
    g.grid_width_m = grid_width_m
    g.conductor_spacing_m = conductor_spacing_m
    g.burial_depth_m = burial_depth_m
    g.conductor_diameter_m = conductor_diameter_m
    g.soil_resistivity_ohm_m = soil_resistivity_ohm_m
    g.surface_resistivity_ohm_m = surface_resistivity_ohm_m
    g.surface_layer_depth_m = surface_layer_depth_m
    g.fault_current_ka = fault_current_ka
    g.fault_duration_s = fault_duration_s
    g.decrement_factor = decrement_factor
    g.num_ground_rods = num_rods
    g.rod_length_m = rod_length_m
    g.rod_diameter_m = rod_diameter_m
    return _analyze_grid(g)


def _analyze_grid(g) -> dict:
    """Core IEEE 80-2013 calculations for one grid object."""
    rho   = g.soil_resistivity_ohm_m
    rho_s = g.surface_resistivity_ohm_m
    h     = g.burial_depth_m
    D     = g.conductor_spacing_m
    d     = g.conductor_diameter_m
    Lx    = g.grid_length_m
    Ly    = g.grid_width_m
    h_s   = g.surface_layer_depth_m
    I_g   = g.fault_current_ka * 1000.0 * g.decrement_factor   # A
    t_f   = g.fault_duration_s
    n_rods= g.num_ground_rods
    Lr    = g.rod_length_m
    dr    = g.rod_diameter_m

    # ---- Grid geometry ----
    A  = Lx * Ly                          # m²
    nx = max(2, int(Lx / D) + 1)
    ny = max(2, int(Ly / D) + 1)
    n  = math.sqrt(nx * ny)               # effective number of conductors (Eq. 85)

    # Total buried conductor length
    LC = nx * Ly + ny * Lx                # m
    # Effective length including ground rods (Eq. 85)
    if n_rods > 0 and Lr > 0:
        LR = n_rods * Lr
        # Schwarz formula correction factor
        Lr_corr = (1.55 + 1.22 * (Lr / math.sqrt(Lx**2 + Ly**2))) * LR
        LM  = LC + Lr_corr   # for mesh voltage
        LS  = 0.75 * LC + 0.85 * LR   # for step voltage
        L_T = LC + LR        # total for resistance
    else:
        LR = 0
        LM = LC
        LS = 0.75 * LC
        L_T = LC

    # ---- Grid resistance (IEEE 80 Eq. 57, Sverak) ----
    sqrt_A = math.sqrt(A)
    factor = (1.0 / L_T
              + 1.0 / (math.sqrt(20.0 * A))
                * (1.0 + 1.0 / (1.0 + h * math.sqrt(20.0 / A))))
    R_g = rho * factor

    # ---- Ground Potential Rise ----
    GPR = I_g * R_g

    # ---- Surface layer reduction factor (Eq. 27) ----
    Cs = _calc_cs(rho, rho_s, h_s)

    # ---- Irregularity factor Ki (Eq. 89) ----
    Ki = 0.644 + 0.148 * n

    # ---- Mesh voltage Em (Eq. 80-88) ----
    Kh = math.sqrt(1.0 + h / 1.0)   # simplified (h0 = 1 m reference)

    if n_rods > 0:
        Kii = 1.0 / (2.0 * n ** (2.0 / n))
    else:
        Kii = 1.0

    # Km (Eq. 88)
    term1 = math.log(D**2 / (16.0 * h * d) + (D + 2.0 * h)**2 / (8.0 * D * d) - h / (4.0 * d))
    term2 = (Kii / Kh) * math.log(8.0 / (math.pi * (2.0 * n - 1)))
    Km = (1.0 / (2.0 * math.pi)) * (term1 + term2)

    Em = rho * Km * Ki * I_g / LM

    # ---- Step voltage Es (Eq. 92) ----
    Ks = (1.0 / math.pi) * (
        1.0 / (2.0 * h)
        + 1.0 / (D + h)
        + (1.0 / D) * (1.0 - 0.5 ** (n - 2))
    )
    Es = rho * Ks * Ki * I_g / LS

    # ---- Tolerable voltages (IEEE 80 Section 8) ----
    # Body weight 50 kg (conservative, distribution systems)
    Et_50  = (1000.0 + 1.5 * Cs * rho_s) * (0.116 / math.sqrt(t_f))   # touch
    Es_50  = (1000.0 + 6.0 * Cs * rho_s) * (0.116 / math.sqrt(t_f))   # step
    # Body weight 70 kg (transmission substations)
    Et_70  = (1000.0 + 1.5 * Cs * rho_s) * (0.157 / math.sqrt(t_f))
    Es_70  = (1000.0 + 6.0 * Cs * rho_s) * (0.157 / math.sqrt(t_f))

    touch_safe = Em <= Et_50
    step_safe  = Es <= Es_50
    gpr_ok     = GPR < 5.0 * Et_50   # IEEE 80 simplified screening criterion

    compliant = touch_safe and step_safe

    # ---- Conductor sizing adequacy (IEEE 80 Eq. 37, simplified Neher-McGrath) ----
    # Minimum cross-sectional area for copper:  A_mm2 ≥ I · √(t_c) / (TCAP/αρr·ln(...)
    # Simplified check: use Eq. 37 for copper at 20°C → 65°C max
    Acca_factor = 7.06e4   # A·s^0.5/mm² for soft-drawn copper (IEEE 80 Table 1)
    A_min_mm2 = (I_g * math.sqrt(t_f)) / Acca_factor
    # Actual conductor cross-section from diameter
    A_actual_mm2 = math.pi * (d / 2.0)**2 * 1e6   # mm²
    conductor_adequate = A_actual_mm2 >= A_min_mm2

    # ---- Recommendations ----
    recommendations = _generate_recommendations(
        touch_safe, step_safe, conductor_adequate,
        Em, Et_50, Es, Es_50, GPR, R_g,
        Lx, Ly, D, n_rods, rho, rho_s
    )

    return dict(
        name=g.name,
        # Input summary
        grid_area_m2=round(A, 1),
        total_conductor_m=round(L_T, 1),
        nx_conductors=nx,
        ny_conductors=ny,
        fault_current_a=round(I_g, 1),
        # Results
        grid_resistance_ohm=round(R_g, 4),
        gpr_v=round(GPR, 1),
        mesh_voltage_v=round(Em, 1),
        step_voltage_v=round(Es, 1),
        # Tolerable limits
        tolerable_touch_50kg_v=round(Et_50, 1),
        tolerable_step_50kg_v=round(Es_50, 1),
        tolerable_touch_70kg_v=round(Et_70, 1),
        tolerable_step_70kg_v=round(Es_70, 1),
        # Intermediate factors
        Cs=round(Cs, 4),
        Km=round(Km, 4),
        Ks=round(Ks, 4),
        Ki=round(Ki, 3),
        n_equivalent=round(n, 2),
        # Compliance
        touch_voltage_safe=touch_safe,
        step_voltage_safe=step_safe,
        gpr_screening_ok=gpr_ok,
        conductor_adequate=conductor_adequate,
        conductor_actual_mm2=round(A_actual_mm2, 2),
        conductor_required_mm2=round(A_min_mm2, 2),
        compliant=compliant,
        recommendations=recommendations,
    )


def _calc_cs(rho: float, rho_s: float, h_s: float) -> float:
    """Surface layer reduction factor Cs (IEEE 80-2013, Eq. 27 approximation)."""
    if rho_s <= 0 or rho <= 0 or h_s <= 0:
        return 1.0
    ratio = rho / rho_s
    if ratio >= 1.0:
        return 1.0
    Cs = 1.0 - 0.09 * (1.0 - ratio) / (2.0 * h_s + 0.09)
    return max(Cs, 0.25)


def _generate_recommendations(
    touch_safe, step_safe, conductor_ok,
    Em, Et, Es, Es_lim, GPR, Rg,
    Lx, Ly, D, n_rods, rho, rho_s
) -> list[str]:
    recs = []

    if not touch_safe:
        overage = (Em / Et - 1.0) * 100
        recs.append(
            f"TOUCH VOLTAGE VIOLATION: Em={Em:.0f} V exceeds tolerable {Et:.0f} V "
            f"(+{overage:.0f}%). Options:"
        )
        recs.append("  1. Reduce conductor spacing D to lower mesh voltage.")
        recs.append("  2. Increase grid burial depth h.")
        recs.append("  3. Add surface insulating layer (crushed rock ρₛ ≥ 2500 Ω·m).")
        recs.append("  4. Add gradient control conductors near fence/equipment.")

    if not step_safe:
        overage = (Es / Es_lim - 1.0) * 100
        recs.append(
            f"STEP VOLTAGE VIOLATION: Es={Es:.0f} V exceeds tolerable {Es_lim:.0f} V "
            f"(+{overage:.0f}%). Options:"
        )
        recs.append("  1. Add peripheral ground rods to reduce step voltage at grid edges.")
        recs.append("  2. Extend the grid beyond substation fence line.")
        recs.append("  3. Install surface insulating layer.")

    if not conductor_ok:
        recs.append(
            "CONDUCTOR SIZE: Conductor cross-section may be insufficient for the fault current "
            "and clearing time. Verify against IEEE 80 Table 1."
        )

    if touch_safe and step_safe and conductor_ok:
        recs.append("Grid design meets IEEE 80-2013 touch voltage, step voltage, and conductor size requirements.")

    if Rg > 1.0:
        recs.append(f"Grid resistance Rg = {Rg:.3f} Ω is above 1 Ω – consider enlarging grid or adding ground rods.")

    if n_rods == 0:
        recs.append("Consider adding ground rods at grid corners and along perimeter to reduce resistance.")

    return recs


def _build_grounding_summary(grid_results: list) -> list[str]:
    findings = []
    findings.append(f"Grounding analysis for {len(grid_results)} grid(s) per IEEE Std 80-2013.")
    for r in grid_results:
        status = "COMPLIANT" if r["compliant"] else "NON-COMPLIANT"
        findings.append(
            f"  {r['name']}: Rg={r['grid_resistance_ohm']:.4f} Ω, "
            f"GPR={r['gpr_v']:.0f} V, Em={r['mesh_voltage_v']:.0f} V (limit {r['tolerable_touch_50kg_v']:.0f} V), "
            f"Es={r['step_voltage_v']:.0f} V (limit {r['tolerable_step_50kg_v']:.0f} V)  → {status}"
        )
    non_comp = [r for r in grid_results if not r["compliant"]]
    if non_comp:
        findings.append(
            f"ACTION REQUIRED: {len(non_comp)} grid(s) do not meet IEEE 80-2013 safety requirements."
        )
    else:
        findings.append("All grids meet IEEE 80-2013 touch and step voltage safety requirements.")
    return findings
