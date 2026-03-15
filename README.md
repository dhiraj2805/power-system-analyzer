# Power System Analysis AI Tool

A comprehensive engineering-grade power-system analysis platform covering:

| Module | Description |
|---|---|
| Load Flow | Newton-Raphson / IWAMOTO / BFS convergence, voltage profiles, loss summaries |
| Short Circuit | IEC 60909 & ANSI – 3Ø, SLG, DLG, LL fault currents, X/R ratios, SC MVA |
| Transient Stability | Classical machine swing-equation (RK4), rotor-angle plots, CCT estimation |
| Protection Coordination | ANSI/IEC TCC curves, CTI margin verification, automated relay-setting recommendation |
| Grounding System | IEEE 80-2013 grid resistance, GPR, mesh/step voltage, tolerable-limit compliance |
| Reports | PDF report generator (per study + executive summary) |
| AI Analysis | Optional OpenAI / Anthropic integration for narrative findings and recommendations |

---

## Quick Start

### Requirements
- Python 3.9 or newer
- Internet access for first-time package download

### Installation & Launch (Windows PowerShell)

```powershell
cd power_system_analyzer
.\run.ps1
```

Then open **http://localhost:8501** in your browser.

---

## Workflow

1. **Project** page – create a new project and set base parameters (MVA, frequency, voltage base).
2. **Network Data** page – enter buses, lines, transformers, generators, loads, and shunts via editable tables or CSV import.
3. Run each analysis module from its dedicated page.
4. **Reports** page – select studies, optionally enable AI narrative, and export a PDF.

---

## Data Import

Each equipment table supports CSV import/export. Template files are generated on the Network Data page.

---

## AI Integration (optional)

Set one of the following environment variables before launching:

```powershell
$env:OPENAI_API_KEY  = "sk-..."
$env:ANTHROPIC_API_KEY = "sk-ant-..."
```

If neither key is set, the tool runs fully offline and skips the narrative section of reports.

---

## Standards Reference

- Load Flow: IEEE Std 399 (Brown Book)
- Short Circuit: IEC 60909-0 / ANSI C37 series
- Transient Stability: IEEE Std 1110
- Protection: IEEE C37.112, IEC 60255
- Grounding: IEEE Std 80-2013
- Distribution: IEEE Std 141 (Red Book)
