from __future__ import annotations

import copy
import uuid
from typing import Any, Dict, List, Optional

from models.core import Chart, Evidence, Finding

# ---------------------------------------------------------------------------
# Intent → chart type mapping
# ---------------------------------------------------------------------------

INTENT_MAP: Dict[str, Dict[str, Any]] = {
    "trend_over_time": {
        "default_chart_type": "line",
        "few_period_chart_type": "bar",
        "few_period_threshold": 6,
    },
    "comparison_across_categories": {
        "default_chart_type": "horizontal_bar",
        "top_n": 10,
        "other_label": "Other",
    },
    "period_over_period_change": {
        "default_chart_type": "waterfall",
    },
    "composition": {
        "default_chart_type": "stacked_bar",
        "pie_threshold": 5,
    },
    "relationship": {
        "default_chart_type": "scatter",
        "add_trend_line": True,
    },
    "distribution": {
        "default_chart_type": "histogram",
    },
    "before_vs_after": {
        "default_chart_type": "paired_bar",
    },
}

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_chart(
    finding: Finding,
    evidence: Evidence,
    analytical_intent: str,
) -> Chart:
    """
    Build a deterministic Vega-Lite spec for a finding/evidence pair.
    """
    intent_config = INTENT_MAP.get(analytical_intent, INTENT_MAP["trend_over_time"])
    chart_type, spec = _build_spec(finding, evidence, analytical_intent, intent_config)

    chart_title = _derive_chart_title(finding, evidence)
    spec["title"] = chart_title

    # Add source annotation
    spec.setdefault("data", {})
    if "description" not in spec:
        spec["description"] = _build_annotation(finding, evidence)

    lint_issues = chart_integrity_lint(spec)
    if lint_issues:
        spec.setdefault("$schema_notes", lint_issues)

    return Chart(
        id=str(uuid.uuid4()),
        finding_id=finding.id,
        session_id=finding.session_id,
        chart_type=chart_type,
        analytical_intent=analytical_intent,
        vega_lite_spec=spec,
        title=chart_title,
    )


def _build_spec(
    finding: Finding,
    evidence: Evidence,
    analytical_intent: str,
    config: Dict[str, Any],
) -> tuple[str, Dict[str, Any]]:
    value = evidence.value
    unit = finding.unit or evidence.unit or ""
    metric = finding.metric or evidence.metric or "value"

    if analytical_intent == "trend_over_time":
        return _trend_spec(value, metric, unit, config, evidence)

    elif analytical_intent == "comparison_across_categories":
        return _category_comparison_spec(value, metric, unit, config, evidence)

    elif analytical_intent == "period_over_period_change":
        return _period_change_spec(value, metric, unit, evidence)

    elif analytical_intent == "composition":
        return _composition_spec(value, metric, unit, config, evidence)

    elif analytical_intent == "relationship":
        return _scatter_spec(value, metric, unit, evidence)

    elif analytical_intent == "distribution":
        return _histogram_spec(value, metric, unit, evidence)

    elif analytical_intent == "before_vs_after":
        return _before_after_spec(value, metric, unit, evidence)

    # Default: bar chart
    return _fallback_bar(value, metric, unit, evidence)


# ---------------------------------------------------------------------------
# Spec builders
# ---------------------------------------------------------------------------


def _trend_spec(
    value: Any,
    metric: str,
    unit: str,
    config: Dict[str, Any],
    evidence: Evidence,
) -> tuple[str, Dict[str, Any]]:
    # Value should be a list of {period_date, value} or similar
    if isinstance(value, dict) and "anomalies" in value:
        # anomaly evidence — plot all periods with anomaly markers
        records = []
        return "line", {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "data": {"values": records},
            "layer": [
                {
                    "mark": "line",
                    "encoding": {
                        "x": {"field": "period_date", "type": "temporal", "title": "Period"},
                        "y": {"field": "value", "type": "quantitative", "title": _axis_label(metric, unit), "scale": {"zero": True}},
                    },
                }
            ],
            "description": _source_annotation(evidence),
        }

    if isinstance(value, list):
        periods = len(value)
        chart_type = "bar" if periods <= config.get("few_period_threshold", 6) else "line"
        mark = "bar" if chart_type == "bar" else "line"
        return chart_type, {
            "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
            "data": {"values": value},
            "mark": mark,
            "encoding": {
                "x": {"field": "period", "type": "temporal", "title": "Period"},
                "y": {
                    "field": "value",
                    "type": "quantitative",
                    "title": _axis_label(metric, unit),
                    "scale": {"zero": True},
                },
            },
            "description": _source_annotation(evidence),
        }

    return _fallback_bar(value, metric, unit, evidence)


