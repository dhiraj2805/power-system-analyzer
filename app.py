"""
Power System Analysis AI Tool
Main Streamlit entry point (home / project selector page).
"""
import sys
import os
from pathlib import Path

# Ensure the project root is on sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st

# ---- Page config ----
st.set_page_config(
    page_title="Power System Analysis AI Tool",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---- DB init ----
try:
    from models.database import init_db
    init_db()
except Exception as e:
    st.error(f"Database initialisation failed: {e}")
    st.stop()

from models.database import get_session
from models.schema import Project, AnalysisResult


# ---- Session state defaults ----
if "project_id" not in st.session_state:
    st.session_state.project_id = None
if "project_name" not in st.session_state:
    st.session_state.project_name = ""


# ---- Sidebar: project selector ----
def sidebar_project_selector():
    st.sidebar.header("Active Project")
    session = get_session()
    try:
        projects = session.query(Project).order_by(Project.created_at.desc()).all()
    finally:
        session.close()

    if not projects:
        st.sidebar.info("No projects yet. Use **01 Project** page to create one.")
        st.session_state.project_id = None
        return

    options = {f"{p.name} (id={p.id})": p.id for p in projects}
    # Pre-select current project if it still exists
    current_label = None
    if st.session_state.project_id:
        for lbl, pid in options.items():
            if pid == st.session_state.project_id:
                current_label = lbl
                break

    selected = st.sidebar.selectbox(
        "Select project",
        list(options.keys()),
        index=list(options.keys()).index(current_label) if current_label else 0,
    )
    new_id = options[selected]
    if new_id != st.session_state.project_id:
        st.session_state.project_id = new_id
        st.session_state.project_name = selected.split(" (id=")[0]
        st.rerun()

    st.sidebar.caption(f"Project ID: {st.session_state.project_id}")


sidebar_project_selector()

# ---- Main content ----
st.title("⚡ Power System Analysis AI Tool")
st.markdown(
    "A comprehensive platform for **distribution and transmission** power system analysis "
    "covering all major engineering studies."
)

col1, col2, col3, col4, col5 = st.columns(5)
modules = [
    (col1, "⚡", "Load Flow",         "Newton-Raphson, IWAMOTO, BFS; voltage profiles, losses"),
    (col2, "💥", "Short Circuit",     "IEC 60909 / ANSI; 3Φ, SLG, DLG, LL fault currents"),
    (col3, "📊", "Transient Stability","Swing-equation simulation, CCT estimation"),
    (col4, "🛡️", "Protection",        "ANSI/IEC TCC curves, CTI verification, settings"),
    (col5, "🌍", "Grounding",         "IEEE 80-2013: mesh/step voltage, compliance check"),
]
for col, icon, title, desc in modules:
    with col:
        st.markdown(f"### {icon} {title}")
        st.caption(desc)

st.divider()

# ---- Project status ----
if st.session_state.project_id is None:
    st.info("👈 No project selected. Go to **01 Project** in the sidebar to create or load a project.")
    st.stop()

pid = st.session_state.project_id
session = get_session()
try:
    project = session.query(Project).filter_by(id=pid).first()
    if not project:
        st.error("Selected project not found. Please choose another.")
        st.stop()

    results_all = (
        session.query(AnalysisResult)
        .filter_by(project_id=pid)
        .order_by(AnalysisResult.created_at.desc())
        .all()
    )
finally:
    session.close()

st.subheader(f"Project: {project.name}")
c1, c2, c3 = st.columns(3)
c1.metric("Client",   project.client or "—")
c2.metric("Engineer", project.engineer or "—")
c3.metric("MVA Base", f"{project.mva_base} MVA | {project.frequency} Hz")

st.divider()
st.subheader("Analysis Status")

analysis_types = {
    "load_flow":     ("⚡ Load Flow",         "03 Load Flow"),
    "short_circuit": ("💥 Short Circuit",      "04 Short Circuit"),
    "transient":     ("📊 Transient Stability","05 Transient Stability"),
    "protection":    ("🛡️ Protection",         "06 Protection Coordination"),
    "grounding":     ("🌍 Grounding",          "07 Grounding Analysis"),
}

latest = {}
for r in results_all:
    if r.analysis_type not in latest:
        latest[r.analysis_type] = r

cols = st.columns(5)
for i, (atype, (label, page)) in enumerate(analysis_types.items()):
    with cols[i]:
        if atype in latest:
            r = latest[atype]
            if r.status == "completed":
                st.success(f"**{label}**\n\n✅ Completed\n\n{r.created_at.strftime('%Y-%m-%d %H:%M')}")
            else:
                st.error(f"**{label}**\n\n❌ Error")
        else:
            st.info(f"**{label}**\n\n⬜ Not run\n\nGo to page *{page}*")

st.divider()
st.subheader("Quick Start")
st.markdown("""
1. **01 Project** – Create / edit project metadata and system base
2. **02 Network Data** – Enter buses, lines, transformers, generators, loads
3. Run each analysis from pages 03–07
4. **08 Reports** – Generate the full PDF engineering report
""")
