"""Page 05 – Transient Stability Analysis"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from models.database import get_session, init_db
from models.schema import AnalysisResult, Bus
from engine.transient_stability import run_transient_stability

st.set_page_config(page_title="Transient Stability", page_icon="📊", layout="wide")
init_db()
if "project_id" not in st.session_state:
    st.session_state.project_id = None

st.title("📊 Transient Stability Analysis")
pid = st.session_state.get("project_id")
if not pid:
    st.warning("No project selected.")
    st.stop()

# Load bus list for fault bus selector
session = get_session()
try:
    buses = session.query(Bus).filter_by(project_id=pid).all()
    bus_opts = {f"{b.name} ({b.base_kv} kV)": b.id for b in buses}
finally:
    session.close()

with st.sidebar:
    st.header("Fault Scenario")
    if not bus_opts:
        st.warning("No buses defined.")
    else:
        fault_label = st.selectbox("Fault Bus", list(bus_opts.keys()))
        fault_bus_id = bus_opts[fault_label]
    fault_start = st.number_input("Fault Inception (s)", value=0.10, step=0.01, format="%.3f")
    fault_clear = st.number_input("Fault Clearing (s)", value=0.20, step=0.01, format="%.3f")
    sim_time    = st.number_input("Simulation Time (s)", value=3.0, step=0.5, format="%.1f")
    st.caption("Ref: IEEE Std 1110-2019 (Classical machine model)")

def _last_result():
    s = get_session()
    try:
        r = (s.query(AnalysisResult)
             .filter_by(project_id=pid, analysis_type="transient")
             .order_by(AnalysisResult.created_at.desc())
             .first())
        return r.result_json if r and r.status == "completed" else None
    finally:
        s.close()

def _save_result(data: dict):
    s = get_session()
    try:
        s.add(AnalysisResult(project_id=pid, analysis_type="transient",
                              status="completed" if "error" not in data else "error",
                              result_json=data, error_msg=data.get("error", "")))
        s.commit()
    finally:
        s.close()

col_run, col_info = st.columns([2, 3])
with col_run:
    run_btn = st.button("▶ Run Transient Stability", type="primary",
                        use_container_width=True, disabled=(not bus_opts))
with col_info:
    st.caption("CCT = Critical Clearing Time (estimated via bisection method)")

if run_btn and bus_opts:
    with st.spinner("Running transient stability simulation (may take ~10–20 s)..."):
        result = run_transient_stability(
            pid, fault_bus_id=fault_bus_id,
            fault_start=fault_start, fault_clear=fault_clear, sim_time=sim_time
        )
        _save_result(result)
    if "error" in result:
        st.error(f"Stability error: {result['error']}")
        if result.get("traceback"):
            with st.expander("Details"): st.code(result["traceback"])
    else:
        st.success("Simulation complete.")
    st.rerun()

result = _last_result()
if not result:
    st.info("No results yet. Configure fault scenario in the sidebar and click Run.")
    st.stop()
if "error" in result:
    st.error(f"Last run error: {result['error']}")
    st.stop()

# ── Key metrics ───────────────────────────────────────────────────────────────
c1, c2, c3, c4 = st.columns(4)
c1.metric("System Stable", "YES" if result.get("stable") else "NO ⚠️",
          delta="STABLE" if result.get("stable") else "UNSTABLE",
          delta_color="normal" if result.get("stable") else "inverse")
c2.metric("Fault Cleared At", f"{result.get('fault_clear_s', 0):.3f} s")
c3.metric("CCT Estimate",     f"{result.get('cct_s', 0):.3f} s")
margin = result.get("cct_s", 0) - result.get("fault_clear_s", 0)
c4.metric("Stability Margin", f"{margin:.3f} s",
          delta="ADEQUATE" if margin > 0.1 else ("MARGINAL" if margin > 0 else "INSUFFICIENT"),
          delta_color="normal" if margin > 0.1 else "inverse")

# Findings
st.subheader("Findings")
for f in result.get("summary", []):
    if "UNSTABLE" in f or "CRITICAL" in f or "INSUFFICIENT" in f:
        st.error(f)
    elif "MARGINAL" in f:
        st.warning(f)
    else:
        st.success(f)

# ── Rotor angle plot ──────────────────────────────────────────────────────────
st.subheader("Rotor Angle Trajectories")
gens = result.get("generators", [])
time = result.get("time", [])
if gens and time:
    fig = go.Figure()
    colors = ["#2563eb","#dc2626","#16a34a","#d97706","#7c3aed","#0891b2"]
    for i, g in enumerate(gens):
        color = colors[i % len(colors)]
        line_style = "solid" if g["stable"] else "dash"
        fig.add_trace(go.Scatter(
            x=time, y=g["delta_deg"],
            name=f"{g['name']} ({'STABLE' if g['stable'] else 'UNSTABLE'})",
            line=dict(color=color, dash=line_style, width=2),
        ))
    # Fault period shading
    fc = result.get("fault_clear_s", 0)
    fi = result.get("fault_start_s", 0)
    fig.add_vrect(x0=fi, x1=fc, fillcolor="red", opacity=0.1,
                  annotation_text="Fault", annotation_position="top left")
    fig.add_hline(y=180, line_dash="dot", line_color="red", annotation_text="180° limit")
    fig.update_layout(title="Generator Rotor Angles vs Time",
                      xaxis_title="Time (s)", yaxis_title="Rotor Angle δ (°)",
                      height=400, legend=dict(orientation="h"))
    st.plotly_chart(fig, use_container_width=True)

    # Generator stability table
    st.subheader("Generator Results")
    df_g = pd.DataFrame([
        {"Generator": g["name"], "Initial δ (°)": g["initial_delta_deg"],
         "Max |δ| (°)": g["max_delta_deg"],
         "Stability": "STABLE" if g["stable"] else "UNSTABLE"}
        for g in gens
    ])
    def _stab_color(val):
        return "color: green" if val == "STABLE" else "color: red; font-weight: bold"
    st.dataframe(df_g.style.applymap(_stab_color, subset=["Stability"]), use_container_width=True)
