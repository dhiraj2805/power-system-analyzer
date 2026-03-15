"""Page 02 – Network Data Entry"""
import sys, io, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
from models.database import get_session, init_db
from models.schema import Bus, Line, Transformer, Generator, Load, Shunt

st.set_page_config(page_title="Network Data", page_icon="🔌", layout="wide")
init_db()

if "project_id" not in st.session_state:
    st.session_state.project_id = None

st.title("🔌 Network Data Entry")
pid = st.session_state.get("project_id")
if not pid:
    st.warning("No project selected. Go to **01 Project** first.")
    st.stop()

# ── Helper ────────────────────────────────────────────────────────────────────

def _load_df(model, columns: list[str]) -> pd.DataFrame:
    session = get_session()
    try:
        rows = session.query(model).filter_by(project_id=pid).all()
        records = [{c: getattr(r, c) for c in columns} for r in rows]
    finally:
        session.close()
    return pd.DataFrame(records, columns=columns) if records else pd.DataFrame(columns=columns)


def _save_bus_data(df: pd.DataFrame):
    session = get_session()
    try:
        session.query(Bus).filter_by(project_id=pid).delete()
        for _, row in df.iterrows():
            session.add(Bus(project_id=pid, name=str(row["name"]),
                            base_kv=float(row["base_kv"]),
                            bus_type=int(row["bus_type"]),
                            zone=str(row.get("zone", "")),
                            vm_pu=float(row.get("vm_pu", 1.0))))
        session.commit()
    finally:
        session.close()


def _save_line_data(df: pd.DataFrame, bus_map: dict):
    session = get_session()
    try:
        session.query(Line).filter_by(project_id=pid).delete()
        for _, row in df.iterrows():
            fb = bus_map.get(str(row["from_bus"]))
            tb = bus_map.get(str(row["to_bus"]))
            if not fb or not tb:
                continue
            session.add(Line(project_id=pid, name=str(row["name"]),
                             from_bus_id=fb, to_bus_id=tb,
                             r_ohm_per_km=float(row["r_ohm_per_km"]),
                             x_ohm_per_km=float(row["x_ohm_per_km"]),
                             c_nf_per_km=float(row.get("c_nf_per_km", 0.0)),
                             length_km=float(row["length_km"]),
                             max_i_ka=float(row.get("max_i_ka", 1.0))))
        session.commit()
    finally:
        session.close()


def _save_trafo_data(df: pd.DataFrame, bus_map: dict):
    session = get_session()
    try:
        session.query(Transformer).filter_by(project_id=pid).delete()
        for _, row in df.iterrows():
            hv = bus_map.get(str(row["hv_bus"]))
            lv = bus_map.get(str(row["lv_bus"]))
            if not hv or not lv:
                continue
            session.add(Transformer(project_id=pid, name=str(row["name"]),
                                    hv_bus_id=hv, lv_bus_id=lv,
                                    sn_mva=float(row["sn_mva"]),
                                    vn_hv_kv=float(row["vn_hv_kv"]),
                                    vn_lv_kv=float(row["vn_lv_kv"]),
                                    vk_percent=float(row["vk_percent"]),
                                    vkr_percent=float(row.get("vkr_percent", 0.3)),
                                    pfe_kw=float(row.get("pfe_kw", 0.0)),
                                    i0_percent=float(row.get("i0_percent", 0.0)),
                                    vector_group=str(row.get("vector_group", "Dyn11"))))
        session.commit()
    finally:
        session.close()


def _save_gen_data(df: pd.DataFrame, bus_map: dict):
    session = get_session()
    try:
        session.query(Generator).filter_by(project_id=pid).delete()
        for _, row in df.iterrows():
            bid = bus_map.get(str(row["bus"]))
            if not bid:
                continue
            session.add(Generator(project_id=pid, name=str(row["name"]),
                                   bus_id=bid, p_mw=float(row["p_mw"]),
                                   vm_pu=float(row.get("vm_pu", 1.0)),
                                   sn_mva=float(row.get("sn_mva", 100.0)),
                                   max_q_mvar=float(row.get("max_q_mvar", 999.0)),
                                   min_q_mvar=float(row.get("min_q_mvar", -999.0)),
                                   xd_prime_pu=float(row.get("xd_prime_pu", 0.3)),
                                   xd_dbl_prime_pu=float(row.get("xd_dbl_prime_pu", 0.2)),
                                   H_s=float(row.get("H_s", 5.0)),
                                   D=float(row.get("D", 2.0))))
        session.commit()
    finally:
        session.close()


