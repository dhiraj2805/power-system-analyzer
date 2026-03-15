"""Page 08 – Engineering Report Generator"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import io
import json
from datetime import datetime

import streamlit as st
import pandas as pd

from models.database import get_session, init_db
from models.schema import Project, AnalysisResult
from reports.generator import generate_report, REPORTLAB_OK
from ai.analyzer import get_narrative, check_ai_available, build_prompt

st.set_page_config(page_title="Reports", page_icon="📄", layout="wide")
init_db()
if "project_id" not in st.session_state:
    st.session_state.project_id = None

st.title("📄 Engineering Report Generator")
st.caption("Compile all completed analyses into a professional PDF report (IEEE 399 · IEC 60909 · IEEE 80-2013)")

pid = st.session_state.get("project_id")
if not pid:
    st.warning("No project selected. Use the sidebar to select a project.")
    st.stop()

# ── Load project and latest results ──────────────────────────────────────────
session = get_session()
try:
    project = session.query(Project).filter_by(id=pid).first()
    if not project:
        st.error("Project not found.")
        st.stop()

    all_results = (
        session.query(AnalysisResult)
        .filter_by(project_id=pid)
        .order_by(AnalysisResult.created_at.desc())
        .all()
    )
finally:
    session.close()

# Collect latest result per analysis type
ANALYSIS_TYPES = {
    "load_flow":     ("⚡ Load Flow",          "03 Load Flow"),
    "short_circuit": ("💥 Short Circuit",       "04 Short Circuit"),
    "transient":     ("📊 Transient Stability", "05 Transient Stability"),
    "protection":    ("🛡️ Protection",          "06 Protection Coordination"),
    "grounding":     ("🌍 Grounding",           "07 Grounding Analysis"),
}

latest: dict[str, AnalysisResult] = {}
for r in all_results:
    if r.analysis_type not in latest:
        latest[r.analysis_type] = r

project_info = {
    "name":        project.name,
    "client":      project.client or "—",
    "engineer":    project.engineer or "—",
    "date":        project.date or datetime.today().strftime("%Y-%m-%d"),
    "description": project.description or "",
    "mva_base":    project.mva_base,
    "frequency":   project.frequency,
}

tabs = st.tabs(["📊 Analysis Status", "⚙️ Report Options", "📄 Generate & Download", "🤖 AI Narrative"])

# ── Tab 0: Analysis Status ────────────────────────────────────────────────────
with tabs[0]:
    st.subheader("Completed Analyses")
    cols = st.columns(5)
    for i, (atype, (label, page)) in enumerate(ANALYSIS_TYPES.items()):
        with cols[i]:
            if atype in latest:
                r = latest[atype]
                if r.status == "completed":
                    st.success(f"**{label}**\n\n✅ Done\n\n{r.created_at.strftime('%Y-%m-%d %H:%M')}")
                else:
                    st.error(f"**{label}**\n\n❌ Error")
            else:
                st.warning(f"**{label}**\n\n⬜ Not run\n\nGo to *{page}*")

    st.divider()
    st.subheader("Result Details")
    for atype, (label, _) in ANALYSIS_TYPES.items():
        if atype in latest:
            r = latest[atype]
            with st.expander(f"{label} — {r.created_at.strftime('%Y-%m-%d %H:%M')} "
                             f"({'✅' if r.status == 'completed' else '❌'})"):
                if r.result_json:
                    summary = r.result_json.get("summary", [])
                    if summary:
                        for s in summary:
                            if any(kw in s for kw in ("CRITICAL", "VIOLATION", "NON-COMPLIANT", "UNSTABLE", "PROBLEM")):
                                st.error(s)
                            elif any(kw in s for kw in ("WARNING", "MARGINAL", "CAUTION")):
                                st.warning(s)
                            else:
                                st.success(s)
                    else:
                        st.info("No summary available.")
                    with st.expander("Raw JSON"):
                        st.json(r.result_json)
                if r.error_msg:
                    st.error(f"Error: {r.error_msg}")

# ── Tab 1: Report Options ─────────────────────────────────────────────────────
with tabs[1]:
    st.subheader("Report Configuration")

    c1, c2 = st.columns(2)
    with c1:
        report_name = st.text_input("Project Name (on cover)", value=project.name)
        report_client = st.text_input("Client Name", value=project.client or "")
        report_engineer = st.text_input("Engineer of Record", value=project.engineer or "")
    with c2:
        report_date = st.text_input("Report Date", value=project.date or datetime.today().strftime("%Y-%m-%d"))
        report_desc = st.text_area("Description / Scope", value=project.description or "", height=100)

    st.divider()
    st.subheader("Sections to Include")
    include_cols = st.columns(5)
    include_flags = {}
    for i, (atype, (label, _)) in enumerate(ANALYSIS_TYPES.items()):
        available = atype in latest and latest[atype].status == "completed"
        default_val = available
        include_flags[atype] = include_cols[i].checkbox(
            label,
            value=default_val,
            disabled=not available,
            help="Analysis not run" if not available else None,
        )

    st.divider()
    include_ai = st.checkbox("Include AI Findings & Recommendations section", value=False)
    if include_ai:
        ai_status = check_ai_available()
        if ai_status["any"]:
            st.success("AI provider available: "
                       + ("OpenAI" if ai_status["openai"] else "Anthropic"))
        else:
            st.warning("No AI API key detected. Set `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` "
                       "environment variable to enable AI narrative.")

    # Store config in session state for Tab 2
    st.session_state["rpt_cfg"] = {
        "project_info": {
            "name": report_name, "client": report_client,
            "engineer": report_engineer, "date": report_date,
            "description": report_desc, "mva_base": project.mva_base,
            "frequency": project.frequency,
        },
        "include_flags": include_flags,
        "include_ai": include_ai,
    }
    st.info("Configure options above, then go to **Generate & Download** tab.")

# ── Tab 2: Generate & Download ────────────────────────────────────────────────
with tabs[2]:
    st.subheader("Generate PDF Report")

    cfg = st.session_state.get("rpt_cfg", {})
    p_info = cfg.get("project_info", project_info)
    i_flags = cfg.get("include_flags", {atype: atype in latest for atype in ANALYSIS_TYPES})
    i_ai    = cfg.get("include_ai", False)

    if not REPORTLAB_OK:
        st.error("ReportLab is not installed. Run: `pip install reportlab`")
        st.stop()

    # Show summary of what will be included
    included = [label for atype, (label, _) in ANALYSIS_TYPES.items() if i_flags.get(atype)]
    if not included:
        st.warning("No analyses selected. Configure sections in the **Report Options** tab.")
    else:
        st.markdown("**Report will include:** " + " · ".join(included))

    col_gen, col_info = st.columns([1, 3])
    generate_btn = col_gen.button("📄 Generate PDF", type="primary", disabled=len(included) == 0)

    if generate_btn or "report_pdf_bytes" in st.session_state:
        if generate_btn:
            with st.spinner("Generating report…"):
                # Collect results
                results_for_report = {}
                for atype in ANALYSIS_TYPES:
                    if i_flags.get(atype) and atype in latest and latest[atype].result_json:
                        results_for_report[atype] = latest[atype].result_json

                # AI narrative
                ai_narrative = ""
                if i_ai:
                    with st.spinner("Generating AI narrative…"):
                        ai_narrative = get_narrative(p_info, results_for_report)

                try:
                    pdf_bytes = generate_report(
                        project_info=p_info,
                        results=results_for_report,
                        include_ai_narrative=i_ai,
                        ai_narrative=ai_narrative,
                    )
                    st.session_state["report_pdf_bytes"] = pdf_bytes
                    st.session_state["report_filename"] = (
                        f"{p_info['name'].replace(' ', '_')}_Report_{datetime.today().strftime('%Y%m%d')}.pdf"
                    )
                    st.success("Report generated successfully!")
                except Exception as exc:
                    st.error(f"Report generation failed: {exc}")
                    st.session_state.pop("report_pdf_bytes", None)

        if "report_pdf_bytes" in st.session_state:
            pdf_bytes = st.session_state["report_pdf_bytes"]
            filename  = st.session_state.get("report_filename", "report.pdf")

            st.download_button(
                label="⬇️ Download PDF Report",
                data=pdf_bytes,
                file_name=filename,
                mime="application/pdf",
                type="primary",
            )
            st.caption(f"File: `{filename}`  |  Size: {len(pdf_bytes) / 1024:.1f} KB")

            # Quick page count estimate
            st.info(f"Approx. {max(1, len(pdf_bytes) // 8000)} pages "
                    f"| {len(included)} analysis section(s) included")

            if st.button("🗑️ Clear cached report"):
                st.session_state.pop("report_pdf_bytes", None)
                st.session_state.pop("report_filename", None)
                st.rerun()

# ── Tab 3: AI Narrative Preview ───────────────────────────────────────────────
with tabs[3]:
    st.subheader("AI Narrative Preview")
    st.caption("Generate a standalone AI engineering narrative without producing a full PDF.")

    ai_status = check_ai_available()
    if not ai_status["any"]:
        st.warning(
            "No AI API key is configured.\n\n"
            "To enable AI analysis:\n"
            "- Set `OPENAI_API_KEY` for GPT-4o-mini (recommended)\n"
            "- Or set `ANTHROPIC_API_KEY` for Claude"
        )

    col_p, col_m = st.columns([2, 1])
    ai_provider = col_p.selectbox("Provider", ["auto", "openai", "anthropic"])
    ai_model_override = col_m.text_input("Model override (optional)", placeholder="e.g. gpt-4o")

    with st.expander("📋 View LLM Prompt"):
        results_preview = {
            atype: latest[atype].result_json
            for atype in ANALYSIS_TYPES
            if atype in latest and latest[atype].result_json
        }
        prompt_preview = build_prompt(project_info, results_preview)
        st.code(prompt_preview, language="text")

    run_ai_btn = st.button("🤖 Generate AI Narrative", type="primary",
                            disabled=not ai_status["any"])

    if run_ai_btn:
        results_for_ai = {
            atype: latest[atype].result_json
            for atype in ANALYSIS_TYPES
            if atype in latest and latest[atype].result_json
        }
        with st.spinner("Calling AI provider…"):
            narrative = get_narrative(
                project_info=project_info,
                results=results_for_ai,
                provider=ai_provider,
                model=ai_model_override or None,
            )
        st.session_state["ai_narrative_preview"] = narrative

    if "ai_narrative_preview" in st.session_state:
        st.divider()
        st.subheader("AI Analysis Output")
        narrative_text = st.session_state["ai_narrative_preview"]
        for para in narrative_text.split("\n\n"):
            if para.strip():
                st.markdown(para.strip())

        st.download_button(
            "⬇️ Download Narrative (.txt)",
            data=narrative_text,
            file_name=f"{project.name.replace(' ', '_')}_AI_Narrative.txt",
            mime="text/plain",
        )

        if st.button("🗑️ Clear AI narrative"):
            st.session_state.pop("ai_narrative_preview", None)
            st.rerun()

# ── Sidebar info ──────────────────────────────────────────────────────────────
with st.sidebar:
    st.divider()
    st.markdown("### 📄 Report Status")
    completed_count = sum(
        1 for atype in ANALYSIS_TYPES
        if atype in latest and latest[atype].status == "completed"
    )
    st.metric("Analyses Completed", f"{completed_count} / {len(ANALYSIS_TYPES)}")
    if completed_count == len(ANALYSIS_TYPES):
        st.success("All analyses complete – ready for full report!")
    elif completed_count > 0:
        st.info(f"{len(ANALYSIS_TYPES) - completed_count} analyses still pending.")
    else:
        st.warning("No analyses run yet. Complete pages 03–07 first.")

    st.markdown("### Standards")
    st.caption(
        "IEEE 399 · IEC 60909 · IEEE C37.112 · "
        "IEC 60255 · IEEE 1110 · IEEE 80-2013"
    )
