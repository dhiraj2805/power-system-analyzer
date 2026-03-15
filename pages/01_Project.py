"""Page 01 – Project Management"""
import sys, json
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st
from datetime import datetime
from models.database import get_session, init_db
from models.schema import (Project, Bus, Line, Transformer, Generator, Load,
                            Shunt, ProtectionDevice, GroundingGrid)

st.set_page_config(page_title="Project Management", page_icon="📋", layout="wide")
init_db()

if "project_id" not in st.session_state:
    st.session_state.project_id = None

st.title("📋 Project Management")

tab1, tab2, tab3 = st.tabs(["New Project", "Edit Project", "Import Sample"])

# ── New Project ──────────────────────────────────────────────────────────────
with tab1:
    st.subheader("Create New Project")
    with st.form("new_project"):
        name        = st.text_input("Project Name *", placeholder="Substation XYZ Load Study")
        client      = st.text_input("Client")
        engineer    = st.text_input("Engineer")
        date        = st.date_input("Date", value=datetime.today()).strftime("%Y-%m-%d")
        description = st.text_area("Description")
        c1, c2 = st.columns(2)
        mva_base  = c1.number_input("System MVA Base", value=100.0, min_value=0.1, step=10.0)
        frequency = c2.number_input("Frequency (Hz)", value=60.0, min_value=50.0, max_value=60.0, step=10.0)
        submitted = st.form_submit_button("Create Project", type="primary")

    if submitted:
        if not name.strip():
            st.error("Project name is required.")
        else:
            session = get_session()
            try:
                proj = Project(name=name, client=client, engineer=engineer, date=date,
                               description=description, mva_base=mva_base, frequency=frequency)
                session.add(proj)
                session.commit()
                st.session_state.project_id = proj.id
                st.session_state.project_name = proj.name
                st.success(f"Project '{name}' created (id={proj.id}). Use the sidebar to switch projects.")
                st.rerun()
            except Exception as e:
                st.error(f"Error: {e}")
            finally:
                session.close()

# ── Edit Project ─────────────────────────────────────────────────────────────
with tab2:
    pid = st.session_state.get("project_id")
    if not pid:
        st.info("No project selected. Create one first or use the sidebar.")
    else:
        session = get_session()
        try:
            proj = session.query(Project).filter_by(id=pid).first()
        finally:
            session.close()

        if proj:
            with st.form("edit_project"):
                e_name  = st.text_input("Project Name", value=proj.name)
                e_client= st.text_input("Client",       value=proj.client or "")
                e_eng   = st.text_input("Engineer",     value=proj.engineer or "")
                e_desc  = st.text_area("Description",   value=proj.description or "")
                c1, c2  = st.columns(2)
                e_mva   = c1.number_input("MVA Base", value=float(proj.mva_base), step=10.0)
                e_freq  = c2.number_input("Frequency", value=float(proj.frequency), step=10.0)
                save    = st.form_submit_button("Save Changes", type="primary")

            if save:
                session = get_session()
                try:
                    p = session.query(Project).filter_by(id=pid).first()
                    p.name, p.client, p.engineer = e_name, e_client, e_eng
                    p.description, p.mva_base, p.frequency = e_desc, e_mva, e_freq
                    session.commit()
                    st.success("Project updated.")
                    st.rerun()
                except Exception as e:
                    st.error(f"Error: {e}")
                finally:
                    session.close()

            st.divider()
            with st.expander("⚠️ Danger Zone – Delete Project", expanded=False):
                st.warning("This will permanently delete the project and ALL associated data.")
                if st.button("DELETE PROJECT", type="primary"):
                    session = get_session()
                    try:
                        session.query(Project).filter_by(id=pid).delete()
                        session.commit()
                        st.session_state.project_id = None
                        st.success("Project deleted.")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")
                    finally:
                        session.close()

# ── Import Sample Data ────────────────────────────────────────────────────────
with tab3:
    st.subheader("Import Sample Project (IEEE 5-bus)")
    st.write("Loads a small pre-built distribution network to test all analysis modules.")
    if st.button("Load Sample Project", type="primary"):
        _sample = Path(ROOT / "data" / "sample_project.json")
        if not _sample.exists():
            st.error("sample_project.json not found. Make sure the data/ folder exists.")
        else:
            try:
                data = json.loads(_sample.read_text())
                session = get_session()
                try:
                    proj = Project(**{k: v for k, v in data["project"].items()})
                    session.add(proj)
                    session.flush()
                    pid_new = proj.id

                    bus_id_map = {}
                    for b in data.get("buses", []):
                        orig_id = b.pop("id")
                        bus = Bus(project_id=pid_new, **b)
                        session.add(bus); session.flush()
                        bus_id_map[orig_id] = bus.id

                    for L in data.get("lines", []):
                        L.pop("id", None)
                        L["from_bus_id"] = bus_id_map[L["from_bus_id"]]
                        L["to_bus_id"]   = bus_id_map[L["to_bus_id"]]
                        session.add(Line(project_id=pid_new, **L))

                    for T in data.get("transformers", []):
                        T.pop("id", None)
                        T["hv_bus_id"] = bus_id_map[T["hv_bus_id"]]
                        T["lv_bus_id"] = bus_id_map[T["lv_bus_id"]]
                        session.add(Transformer(project_id=pid_new, **T))

                    for G in data.get("generators", []):
                        G.pop("id", None)
                        G["bus_id"] = bus_id_map[G["bus_id"]]
                        session.add(Generator(project_id=pid_new, **G))

                    for Ld in data.get("loads", []):
                        Ld.pop("id", None)
                        Ld["bus_id"] = bus_id_map[Ld["bus_id"]]
                        session.add(Load(project_id=pid_new, **Ld))

                    for Sh in data.get("shunts", []):
                        Sh.pop("id", None)
                        Sh["bus_id"] = bus_id_map[Sh["bus_id"]]
                        session.add(Shunt(project_id=pid_new, **Sh))

                    for Pd in data.get("protection_devices", []):
                        Pd.pop("id", None)
                        if "bus_id" in Pd and Pd["bus_id"]:
                            Pd["bus_id"] = bus_id_map.get(Pd["bus_id"])
                        session.add(ProtectionDevice(project_id=pid_new, **Pd))

                    for Gr in data.get("grounding_grids", []):
                        Gr.pop("id", None)
                        if "bus_id" in Gr and Gr["bus_id"]:
                            Gr["bus_id"] = bus_id_map.get(Gr["bus_id"])
                        session.add(GroundingGrid(project_id=pid_new, **Gr))

                    session.commit()
                    st.session_state.project_id = pid_new
                    st.success(f"Sample project loaded (id={pid_new}). Ready to run analyses.")
                    st.rerun()
                except Exception as e:
                    session.rollback()
                    st.error(f"Import error: {e}")
                finally:
                    session.close()
            except Exception as e:
                st.error(f"Failed to read sample file: {e}")
