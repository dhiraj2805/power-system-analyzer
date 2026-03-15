"""Page 04 – Short Circuit Analysis"""
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
from engine.short_circuit import run_short_circuit, FAULT_TYPES

st.set_page_config(page_title="Short Circuit", page_icon="💥", layout="wide")
init_db()
if "project_id" not in st.session_state:
    st.session_state.project_id = None

st.title("💥 Short Circuit Analysis")
pid = st.session_state.get("project_id")
if not pid:
    st.warning("No project selected.")
    st.stop()

with st.sidebar:
    st.header("Short Circuit Settings")
    fault_type = st.selectbox("Fault Type", list(FAULT_TYPES.keys()),
                               format_func=lambda x: FAULT_TYPES[x])
    case       = st.radio("Case", ["max", "min"],
                           format_func=lambda x: "Maximum (worst case)" if x == "max" else "Minimum (best case)")
    standard   = st.radio("Standard", ["iec", "ansi"],
                           format_func=lambda x: x.upper())

def _last_result():
    s = get_session()
    try:
        r = (s.query(AnalysisResult)
             .filter_by(project_id=pid, analysis_type="short_circuit")
             .order_by(AnalysisResult.created_at.desc())
             .first())
        return r.result_json if r and r.status == "completed" else None
    finally:
        s.close()

def _save_result(data: dict):
    s = get_session()
    try:
        s.add(AnalysisResult(project_id=pid, analysis_type="short_circuit",
                              status="completed" if "error" not in data else "error",
                              result_json=data, error_msg=data.get("error", "")))
        s.commit()
    finally:
        s.close()

col_run, col_info = st.columns([2, 3])
with col_run:
    run_btn = st.button("▶ Run Short Circuit", type="primary", use_container_width=True)
with col_info:
    st.caption("Standards: IEC 60909-0 / ANSI C37.010 · Equipment ratings per IEC 62271-100")

if run_btn:
    with st.spinner("Running short circuit analysis..."):
        result = run_short_circuit(pid, fault_type=fault_type, case=case, standard=standard)
        _save_result(result)
    if "error" in result:
        st.error(f"Short circuit failed: {result['error']}")
        if result.get("traceback"):
            with st.expander("Details"): st.code(result["traceback"])
    else:
        st.success("Short circuit analysis complete.")
    st.rerun()

result = _last_result()
if not result:
    st.info("No results yet. Click **Run Short Circuit** to start.")
    st.stop()
if "error" in result:
    st.error(f"Last run error: {result['error']}")
    st.stop()

st.info(f"**{result.get('fault_type_label')}** | Case: **{result.get('case','').upper()}** | "
        f"Standard: **{result.get('standard','')}**")

for f in result.get("summary", []):
    if "CAUTION" in f or "WARNING" in f:
        st.warning(f)
    else:
        st.info(f)

st.subheader("Bus Fault Current Results")
df = pd.DataFrame(result.get("bus_results", []))
if not df.empty:
    def _color_sc(val):
        if val == "VERY HIGH": return "background-color: #ffe6e6; color: red; font-weight:bold"
        if val == "HIGH":      return "background-color: #fff4cc; color: #cc6600"
        return "color: green"
    cols_show = [c for c in ["name","base_kv","ikss_ka","skss_mva","ip_ka","ith_ka","rk_ohm","xk_ohm","x_r_ratio","status"] if c in df.columns]
    st.dataframe(df[cols_show].style.applymap(_color_sc, subset=["status"]), use_container_width=True)

    # Fault current bar chart
    fig = go.Figure()
    colors = ["#dc2626" if s == "VERY HIGH" else "#f97316" if s == "HIGH" else "#2563eb"
              for s in df["status"].tolist()]
    fig.add_trace(go.Bar(x=df["name"], y=df["ikss_ka"], marker_color=colors, name="Ikss (kA)"))
    fig.update_layout(title=f"Fault Current by Bus – {result.get('fault_type_label')}",
                      xaxis_title="Bus", yaxis_title="Ikss (kA)", height=350)
    st.plotly_chart(fig, use_container_width=True)

    # SC MVA chart
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(x=df["name"], y=df["skss_mva"], marker_color="#7c3aed", name="Skss (MVA)"))
    fig2.update_layout(title="Short Circuit MVA by Bus", xaxis_title="Bus",
                       yaxis_title="Skss (MVA)", height=300)
    st.plotly_chart(fig2, use_container_width=True)
