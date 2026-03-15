"""
Load Flow Analysis Engine
Uses pandapower for Newton-Raphson / IWAMOTO / BFS power-flow calculations.
Standards reference: IEEE Std 399 (Brown Book), IEC 60909
"""
import sys
import traceback
import numpy as np
import pandas as pd

try:
    import pandapower as pp
    PANDAPOWER_OK = True
except ImportError:
    PANDAPOWER_OK = False

from models.database import get_session
from models.schema import Bus, Line, Transformer, Generator, Load, Shunt, Project


# ---------------------------------------------------------------------------
# Network builder
# ---------------------------------------------------------------------------

def build_pandapower_net(project_id: int, session=None) -> tuple:
    """
    Build a pandapower network object from the database for a given project.
    Returns (net, bus_map) where bus_map = {db_bus_id: pp_bus_index}.
    """
    close = session is None
    if session is None:
        session = get_session()

    try:
        project = session.query(Project).filter_by(id=project_id).first()
        if not project:
            raise ValueError(f"Project id={project_id} not found in database.")

        net = pp.create_empty_network(sn_mva=project.mva_base, f_hz=project.frequency)

        # ---- Buses ----
        bus_map: dict[int, int] = {}
        for bus in session.query(Bus).filter_by(project_id=project_id).all():
            pp_idx = pp.create_bus(
                net,
                vn_kv=bus.base_kv,
                name=bus.name,
                type="b",
                zone=bus.zone or None,
            )
            bus_map[bus.id] = pp_idx

        # ---- External grid (slack bus) ----
        for bus in session.query(Bus).filter_by(project_id=project_id, bus_type=3).all():
            pp.create_ext_grid(
                net,
                bus=bus_map[bus.id],
                vm_pu=bus.vm_pu or 1.0,
                va_degree=0.0,
                name=f"Slack_{bus.name}",
            )

        # ---- Lines ----
        for line in session.query(Line).filter_by(project_id=project_id).all():
            if not line.in_service:
                continue
            if line.from_bus_id not in bus_map or line.to_bus_id not in bus_map:
                continue
            pp.create_line_from_parameters(
                net,
                from_bus=bus_map[line.from_bus_id],
                to_bus=bus_map[line.to_bus_id],
                length_km=line.length_km,
                r_ohm_per_km=line.r_ohm_per_km,
                x_ohm_per_km=line.x_ohm_per_km,
                c_nf_per_km=line.c_nf_per_km or 0.0,
                max_i_ka=line.max_i_ka or 9999.0,
                name=line.name,
                in_service=line.in_service,
                # Zero-sequence parameters (optional, for SC)
                r0_ohm_per_km=line.r0_ohm_per_km if line.r0_ohm_per_km else line.r_ohm_per_km * 3,
                x0_ohm_per_km=line.x0_ohm_per_km if line.x0_ohm_per_km else line.x_ohm_per_km * 3,
            )

        # ---- Transformers ----
        for trafo in session.query(Transformer).filter_by(project_id=project_id).all():
            if not trafo.in_service:
                continue
            if trafo.hv_bus_id not in bus_map or trafo.lv_bus_id not in bus_map:
                continue
            try:
                pp.create_transformer_from_parameters(
                    net,
                    hv_bus=bus_map[trafo.hv_bus_id],
                    lv_bus=bus_map[trafo.lv_bus_id],
                    sn_mva=trafo.sn_mva,
                    vn_hv_kv=trafo.vn_hv_kv,
                    vn_lv_kv=trafo.vn_lv_kv,
                    vkr_percent=trafo.vkr_percent,
                    vk_percent=trafo.vk_percent,
                    pfe_kw=trafo.pfe_kw or 0.0,
                    i0_percent=trafo.i0_percent or 0.0,
                    name=trafo.name,
                    tap_pos=trafo.tap_pos,
                    tap_neutral=trafo.tap_neutral,
                    tap_min=trafo.tap_min,
                    tap_max=trafo.tap_max,
                    tap_step_percent=trafo.tap_step_pct,
                    vector_group=trafo.vector_group or "Dyn11",
                    vk0_percent=trafo.vk_percent,          # zero-seq ~ pos-seq for simplicity
                    vkr0_percent=trafo.vkr_percent,
                )
            except Exception:
                # Fallback without zero-seq params for older pandapower
                pp.create_transformer_from_parameters(
                    net,
                    hv_bus=bus_map[trafo.hv_bus_id],
                    lv_bus=bus_map[trafo.lv_bus_id],
                    sn_mva=trafo.sn_mva,
                    vn_hv_kv=trafo.vn_hv_kv,
                    vn_lv_kv=trafo.vn_lv_kv,
                    vkr_percent=trafo.vkr_percent,
                    vk_percent=trafo.vk_percent,
                    pfe_kw=trafo.pfe_kw or 0.0,
                    i0_percent=trafo.i0_percent or 0.0,
                    name=trafo.name,
                )

        # ---- Generators (PV) ----
        for gen in session.query(Generator).filter_by(project_id=project_id).all():
            if not gen.in_service or gen.bus_id not in bus_map:
                continue
            # Skip slack-bus generators (already modelled as ext_grid)
            bus_obj = session.query(Bus).filter_by(id=gen.bus_id).first()
            if bus_obj and bus_obj.bus_type == 3:
                continue
            # pandapower 3.x needs vn_kv on gen for SC calculations
            gen_vn_kv  = bus_obj.base_kv if bus_obj else 1.0
            sn_mva_gen = gen.sn_mva or 100.0
            # Convert per-unit resistance to ohms on machine base
            # Z_base (Ω) = vn_kv² / sn_mva
            z_base = gen_vn_kv ** 2 / sn_mva_gen
            rdss_ohm = (gen.ra_pu or 0.001) * z_base
            pp.create_gen(
                net,
                bus=bus_map[gen.bus_id],
                p_mw=gen.p_mw,
                vm_pu=gen.vm_pu or 1.0,
                vn_kv=gen_vn_kv,
                sn_mva=sn_mva_gen,
                name=gen.name,
                max_q_mvar=gen.max_q_mvar or 9999.0,
                min_q_mvar=gen.min_q_mvar or -9999.0,
                # SC parameters (pandapower 3.x uses rdss_ohm)
                xdss_pu=gen.xd_dbl_prime_pu or 0.2,
                rdss_ohm=rdss_ohm,
                cos_phi=0.8,
            )

        # ---- Loads ----
        for load in session.query(Load).filter_by(project_id=project_id).all():
            if not load.in_service or load.bus_id not in bus_map:
                continue
            pp.create_load(
                net,
                bus=bus_map[load.bus_id],
                p_mw=load.p_mw,
                q_mvar=load.q_mvar or 0.0,
                name=load.name,
            )

        # ---- Shunts ----
        for shunt in session.query(Shunt).filter_by(project_id=project_id).all():
            if not shunt.in_service or shunt.bus_id not in bus_map:
                continue
            pp.create_shunt(
                net,
                bus=bus_map[shunt.bus_id],
                q_mvar=-shunt.q_mvar,  # pandapower sign: positive = inductive absorption
                p_mw=0.0,
                name=shunt.name,
            )

        return net, bus_map

    finally:
        if close:
            session.close()