def _save_load_data(df: pd.DataFrame, bus_map: dict):
    session = get_session()
    try:
        session.query(Load).filter_by(project_id=pid).delete()
        for _, row in df.iterrows():
            bid = bus_map.get(str(row["bus"]))
            if not bid:
                continue
            session.add(Load(project_id=pid, name=str(row["name"]),
                              bus_id=bid, p_mw=float(row["p_mw"]),
                              q_mvar=float(row.get("q_mvar", 0.0))))
        session.commit()
    finally:
        session.close()


# ── Bus name -> DB id map ─────────────────────────────────────────────────────
def _get_bus_map() -> dict:
    session = get_session()
    try:
        return {b.name: b.id for b in session.query(Bus).filter_by(project_id=pid).all()}
    finally:
        session.close()


# ── Tabs ─────────────────────────────────────────────────────────────────────
tabs = st.tabs(["🚌 Buses", "📏 Lines", "🔄 Transformers", "⚙️ Generators", "💡 Loads", "⚡ Shunts"])

# ---- Buses ----
with tabs[0]:
    st.subheader("Bus Data")
    st.caption("Bus type: 1=Load (PQ), 2=Generator (PV), 3=Slack/Reference")
    bus_cols = ["id", "name", "base_kv", "bus_type", "zone", "vm_pu"]
    df_bus = _load_df(Bus, bus_cols)
    edited = st.data_editor(
        df_bus.drop(columns=["id"], errors="ignore"),
        num_rows="dynamic",
        column_config={
            "name":     st.column_config.TextColumn("Bus Name", required=True),
            "base_kv":  st.column_config.NumberColumn("Base kV", min_value=0.1, format="%.2f"),
            "bus_type": st.column_config.SelectboxColumn("Type", options=[1,2,3]),
            "zone":     st.column_config.TextColumn("Zone"),
            "vm_pu":    st.column_config.NumberColumn("Vm (pu)", min_value=0.8, max_value=1.2, format="%.4f"),
        },
        use_container_width=True,
    )
    if st.button("💾 Save Buses", type="primary"):
        try:
            _save_bus_data(edited)
            st.success("Buses saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Save error: {e}")

    csv = edited.to_csv(index=False).encode()
    st.download_button("⬇ Export CSV", csv, "buses.csv", "text/csv")

# ---- Lines ----
with tabs[1]:
    st.subheader("Line / Cable Data")
    line_cols = ["id", "name", "from_bus_id", "to_bus_id", "r_ohm_per_km",
                 "x_ohm_per_km", "c_nf_per_km", "length_km", "max_i_ka"]
    df_raw = _load_df(Line, line_cols)
    # Replace bus IDs with names for display
    session = get_session()
    try:
        bus_id_name = {b.id: b.name for b in session.query(Bus).filter_by(project_id=pid).all()}
    finally:
        session.close()
    bus_names = list(bus_id_name.values())

    df_lines = df_raw.copy()
    df_lines["from_bus"] = df_lines["from_bus_id"].map(bus_id_name).fillna("")
    df_lines["to_bus"]   = df_lines["to_bus_id"].map(bus_id_name).fillna("")
    display_cols = ["name", "from_bus", "to_bus", "r_ohm_per_km", "x_ohm_per_km",
                    "c_nf_per_km", "length_km", "max_i_ka"]

    edited_lines = st.data_editor(
        df_lines[display_cols] if not df_lines.empty else pd.DataFrame(columns=display_cols),
        num_rows="dynamic",
        column_config={
            "name":         st.column_config.TextColumn("Line Name", required=True),
            "from_bus":     st.column_config.SelectboxColumn("From Bus", options=bus_names),
            "to_bus":       st.column_config.SelectboxColumn("To Bus",   options=bus_names),
            "r_ohm_per_km": st.column_config.NumberColumn("R (Ω/km)",  format="%.4f"),
            "x_ohm_per_km": st.column_config.NumberColumn("X (Ω/km)",  format="%.4f"),
            "c_nf_per_km":  st.column_config.NumberColumn("C (nF/km)", format="%.2f"),
            "length_km":    st.column_config.NumberColumn("Length (km)",format="%.3f"),
            "max_i_ka":     st.column_config.NumberColumn("Imax (kA)",  format="%.3f"),
        },
        use_container_width=True,
    )
    if st.button("💾 Save Lines", type="primary"):
        bmap = {v: k for k, v in bus_id_name.items()}
        try:
            _save_line_data(edited_lines, bmap)
            st.success("Lines saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Save error: {e}")

