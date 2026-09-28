from __future__ import annotations

import json
import uuid
from typing import Any, Dict, List, Optional

from models.core import (
    AnalysisPlan,
    AnalysisSession,
    AnalysisSpec,
    TimeWindow,
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def create_analysis_plan(
    question: str,
    session: AnalysisSession,
    llm_client,
    metric_definitions: Dict[str, str],
) -> AnalysisPlan:
    """
    Call the LLM with the schema summary (NOT raw data) to produce an AnalysisPlan.
    The LLM output is validated against AnalysisPlan schema.
    """
    schema_summary = _build_schema_summary(session)
    prompt = _build_planning_prompt(question, schema_summary, session, metric_definitions)

    messages = [
        {
            "role": "system",
            "content": (
                "You are an analytical planning assistant. "
                "Your job is to produce a JSON analysis plan. "
                "Never include raw data or specific cell values in your response. "
                "Only reference column names, metric names, and time expressions."
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response_text = await llm_client.chat_completion(
            messages=messages,
            model=llm_client.strong_model,
        )
        plan = _parse_plan_response(response_text, question, session.id, metric_definitions)
        if plan.specs:
            return plan
    except Exception as e:
        pass

    return _build_fallback_plan(question, session, metric_definitions)


def _build_fallback_plan(
    question: str,
    session: AnalysisSession,
    metric_definitions: Dict[str, str],
) -> AnalysisPlan:
    primary_dataset_id = session.dataset_ids[0] if session.dataset_ids else ""
    dictionary = session.dictionaries.get(primary_dataset_id, [])

    measure_cols = [e.column for e in dictionary if str(e.role) == "measure"]
    date_cols = [e.column for e in dictionary if str(e.role) == "date"]
    dimension_cols = [e.column for e in dictionary if str(e.role) == "dimension"]

    specs: List[AnalysisSpec] = []
    metric = measure_cols[0] if measure_cols else (list(metric_definitions.keys())[0] if metric_definitions else "")

    if date_cols and metric:
        specs.append(
            AnalysisSpec(
                analysis_type="compare_periods",
                metric=metric,
                date_col=date_cols[0],
                dimensions=dimension_cols[:1],
            )
        )
    elif dimension_cols and metric:
        specs.append(
            AnalysisSpec(
                analysis_type="contribution",
                metric=metric,
                dimensions=dimension_cols[:1],
            )
        )
    elif metric:
        specs.append(
            AnalysisSpec(
                analysis_type="generic",
                metric=metric,
            )
        )

    return AnalysisPlan(
        id=str(uuid.uuid4()),
        session_id=session.id,
        question=question,
        specs=specs,
        metric_definitions=metric_definitions,
        reasoning="Automated heuristic plan derived from dataset schema (measures, dates, and dimensions).",
    )


def plan_to_specs(plan: AnalysisPlan, session: AnalysisSession) -> List[AnalysisSpec]:
    """
    Return the list of AnalysisSpec objects from the plan,
    resolving any time expressions via the session's time anchors.
    """
    return plan.specs


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_schema_summary(session: AnalysisSession) -> str:
    parts: List[str] = []
    for dataset_id in session.dataset_ids:
        version = session.dataset_versions.get(dataset_id)
        dictionary = session.dictionaries.get(dataset_id, [])

        if version:
            parts.append(f"Dataset: {dataset_id} ({version.source_filename})")
            parts.append(f"  Rows: {version.row_count}, Columns: {version.column_count}")

        if dictionary:
            parts.append("  Columns:")
            for entry in dictionary:
                unit_str = f" [{entry.unit}]" if entry.unit else ""
                currency_str = f" ({entry.currency_symbol})" if entry.currency_symbol else ""
                sample_str = f" e.g. {entry.sample_values[:3]}" if entry.sample_values else ""
                parts.append(
                    f"    - {entry.column} ({entry.role}){unit_str}{currency_str}{sample_str}"
                )

    return "\n".join(parts)


def _build_planning_prompt(
    question: str,
    schema_summary: str,
    session: AnalysisSession,
    metric_definitions: Dict[str, str],
) -> str:
    metrics_str = "\n".join(f"  {k}: {v}" for k, v in metric_definitions.items())
    assumptions_str = "\n".join(
        f"  - {a.text}" for a in session.assumptions if a.confirmed
    )

    return f"""
User question: {question}

Available data schema:
{schema_summary}

Available metric definitions:
{metrics_str if metrics_str else "  (none resolved — use column names directly)"}

Confirmed assumptions:
{assumptions_str if assumptions_str else "  (none)"}

Produce a JSON analysis plan with the following structure:
{{
  "reasoning": "<brief explanation of your approach>",
  "specs": [
    {{
      "analysis_type": "<compare_periods|contribution|anomaly_detection|volume_price_decomp|generic>",
      "metric": "<metric name from the definitions above, or column name>",
      "date_col": "<date column name, if applicable>",
      "current_window": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "label": "..."}},
      "baseline_window": {{"start": "YYYY-MM-DD", "end": "YYYY-MM-DD", "label": "..."}},
      "dimensions": ["<dimension column names>"],
      "filters": {{}},
      "assumption_ids": []
    }}
  ]
}}

Rules:
- Only reference column names from the schema above.
- Use ISO date strings (YYYY-MM-DD) for time windows.
- Return pure JSON only. No prose outside the JSON object.
- If the question cannot be answered with available data, set specs to [].
""".strip()


def _parse_plan_response(
    response_text: str,
    question: str,
    session_id: str,
    metric_definitions: Dict[str, str],
) -> AnalysisPlan:
    """Parse LLM JSON response into an AnalysisPlan, with fallback on parse error."""
    # Extract JSON from the response
    text = response_text.strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        # Best-effort: find JSON object in response
        import re
        match = re.search(r"\{[\s\S]*\}", text)
        if match:
            try:
                data = json.loads(match.group())
            except json.JSONDecodeError:
                data = {}
        else:
            data = {}

    reasoning = data.get("reasoning", "")
    raw_specs = data.get("specs", [])

    specs: List[AnalysisSpec] = []
    for raw in raw_specs:
        try:
            current_w = None
            baseline_w = None
            if raw.get("current_window"):
                current_w = TimeWindow(**raw["current_window"])
            if raw.get("baseline_window"):
                baseline_w = TimeWindow(**raw["baseline_window"])

            spec = AnalysisSpec(
                analysis_type=raw.get("analysis_type", "generic"),
                metric=raw.get("metric", ""),
                date_col=raw.get("date_col"),
                current_window=current_w,
                baseline_window=baseline_w,
                dimensions=raw.get("dimensions", []),
                filters=raw.get("filters", {}),
                assumption_ids=raw.get("assumption_ids", []),
            )
            specs.append(spec)
        except Exception:
            continue

    return AnalysisPlan(
        id=str(uuid.uuid4()),
        session_id=session_id,
        question=question,
        specs=specs,
        metric_definitions=metric_definitions,
        reasoning=reasoning,
    )