# ---------------------------------------------------------------------------
# Load flow runner
# ---------------------------------------------------------------------------

def run_load_flow(
    project_id: int,
    algorithm: str = "nr",
    max_iteration: int = 50,
    tolerance_mva: float = 1e-8,
    calculate_voltage_angles: bool = True,
    enforce_q_lims: bool = True,
) -> dict:
    """
    Run load flow for the given project and return a results dict.

    Algorithm options: 'nr' (Newton-Raphson), 'iwamoto_nr', 'bfsw' (radial/distribution).
    """
    if not PANDAPOWER_OK:
        return {"error": "pandapower is not installed. Run: pip install pandapower"}

    session = get_session()
    try:
        net, bus_map = build_pandapower_net(project_id, session)

        if len(net.bus) == 0:
            return {"error": "Network has no buses. Please enter network data first."}

        pp.runpp(
            net,
            algorithm=algorithm,
            max_iteration=max_iteration,
            tolerance_mva=tolerance_mva,
            calculate_voltage_angles=calculate_voltage_angles,
            enforce_q_lims=enforce_q_lims,
        )

        return _extract_results(net, session, project_id, bus_map)

    except pp.powerflow.LoadflowNotConverged:
        return {"error": "Load flow did not converge. Check network data (slack bus, connectivity)."}
    except Exception as exc:
        return {"error": str(exc), "traceback": traceback.format_exc()}
    finally:
        session.close()


