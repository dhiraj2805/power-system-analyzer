"""Page 07 – Grounding System Analysis (IEEE 80-2013)"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from models.database import get_session, init_db
from models.schema import AnalysisResult, GroundingGrid, Bus
from engine.grounding import run_grounding_analysis, analyze_single_grid

st.set_page_config(page_title="Grounding Analysis", page_icon="🌍", layout="wide")
init_db()
if "project_id" not in st.session_state:
    st.session_state.project_id = None

st.title("🌍 Grounding System Analysis")
st.caption("IEEE Std 80-2013 – Guide for Safety in AC Substation Grounding")
pid = st.session_state.get("project_id")
if not pid:
    st.warning("No project selected.")
    st.stop()

session = get_session()
try:
    buses = {b.id: b.name for b in session.query(Bus).filter_by(project_id=pid).all()}
    grids = session.query(GroundingGrid).filter_by(project_id=pid).all()
finally:
    session.close()

tabs = st.tabs(["Manage Grids", "Run Analysis", "Quick Calculator"])

# ── Manage grids ──────────────────────────────────────────────────────────────
with tabs[0]:
    st.subheader("Grounding Grids")
    grid_data = [{
        "id": g.id, "name": g.name, "bus": buses.get(g.bus_id, ""),
        "grid_length_m": g.grid_length_m, "grid_width_m": g.grid_width_m,
        "conductor_spacing_m": g.conductor_spacing_m, "burial_depth_m": g.burial_depth_m,
        "conductor_diameter_m": g.conductor_diameter_m,
        "num_ground_rods": g.num_ground_rods, "rod_length_m": g.rod_length_m,
        "soil_resistivity_ohm_m": g.soil_resistivity_ohm_m,
        "surface_resistivity_ohm_m": g.surface_resistivity_ohm_m,
        "surface_layer_depth_m": g.surface_layer_depth_m,
        "fault_current_ka": g.fault_current_ka, "fault_duration_s": g.fault_duration_s,
        "decrement_factor": g.decrement_factor,
    } for g in grids]
    df_grids = pd.DataFrame(grid_data) if grid_data else pd.DataFrame(columns=[
        "name","bus","grid_length_m","grid_width_m","conductor_spacing_m","burial_depth_m",
        "conductor_diameter_m","num_ground_rods","rod_length_m","soil_resistivity_ohm_m",
        "surface_resistivity_ohm_m","surface_layer_depth_m",
        "fault_current_ka","fault_duration_s","decrement_factor"])

    edited_grids = st.data_editor(
        df_grids.drop(columns=["id"], errors="ignore"),
        num_rows="dynamic",
        column_config={
            "name":                      st.column_config.TextColumn("Grid Name"),
            "bus":                       st.column_config.SelectboxColumn("Bus", options=list(buses.values())),
            "grid_length_m":             st.column_config.NumberColumn("Length (m)", format="%.1f"),
            "grid_width_m":              st.column_config.NumberColumn("Width (m)", format="%.1f"),
            "conductor_spacing_m":       st.column_config.NumberColumn("Spacing D (m)", format="%.1f"),
            "burial_depth_m":            st.column_config.NumberColumn("Depth h (m)", format="%.2f"),
            "conductor_diameter_m":      st.column_config.NumberColumn("Cond. diam (m)", format="%.4f"),
            "num_ground_rods":           st.column_config.NumberColumn("# Rods", format="%d"),
            "rod_length_m":              st.column_config.NumberColumn("Rod Length (m)", format="%.1f"),
            "soil_resistivity_ohm_m":    st.column_config.NumberColumn("ρ soil (Ω·m)", format="%.1f"),
            "surface_resistivity_ohm_m": st.column_config.NumberColumn("ρ surface (Ω·m)", format="%.0f"),
            "surface_layer_depth_m":     st.column_config.NumberColumn("Surface depth (m)", format="%.2f"),
            "fault_current_ka":          st.column_config.NumberColumn("3I0 (kA)", format="%.2f"),
            "fault_duration_s":          st.column_config.NumberColumn("t_f (s)", format="%.2f"),
            "decrement_factor":          st.column_config.NumberColumn("Df", format="%.2f"),
        },
        use_container_width=True,
    )

    if st.button("💾 Save Grids", type="primary"):
        bname_id = {v: k for k, v in buses.items()}
        session = get_session()
        try:
            session.query(GroundingGrid).filter_by(project_id=pid).delete()
            for _, row in edited_grids.iterrows():
                bid = bname_id.get(str(row.get("bus", "")))
                session.add(GroundingGrid(
                    project_id=pid,
                    name=str(row.get("name", "Grid")),
                    bus_id=bid,
                    grid_length_m=float(row.get("grid_length_m", 50)),
                    grid_width_m=float(row.get("grid_width_m", 50)),
                    conductor_spacing_m=float(row.get("conductor_spacing_m", 5)),
                    burial_depth_m=float(row.get("burial_depth_m", 0.5)),
                    conductor_diameter_m=float(row.get("conductor_diameter_m", 0.01)),
                    num_ground_rods=int(row.get("num_ground_rods", 0)),
                    rod_length_m=float(row.get("rod_length_m", 3.0)),
                    soil_resistivity_ohm_m=float(row.get("soil_resistivity_ohm_m", 100)),
                    surface_resistivity_ohm_m=float(row.get("surface_resistivity_ohm_m", 2000)),
                    surface_layer_depth_m=float(row.get("surface_layer_depth_m", 0.1)),
                    fault_current_ka=float(row.get("fault_current_ka", 10)),
                    fault_duration_s=float(row.get("fault_duration_s", 0.5)),
                    decrement_factor=float(row.get("decrement_factor", 1.0)),
                ))
            session.commit()
            st.success("Grids saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Save error: {e}")
        finally:
            session.close()

# ── Run analysis ──────────────────────────────────────────────────────────────
with tabs[1]:
    run_btn = st.button("▶ Run Grounding Analysis", type="primary")

    def _last_result():
        s = get_session()
        try:
            r = (s.query(AnalysisResult)
                 .filter_by(project_id=pid, analysis_type="grounding")
                 .order_by(AnalysisResult.created_at.desc())
                 .first())
            return r.result_json if r and r.status == "completed" else None
        finally:
            s.close()

    if run_btn:
        result = run_grounding_analysis(pid)
        s = get_session()
        try:
            s.add(AnalysisResult(project_id=pid, analysis_type="grounding",
                                  status="completed" if "error" not in result else "error",
                                  result_json=result, error_msg=result.get("error", "")))
            s.commit()
        finally:
            s.close()
        st.rerun()

    result = _last_result()
    if not result:
        st.info("No results. Click **Run Grounding Analysis**.")
    elif "error" in result:
        st.error(result["error"])
    else:
        for f in result.get("summary", []):
            if "NON-COMPLIANT" in f or "ACTION" in f:
                st.error(f)
            elif "COMPLIANT" in f:
                st.success(f)
            else:
                st.info(f)

        for gr in result.get("grid_results", []):
            with st.expander(f"📐 Grid: {gr['name']} – {'✅ COMPLIANT' if gr['compliant'] else '❌ NON-COMPLIANT'}",
                             expanded=True):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Grid Resistance", f"{gr['grid_resistance_ohm']:.4f} Ω")
                c2.metric("GPR", f"{gr['gpr_v']:.0f} V")
                c3.metric("Mesh Voltage Em",  f"{gr['mesh_voltage_v']:.0f} V",
                           delta=f"Limit {gr['tolerable_touch_50kg_v']:.0f} V",
                           delta_color="normal" if gr["touch_voltage_safe"] else "inverse")
                c4.metric("Step Voltage Es",  f"{gr['step_voltage_v']:.0f} V",
                           delta=f"Limit {gr['tolerable_step_50kg_v']:.0f} V",
                           delta_color="normal" if gr["step_voltage_safe"] else "inverse")

                # Comparison bar chart
                fig = go.Figure()
                categories = ["Em vs Touch Limit", "Es vs Step Limit"]
                actual = [gr["mesh_voltage_v"], gr["step_voltage_v"]]
                limit  = [gr["tolerable_touch_50kg_v"], gr["tolerable_step_50kg_v"]]
                fig.add_trace(go.Bar(name="Calculated", x=categories, y=actual,
                                     marker_color=["#dc2626" if a > l else "#16a34a"
                                                   for a, l in zip(actual, limit)]))
                fig.add_trace(go.Bar(name="Tolerable Limit (50 kg)", x=categories, y=limit,
                                     marker_color="#94a3b8"))
                fig.update_layout(barmode="group", title="Voltage Compliance Check",
                                   yaxis_title="Voltage (V)", height=300)
                st.plotly_chart(fig, use_container_width=True)

                # Recommendations
                for rec in gr.get("recommendations", []):
                    if "VIOLATION" in rec or "INSUFFICIENT" in rec:
                        st.error(rec)
                    elif "above" in rec or "Consider" in rec:
                        st.warning(rec)
                    else:
                        st.success(rec)

# ── Quick calculator ──────────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("Quick IEEE 80-2013 Calculator")
    st.caption("Run a calculation without saving to the project database.")

    with st.form("quick_calc"):
        c1, c2, c3 = st.columns(3)
        ql  = c1.number_input("Grid Length (m)", value=40.0)
        qw  = c2.number_input("Grid Width (m)", value=40.0)
        qD  = c3.number_input("Conductor Spacing D (m)", value=5.0)
        c4, c5, c6 = st.columns(3)
        qh  = c4.number_input("Burial Depth h (m)", value=0.5)
        qd  = c5.number_input("Conductor Diameter (m)", value=0.01)
        qrho= c6.number_input("Soil Resistivity ρ (Ω·m)", value=100.0)
        c7, c8, c9 = st.columns(3)
        qrhos = c7.number_input("Surface Layer ρ (Ω·m)", value=2000.0)
        qhs   = c8.number_input("Surface Layer Depth (m)", value=0.1)
        qIg   = c9.number_input("Fault Current 3I0 (kA)", value=8.0)
        c10, c11 = st.columns(2)
        qtf   = c10.number_input("Fault Duration (s)", value=0.5)
        qrods = c11.number_input("Number of Ground Rods", value=0)
        run_quick = st.form_submit_button("Calculate", type="primary")

    if run_quick:
        r = analyze_single_grid(
            grid_length_m=ql, grid_width_m=qw, conductor_spacing_m=qD,
            burial_depth_m=qh, conductor_diameter_m=qd,
            soil_resistivity_ohm_m=qrho, surface_resistivity_ohm_m=qrhos,
            surface_layer_depth_m=qhs, fault_current_ka=qIg, fault_duration_s=qtf,
            num_rods=int(qrods), name="Quick Calc Grid"
        )
        c1, c2, c3 = st.columns(3)
        c1.metric("Rg", f"{r['grid_resistance_ohm']:.4f} Ω")
        c2.metric("GPR", f"{r['gpr_v']:.0f} V")
        c3.metric("Compliant", "YES ✅" if r["compliant"] else "NO ❌")
        col_a, col_b = st.columns(2)
        col_a.metric("Em (Mesh V)", f"{r['mesh_voltage_v']:.0f} V",
                      delta=f"Limit {r['tolerable_touch_50kg_v']:.0f} V (50 kg)",
                      delta_color="normal" if r["touch_voltage_safe"] else "inverse")
        col_b.metric("Es (Step V)", f"{r['step_voltage_v']:.0f} V",
                      delta=f"Limit {r['tolerable_step_50kg_v']:.0f} V (50 kg)",
                      delta_color="normal" if r["step_voltage_safe"] else "inverse")
        with st.expander("Full results"):
            st.json(r)
        for rec in r.get("recommendations", []):
            if "VIOLATION" in rec: st.error(rec)
            elif "above" in rec or "Consider" in rec: st.warning(rec)
            else: st.success(rec)
