"""
Short Circuit Analysis Engine
Supports: 3-phase (3ph), Single-Line-to-Ground (1ph), Double-Line-to-Ground (2ph_g),
          Line-to-Line (2ph) fault calculations.
Standards: IEC 60909-0:2016 / ANSI C37.010 / ANSI C37.013
"""
import traceback

try:
    import pandapower as pp
    import pandapower.shortcircuit as sc
    PANDAPOWER_OK = True
except ImportError:
    PANDAPOWER_OK = False

from engine.load_flow import build_pandapower_net
from models.database import get_session
from models.schema import Bus, Line, Transformer


FAULT_TYPES = {
    "3ph":    "Three-Phase (3Φ) Balanced Fault",
    "1ph":    "Single-Line-to-Ground (SLG) Fault",
    "2ph":    "Line-to-Line (LL) Fault",
    "2ph_g":  "Double-Line-to-Ground (DLG) Fault",
}


def run_short_circuit(
    project_id: int,
    fault_type: str = "3ph",
    case: str = "max",              # 'max' or 'min'
    standard: str = "iec",          # 'iec' or 'ansi'
    ip: bool = True,                # peak short-circuit current
    ith: bool = True,               # equivalent thermal current
) -> dict:
    """
    Run short circuit study for all buses in the project.

    Returns a dict with per-bus fault currents and a summary.
    """
    if not PANDAPOWER_OK:
        return {"error": "pandapower is not installed. Run: pip install pandapower"}

    if fault_type not in FAULT_TYPES:
        return {"error": f"Unknown fault type '{fault_type}'. Valid: {list(FAULT_TYPES.keys())}"}

    session = get_session()
    try:
        net, bus_map = build_pandapower_net(project_id, session)

        if len(net.bus) == 0:
            return {"error": "No buses in network. Enter network data first."}

        # pandapower SC requires at least one ext_grid
        if net.ext_grid.empty:
            return {"error": "No slack bus defined. Add a Bus with type=Slack (type 3) and a Generator."}

        # pandapower 3.x requires SC parameters on ext_grid
        # Set defaults if not already present
        if "s_sc_max_mva" not in net.ext_grid.columns or net.ext_grid["s_sc_max_mva"].isna().any():
            net.ext_grid["s_sc_max_mva"] = 10000.0   # 10 GVA – strong infinite bus
        if "s_sc_min_mva" not in net.ext_grid.columns or net.ext_grid["s_sc_min_mva"].isna().any():
            net.ext_grid["s_sc_min_mva"] = 8000.0
        if "rx_max" not in net.ext_grid.columns or net.ext_grid["rx_max"].isna().any():
            net.ext_grid["rx_max"] = 0.1
        if "rx_min" not in net.ext_grid.columns or net.ext_grid["rx_min"].isna().any():
            net.ext_grid["rx_min"] = 0.1
        if "x0x_max" not in net.ext_grid.columns or net.ext_grid["x0x_max"].isna().any():
            net.ext_grid["x0x_max"] = 1.0
        if "r0x0_max" not in net.ext_grid.columns or net.ext_grid["r0x0_max"].isna().any():
            net.ext_grid["r0x0_max"] = 0.1

        # Run short circuit
        sc.calc_sc(
            net,
            fault=fault_type,
            case=case,
            ip=ip,
            ith=ith,
            branch_results=True,
        )

        rev_map = {v: k for k, v in bus_map.items()}
        buses_db = {b.id: b for b in session.query(Bus).filter_by(project_id=project_id).all()}

        # Bus SC results
        bus_results = []
        for pp_idx, row in net.res_bus_sc.iterrows():
            db_id = rev_map.get(pp_idx)
            bus = buses_db.get(db_id)
            ikss = float(row.get("ikss_ka", 0))
            skss = float(row.get("skss_mva", 0))
            base_kv = bus.base_kv if bus else net.bus.at[pp_idx, "vn_kv"]
            base_i = skss / (1.732 * base_kv) if base_kv > 0 else 0
            xr = float(row.get("x_r_ratio", row.get("r_fault_ohm", 0)))
            rk = float(row.get("rk_ohm", 0))
            xk = float(row.get("xk_ohm", 0))
            xr_ratio = xk / rk if rk != 0 else None

            bus_results.append(dict(
                bus_id=db_id,
                name=bus.name if bus else f"Bus_{pp_idx}",
                base_kv=base_kv,
                ikss_ka=round(ikss, 4),
                skss_mva=round(skss, 2),
                ip_ka=round(float(row.get("ip_ka", 0)), 4),
                ith_ka=round(float(row.get("ith_ka", 0)), 4),
                rk_ohm=round(rk, 5),
                xk_ohm=round(xk, 5),
                x_r_ratio=round(xr_ratio, 2) if xr_ratio is not None else None,
                status=_assess_sc(ikss, base_kv),
            ))

        # Branch SC results (line/transformer contributions)
        branch_results = []
        if hasattr(net, "res_line_sc") and not net.res_line_sc.empty:
            lines_db = list(session.query(Line).filter_by(project_id=project_id).all())
            for pp_idx, row in net.res_line_sc.iterrows():
                line = lines_db[pp_idx] if pp_idx < len(lines_db) else None
                branch_results.append(dict(
                    type="line",
                    name=line.name if line else f"Line_{pp_idx}",
                    ikss_from_ka=round(float(row.get("ikss_from_ka", 0)), 4),
                    ikss_to_ka=round(float(row.get("ikss_to_ka", 0)), 4),
                ))

        # Maximum bus fault
        if bus_results:
            max_bus = max(bus_results, key=lambda x: x["ikss_ka"])
            min_bus = min(bus_results, key=lambda x: x["ikss_ka"])
        else:
            max_bus = min_bus = None

        summary = _build_sc_summary(bus_results, fault_type, case, standard)

        return dict(
            fault_type=fault_type,
            fault_type_label=FAULT_TYPES[fault_type],
            case=case,
            standard=standard.upper(),
            bus_results=bus_results,
            branch_results=branch_results,
            max_fault_bus=max_bus,
            min_fault_bus=min_bus,
            summary=summary,
        )

    except Exception as exc:
        return {"error": str(exc), "traceback": traceback.format_exc()}
    finally:
        session.close()