def _category_comparison_spec(
    value: Any,
    metric: str,
    unit: str,
    config: Dict[str, Any],
    evidence: Evidence,
) -> tuple[str, Dict[str, Any]]:
    top_n = config.get("top_n", 10)
    other_label = config.get("other_label", "Other")

    records: List[Dict[str, Any]] = []
    if isinstance(value, dict) and "segments" in value:
        segs = sorted(value["segments"], key=lambda s: s.get("metric_value_current", 0), reverse=True)
        top_segs = segs[:top_n]
        if len(segs) > top_n:
            other_val = sum(s.get("metric_value_current", 0) for s in segs[top_n:])
            top_segs.append({"segment": other_label, "metric_value_current": other_val})
        records = [{"category": s["segment"], "value": s.get("metric_value_current", 0)} for s in top_segs]
    elif isinstance(value, list):
        records = value[:top_n]

    return "horizontal_bar", {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": records},
        "mark": "bar",
        "encoding": {
            "y": {"field": "category", "type": "nominal", "sort": "-x", "title": None},
            "x": {
                "field": "value",
                "type": "quantitative",
                "title": _axis_label(metric, unit),
                "scale": {"zero": True},
            },
            "tooltip": [
                {"field": "category", "type": "nominal"},
                {"field": "value", "type": "quantitative", "format": ",.2f"},
            ],
        },
        "description": _source_annotation(evidence),
    }