# ---- Transformers ----
with tabs[2]:
    st.subheader("Transformer Data")
    trafo_cols = ["id", "name", "hv_bus_id", "lv_bus_id", "sn_mva", "vn_hv_kv", "vn_lv_kv",
                  "vk_percent", "vkr_percent", "pfe_kw", "i0_percent", "vector_group"]
    df_raw_t = _load_df(Transformer, trafo_cols)
    df_t = df_raw_t.copy()
    df_t["hv_bus"] = df_t["hv_bus_id"].map(bus_id_name).fillna("")
    df_t["lv_bus"] = df_t["lv_bus_id"].map(bus_id_name).fillna("")
    t_cols = ["name", "hv_bus", "lv_bus", "sn_mva", "vn_hv_kv", "vn_lv_kv",
              "vk_percent", "vkr_percent", "pfe_kw", "i0_percent", "vector_group"]

    edited_t = st.data_editor(
        df_t[t_cols] if not df_t.empty else pd.DataFrame(columns=t_cols),
        num_rows="dynamic",
        column_config={
            "name":         st.column_config.TextColumn("Name", required=True),
            "hv_bus":       st.column_config.SelectboxColumn("HV Bus", options=bus_names),
            "lv_bus":       st.column_config.SelectboxColumn("LV Bus", options=bus_names),
            "sn_mva":       st.column_config.NumberColumn("Sn (MVA)", format="%.2f"),
            "vn_hv_kv":     st.column_config.NumberColumn("Vn HV (kV)", format="%.2f"),
            "vn_lv_kv":     st.column_config.NumberColumn("Vn LV (kV)", format="%.2f"),
            "vk_percent":   st.column_config.NumberColumn("Vk%", format="%.2f"),
            "vkr_percent":  st.column_config.NumberColumn("Vkr%", format="%.3f"),
            "pfe_kw":       st.column_config.NumberColumn("Pfe (kW)", format="%.2f"),
            "i0_percent":   st.column_config.NumberColumn("i0%", format="%.3f"),
            "vector_group": st.column_config.TextColumn("Vector Group"),
        },
        use_container_width=True,
    )
    if st.button("💾 Save Transformers", type="primary"):
        bmap = {v: k for k, v in bus_id_name.items()}
        try:
            _save_trafo_data(edited_t, bmap)
            st.success("Transformers saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Save error: {e}")

# ---- Generators ----
with tabs[3]:
    st.subheader("Generator / Source Data")
    gen_cols = ["id", "name", "bus_id", "p_mw", "vm_pu", "sn_mva",
                "max_q_mvar", "min_q_mvar", "xd_prime_pu", "xd_dbl_prime_pu", "H_s", "D"]
    df_g = _load_df(Generator, gen_cols)
    df_g["bus"] = df_g["bus_id"].map(bus_id_name).fillna("")
    g_cols = ["name", "bus", "p_mw", "vm_pu", "sn_mva", "max_q_mvar", "min_q_mvar",
              "xd_prime_pu", "xd_dbl_prime_pu", "H_s", "D"]

    edited_g = st.data_editor(
        df_g[g_cols] if not df_g.empty else pd.DataFrame(columns=g_cols),
        num_rows="dynamic",
        column_config={
            "name":            st.column_config.TextColumn("Name", required=True),
            "bus":             st.column_config.SelectboxColumn("Bus", options=bus_names),
            "p_mw":            st.column_config.NumberColumn("P (MW)", format="%.2f"),
            "vm_pu":           st.column_config.NumberColumn("Vm (pu)", format="%.3f"),
            "sn_mva":          st.column_config.NumberColumn("Sn (MVA)", format="%.1f"),
            "xd_prime_pu":     st.column_config.NumberColumn("Xd' (pu)", format="%.3f"),
            "xd_dbl_prime_pu": st.column_config.NumberColumn("Xd'' (pu)", format="%.3f"),
            "H_s":             st.column_config.NumberColumn("H (s)", format="%.2f"),
            "D":               st.column_config.NumberColumn("D", format="%.2f"),
        },
        use_container_width=True,
    )
    if st.button("💾 Save Generators", type="primary"):
        bmap = {v: k for k, v in bus_id_name.items()}
        try:
            _save_gen_data(edited_g, bmap)
            st.success("Generators saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Save error: {e}")

