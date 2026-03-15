"""
PDF Report Generator
Produces a professional engineering report covering all completed analyses.
Uses ReportLab Platypus for multi-page layout.
"""
import io
import os
import traceback
from datetime import datetime
from pathlib import Path

try:
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, HRFlowable, KeepTogether,
    )
    from reportlab.platypus.tableofcontents import TableOfContents
    from reportlab.lib.pagesizes import A4, letter
    from reportlab.lib import colors
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import cm, inch
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT, TA_JUSTIFY
    REPORTLAB_OK = True
except ImportError:
    REPORTLAB_OK = False


# ---------------------------------------------------------------------------
# Style helpers
# ---------------------------------------------------------------------------

def _make_styles():
    base = getSampleStyleSheet()
    styles = {
        "title":     ParagraphStyle("title",     parent=base["Title"],   fontSize=22, spaceAfter=6),
        "subtitle":  ParagraphStyle("subtitle",  parent=base["Normal"],  fontSize=12, spaceAfter=4, textColor=colors.HexColor("#555555")),
        "h1":        ParagraphStyle("h1",        parent=base["Heading1"],fontSize=14, spaceAfter=6, spaceBefore=12,
                                     textColor=colors.HexColor("#1a3a5c"), borderPad=2),
        "h2":        ParagraphStyle("h2",        parent=base["Heading2"],fontSize=12, spaceAfter=4, spaceBefore=8,
                                     textColor=colors.HexColor("#1a3a5c")),
        "body":      ParagraphStyle("body",      parent=base["Normal"],  fontSize=9,  leading=12, spaceAfter=4),
        "finding_ok":   ParagraphStyle("ok",     parent=base["Normal"],  fontSize=9,  textColor=colors.green),
        "finding_warn": ParagraphStyle("warn",   parent=base["Normal"],  fontSize=9,  textColor=colors.HexColor("#cc6600")),
        "finding_crit": ParagraphStyle("crit",   parent=base["Normal"],  fontSize=9,  textColor=colors.red),
        "monospace":    ParagraphStyle("mono",   parent=base["Code"],    fontSize=8,  leading=10),
        "footer":       ParagraphStyle("footer", parent=base["Normal"],  fontSize=7,  textColor=colors.grey, alignment=TA_CENTER),
    }
    return styles


_HDR_STYLE = TableStyle([
    ("BACKGROUND",   (0, 0), (-1, 0), colors.HexColor("#1a3a5c")),
    ("TEXTCOLOR",    (0, 0), (-1, 0), colors.white),
    ("FONTNAME",     (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE",     (0, 0), (-1, 0), 8),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#eef2f7")]),
    ("FONTSIZE",     (0, 1), (-1, -1), 8),
    ("GRID",         (0, 0), (-1, -1), 0.25, colors.HexColor("#cccccc")),
    ("VALIGN",       (0, 0), (-1, -1), "MIDDLE"),
    ("TOPPADDING",   (0, 0), (-1, -1), 3),
    ("BOTTOMPADDING",(0, 0), (-1, -1), 3),
    ("LEFTPADDING",  (0, 0), (-1, -1), 5),
])


# ---------------------------------------------------------------------------
# Main generator
# ---------------------------------------------------------------------------

