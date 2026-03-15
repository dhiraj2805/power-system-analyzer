"""
AI Analysis Module
Sends structured power-system results to an LLM (OpenAI or Anthropic)
and returns a human-readable narrative with findings and recommendations.
"""
import os
import json
import textwrap
from typing import Optional


def _truncate(obj, max_items: int = 15) -> object:
    """Truncate long lists in results to keep prompts manageable."""
    if isinstance(obj, list):
        return obj[:max_items]
    if isinstance(obj, dict):
        return {k: _truncate(v, max_items) for k, v in obj.items()}
    return obj


def build_prompt(project_info: dict, results: dict) -> str:
    """Build a structured LLM prompt from analysis results."""

    def _fmt(res_dict: dict, key: str) -> str:
        r = res_dict.get(key)
        if not r:
            return "  Not performed."
        if "error" in r:
            return f"  Error: {r['error']}"
        summary = r.get("summary", [])
        return "\n".join(f"  - {s}" for s in summary) if summary else "  (No summary available)"

    prompt = textwrap.dedent(f"""
    You are a senior power systems engineer reviewing the following analysis results.

    PROJECT: {project_info.get('name')}
    Client: {project_info.get('client')}
    System Base: {project_info.get('mva_base')} MVA, {project_info.get('frequency')} Hz

    === LOAD FLOW ===
    {_fmt(results, 'load_flow')}

    === SHORT CIRCUIT ===
    {_fmt(results, 'short_circuit')}

    === TRANSIENT STABILITY ===
    {_fmt(results, 'transient')}

    === PROTECTION COORDINATION ===
    {_fmt(results, 'protection')}

    === GROUNDING (IEEE 80-2013) ===
    {_fmt(results, 'grounding')}

    Based on the above findings, provide a concise but thorough engineering analysis covering:
    1. Executive Summary (2-3 sentences)
    2. Critical Issues Requiring Immediate Action (if any)
    3. Load Flow Assessment – voltage profile quality, loss level, over/under-loaded elements
    4. Short Circuit Assessment – fault level adequacy, equipment rating concerns
    5. Transient Stability Assessment – stability margins, CCT adequacy
    6. Protection Coordination Assessment – CTI compliance, relay setting concerns
    7. Grounding Assessment – IEEE 80 compliance, step/touch voltage margins
    8. Prioritised Recommendations for System Improvement (numbered list)
    9. Suggested Further Studies

    Write in professional engineering report style. Reference applicable standards.
    Be specific about which buses, equipment, or device names have issues.
    """).strip()

    return prompt


def get_narrative(
    project_info: dict,
    results: dict,
    provider: str = "auto",
    model: str = None,
) -> str:
    """
    Generate an AI narrative for the analysis results.

    Parameters
    ----------
    project_info : project metadata dict
    results      : dict of analysis result dicts
    provider     : 'openai', 'anthropic', or 'auto' (tries OpenAI first, then Anthropic)
    model        : optional model override

    Returns the narrative string, or an error message if no API key is available.
    """
    openai_key    = os.environ.get("OPENAI_API_KEY", "")
    anthropic_key = os.environ.get("ANTHROPIC_API_KEY", "")

    if provider == "auto":
        if openai_key:
            provider = "openai"
        elif anthropic_key:
            provider = "anthropic"
        else:
            return (
                "AI narrative not available: no API key set.\n"
                "Set OPENAI_API_KEY or ANTHROPIC_API_KEY environment variable to enable."
            )

    prompt = build_prompt(project_info, results)

    if provider == "openai":
        return _call_openai(prompt, openai_key, model or "gpt-4o-mini")
    elif provider == "anthropic":
        return _call_anthropic(prompt, anthropic_key, model or "claude-3-5-haiku-latest")
    else:
        return f"Unknown provider '{provider}'."


def _call_openai(prompt: str, api_key: str, model: str) -> str:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "You are a senior power systems engineer."},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=2000,
            temperature=0.3,
        )
        return response.choices[0].message.content.strip()
    except ImportError:
        return "openai package not installed. Run: pip install openai"
    except Exception as exc:
        return f"OpenAI API error: {exc}"


def _call_anthropic(prompt: str, api_key: str, model: str) -> str:
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        message = client.messages.create(
            model=model,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text.strip()
    except ImportError:
        return "anthropic package not installed. Run: pip install anthropic"
    except Exception as exc:
        return f"Anthropic API error: {exc}"


def check_ai_available() -> dict:
    """Return availability status for each AI provider."""
    return {
        "openai":    bool(os.environ.get("OPENAI_API_KEY")),
        "anthropic": bool(os.environ.get("ANTHROPIC_API_KEY")),
        "any":       bool(os.environ.get("OPENAI_API_KEY") or os.environ.get("ANTHROPIC_API_KEY")),
    }
