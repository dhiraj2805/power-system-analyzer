"""Page 09 – Interactive Single Line Diagram (SLD)

Renders an interactive, IEEE-style single line diagram for the active project.
Features
--------
- Hierarchical auto-layout: buses grouped by voltage level (HV at top)
- Standard SLD symbols: bus bars, transformers (two circles),
  generators (G circle), loads (▼ triangle), shunts/cap-banks
- Load-flow overlay: per-bus voltage in p.u., line loading %, colour coding
- Manual layout editor: drag-free but precise x/y override per bus
- Plotly pan/zoom, hover tooltips on all equipment
"""
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collections import defaultdict

import streamlit as st
import plotly.graph_objects as go

from models.database import get_session, init_db
from models.schema import (
    Bus, Line, Transformer, Generator, Load, Shunt, AnalysisResult,
)

st.set_page_config(page_title="Single Line Diagram", page_icon="📐", layout="wide")
init_db()
if "project_id" not in st.session_state:
    st.session_state.project_id = None

st.title("📐 Single Line Diagram")
st.caption("Interactive IEEE-style network diagram with load-flow overlay")

pid = st.session_state.get("project_id")
if not pid:
    st.warning("No project selected. Use the sidebar to select a project.")
    st.stop()

# ── Data loading ───────────────────────────────────────────────────────────────
session = get_session()
try:
    buses   = session.query(Bus).filter_by(project_id=pid).all()
    lines   = session.query(Line).filter_by(project_id=pid).all()
    trafos  = session.query(Transformer).filter_by(project_id=pid).all()
    gens    = session.query(Generator).filter_by(project_id=pid).all()
    loads   = session.query(Load).filter_by(project_id=pid).all()
    shunts  = session.query(Shunt).filter_by(project_id=pid).all()
    lf_rec  = (session.query(AnalysisResult)
               .filter_by(project_id=pid, analysis_type="load_flow")
               .order_by(AnalysisResult.created_at.desc()).first())
    sc_rec  = (session.query(AnalysisResult)
               .filter_by(project_id=pid, analysis_type="short_circuit")
               .order_by(AnalysisResult.created_at.desc()).first())
finally:
    session.close()

if not buses:
    st.info("No buses found. Go to **02 Network Data** to add network equipment.")
    st.stop()

lf_data = lf_rec.result_json if lf_rec and lf_rec.status == "completed" else None
sc_data = sc_rec.result_json if sc_rec and sc_rec.status == "completed" else None

# ── Colour palette (voltage level → colour) ────────────────────────────────────
_sorted_kvs = sorted({b.base_kv for b in buses}, reverse=True)
_palette     = ["#b91c1c", "#b45309", "#15803d", "#1d4ed8", "#6d28d9", "#0e7490"]
KV_COLOR     = {kv: _palette[i % len(_palette)] for i, kv in enumerate(_sorted_kvs)}

# ── Session-state key for bus positions ───────────────────────────────────────
POS_KEY = f"sld_pos_{pid}"

# ── Layout computation (networkx spring + voltage-level snap) ─────────────────

def _auto_layout() -> dict:
    try:
        import networkx as nx
        G = nx.Graph()
        bid_set = {b.id for b in buses}
        for b in buses:
            G.add_node(b.id)
        for ln in lines:
            if ln.from_bus_id in bid_set and ln.to_bus_id in bid_set:
                G.add_edge(ln.from_bus_id, ln.to_bus_id)
        for t in trafos:
            if t.hv_bus_id in bid_set and t.lv_bus_id in bid_set:
                G.add_edge(t.hv_bus_id, t.lv_bus_id, weight=0.4)
        spring = nx.spring_layout(G, seed=42, k=2.5, iterations=120)
    except Exception:
        spring = {b.id: (i * 2.0, 0.0) for i, b in enumerate(buses)}

    kv_groups = defaultdict(list)
    for b in buses:
        kv_groups[b.base_kv].append(b)

    pos = {}
    for level_i, kv in enumerate(sorted(kv_groups, reverse=True)):
        y = -level_i * 7.0
        grp = sorted(kv_groups[kv], key=lambda b: spring.get(b.id, (0, 0))[0])
        n   = len(grp)
        for xi, b in enumerate(grp):
            x = (xi - (n - 1) / 2.0) * 11.0
            pos[b.id] = (round(x, 2), round(y, 2))
    return pos