def generate_report(
    project_info: dict,
    results: dict,
    output_path: str = None,
    include_ai_narrative: bool = False,
    ai_narrative: str = "",
) -> bytes:
    """
    Generate a PDF engineering report.

    Parameters
    ----------
    project_info : dict – project metadata
    results      : dict – keyed by analysis type: load_flow, short_circuit, transient, protection, grounding
    output_path  : optional file path to save PDF; if None returns bytes
    include_ai_narrative : whether to include the AI section
    ai_narrative : AI-generated text string

    Returns PDF as bytes.
    """
    if not REPORTLAB_OK:
        raise RuntimeError("reportlab is not installed. Run: pip install reportlab")

    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=1.8 * cm,
        leftMargin=1.8 * cm,
        topMargin=2.0 * cm,
        bottomMargin=2.0 * cm,
        title=f"Power System Analysis Report – {project_info.get('name', '')}",
        author=project_info.get("engineer", ""),
    )

    styles = _make_styles()
    story = []

    # ---- Cover page ----
    story += _cover_page(project_info, styles)
    story.append(PageBreak())

    # ---- Table of contents placeholder (manual) ----
    story.append(Paragraph("Table of Contents", styles["h1"]))
    toc_items = ["1. Project Information", "2. Load Flow Analysis",
                 "3. Short Circuit Analysis", "4. Transient Stability",
                 "5. Protection Coordination", "6. Grounding Analysis"]
    if include_ai_narrative:
        toc_items.append("7. AI Findings & Recommendations")
    for item in toc_items:
        story.append(Paragraph(item, styles["body"]))
    story.append(PageBreak())

    # ---- 1. Project Information ----
    story += _project_section(project_info, styles)
    story.append(PageBreak())

    # ---- 2. Load Flow ----
    if "load_flow" in results and results["load_flow"]:
        story += _load_flow_section(results["load_flow"], styles)
        story.append(PageBreak())

    # ---- 3. Short Circuit ----
    if "short_circuit" in results and results["short_circuit"]:
        story += _short_circuit_section(results["short_circuit"], styles)
        story.append(PageBreak())

    # ---- 4. Transient Stability ----
    if "transient" in results and results["transient"]:
        story += _transient_section(results["transient"], styles)
        story.append(PageBreak())

    # ---- 5. Protection Coordination ----
    if "protection" in results and results["protection"]:
        story += _protection_section(results["protection"], styles)
        story.append(PageBreak())

    # ---- 6. Grounding ----
    if "grounding" in results and results["grounding"]:
        story += _grounding_section(results["grounding"], styles)
        story.append(PageBreak())

    # ---- 7. AI Narrative ----
    if include_ai_narrative and ai_narrative:
        story += _ai_section(ai_narrative, styles)
        story.append(PageBreak())

    # ---- Back page / signature block ----
    story += _signature_block(project_info, styles)

    doc.build(story, onFirstPage=_add_header_footer, onLaterPages=_add_header_footer)

    pdf_bytes = buf.getvalue()
    if output_path:
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

    return pdf_bytes


# ---------------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------------

