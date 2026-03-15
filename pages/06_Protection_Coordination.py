"""Page 06 – Protection Coordination"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from models.database import get_session, init_db
from models.schema import AnalysisResult, ProtectionDevice, Bus
from engine.protection import (check_coordination, recommend_settings,
                                available_curves, CURVE_CONSTANTS, relay_time)

st.set_page_config(page_title="Protection Coordination", page_icon="🛡️", layout="wide")
init_db()
if "project_id" not in st.session_state:
    st.session_state.project_id = None

st.title("🛡️ Protection Coordination")
pid = st.session_state.get("project_id")
if not pid:
    st.warning("No project selected.")
    st.stop()

session = get_session()
try:
    buses = {b.id: b.name for b in session.query(Bus).filter_by(project_id=pid).all()}
finally:
    session.close()

curve_keys = [c["key"] for c in available_curves()]

tabs = st.tabs(["Device Settings", "Coordination Check", "Setting Calculator"])

# ── Device settings ───────────────────────────────────────────────────────────
with tabs[0]:
    st.subheader("Protection Device List")
    st.caption("coord_order: 1 = most downstream (closest to load). Sort devices in sequence for coordination.")

    session = get_session()
    try:
        devs = session.query(ProtectionDevice).filter_by(project_id=pid).order_by(ProtectionDevice.coord_order).all()
        dev_data = [{
            "id": d.id, "name": d.name, "device_type": d.device_type,
            "bus": buses.get(d.bus_id, ""), "pickup_a": d.pickup_current_a,
            "tds": d.tds, "curve": d.curve_type, "ct_ratio": d.ct_ratio,
            "inst_pickup_a": d.inst_pickup_a or 0.0, "inst_delay_s": d.inst_delay_s or 0.05,
            "coord_order": d.coord_order
        } for d in devs]
    finally:
        session.close()

    df_dev = pd.DataFrame(dev_data) if dev_data else pd.DataFrame(
        columns=["name","device_type","bus","pickup_a","tds","curve","ct_ratio","inst_pickup_a","inst_delay_s","coord_order"])

    edited_dev = st.data_editor(
        df_dev.drop(columns=["id"], errors="ignore") if not df_dev.empty else df_dev,
        num_rows="dynamic",
        column_config={
            "name":          st.column_config.TextColumn("Device Name"),
            "device_type":   st.column_config.SelectboxColumn("Type", options=["overcurrent","differential","distance","fuse","recloser"]),
            "bus":           st.column_config.SelectboxColumn("Bus", options=list(buses.values())),
            "pickup_a":      st.column_config.NumberColumn("Pickup (A)", format="%.1f"),
            "tds":           st.column_config.NumberColumn("TDS/TMS", format="%.2f"),
            "curve":         st.column_config.SelectboxColumn("Curve", options=curve_keys),
            "ct_ratio":      st.column_config.TextColumn("CT Ratio"),
            "inst_pickup_a": st.column_config.NumberColumn("Inst. Pickup (A)", format="%.0f"),
            "inst_delay_s":  st.column_config.NumberColumn("Inst. Delay (s)", format="%.3f"),
            "coord_order":   st.column_config.NumberColumn("Coord Order", format="%d"),
        },
        use_container_width=True,
    )

    if st.button("💾 Save Devices", type="primary"):
        bus_name_id = {v: k for k, v in buses.items()}
        session = get_session()
        try:
            session.query(ProtectionDevice).filter_by(project_id=pid).delete()
            for _, row in edited_dev.iterrows():
                bid = bus_name_id.get(str(row.get("bus", "")))
                session.add(ProtectionDevice(
                    project_id=pid,
                    name=str(row["name"]),
                    device_type=str(row.get("device_type", "overcurrent")),
                    bus_id=bid,
                    pickup_current_a=float(row.get("pickup_a", 100)),
                    tds=float(row.get("tds", 0.5)),
                    curve_type=str(row.get("curve", "VI")),
                    ct_ratio=str(row.get("ct_ratio", "200/5")),
                    inst_pickup_a=float(row.get("inst_pickup_a", 0)) or None,
                    inst_delay_s=float(row.get("inst_delay_s", 0.05)),
                    coord_order=int(row.get("coord_order", 1)),
                ))
            session.commit()
            st.success("Devices saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Save error: {e}")
        finally:
            session.close()

# ── Coordination check ────────────────────────────────────────────────────────
with tabs[1]:
    st.subheader("Coordination Check")
    c1, c2 = st.columns([1, 3])
    cti = c1.number_input("Required CTI (s)", value=0.30, min_value=0.10, max_value=1.0, step=0.05)
    run_coord = c2.button("▶ Run Coordination Check", type="primary")

    def _last_prot_result():
        s = get_session()
        try:
            r = (s.query(AnalysisResult)
                 .filter_by(project_id=pid, analysis_type="protection")
                 .order_by(AnalysisResult.created_at.desc())
                 .first())
            return r.result_json if r and r.status == "completed" else None
        finally:
            s.close()

    if run_coord:
        result = check_coordination(pid, cti=cti)
        s = get_session()
        try:
            s.add(AnalysisResult(project_id=pid, analysis_type="protection",
                                  status="completed" if "error" not in result else "error",
                                  result_json=result, error_msg=result.get("error","")))
            s.commit()
        finally:
            s.close()
        st.rerun()

    result = _last_prot_result()
    if not result:
        st.info("No coordination results. Click **Run Coordination Check**.")
    elif "error" in result:
        st.error(result["error"])
    else:
        for f in result.get("summary", []):
            if "PROBLEM" in f or "FAIL" in f:
                st.error(f)
            elif "coordinated" in f.lower() or "OK" in f:
                st.success(f)
            else:
                st.info(f)

        # TCC plot
        st.subheader("Time-Current Characteristic Curves")
        tcc_curves = result.get("tcc_curves", [])
        if tcc_curves:
            fig = go.Figure()
            pal = ["#2563eb","#dc2626","#16a34a","#d97706","#7c3aed","#0891b2"]
            for i, curve in enumerate(tcc_curves):
                c = pal[i % len(pal)]
                if curve["curve_I"]:
                    fig.add_trace(go.Scatter(x=curve["curve_I"], y=curve["curve_t"],
                                             name=f"{curve['name']} ({curve['curve_type']})",
                                             line=dict(color=c, width=2)))
                if curve.get("inst_I"):
                    fig.add_trace(go.Scatter(x=curve["inst_I"], y=curve["inst_t"],
                                             name=f"{curve['name']} INST",
                                             line=dict(color=c, width=1, dash="dot"),
                                             showlegend=False))
            fig.update_xaxes(type="log", title="Current (A)")
            fig.update_yaxes(type="log", title="Operating Time (s)")
            fig.update_layout(title="TCC – Protective Device Coordination", height=450,
                               xaxis_range=[1, 6], yaxis_range=[-2, 2])
            st.plotly_chart(fig, use_container_width=True)

        # Margin table
        st.subheader("Coordination Margins")
        for pair in result.get("pairs", []):
            icon = "✅" if pair["coordinated"] else "❌"
            st.markdown(f"**{icon} {pair['downstream']} → {pair['upstream']}**  "
                        f"(min margin = **{(pair['min_margin_s'] or 0)*1000:.0f} ms**, "
                        f"required {cti*1000:.0f} ms)")
            if pair.get("margins"):
                df_m = pd.DataFrame(pair["margins"])
                st.dataframe(df_m[["fault_a","t_downstream_s","t_upstream_s","margin_s","ok"]],
                             use_container_width=True, height=160)

# ── Setting calculator ────────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("Relay Setting Calculator")
    st.caption("Calculates recommended pickup and TDS/TMS for a new relay zone.")

    with st.form("calc_settings"):
        c1, c2, c3 = st.columns(3)
        load_a   = c1.number_input("Max Load Current (A primary)", value=200.0)
        fault_max= c2.number_input("Max Fault Current (A primary)", value=5000.0)
        fault_min= c3.number_input("Min Fault Current (A primary)", value=1000.0)
        curve_sel= st.selectbox("Desired Curve", curve_keys,
                                 format_func=lambda k: CURVE_CONSTANTS[k]["label"])
        cti_val  = st.number_input("Required CTI (s)", value=0.30, step=0.05)
        st.markdown("**Downstream device settings (leave 0 if first device):**")
        c4, c5, c6 = st.columns(3)
        prev_pickup = c4.number_input("Downstream Pickup (A)", value=0.0)
        prev_tds    = c5.number_input("Downstream TDS", value=0.0)
        prev_curve  = c6.selectbox("Downstream Curve", curve_keys,
                                    format_func=lambda k: CURVE_CONSTANTS[k]["label"])
        calc_btn = st.form_submit_button("Calculate Settings", type="primary")

    if calc_btn:
        prev = None
        if prev_pickup > 0:
            prev = {"name": "Downstream", "pickup_current_a": prev_pickup,
                    "tds": prev_tds, "curve_type": prev_curve}
        rec = recommend_settings(load_a, fault_max, fault_min, prev_device=prev,
                                  curve=curve_sel, cti=cti_val)
        st.success("Recommended Settings:")
        st.json(rec)