def _get_pos() -> dict:
    if POS_KEY not in st.session_state:
        st.session_state[POS_KEY] = _auto_layout()
    return st.session_state[POS_KEY]


# ── Figure builder ─────────────────────────────────────────────────────────────

def _build_figure(pos: dict, show_lf: bool, show_labels: bool,
                  show_sc: bool) -> go.Figure:
    fig = go.Figure()
    shapes: list = []
    annots: list = []

    # ── lookup tables ──────────────────────────────────────────────────────────
    bus_lf:  dict = {}   # bus_id → bus result dict
    line_lf: dict = {}   # name   → line result dict
    bus_sc:  dict = {}   # bus_id → sc result dict

    if lf_data and show_lf:
        for br in lf_data.get("bus_results", []):
            if br.get("bus_id") is not None:
                bus_lf[br["bus_id"]] = br
        for lr in (lf_data.get("line_results", []) +
                   lf_data.get("trafo_results", [])):
            line_lf[lr.get("name", "")] = lr

    if sc_data and show_sc:
        for br in sc_data.get("bus_results", []):
            if br.get("bus_id") is not None:
                bus_sc[br["bus_id"]] = br

    # ══════════════════════════════════════════════════════════════════════════
    # 1. TRANSMISSION LINES
    # ══════════════════════════════════════════════════════════════════════════
    for ln in lines:
        if not ln.in_service:
            continue
        p1 = pos.get(ln.from_bus_id)
        p2 = pos.get(ln.to_bus_id)
        if not p1 or not p2:
            continue

        lr      = line_lf.get(ln.name, {})
        loading = lr.get("loading_pct")
        lcolor  = ("#ef4444" if loading is not None and loading > 100 else
                   "#f97316" if loading is not None and loading > 80  else
                   "#475569")
        lwidth  = 3 if loading is not None and loading > 80 else 2

        hover = (f"<b>{ln.name}</b><br>"
                 f"Length: {ln.length_km} km<br>"
                 f"R={ln.r_ohm_per_km:.4f} Ω/km  X={ln.x_ohm_per_km:.4f} Ω/km<br>"
                 + (f"Loading: <b>{loading:.1f}%</b>" if loading is not None
                    else "Run Load Flow for loading"))

        fig.add_trace(go.Scatter(
            x=[p1[0], p2[0]], y=[p1[1], p2[1]],
            mode="lines",
            line=dict(color=lcolor, width=lwidth),
            hoverinfo="text", hovertext=hover,
            showlegend=False, name=ln.name,
        ))

        if show_labels:
            mx, my = (p1[0] + p2[0]) / 2, (p1[1] + p2[1]) / 2
            lbl = ln.name
            if loading is not None:
                lbl += f"<br>{loading:.0f}%"
            annots.append(dict(
                x=mx, y=my, text=lbl, showarrow=False,
                font=dict(size=7, color=lcolor),
                bgcolor="rgba(255,255,255,0.75)", borderpad=2,
            ))

    # ══════════════════════════════════════════════════════════════════════════
    # 2. TRANSFORMERS
    # ══════════════════════════════════════════════════════════════════════════
    for t in trafos:
        if not t.in_service:
            continue
        p1 = pos.get(t.hv_bus_id)
        p2 = pos.get(t.lv_bus_id)
        if not p1 or not p2:
            continue

        mx = (p1[0] + p2[0]) / 2
        my = (p1[1] + p2[1]) / 2
        r   = 0.65    # circle radius
        gap = 0.08    # gap between the two circles

        hover_t = (f"<b>{t.name}</b><br>"
                   f"{t.sn_mva} MVA  {t.vn_hv_kv}/{t.vn_lv_kv} kV<br>"
                   f"vk={t.vk_percent}%  vkr={t.vkr_percent}%<br>"
                   f"Vector: {t.vector_group}")

        # Wire from HV bus → inside upper circle
        fig.add_trace(go.Scatter(
            x=[p1[0], mx], y=[p1[1], my + r + gap],
            mode="lines", line=dict(color="#334155", width=2),
            hoverinfo="skip", showlegend=False,
        ))
        # Wire from inside lower circle → LV bus
        fig.add_trace(go.Scatter(
            x=[mx, p2[0]], y=[my - r - gap, p2[1]],
            mode="lines", line=dict(color="#334155", width=2),
            hoverinfo="skip", showlegend=False,
        ))
        # Upper transformer circle
        shapes.append(dict(
            type="circle", xref="x", yref="y",
            x0=mx - r, y0=my + gap / 2,
            x1=mx + r, y1=my + 2 * r + gap / 2,
            line=dict(color="#334155", width=2.5),
            fillcolor="white", layer="above",
        ))
        # Lower transformer circle
        shapes.append(dict(
            type="circle", xref="x", yref="y",
            x0=mx - r, y0=my - 2 * r - gap / 2,
            x1=mx + r, y1=my - gap / 2,
            line=dict(color="#334155", width=2.5),
            fillcolor="white", layer="above",
        ))
        # Invisible hover target at midpoint
        fig.add_trace(go.Scatter(
            x=[mx], y=[my],
            mode="markers",
            marker=dict(symbol="square", size=30,
                        color="rgba(0,0,0,0)",
                        line=dict(color="rgba(0,0,0,0)")),
            hoverinfo="text", hovertext=hover_t,
            showlegend=False, name=t.name,
        ))

        if show_labels:
            annots.append(dict(
                x=mx + r + 0.5, y=my, text=f"<b>{t.name}</b><br>{t.sn_mva} MVA",
                showarrow=False, xanchor="left",
                font=dict(size=8, color="#334155"),
                bgcolor="rgba(255,255,255,0.85)",
            ))

    # ══════════════════════════════════════════════════════════════════════════
    # 3. BUS BARS
    # ══════════════════════════════════════════════════════════════════════════
    for bus in buses:
        p = pos.get(bus.id)
        if not p:
            continue
        x, y   = p
        bcolor = KV_COLOR.get(bus.base_kv, "#475569")
        hw     = 3.2   # half-width of bus bar

        shapes.append(dict(
            type="line", xref="x", yref="y",
            x0=x - hw, y0=y, x1=x + hw, y1=y,
            line=dict(color=bcolor, width=11),
            layer="above",
        ))

        # Voltage annotation
        lf_bus = bus_lf.get(bus.id, {})
        sc_bus = bus_sc.get(bus.id, {})
        vm     = lf_bus.get("vm_pu")
        va     = lf_bus.get("va_deg")
        ikss   = sc_bus.get("ikss_ka")

        vm_color = bcolor
        if vm is not None:
            vm_color = ("#dc2626" if vm < 0.95 or vm > 1.05 else
                        "#f97316" if vm < 0.97 or vm > 1.03 else
                        "#15803d")

        lbl_top = f"<b>{bus.name}</b>  {bus.base_kv} kV"
        lbl_bot = ""
        if vm is not None and show_lf:
            lbl_bot += f"<span style='color:{vm_color}'>{vm:.4f} pu</span>"
            if va is not None:
                lbl_bot += f"  {va:.2f}°"
        if ikss is not None and show_sc:
            lbl_bot += f"  Ikss={ikss:.2f} kA"

        hover_b = (f"<b>{bus.name}</b><br>"
                   f"Base: {bus.base_kv} kV  Type: {bus.bus_type}<br>"
                   f"Zone: {bus.zone or '—'}"
                   + (f"<br>Vm={vm:.4f} pu  Va={va:.2f}°" if vm else "")
                   + (f"<br>Ikss={ikss:.3f} kA" if ikss else ""))

        # Invisible hover bar over the bus bar
        fig.add_trace(go.Scatter(
            x=[x - hw, x + hw], y=[y, y],
            mode="lines",
            line=dict(color="rgba(0,0,0,0)", width=12),
            hoverinfo="text", hovertext=hover_b,
            showlegend=False, name=bus.name,
        ))

        # Label above bus bar
        annots.append(dict(
            x=x, y=y + 0.55,
            text=lbl_top,
            showarrow=False,
            font=dict(size=9, color=bcolor),
            bgcolor="rgba(255,255,255,0.90)",
            bordercolor=bcolor, borderwidth=1, borderpad=3,
        ))
        # Readings below bus bar
        if lbl_bot:
            annots.append(dict(
                x=x, y=y - 0.5,
                text=lbl_bot,
                showarrow=False,
                font=dict(size=8, color=vm_color),
                bgcolor="rgba(255,255,255,0.80)",
            ))

    # ══════════════════════════════════════════════════════════════════════════
    # 4. GENERATORS
    # ══════════════════════════════════════════════════════════════════════════
    gen_slot = defaultdict(int)
    for gen in gens:
        if not gen.in_service:
            continue
        p = pos.get(gen.bus_id)
        if not p:
            continue
        x, y  = p
        slot  = gen_slot[gen.bus_id]
        gen_slot[gen.bus_id] += 1
        gx = x - 4.0 - slot * 2.8
        gy = y - 2.5

        # Connection stub: bus → elbow → generator
        fig.add_trace(go.Scatter(
            x=[x - 3.2, x - 3.2, gx],
            y=[y,        gy + 0.65, gy + 0.65],
            mode="lines", line=dict(color="#78350f", width=1.8),
            hoverinfo="skip", showlegend=False,
        ))
        # Generator circle
        fig.add_trace(go.Scatter(
            x=[gx], y=[gy],
            mode="markers+text",
            marker=dict(
                symbol="circle", size=36,
                color="#fef3c7",
                line=dict(color="#92400e", width=2.5),
            ),
            text=["G"],
            textposition="middle center",
            textfont=dict(size=14, color="#92400e", family="Arial Black"),
            hoverinfo="text",
            hovertext=(f"<b>{gen.name}</b><br>"
                       f"P = {gen.p_mw} MW<br>"
                       f"Vm = {gen.vm_pu} pu<br>"
                       f"Sn = {gen.sn_mva} MVA<br>"
                       f"H = {gen.H_s} s"),
            showlegend=False, name=gen.name,
        ))
        if show_labels:
            annots.append(dict(
                x=gx, y=gy - 0.85,
                text=f"<b>{gen.name}</b><br>{gen.p_mw} MW",
                showarrow=False,
                font=dict(size=8, color="#92400e"),
                bgcolor="rgba(255,255,255,0.8)",
            ))

    # ══════════════════════════════════════════════════════════════════════════
    # 5. LOADS
    # ══════════════════════════════════════════════════════════════════════════
    load_slot = defaultdict(int)
    for load in loads:
        if not load.in_service:
            continue
        p = pos.get(load.bus_id)
        if not p:
            continue
        x, y  = p
        slot  = load_slot[load.bus_id]
        load_slot[load.bus_id] += 1
        lx = x + 1.2 + slot * 2.6
        ly = y - 2.5

        # Connection stub
        fig.add_trace(go.Scatter(
            x=[lx, lx, lx],
            y=[y,  ly + 0.7, ly + 0.35],
            mode="lines", line=dict(color="#7f1d1d", width=1.8),
            hoverinfo="skip", showlegend=False,
        ))
        # Load triangle
        fig.add_trace(go.Scatter(
            x=[lx], y=[ly],
            mode="markers",
            marker=dict(
                symbol="triangle-down", size=22,
                color="#fee2e2",
                line=dict(color="#7f1d1d", width=2.5),
            ),
            hoverinfo="text",
            hovertext=(f"<b>{load.name}</b><br>"
                       f"P = {load.p_mw} MW<br>"
                       f"Q = {load.q_mvar} Mvar"),
            showlegend=False, name=load.name,
        ))
        if show_labels:
            annots.append(dict(
                x=lx + 0.55, y=ly,
                text=f"{load.p_mw} MW",
                showarrow=False, xanchor="left",
                font=dict(size=8, color="#7f1d1d"),
            ))

    # ══════════════════════════════════════════════════════════════════════════
    # 6. SHUNTS / CAPACITOR BANKS
    # ══════════════════════════════════════════════════════════════════════════
    shunt_slot = defaultdict(int)
    for sh in shunts:
        if not sh.in_service:
            continue
        p = pos.get(sh.bus_id)
        if not p:
            continue
        x, y  = p
        slot  = shunt_slot[sh.bus_id]
        shunt_slot[sh.bus_id] += 1
        sx = x - 1.2 - slot * 2.6
        sy = y - 2.5
        sc = "#15803d" if sh.q_mvar > 0 else "#dc2626"
        lbl_q = f"{'C' if sh.q_mvar > 0 else 'R'} {abs(sh.q_mvar)} Mvar"

        # Connection stub
        fig.add_trace(go.Scatter(
            x=[sx, sx, sx],
            y=[y,  sy + 0.7, sy + 0.38],
            mode="lines", line=dict(color=sc, width=1.8),
            hoverinfo="skip", showlegend=False,
        ))
        # Capacitor plates (two horizontal lines)
        for yoff in [0.28, 0.0]:
            shapes.append(dict(
                type="line", xref="x", yref="y",
                x0=sx - 0.5, y0=sy + yoff,
                x1=sx + 0.5, y1=sy + yoff,
                line=dict(color=sc, width=3.5),
            ))
        # Ground line
        shapes.append(dict(
            type="line", xref="x", yref="y",
            x0=sx, y0=sy, x1=sx, y1=sy - 0.4,
            line=dict(color=sc, width=2),
        ))
        # Ground symbol (short lines fanning out)
        for i, hw in enumerate([0.35, 0.22, 0.10]):
            shapes.append(dict(
                type="line", xref="x", yref="y",
                x0=sx - hw, y0=sy - 0.4 - i * 0.15,
                x1=sx + hw, y1=sy - 0.4 - i * 0.15,
                line=dict(color=sc, width=2 - i * 0.5),
            ))

        # Hover
        fig.add_trace(go.Scatter(
            x=[sx], y=[sy + 0.14],
            mode="markers",
            marker=dict(symbol="square", size=20,
                        color="rgba(0,0,0,0)",
                        line=dict(color="rgba(0,0,0,0)")),
            hoverinfo="text",
            hovertext=(f"<b>{sh.name}</b><br>{lbl_q}"),
            showlegend=False, name=sh.name,
        ))
        if show_labels:
            annots.append(dict(
                x=sx + 0.6, y=sy + 0.14,
                text=lbl_q, showarrow=False, xanchor="left",
                font=dict(size=8, color=sc),
            ))

    # ══════════════════════════════════════════════════════════════════════════
    # 7. LEGEND (voltage levels)
    # ══════════════════════════════════════════════════════════════════════════
    for i, (kv, color) in enumerate(sorted(KV_COLOR.items(), reverse=True)):
        annots.append(dict(
            xref="paper", yref="paper",
            x=0.01, y=0.99 - i * 0.055,
            text=f"<b style='color:{color}'>━</b>  {kv} kV",
            showarrow=False, xanchor="left",
            font=dict(size=10, color=color),
            bgcolor="rgba(255,255,255,0)",
        ))

    # ══════════════════════════════════════════════════════════════════════════
    # Layout
    # ══════════════════════════════════════════════════════════════════════════
    xs = [v[0] for v in pos.values()]
    ys = [v[1] for v in pos.values()]
    pad_x, pad_y = 8, 5

    fig.update_layout(
        shapes=shapes,
        annotations=annots,
        showlegend=False,
        xaxis=dict(
            range=[min(xs) - pad_x, max(xs) + pad_x],
            showgrid=False, showticklabels=False, zeroline=False,
        ),
        yaxis=dict(
            range=[min(ys) - pad_y, max(ys) + 3],
            showgrid=False, showticklabels=False, zeroline=False,
            scaleanchor="x", scaleratio=1,
        ),
        plot_bgcolor="#f1f5f9",
        paper_bgcolor="white",
        height=720,
        margin=dict(l=5, r=5, t=10, b=5),
        dragmode="pan",
        hovermode="closest",
    )
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# Page UI
# ══════════════════════════════════════════════════════════════════════════════