def _cover_page(info: dict, styles) -> list:
    story = [Spacer(1, 3 * cm)]
    story.append(Paragraph("POWER SYSTEM ANALYSIS REPORT", styles["title"]))
    story.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor("#1a3a5c")))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph(info.get("name", "Untitled Project"), styles["subtitle"]))
    story.append(Spacer(1, 1.5 * cm))

    cover_data = [
        ["Client:",      info.get("client", "—")],
        ["Engineer:",    info.get("engineer", "—")],
        ["Date:",        info.get("date", datetime.today().strftime("%Y-%m-%d"))],
        ["Description:", info.get("description", "—")],
    ]
    t = Table(cover_data, colWidths=[3.5 * cm, 12 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 0), (-1, -1), 0.25, colors.lightgrey),
        ("VALIGN",   (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    story.append(t)
    story.append(Spacer(1, 2 * cm))

    analyses = ["Load Flow", "Short Circuit", "Transient Stability",
                "Protection Coordination", "Grounding (IEEE 80-2013)"]
    story.append(Paragraph("Studies Included:", styles["h2"]))
    for a in analyses:
        story.append(Paragraph(f"  ✔  {a}", styles["body"]))

    story.append(Spacer(1, 1 * cm))
    story.append(Paragraph(
        "Standards: IEEE 399 · IEC 60909 · IEEE C37.112 · IEC 60255 · IEEE 1110 · IEEE 80-2013",
        ParagraphStyle("sm", fontSize=8, textColor=colors.grey)
    ))
    return story


def _project_section(info: dict, styles) -> list:
    story = [Paragraph("1. Project Information", styles["h1"])]
    rows = [
        ["Parameter", "Value"],
        ["Project Name", info.get("name", "—")],
        ["Client", info.get("client", "—")],
        ["Engineer", info.get("engineer", "—")],
        ["Date", info.get("date", "—")],
        ["System MVA Base", str(info.get("mva_base", "100")) + " MVA"],
        ["System Frequency", str(info.get("frequency", "60")) + " Hz"],
        ["Description", info.get("description", "—")],
    ]
    story.append(_make_table(rows))
    return story


def _load_flow_section(res: dict, styles) -> list:
    story = [Paragraph("2. Load Flow Analysis", styles["h1"])]

    if "error" in res:
        story.append(Paragraph(f"Error: {res['error']}", styles["finding_crit"]))
        return story

    # Summary metrics
    story.append(Paragraph("2.1 Power Balance Summary", styles["h2"]))
    summary_rows = [
        ["Item", "Value"],
        ["Total Generation", f"{res.get('total_generation_mw', 0):.2f} MW"],
        ["Total Load", f"{res.get('total_load_mw', 0):.2f} MW"],
        ["Line Losses", f"{res.get('total_line_losses_mw', 0):.4f} MW"],
        ["Transformer Losses", f"{res.get('total_trafo_losses_mw', 0):.4f} MW"],
        ["Total Losses", f"{res.get('total_losses_mw', 0):.4f} MW"],
    ]
    story.append(_make_table(summary_rows))

    # Findings
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("2.2 Findings", styles["h2"]))
    for f in res.get("summary", []):
        sty = "finding_ok"
        if "CRITICAL" in f or "OVERLOADED" in f or "VIOLATION" in f:
            sty = "finding_crit"
        elif "WARNING" in f:
            sty = "finding_warn"
        story.append(Paragraph(f, styles[sty]))

    # Bus voltage table
    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("2.3 Bus Voltage Results", styles["h2"]))
    bus_rows = [["Bus Name", "Base kV", "Vm (pu)", "Va (°)", "Vm (kV)", "P (MW)", "Q (Mvar)", "Status"]]
    for b in res.get("bus_results", []):
        bus_rows.append([
            b["name"], str(b["base_kv"]),
            f"{b['vm_pu']:.4f}", f"{b['va_deg']:.2f}",
            f"{b['vm_kv']:.3f}", f"{b['p_mw']:.3f}", f"{b['q_mvar']:.3f}",
            b["status"],
        ])
    story.append(_make_table(bus_rows, col_widths=[3, 1.5, 1.8, 1.8, 1.8, 1.8, 1.8, 2], highlight_col=7,
                             good="OK", warn="WARNING", bad="VIOLATION"))

    # Branch table
    if res.get("line_results"):
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph("2.4 Branch Loading Results", styles["h2"]))
        br_rows = [["Branch", "From", "To", "P_from (MW)", "Q_from (Mvar)", "Loss (MW)", "Loading %", "Status"]]
        for ln in res["line_results"]:
            br_rows.append([
                ln["name"], ln["from_bus"], ln["to_bus"],
                f"{ln['p_from_mw']:.3f}", f"{ln['q_from_mvar']:.3f}",
                f"{ln['pl_mw']:.5f}", f"{ln['loading_pct']:.1f}",
                ln["status"],
            ])
        story.append(_make_table(br_rows, col_widths=[2.5, 2, 2, 2.2, 2.2, 2, 1.8, 2],
                                 highlight_col=7, good="OK", warn="WARNING", bad="OVERLOADED"))

    return story


def _short_circuit_section(res: dict, styles) -> list:
    story = [Paragraph("3. Short Circuit Analysis", styles["h1"])]

    if "error" in res:
        story.append(Paragraph(f"Error: {res['error']}", styles["finding_crit"]))
        return story

    story.append(Paragraph(
        f"Fault Type: {res.get('fault_type_label', '')}  |  Case: {res.get('case','').upper()}  |  Standard: {res.get('standard','')}",
        styles["body"]
    ))

    for f in res.get("summary", []):
        sty = "finding_crit" if "CAUTION" in f or "WARNING" in f else "body"
        story.append(Paragraph(f, styles[sty]))

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Bus Fault Current Summary", styles["h2"]))
    rows = [["Bus Name", "Base kV", "Ikss (kA)", "Skss (MVA)", "Ip (kA)", "Rk (Ω)", "Xk (Ω)", "X/R", "Status"]]
    for b in res.get("bus_results", []):
        rows.append([
            b["name"], str(b["base_kv"]),
            f"{b['ikss_ka']:.3f}", f"{b['skss_mva']:.1f}",
            f"{b['ip_ka']:.3f}",
            f"{b['rk_ohm']:.4f}", f"{b['xk_ohm']:.4f}",
            str(b["x_r_ratio"]) if b["x_r_ratio"] else "—",
            b["status"],
        ])
    story.append(_make_table(rows, col_widths=[3, 1.5, 1.8, 1.8, 1.8, 1.8, 1.8, 1.2, 2],
                             highlight_col=8, good="NORMAL", warn="HIGH", bad="VERY HIGH"))
    return story


