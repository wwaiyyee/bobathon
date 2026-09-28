from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import markdown as md

from models.core import (
    AnalysisSession,
    Assumption,
    Chart,
    Evidence,
    Finding,
    TransformationStep,
)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class ReportDocument:
    session_id: str
    executive_summary: str = ""
    dataset_overview: str = ""
    key_findings: str = ""
    detailed_analysis: str = ""
    anomalies: str = ""
    data_quality: str = ""
    assumptions_definitions: str = ""
    limitations: str = ""
    next_steps: str = ""
    methodology_reproducibility: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "executive_summary": self.executive_summary,
            "dataset_overview": self.dataset_overview,
            "key_findings": self.key_findings,
            "detailed_analysis": self.detailed_analysis,
            "anomalies": self.anomalies,
            "data_quality": self.data_quality,
            "assumptions_definitions": self.assumptions_definitions,
            "limitations": self.limitations,
            "next_steps": self.next_steps,
            "methodology_reproducibility": self.methodology_reproducibility,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def generate_report(
    session: AnalysisSession,
    findings: List[Finding],
    evidence: List[Evidence],
    charts: List[Chart],
    assumptions: List[Assumption],
    transformations: List[TransformationStep],
    llm_client,
) -> ReportDocument:
    report = ReportDocument(session_id=session.id)

    # Build context for the LLM (IDs and summaries only)
    findings_summary = "\n".join(
        f"- [{f.claim_type}/{f.strength}/{f.evidence_status}] {f.claim}"
        for f in findings[:30]
    )
    evidence_summary = "\n".join(
        f"- [{ev.id[:8]}] {ev.metric}: {_format_value(ev.value)} ({ev.rows_used or 'N/A'} rows)"
        for ev in evidence[:30]
    )
    datasets_summary = "\n".join(
        f"- {ds_id}: {v.row_count} rows, {v.column_count} columns ({v.source_filename})"
        for ds_id, v in session.dataset_versions.items()
    )
    quality_summary = ""
    assumptions_text = "\n".join(f"- {a.text}" for a in assumptions) or "None"
    transformations_text = "\n".join(
        f"- {t.step_type}: {t.description}" for t in transformations
    ) or "None"
    anomaly_findings = [
        f for f in findings if "anomal" in f.claim.lower()
    ]
    anomaly_text = "\n".join(f"- {f.claim}" for f in anomaly_findings) or "None detected."

    prompt = f"""Generate a comprehensive analytical report with exactly 10 sections.
    
Dataset overview:
{datasets_summary}

Key findings ({len(findings)} total):
{findings_summary}

Evidence summary:
{evidence_summary}

Anomalies:
{anomaly_text}

Transformations applied:
{transformations_text}

Assumptions:
{assumptions_text}

Write each section clearly. Use markdown formatting.
Respond with a JSON object with these exact keys:
executive_summary, dataset_overview, key_findings, detailed_analysis, anomalies, 
data_quality, assumptions_definitions, limitations, next_steps, methodology_reproducibility.

Rules:
- Do not invent numbers not present in the findings/evidence above.
- Use associational language (not causal).
- In methodology_reproducibility, state that all computations were performed by the analysis engine and can be reproduced using the evidence IDs.
"""

    messages = [
        {
            "role": "system",
            "content": (
                "You are an expert data analyst writing a professional analytical report. "
                "Be precise, evidence-based, and disclose all caveats and limitations. "
                "Never invent numbers. Respond only in JSON."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = await llm_client.chat_completion(
            messages=messages,
            model=llm_client.strong_model,
        )
        text = response.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        data = json.loads(text)
        report.executive_summary = data.get("executive_summary", "")
        report.dataset_overview = data.get("dataset_overview", "")
        report.key_findings = data.get("key_findings", "")
        report.detailed_analysis = data.get("detailed_analysis", "")
        report.anomalies = data.get("anomalies", "")
        report.data_quality = data.get("data_quality", "")
        report.assumptions_definitions = data.get("assumptions_definitions", "")
        report.limitations = data.get("limitations", "")
        report.next_steps = data.get("next_steps", "")
        report.methodology_reproducibility = data.get("methodology_reproducibility", "")

    except Exception as e:
        # Fallback: construct report deterministically
        report = _build_fallback_report(
            session, findings, evidence, assumptions, transformations, str(e)
        )

    return report


def render_markdown(report: ReportDocument) -> str:
    """Render all 10 sections as a single Markdown document."""
    sections = [
        ("Executive Summary", report.executive_summary),
        ("Dataset Overview", report.dataset_overview),
        ("Key Findings", report.key_findings),
        ("Detailed Analysis", report.detailed_analysis),
        ("Anomalies", report.anomalies),
        ("Data Quality", report.data_quality),
        ("Assumptions & Definitions", report.assumptions_definitions),
        ("Limitations", report.limitations),
        ("Next Steps", report.next_steps),
        ("Methodology & Reproducibility", report.methodology_reproducibility),
    ]

    lines = [f"# InsightOS Analytical Report\n"]
    for title, content in sections:
        lines.append(f"\n## {title}\n")
        lines.append(content or "_Not available._")
        lines.append("")

    return "\n".join(lines)


def render_html(report: ReportDocument) -> str:
    """Render the Markdown report as an HTML document."""
    markdown_text = render_markdown(report)
    body_html = md.markdown(markdown_text, extensions=["tables", "fenced_code"])
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>InsightOS Report</title>
<style>
  body {{ font-family: -apple-system, 'Segoe UI', system-ui, sans-serif; max-width: 900px; margin: 40px auto; padding: 0 24px; color: #1f2328; line-height: 1.7; }}
  h1 {{ border-bottom: 2px solid #e5e7eb; padding-bottom: 8px; }}
  h2 {{ color: #3b82d4; margin-top: 2em; }}
  table {{ border-collapse: collapse; width: 100%; }}
  th, td {{ border: 1px solid #e5e7eb; padding: 8px 12px; text-align: left; }}
  th {{ background: #f7f8fa; }}
  code {{ background: #f7f8fa; padding: 2px 6px; border-radius: 3px; font-size: 0.9em; }}
  pre {{ background: #f7f8fa; padding: 16px; border-radius: 6px; overflow-x: auto; }}
</style>
</head>
<body>
{body_html}
</body>
</html>"""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _format_value(value: Any) -> str:
    if value is None:
        return "N/A"
    if isinstance(value, dict):
        if "current" in value:
            return f"current={value['current']}, change_pct={value.get('change_pct', 'N/A')}%"
        return "{...}"
    if isinstance(value, list):
        return f"[{len(value)} records]"
    return str(value)


def _build_fallback_report(
    session: AnalysisSession,
    findings: List[Finding],
    evidence: List[Evidence],
    assumptions: List[Assumption],
    transformations: List[TransformationStep],
    error: str,
) -> ReportDocument:
    report = ReportDocument(session_id=session.id)

    report.executive_summary = (
        f"Analysis complete. {len(findings)} findings identified across "
        f"{len(session.dataset_ids)} dataset(s)."
    )
    report.dataset_overview = "\n".join(
        f"- {ds_id}: {v.row_count} rows, {v.column_count} columns"
        for ds_id, v in session.dataset_versions.items()
    )
    report.key_findings = "\n".join(f"- {f.claim}" for f in findings[:10])
    report.detailed_analysis = "\n".join(
        f"- Evidence [{ev.id[:8]}]: {ev.metric}" for ev in evidence[:10]
    )
    report.anomalies = "\n".join(
        f"- {f.claim}" for f in findings if "anomal" in f.claim.lower()
    ) or "None detected."
    report.data_quality = "Data quality check was not available."
    report.assumptions_definitions = "\n".join(f"- {a.text}" for a in assumptions) or "None."
    report.limitations = (
        "This report is based on the data as provided. "
        "Results should be interpreted in the context of data completeness."
    )
    report.next_steps = "Review findings with data owners and validate key assumptions."
    report.methodology_reproducibility = (
        "All computations were performed deterministically by the analysis engine. "
        "Each finding is backed by an evidence ID that can be used to reproduce the calculation. "
        f"Engine version: 1.0. Note: LLM narrative generation encountered: {error}"
    )

    return report