tabs = st.tabs(["📐 Diagram", "✏️ Layout Editor", "📋 Network Summary"])

# ── TAB 0: Diagram ─────────────────────────────────────────────────────────────
with tabs[0]:
    c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
    show_lf  = c1.checkbox("⚡ LF Overlay",    value=bool(lf_data),
                            help="Show load-flow voltages & line loadings")
    show_sc  = c2.checkbox("💥 SC Overlay",    value=False,
                            help="Show short-circuit fault currents")
    show_lbl = c3.checkbox("🏷️ Labels",         value=True)

    if c4.button("🔄 Reset Auto-Layout"):
        st.session_state[POS_KEY] = _auto_layout()
        st.rerun()

    if not lf_data and show_lf:
        st.info("No load-flow results yet. Run Load Flow (page 03) to enable overlay.")
    if not sc_data and show_sc:
        st.info("No short-circuit results yet. Run Short Circuit (page 04) to enable overlay.")

    fig = _build_figure(_get_pos(), show_lf=show_lf, show_labels=show_lbl, show_sc=show_sc)
    st.plotly_chart(fig, use_container_width=True)

    # Symbol legend
    st.caption(
        "**Symbols:** "
        "━  Bus bar  |  "
        "⊙  Transformer (2 circles)  |  "
        "🟡 G  Generator  |  "
        "🔴 ▼  Load  |  "
        "═  Capacitor / Reactor  |  "
        "**Line colours:** grey = normal · orange = >80% · red = overloaded"
    )