def _transient_section(res: dict, styles) -> list:
    story = [Paragraph("4. Transient Stability Analysis", styles["h1"])]

    if "error" in res:
        story.append(Paragraph(f"Error: {res['error']}", styles["finding_crit"]))
        return story

    for f in res.get("summary", []):
        sty = "finding_crit" if "UNSTABLE" in f or "CRITICAL" in f else ("finding_warn" if "MARGINAL" in f else "body")
        story.append(Paragraph(f, styles[sty]))

    rows = [["Generator", "Initial δ (°)", "Max |δ| (°)", "Stability"]]
    for g in res.get("generators", []):
        rows.append([
            g["name"],
            f"{g['initial_delta_deg']:.1f}",
            f"{g['max_delta_deg']:.1f}",
            "STABLE" if g["stable"] else "UNSTABLE",
        ])
    story.append(_make_table(rows, col_widths=[5, 3, 3, 3],
                             highlight_col=3, good="STABLE", warn="STABLE", bad="UNSTABLE"))
    return story


def _protection_section(res: dict, styles) -> list:
    story = [Paragraph("5. Protective Device Coordination", styles["h1"])]

    if "error" in res:
        story.append(Paragraph(f"Error: {res['error']}", styles["finding_crit"]))
        return story

    for f in res.get("summary", []):
        sty = "finding_crit" if "PROBLEM" in f else ("finding_ok" if "coordinated" in f.lower() else "body")
        story.append(Paragraph(f, styles[sty]))

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Device Settings", styles["h2"]))
    drows = [["Device", "Pickup (A)", "TDS/TMS", "Curve", "CT Ratio", "Order"]]
    for d in res.get("devices", []):
        drows.append([
            d["name"], str(d["pickup_current_a"]),
            str(d["tds"]), d["curve_type"], d["ct_ratio"], str(d["coord_order"]),
        ])
    story.append(_make_table(drows))

    story.append(Spacer(1, 0.3 * cm))
    story.append(Paragraph("Coordination Margins", styles["h2"]))
    for pair in res.get("pairs", []):
        status = "OK" if pair["coordinated"] else "FAIL"
        sty = "finding_ok" if pair["coordinated"] else "finding_crit"
        story.append(Paragraph(
            f"  {pair['downstream']} → {pair['upstream']}:  "
            f"min margin = {(pair['min_margin_s'] or 0)*1000:.0f} ms  [{status}]",
            styles[sty]
        ))
    return story


def _grounding_section(res: dict, styles) -> list:
    story = [Paragraph("6. Grounding System Analysis (IEEE 80-2013)", styles["h1"])]

    if "error" in res:
        story.append(Paragraph(f"Error: {res['error']}", styles["finding_crit"]))
        return story

    for f in res.get("summary", []):
        sty = "finding_ok" if "COMPLIANT" in f and "NON" not in f and "ACTION" not in f else (
              "finding_crit" if "NON-COMPLIANT" in f or "ACTION" in f else "body")
        story.append(Paragraph(f, styles[sty]))

    for gr in res.get("grid_results", []):
        story.append(Spacer(1, 0.3 * cm))
        story.append(Paragraph(f"Grid: {gr['name']}", styles["h2"]))
        rows = [
            ["Parameter", "Value", "Limit", "Status"],
            ["Grid Resistance Rg", f"{gr['grid_resistance_ohm']:.4f} Ω", "< 1 Ω typical", "—"],
            ["Ground Potential Rise GPR", f"{gr['gpr_v']:.0f} V", "—", "—"],
            ["Mesh Voltage Em", f"{gr['mesh_voltage_v']:.0f} V",
             f"{gr['tolerable_touch_50kg_v']:.0f} V",
             "OK" if gr["touch_voltage_safe"] else "VIOLATION"],
            ["Step Voltage Es", f"{gr['step_voltage_v']:.0f} V",
             f"{gr['tolerable_step_50kg_v']:.0f} V",
             "OK" if gr["step_voltage_safe"] else "VIOLATION"],
            ["Conductor Area", f"{gr['conductor_actual_mm2']:.2f} mm²",
             f"{gr['conductor_required_mm2']:.2f} mm² (min)",
             "OK" if gr["conductor_adequate"] else "INSUFFICIENT"],
        ]
        story.append(_make_table(rows, col_widths=[5, 3, 4, 2.5],
                                 highlight_col=3, good="OK", warn="—", bad="VIOLATION"))

        for rec in gr.get("recommendations", []):
            sty = "finding_crit" if "VIOLATION" in rec else ("finding_warn" if "INSUFFICIENT" in rec or "above" in rec else "body")
            story.append(Paragraph(rec, styles[sty]))

    return story