def _period_change_spec(
    value: Any,
    metric: str,
    unit: str,
    evidence: Evidence,
) -> tuple[str, Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if isinstance(value, dict):
        records = [
            {"label": value.get("baseline_period", "Baseline"), "value": value.get("baseline", 0), "type": "absolute"},
            {"label": "Change", "value": value.get("change", 0), "type": "delta"},
            {"label": value.get("current_period", "Current"), "value": value.get("current", 0), "type": "absolute"},
        ]

    return "waterfall", {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": records},
        "mark": "bar",
        "encoding": {
            "x": {"field": "label", "type": "nominal", "title": None},
            "y": {
                "field": "value",
                "type": "quantitative",
                "title": _axis_label(metric, unit),
                "scale": {"zero": True},
            },
            "color": {
                "field": "type",
                "type": "nominal",
                "scale": {
                    "domain": ["absolute", "delta"],
                    "range": ["#3b82d4", "#7c5cd8"],
                },
            },
        },
        "description": _source_annotation(evidence),
    }


def _composition_spec(
    value: Any,
    metric: str,
    unit: str,
    config: Dict[str, Any],
    evidence: Evidence,
) -> tuple[str, Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if isinstance(value, dict) and "segments" in value:
        records = [
            {"category": s["segment"], "value": abs(s.get("metric_value_current", 0))}
            for s in value["segments"]
        ]
    elif isinstance(value, list):
        records = value

    pie_threshold = config.get("pie_threshold", 5)
    if len(records) <= pie_threshold:
        chart_type = "pie"
        mark: Any = {"type": "arc"}
        encoding: Dict[str, Any] = {
            "theta": {"field": "value", "type": "quantitative"},
            "color": {"field": "category", "type": "nominal"},
            "tooltip": [
                {"field": "category", "type": "nominal"},
                {"field": "value", "type": "quantitative", "format": ",.2f"},
            ],
        }
    else:
        chart_type = "stacked_bar"
        mark = "bar"
        encoding = {
            "x": {"field": "period", "type": "temporal", "title": "Period"},
            "y": {
                "field": "value",
                "type": "quantitative",
                "title": _axis_label(metric, unit),
                "stack": "normalize",
            },
            "color": {"field": "category", "type": "nominal"},
        }

    return chart_type, {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": records},
        "mark": mark,
        "encoding": encoding,
        "description": _source_annotation(evidence),
    }


def _scatter_spec(
    value: Any,
    metric: str,
    unit: str,
    evidence: Evidence,
) -> tuple[str, Dict[str, Any]]:
    records = value if isinstance(value, list) else []
    return "scatter", {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": records},
        "layer": [
            {
                "mark": "point",
                "encoding": {
                    "x": {"field": "x", "type": "quantitative"},
                    "y": {"field": "y", "type": "quantitative", "title": _axis_label(metric, unit)},
                },
            },
            {
                "mark": {"type": "line", "color": "firebrick"},
                "transform": [{"regression": "y", "on": "x"}],
                "encoding": {
                    "x": {"field": "x", "type": "quantitative"},
                    "y": {"field": "y", "type": "quantitative"},
                },
            },
        ],
        "description": _source_annotation(evidence),
    }


def _histogram_spec(
    value: Any,
    metric: str,
    unit: str,
    evidence: Evidence,
) -> tuple[str, Dict[str, Any]]:
    records = value if isinstance(value, list) else []
    return "histogram", {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": records},
        "mark": "bar",
        "transform": [{"bin": True, "field": "value", "as": "bin_value"}],
        "encoding": {
            "x": {
                "field": "bin_value",
                "bin": {"maxbins": 20},
                "type": "quantitative",
                "title": _axis_label(metric, unit),
            },
            "y": {"aggregate": "count", "type": "quantitative", "title": "Count"},
        },
        "description": _source_annotation(evidence),
    }


def _before_after_spec(
    value: Any,
    metric: str,
    unit: str,
    evidence: Evidence,
) -> tuple[str, Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    if isinstance(value, dict):
        records = [
            {"period": value.get("baseline_period", "Before"), "value": value.get("baseline", 0)},
            {"period": value.get("current_period", "After"), "value": value.get("current", 0)},
        ]
    return "paired_bar", {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": records},
        "mark": "bar",
        "encoding": {
            "x": {"field": "period", "type": "nominal", "title": None},
            "y": {
                "field": "value",
                "type": "quantitative",
                "title": _axis_label(metric, unit),
                "scale": {"zero": True},
            },
            "color": {"field": "period", "type": "nominal"},
        },
        "description": _source_annotation(evidence),
    }


def _fallback_bar(
    value: Any,
    metric: str,
    unit: str,
    evidence: Evidence,
) -> tuple[str, Dict[str, Any]]:
    if isinstance(value, dict):
        records = [{"label": k, "value": v} for k, v in value.items() if isinstance(v, (int, float))]
    elif isinstance(value, list):
        records = value
    else:
        records = [{"label": metric, "value": value}]

    return "bar", {
        "$schema": "https://vega.github.io/schema/vega-lite/v5.json",
        "data": {"values": records},
        "mark": "bar",
        "encoding": {
            "x": {"field": "label", "type": "nominal"},
            "y": {
                "field": "value",
                "type": "quantitative",
                "title": _axis_label(metric, unit),
                "scale": {"zero": True},
            },
        },
        "description": _source_annotation(evidence),
    }


# ---------------------------------------------------------------------------
# Integrity lint
# ---------------------------------------------------------------------------


def chart_integrity_lint(spec: Dict[str, Any]) -> List[str]:
    """
    Check chart spec for common integrity issues.
    Returns a list of issue strings (empty = clean).
    """
    issues: List[str] = []

    encoding = spec.get("encoding", {})
    y_enc = encoding.get("y", {})
    x_enc = encoding.get("x", {})

    # Bars must start at zero
    mark = spec.get("mark", "")
    mark_type = mark if isinstance(mark, str) else mark.get("type", "")
    if mark_type == "bar":
        scale = y_enc.get("scale", {})
        if scale.get("zero") is False or ("zero" in scale and not scale["zero"]):
            issues.append("Bar chart y-axis does not start at zero — could be misleading.")

    # No dual axis (detect by looking for layer with two different y fields)
    layers = spec.get("layer", [])
    y_fields = set()
    for layer in layers:
        layer_y = layer.get("encoding", {}).get("y", {})
        if layer_y.get("field"):
            y_fields.add(layer_y["field"])
    if len(y_fields) > 1 and any("axis" in layer.get("encoding", {}).get("y", {}) for layer in layers):
        issues.append("Dual-axis chart detected — dual axes are misleading and should be avoided.")

    # Check series count (for color/series field)
    data_values = spec.get("data", {}).get("values", [])
    color_enc = encoding.get("color", {})
    if color_enc.get("field") and data_values:
        unique_vals = len(set(str(r.get(color_enc["field"], "")) for r in data_values))
        if unique_vals > 10:
            issues.append(f"Too many series ({unique_vals}) — consider capping at 10 + Other.")

    return issues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _axis_label(metric: str, unit: str) -> str:
    if unit:
        return f"{metric} ({unit})"
    return metric


def _source_annotation(evidence: Evidence) -> str:
    parts = []
    if evidence.source_dataset:
        parts.append(f"Source: {evidence.source_dataset}")
    if evidence.period:
        parts.append(f"Period: {evidence.period}")
    if evidence.rows_used:
        parts.append(f"Rows: {evidence.rows_used:,}")
    return " | ".join(parts)


def _derive_chart_title(finding: Finding, evidence: Evidence) -> str:
    if finding.claim:
        # Use first sentence as chart title (max 80 chars)
        first_sentence = finding.claim.split(".")[0].strip()
        return first_sentence[:80]
    if finding.metric:
        return f"{finding.metric} analysis"
    return "Analysis chart"


def _build_annotation(finding: Finding, evidence: Evidence) -> str:
    parts = [_source_annotation(evidence)]
    if evidence.rows_used:
        parts.append(f"Based on {evidence.rows_used:,} rows")
    return " | ".join(p for p in parts if p)