# ── TAB 1: Layout Editor ───────────────────────────────────────────────────────
with tabs[1]:
    st.subheader("Bus Position Editor")
    st.caption(
        "Manually set (x, y) coordinates for each bus. "
        "Higher y = higher on diagram.  "
        "The auto-layout groups buses by voltage level (step = 7 units per level)."
    )

    pos_now = _get_pos()
    new_pos = {}

    col_hdr = st.columns([3, 2, 2, 2])
    col_hdr[0].markdown("**Bus**")
    col_hdr[1].markdown("**Base kV**")
    col_hdr[2].markdown("**x**")
    col_hdr[3].markdown("**y**")

    for bus in sorted(buses, key=lambda b: (-b.base_kv, b.name)):
        cx, cy = pos_now.get(bus.id, (0.0, 0.0))
        c0, c1, c2, c3 = st.columns([3, 2, 2, 2])
        bcolor = KV_COLOR.get(bus.base_kv, "#475569")
        c0.markdown(
            f"<span style='color:{bcolor};font-weight:bold'>{bus.name}</span>",
            unsafe_allow_html=True
        )
        c1.markdown(f"{bus.base_kv} kV")
        nx_val = c2.number_input(
            f"x_{bus.id}", value=float(cx), step=1.0,
            format="%.1f", label_visibility="collapsed",
        )
        ny_val = c3.number_input(
            f"y_{bus.id}", value=float(cy), step=1.0,
            format="%.1f", label_visibility="collapsed",
        )
        new_pos[bus.id] = (nx_val, ny_val)

    st.divider()
    cola, colb = st.columns(2)
    if cola.button("✅ Apply Custom Layout", type="primary"):
        st.session_state[POS_KEY] = new_pos
        st.success("Layout applied. Switch to the **Diagram** tab to see changes.")
    if colb.button("🔄 Reset to Auto-Layout"):
        st.session_state[POS_KEY] = _auto_layout()
        st.success("Auto-layout restored.")
        st.rerun()

    # Quick layout presets
    st.divider()
    st.subheader("Quick Presets")
    p1, p2 = st.columns(2)
    if p1.button("Hierarchical (default)"):
        st.session_state[POS_KEY] = _auto_layout()
        st.rerun()
    if p2.button("Spread wide (×1.5)"):
        auto = _auto_layout()
        st.session_state[POS_KEY] = {bid: (x * 1.5, y * 1.5)
                                      for bid, (x, y) in auto.items()}
        st.rerun()

