"""Page 03 – Load Flow Analysis"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from models.database import get_session, init_db
from models.schema import AnalysisResult
from engine.load_flow import run_load_flow
from datetime import datetime

st.set_page_config(page_title="Load Flow", page_icon="⚡", layout="wide")
init_db()

if "project_id" not in st.session_state:
    st.session_state.project_id = None

st.title("⚡ Load Flow Analysis")
pid = st.session_state.get("project_id")
if not pid:
    st.warning("No project selected.")
    st.stop()

# ── Settings sidebar ──────────────────────────────────────────────────────────
with st.sidebar:
    st.header("Load Flow Settings")
    algo = st.selectbox("Algorithm", ["nr", "iwamoto_nr", "bfsw"],
                        format_func=lambda x: {"nr": "Newton-Raphson", "iwamoto_nr": "Iwamoto NR (ill-conditioned)",
                                               "bfsw": "Backward/Forward Sweep (radial)"}[x])
    max_iter = st.slider("Max Iterations", 10, 200, 50)
    tol      = st.number_input("Convergence Tolerance (MVA)", value=1e-8, format="%.2e")
    enforce_q = st.checkbox("Enforce Q limits", value=True)

# ── Load last result ──────────────────────────────────────────────────────────
def _last_result():
    s = get_session()
    try:
        r = (s.query(AnalysisResult)
             .filter_by(project_id=pid, analysis_type="load_flow")
             .order_by(AnalysisResult.created_at.desc())
             .first())
        return r.result_json if r and r.status == "completed" else None
    finally:
        s.close()

def _save_result(data: dict):
    s = get_session()
    try:
        s.add(AnalysisResult(project_id=pid, analysis_type="load_flow",
                              status="completed" if "error" not in data else "error",
                              result_json=data,
                              error_msg=data.get("error", "")))
        s.commit()
    finally:
        s.close()

# ── Run ───────────────────────────────────────────────────────────────────────
col_run, col_info = st.columns([2, 3])
with col_run:
    run_btn = st.button("▶ Run Load Flow", type="primary", use_container_width=True)
with col_info:
    st.caption("Standards: IEEE Std 399 (Brown Book) | Voltage limits: 0.95–1.05 pu | Loading warning: 80%")

if run_btn:
    with st.spinner("Running load flow..."):
        result = run_load_flow(pid, algorithm=algo, max_iteration=max_iter,
                               tolerance_mva=tol, enforce_q_lims=enforce_q)
        _save_result(result)
    if "error" in result:
        st.error(f"Load flow failed: {result['error']}")
        if result.get("traceback"):
            with st.expander("Details"): st.code(result["traceback"])
    else:
        st.success("Load flow converged successfully.")
    st.rerun()

result = _last_result()
if not result:
    st.info("No results yet. Click **Run Load Flow** to start.")
    st.stop()
if "error" in result:
    st.error(f"Last run error: {result['error']}")
    st.stop()

# ── Summary metrics ───────────────────────────────────────────────────────────
st.subheader("Power Balance")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Total Generation", f"{result['total_generation_mw']:.2f} MW")
c2.metric("Total Load",       f"{result['total_load_mw']:.2f} MW")
c3.metric("Total Losses",     f"{result['total_losses_mw']:.4f} MW")
loss_pct = 100 * result['total_losses_mw'] / result['total_load_mw'] if result['total_load_mw'] else 0
c4.metric("Loss %",           f"{loss_pct:.2f}%")

# Findings
st.subheader("Findings")
for f in result.get("summary", []):
    if "CRITICAL" in f or "OVERLOADED" in f or "VIOLATION" in f:
        st.error(f)
    elif "WARNING" in f:
        st.warning(f)
    else:
        st.success(f)

# ── Bus voltage table ─────────────────────────────────────────────────────────
st.subheader("Bus Voltage Results")
df_bus = pd.DataFrame(result.get("bus_results", []))
if not df_bus.empty:
    def _color_status(val):
        if val == "VIOLATION": return "background-color: #ffe6e6; color: red"
        if val == "WARNING":   return "background-color: #fff4cc; color: #cc6600"
        return "color: green"
    styled = df_bus[["name","base_kv","vm_pu","va_deg","vm_kv","p_mw","q_mvar","status"]].style.applymap(
        _color_status, subset=["status"])
    st.dataframe(styled, use_container_width=True)

    # Voltage profile chart
    fig = go.Figure()
    names  = df_bus["name"].tolist()
    vm_pu  = df_bus["vm_pu"].tolist()
    colors = ["red" if v < 0.95 or v > 1.05 else
              "#cc6600" if v < 0.97 or v > 1.03 else "#2563eb" for v in vm_pu]
    fig.add_trace(go.Bar(x=names, y=vm_pu, marker_color=colors, name="Vm (pu)"))
    fig.add_hline(y=0.95, line_dash="dash", line_color="red",   annotation_text="0.95 pu limit")
    fig.add_hline(y=1.05, line_dash="dash", line_color="red",   annotation_text="1.05 pu limit")
    fig.add_hline(y=1.0,  line_dash="dot",  line_color="green", annotation_text="Nominal")
    fig.update_layout(title="Bus Voltage Profile", xaxis_title="Bus", yaxis_title="Voltage (pu)",
                      yaxis_range=[0.90, 1.10], height=350)
    st.plotly_chart(fig, use_container_width=True)

# ── Branch loading ────────────────────────────────────────────────────────────
all_branches = result.get("line_results", []) + result.get("trafo_results", [])
if all_branches:
    st.subheader("Branch Loading")
    df_br = pd.DataFrame(all_branches)
    def _color_load(val):
        if val > 100: return "background-color: #ffe6e6; color: red"
        if val > 80:  return "background-color: #fff4cc; color: #cc6600"
        return ""
    if "loading_pct" in df_br.columns:
        styled_br = df_br.style.applymap(_color_load, subset=["loading_pct"])
        st.dataframe(styled_br, use_container_width=True)

        fig2 = go.Figure()
        fig2.add_trace(go.Bar(x=df_br["name"], y=df_br["loading_pct"],
                              marker_color=["red" if v > 100 else "#cc6600" if v > 80 else "#10b981"
                                            for v in df_br["loading_pct"]]))
        fig2.add_hline(y=100, line_dash="dash", line_color="red",   annotation_text="100% overload")
        fig2.add_hline(y=80,  line_dash="dash", line_color="orange",annotation_text="80% warning")
        fig2.update_layout(title="Branch Loading (%)", xaxis_title="Branch",
                           yaxis_title="Loading (%)", height=350)
        st.plotly_chart(fig2, use_container_width=True)