# ---------------------------------------------------------------------------
# Result extractor
# ---------------------------------------------------------------------------

def _extract_results(net, session, project_id: int, bus_map: dict) -> dict:
    rev_map = {v: k for k, v in bus_map.items()}
    buses_db = {b.id: b for b in session.query(Bus).filter_by(project_id=project_id).all()}
    lines_db = list(session.query(Line).filter_by(project_id=project_id).all())
    trafos_db = list(session.query(Transformer).filter_by(project_id=project_id).all())

    # ---- Bus results ----
    bus_rows = []
    for pp_idx, row in net.res_bus.iterrows():
        db_id = rev_map.get(pp_idx)
        bus = buses_db.get(db_id)
        base_kv = bus.base_kv if bus else net.bus.at[pp_idx, "vn_kv"]
        vm = float(row["vm_pu"])
        status = "VIOLATION" if vm < 0.95 or vm > 1.05 else ("WARNING" if vm < 0.97 or vm > 1.03 else "OK")
        bus_rows.append(dict(
            bus_id=db_id,
            name=bus.name if bus else f"Bus_{pp_idx}",
            base_kv=base_kv,
            vm_pu=round(vm, 5),
            va_deg=round(float(row["va_degree"]), 3),
            vm_kv=round(vm * base_kv, 4),
            p_mw=round(float(row["p_mw"]), 4),
            q_mvar=round(float(row["q_mvar"]), 4),
            status=status,
        ))

    # ---- Line results ----
    line_rows = []
    for pp_idx, row in net.res_line.iterrows():
        line = lines_db[pp_idx] if pp_idx < len(lines_db) else None
        loading = float(row["loading_percent"])
        status = "OVERLOADED" if loading > 100 else ("WARNING" if loading > 80 else "OK")
        line_rows.append(dict(
            name=line.name if line else f"Line_{pp_idx}",
            from_bus=buses_db[line.from_bus_id].name if line and line.from_bus_id in buses_db else "",
            to_bus=buses_db[line.to_bus_id].name if line and line.to_bus_id in buses_db else "",
            p_from_mw=round(float(row["p_from_mw"]), 4),
            q_from_mvar=round(float(row["q_from_mvar"]), 4),
            p_to_mw=round(float(row["p_to_mw"]), 4),
            q_to_mvar=round(float(row["q_to_mvar"]), 4),
            pl_mw=round(float(row["pl_mw"]), 6),
            ql_mvar=round(float(row["ql_mvar"]), 6),
            i_from_ka=round(float(row["i_from_ka"]), 5),
            loading_pct=round(loading, 2),
            status=status,
        ))

    # ---- Transformer results ----
    trafo_rows = []
    for pp_idx, row in net.res_trafo.iterrows():
        trafo = trafos_db[pp_idx] if pp_idx < len(trafos_db) else None
        loading = float(row["loading_percent"])
        status = "OVERLOADED" if loading > 100 else ("WARNING" if loading > 80 else "OK")
        trafo_rows.append(dict(
            name=trafo.name if trafo else f"Trafo_{pp_idx}",
            hv_bus=buses_db[trafo.hv_bus_id].name if trafo and trafo.hv_bus_id in buses_db else "",
            lv_bus=buses_db[trafo.lv_bus_id].name if trafo and trafo.lv_bus_id in buses_db else "",
            p_hv_mw=round(float(row["p_hv_mw"]), 4),
            q_hv_mvar=round(float(row["q_hv_mvar"]), 4),
            p_lv_mw=round(float(row["p_lv_mw"]), 4),
            q_lv_mvar=round(float(row["q_lv_mvar"]), 4),
            pl_mw=round(float(row["pl_mw"]), 6),
            loading_pct=round(loading, 2),
            status=status,
        ))

    # ---- Generator dispatch ----
    gen_rows = []
    for pp_idx, row in net.res_gen.iterrows():
        gen_rows.append(dict(
            name=net.gen.at[pp_idx, "name"],
            p_mw=round(float(row["p_mw"]), 4),
            q_mvar=round(float(row["q_mvar"]), 4),
            vm_pu=round(float(row["vm_pu"]), 5),
        ))

    # External grid contribution
    ext_rows = []
    for pp_idx, row in net.res_ext_grid.iterrows():
        ext_rows.append(dict(
            name=net.ext_grid.at[pp_idx, "name"],
            p_mw=round(float(row["p_mw"]), 4),
            q_mvar=round(float(row["q_mvar"]), 4),
        ))

    total_gen = (
        net.res_gen["p_mw"].sum() + net.res_ext_grid["p_mw"].sum()
        if not net.res_gen.empty else net.res_ext_grid["p_mw"].sum()
    )
    total_load = net.res_load["p_mw"].sum() if not net.res_load.empty else 0.0
    total_line_loss = net.res_line["pl_mw"].sum() if not net.res_line.empty else 0.0
    total_trafo_loss = net.res_trafo["pl_mw"].sum() if not net.res_trafo.empty else 0.0

    violations = [b for b in bus_rows if b["status"] != "OK"]
    overloads = [e for e in line_rows + trafo_rows if e["status"] == "OVERLOADED"]

    return dict(
        converged=True,
        algorithm=net.converged,
        bus_results=bus_rows,
        line_results=line_rows,
        trafo_results=trafo_rows,
        gen_results=gen_rows,
        ext_grid_results=ext_rows,
        total_generation_mw=round(float(total_gen), 4),
        total_load_mw=round(float(total_load), 4),
        total_line_losses_mw=round(float(total_line_loss), 6),
        total_trafo_losses_mw=round(float(total_trafo_loss), 6),
        total_losses_mw=round(float(total_line_loss + total_trafo_loss), 6),
        voltage_violations=violations,
        overloads=overloads,
        summary=_build_summary(bus_rows, line_rows, trafo_rows, total_gen, total_load,
                               total_line_loss + total_trafo_loss),
    )


def _build_summary(bus_rows, line_rows, trafo_rows, total_gen, total_load, total_loss) -> list[str]:
    findings = []
    viol = [b for b in bus_rows if b["status"] == "VIOLATION"]
    warn = [b for b in bus_rows if b["status"] == "WARNING"]
    over = [e for e in line_rows + trafo_rows if e["status"] == "OVERLOADED"]
    if not viol and not over:
        findings.append("All bus voltages within 0.95–1.05 pu and no element overloads detected.")
    if viol:
        findings.append(f"CRITICAL: {len(viol)} bus(es) outside 0.95-1.05 pu voltage band: "
                        + ", ".join(b["name"] for b in viol))
    if warn:
        findings.append(f"WARNING: {len(warn)} bus(es) in 0.97-1.03 pu caution band.")
    if over:
        findings.append(f"OVERLOADED: {len(over)} element(s) exceed 100% loading: "
                        + ", ".join(e["name"] for e in over))
    loss_pct = 100 * total_loss / total_load if total_load > 0 else 0
    findings.append(f"Total generation: {total_gen:.2f} MW | Load: {total_load:.2f} MW | "
                    f"Losses: {total_loss:.4f} MW ({loss_pct:.2f}% of load).")
    return findings