# ── TAB 2: Network Summary ─────────────────────────────────────────────────────
with tabs[2]:
    st.subheader("Network Equipment Summary")

    import pandas as pd

    # Metrics
    m = st.columns(6)
    m[0].metric("Buses",        len(buses))
    m[1].metric("Lines",        len(lines))
    m[2].metric("Transformers", len(trafos))
    m[3].metric("Generators",   len(gens))
    m[4].metric("Loads",        len(loads))
    m[5].metric("Shunts",       len(shunts))

    st.divider()

    c_bus, c_equip = st.columns(2)

    with c_bus:
        st.subheader("Buses")
        bus_rows = []
        for b in sorted(buses, key=lambda x: (-x.base_kv, x.name)):
            lf_b = {}
            sc_b = {}
            if lf_data:
                lf_b = next((r for r in lf_data.get("bus_results", [])
                              if r.get("bus_id") == b.id), {})
            if sc_data:
                sc_b = next((r for r in sc_data.get("bus_results", [])
                              if r.get("bus_id") == b.id), {})
            bus_rows.append({
                "Name":     b.name,
                "Base kV":  b.base_kv,
                "Type":     {1: "PQ", 2: "PV", 3: "Slack"}.get(b.bus_type, str(b.bus_type)),
                "Zone":     b.zone or "—",
                "Vm (pu)":  f"{lf_b['vm_pu']:.4f}" if lf_b.get("vm_pu") else "—",
                "Va (°)":   f"{lf_b['va_deg']:.2f}" if lf_b.get("va_deg") is not None else "—",
                "Ikss (kA)":f"{sc_b['ikss_ka']:.3f}" if sc_b.get("ikss_ka") else "—",
            })
        df_bus = pd.DataFrame(bus_rows)
        st.dataframe(df_bus, use_container_width=True, hide_index=True)

    with c_equip:
        st.subheader("Lines & Transformers")
        br_rows = []
        for ln in lines:
            lr = {}
            if lf_data:
                lr = next((r for r in lf_data.get("line_results", [])
                            if r.get("name") == ln.name), {})
            br_rows.append({
                "Name":       ln.name,
                "Type":       "Line",
                "From → To":  f"Bus{ln.from_bus_id} → Bus{ln.to_bus_id}",
                "Loading %":  f"{lr['loading_pct']:.1f}" if lr.get("loading_pct") else "—",
                "Status":     lr.get("status", "—"),
            })
        for t in trafos:
            br_rows.append({
                "Name":       t.name,
                "Type":       "Transformer",
                "From → To":  f"{t.vn_hv_kv} kV → {t.vn_lv_kv} kV",
                "Loading %":  "—",
                "Status":     "In service" if t.in_service else "Out of service",
            })
        df_br = pd.DataFrame(br_rows)
        st.dataframe(df_br, use_container_width=True, hide_index=True)

    st.divider()
    st.subheader("Generators & Loads")
    cg, cl = st.columns(2)
    with cg:
        gen_rows = [{"Name": g.name, "Bus": g.bus_id,
                     "P (MW)": g.p_mw, "Sn (MVA)": g.sn_mva,
                     "Vm (pu)": g.vm_pu} for g in gens]
        st.dataframe(pd.DataFrame(gen_rows) if gen_rows else pd.DataFrame(),
                     use_container_width=True, hide_index=True)
    with cl:
        load_rows = [{"Name": l.name, "Bus": l.bus_id,
                      "P (MW)": l.p_mw, "Q (Mvar)": l.q_mvar} for l in loads]
        st.dataframe(pd.DataFrame(load_rows) if load_rows else pd.DataFrame(),
                     use_container_width=True, hide_index=True)