def _ai_section(narrative: str, styles) -> list:
    story = [Paragraph("7. AI Analysis & Recommendations", styles["h1"])]
    story.append(Paragraph(
        "The following analysis was generated by an AI language model based on the calculated results. "
        "It should be reviewed by a qualified power system engineer.",
        ParagraphStyle("disclaimer", fontSize=8, textColor=colors.grey)
    ))
    story.append(Spacer(1, 0.3 * cm))
    for para in narrative.split("\n\n"):
        if para.strip():
            story.append(Paragraph(para.strip(), styles["body"]))
            story.append(Spacer(1, 0.15 * cm))
    return story


def _signature_block(info: dict, styles) -> list:
    story = [Spacer(1, 2 * cm)]
    story.append(HRFlowable(width="100%", thickness=1, color=colors.lightgrey))
    story.append(Spacer(1, 0.5 * cm))
    story.append(Paragraph("Engineer of Record", styles["h2"]))
    sig_data = [
        ["Name:", info.get("engineer", "___________________")],
        ["Date:", info.get("date", "___________________")],
        ["Signature:", "___________________"],
    ]
    t = Table(sig_data, colWidths=[3 * cm, 8 * cm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("LINEBELOW", (1, 0), (1, -1), 0.5, colors.black),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(t)
    return story


# ---------------------------------------------------------------------------
# Shared table builder
# ---------------------------------------------------------------------------

def _make_table(rows, col_widths=None, highlight_col=None,
                good=None, warn=None, bad=None) -> Table:
    """Build a styled platypus Table."""
    # Convert all cells to string
    str_rows = [[str(c) if c is not None else "—" for c in row] for row in rows]

    if col_widths:
        cw = [w * cm for w in col_widths]
    else:
        # Auto-distribute across 16.5 cm page width
        n = len(rows[0])
        cw = [16.5 / n * cm] * n

    t = Table(str_rows, colWidths=cw, repeatRows=1)
    # ReportLab 4.x removed clone(); recreate from command list instead
    style = TableStyle(_HDR_STYLE.getCommands())

    # Status highlight
    if highlight_col is not None:
        for ri, row in enumerate(str_rows[1:], start=1):
            val = row[highlight_col] if highlight_col < len(row) else ""
            if bad and bad.upper() in val.upper():
                style.add("BACKGROUND", (highlight_col, ri), (highlight_col, ri), colors.HexColor("#ffe6e6"))
                style.add("TEXTCOLOR",  (highlight_col, ri), (highlight_col, ri), colors.red)
                style.add("FONTNAME",   (highlight_col, ri), (highlight_col, ri), "Helvetica-Bold")
            elif warn and warn.upper() in val.upper():
                style.add("BACKGROUND", (highlight_col, ri), (highlight_col, ri), colors.HexColor("#fff4cc"))
                style.add("TEXTCOLOR",  (highlight_col, ri), (highlight_col, ri), colors.HexColor("#cc6600"))
            elif good and good.upper() in val.upper():
                style.add("TEXTCOLOR",  (highlight_col, ri), (highlight_col, ri), colors.green)

    t.setStyle(style)
    return t


# ---------------------------------------------------------------------------
# Page header / footer callback
# ---------------------------------------------------------------------------

def _add_header_footer(canvas, doc):
    canvas.saveState()
    # Header line
    canvas.setStrokeColor(colors.HexColor("#1a3a5c"))
    canvas.setLineWidth(1)
    canvas.line(doc.leftMargin, doc.height + doc.topMargin + 0.3 * cm,
                doc.width + doc.leftMargin, doc.height + doc.topMargin + 0.3 * cm)
    canvas.setFont("Helvetica-Bold", 8)
    canvas.setFillColor(colors.HexColor("#1a3a5c"))
    canvas.drawString(doc.leftMargin, doc.height + doc.topMargin + 0.5 * cm,
                      "POWER SYSTEM ANALYSIS REPORT – CONFIDENTIAL")
    # Footer
    canvas.setFont("Helvetica", 7)
    canvas.setFillColor(colors.grey)
    canvas.drawCentredString(
        doc.width / 2 + doc.leftMargin,
        doc.bottomMargin - 0.5 * cm,
        f"Page {doc.page}  |  Generated {datetime.today().strftime('%Y-%m-%d %H:%M')}  |  IEEE 80 · C37.112 · IEC 60909"
    )
    canvas.restoreState()