# ---- Loads ----
with tabs[4]:
    st.subheader("Load Data")
    load_cols = ["id", "name", "bus_id", "p_mw", "q_mvar"]
    df_l = _load_df(Load, load_cols)
    df_l["bus"] = df_l["bus_id"].map(bus_id_name).fillna("")
    l_cols = ["name", "bus", "p_mw", "q_mvar"]

    edited_l = st.data_editor(
        df_l[l_cols] if not df_l.empty else pd.DataFrame(columns=l_cols),
        num_rows="dynamic",
        column_config={
            "name":  st.column_config.TextColumn("Name", required=True),
            "bus":   st.column_config.SelectboxColumn("Bus", options=bus_names),
            "p_mw":  st.column_config.NumberColumn("P (MW)", format="%.3f"),
            "q_mvar":st.column_config.NumberColumn("Q (Mvar)", format="%.3f"),
        },
        use_container_width=True,
    )
    if st.button("💾 Save Loads", type="primary"):
        bmap = {v: k for k, v in bus_id_name.items()}
        try:
            _save_load_data(edited_l, bmap)
            st.success("Loads saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Save error: {e}")

# ---- Shunts ----
with tabs[5]:
    st.subheader("Shunt Data (Capacitor Banks / Reactors)")
    st.caption("Positive q_mvar = capacitive (reactive injection), negative = inductive (absorption)")
    shunt_cols = ["id", "name", "bus_id", "q_mvar"]
    df_sh = _load_df(Shunt, shunt_cols)
    df_sh["bus"] = df_sh["bus_id"].map(bus_id_name).fillna("")
    sh_cols = ["name", "bus", "q_mvar"]

    edited_sh = st.data_editor(
        df_sh[sh_cols] if not df_sh.empty else pd.DataFrame(columns=sh_cols),
        num_rows="dynamic",
        column_config={
            "name":  st.column_config.TextColumn("Name", required=True),
            "bus":   st.column_config.SelectboxColumn("Bus", options=bus_names),
            "q_mvar":st.column_config.NumberColumn("Q (Mvar)", format="%.3f"),
        },
        use_container_width=True,
    )
    if st.button("💾 Save Shunts", type="primary"):
        bmap = {v: k for k, v in bus_id_name.items()}
        session = get_session()
        try:
            session.query(Shunt).filter_by(project_id=pid).delete()
            for _, row in edited_sh.iterrows():
                bid = bmap.get(str(row["bus"]))
                if bid:
                    session.add(Shunt(project_id=pid, name=str(row["name"]),
                                       bus_id=bid, q_mvar=float(row["q_mvar"])))
            session.commit()
            st.success("Shunts saved.")
            st.rerun()
        except Exception as e:
            st.error(f"Save error: {e}")
        finally:
            session.close()

# ── Network summary ────────────────────────────────────────────────────────────
st.divider()
session = get_session()
try:
    nb = session.query(Bus).filter_by(project_id=pid).count()
    nl = session.query(Line).filter_by(project_id=pid).count()
    nt = session.query(Transformer).filter_by(project_id=pid).count()
    ng = session.query(Generator).filter_by(project_id=pid).count()
    nld= session.query(Load).filter_by(project_id=pid).count()
finally:
    session.close()

c = st.columns(5)
c[0].metric("Buses", nb)
c[1].metric("Lines", nl)
c[2].metric("Transformers", nt)
c[3].metric("Generators", ng)
c[4].metric("Loads", nld)