def _assess_sc(ikss_ka: float, base_kv: float) -> str:
    """Flag buses with extremely high fault currents."""
    # Rough guidance: >50 kA at any voltage level is very high
    if ikss_ka > 50:
        return "VERY HIGH"
    if ikss_ka > 30:
        return "HIGH"
    return "NORMAL"


def _build_sc_summary(bus_results: list, fault_type: str, case: str, standard: str) -> list[str]:
    findings = []
    if not bus_results:
        return ["No results available."]
    total = len(bus_results)
    max_b = max(bus_results, key=lambda x: x["ikss_ka"])
    min_b = min(bus_results, key=lambda x: x["ikss_ka"])
    findings.append(
        f"Fault type: {FAULT_TYPES[fault_type]} | Case: {case.upper()} | Standard: {standard.upper()}"
    )
    findings.append(
        f"Maximum fault: {max_b['ikss_ka']:.3f} kA / {max_b['skss_mva']:.1f} MVA at bus '{max_b['name']}' "
        f"({max_b['base_kv']} kV)"
    )
    findings.append(
        f"Minimum fault: {min_b['ikss_ka']:.3f} kA / {min_b['skss_mva']:.1f} MVA at bus '{min_b['name']}'"
    )
    high = [b for b in bus_results if b["status"] in ("HIGH", "VERY HIGH")]
    if high:
        findings.append(
            f"CAUTION: {len(high)} bus(es) with fault current > 30 kA – verify equipment interrupting ratings."
        )
    no_xr = [b for b in bus_results if b["x_r_ratio"] is None]
    if not no_xr:
        avg_xr = sum(b["x_r_ratio"] for b in bus_results if b["x_r_ratio"]) / total
        findings.append(f"Average X/R ratio across network: {avg_xr:.1f}")
    findings.append(
        "Equipment interrupting ratings should be verified against calculated fault currents "
        "per ANSI C37.010 or IEC 62271-100."
    )
    return findings
