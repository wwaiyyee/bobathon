from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd

from models.core import AnalysisSpec, Evidence, TimeWindow

ENGINE_VERSION = "1.0"


# ---------------------------------------------------------------------------
# Core: run_analysis_spec
# ---------------------------------------------------------------------------


def run_analysis_spec(
    spec: AnalysisSpec,
    parquet_path: str,
    dataset_id: str,
    version_id: str,
    metric_definitions: Dict[str, str],
) -> Evidence:
    """
    Compile an AnalysisSpec to SQL, execute in DuckDB, return an Evidence record.
    The LLM never sees raw numbers — only Evidence IDs are passed back.
    """
    analysis_type = spec.analysis_type

    if analysis_type == "compare_periods":
        return compare_periods(
            parquet_path=parquet_path,
            dataset_id=dataset_id,
            version_id=version_id,
            metric=spec.metric,
            date_col=spec.date_col or "",
            current_window=spec.current_window or TimeWindow(),
            baseline_window=spec.baseline_window or TimeWindow(),
            metric_definitions=metric_definitions,
            dimensions=spec.dimensions,
            filters=spec.filters,
            assumption_ids=spec.assumption_ids,
        )
    elif analysis_type == "contribution":
        dim = spec.dimensions[0] if spec.dimensions else ""
        return contribution_analysis(
            parquet_path=parquet_path,
            dataset_id=dataset_id,
            version_id=version_id,
            metric=spec.metric,
            date_col=spec.date_col or "",
            current_window=spec.current_window or TimeWindow(),
            baseline_window=spec.baseline_window or TimeWindow(),
            metric_definitions=metric_definitions,
            dimension=dim,
            filters=spec.filters,
            assumption_ids=spec.assumption_ids,
        )
    elif analysis_type == "anomaly_detection":
        return detect_anomalies(
            parquet_path=parquet_path,
            dataset_id=dataset_id,
            version_id=version_id,
            metric=spec.metric,
            date_col=spec.date_col or "",
            metric_definitions=metric_definitions,
        )
    elif analysis_type == "volume_price_decomp":
        return volume_price_decomposition(
            parquet_path=parquet_path,
            dataset_id=dataset_id,
            version_id=version_id,
            metric=spec.metric,
            date_col=spec.date_col or "",
            current_window=spec.current_window or TimeWindow(),
            baseline_window=spec.baseline_window or TimeWindow(),
            metric_definitions=metric_definitions,
            filters=spec.filters,
            assumption_ids=spec.assumption_ids,
        )
    else:
        # Generic aggregation
        return _run_generic(spec, parquet_path, dataset_id, version_id, metric_definitions)


def _run_generic(
    spec: AnalysisSpec,
    parquet_path: str,
    dataset_id: str,
    version_id: str,
    metric_definitions: Dict[str, str],
) -> Evidence:
    metric_sql = _resolve_metric_sql(spec.metric, metric_definitions)
    where_clause = _build_where(spec.filters, spec.current_window, spec.date_col)

    query = f"SELECT {metric_sql} AS value FROM read_parquet('{parquet_path}'){where_clause}"

    conn = duckdb.connect(":memory:")
    result = conn.execute(query).fetchone()
    conn.close()

    value = result[0] if result else None
    rows_used = _count_rows(parquet_path, where_clause)

    return Evidence(
        id=str(uuid.uuid4()),
        metric=spec.metric,
        value=value,
        source_dataset=dataset_id,
        dataset_version_id=version_id,
        filters=spec.filters,
        rows_used=rows_used,
        calculation=f"{metric_sql} WHERE {where_clause or 'all rows'}",
        query=query,
        inputs={"spec": spec.model_dump()},
        outputs={"value": value},
        assumption_ids=spec.assumption_ids,
        engine_version=ENGINE_VERSION,
    )


# ---------------------------------------------------------------------------
# compare_periods
# ---------------------------------------------------------------------------


def compare_periods(
    parquet_path: str,
    dataset_id: str,
    version_id: str,
    metric: str,
    date_col: str,
    current_window: TimeWindow,
    baseline_window: TimeWindow,
    metric_definitions: Dict[str, str],
    dimensions: Optional[List[str]] = None,
    filters: Optional[Dict[str, Any]] = None,
    assumption_ids: Optional[List[str]] = None,
) -> Evidence:
    filters = filters or {}
    assumption_ids = assumption_ids or []

    metric_sql = _resolve_metric_sql(metric, metric_definitions)
    safe_date = f'"{date_col}"'

    current_where = _build_window_filter(safe_date, current_window)
    baseline_where = _build_window_filter(safe_date, baseline_window)
    extra_where = _build_filter_clause(filters)

    def _window_query(window_where: str) -> str:
        where_parts = [w for w in [window_where, extra_where] if w]
        where_clause = " AND ".join(where_parts)
        where_str = f" WHERE {where_clause}" if where_clause else ""
        return f"SELECT {metric_sql} AS value FROM read_parquet('{parquet_path}'){where_str}"

    current_q = _window_query(current_where)
    baseline_q = _window_query(baseline_where)

    conn = duckdb.connect(":memory:")
    current_val = conn.execute(current_q).fetchone()[0]  # type: ignore[index]
    baseline_val = conn.execute(baseline_q).fetchone()[0]  # type: ignore[index]
    conn.close()

    if baseline_val and baseline_val != 0:
        change_pct = (current_val - baseline_val) / abs(baseline_val) * 100
    else:
        change_pct = None

    value = {
        "current": current_val,
        "baseline": baseline_val,
        "change": (current_val - baseline_val) if current_val is not None and baseline_val is not None else None,
        "change_pct": change_pct,
        "current_period": current_window.label or f"{current_window.start} to {current_window.end}",
        "baseline_period": baseline_window.label or f"{baseline_window.start} to {baseline_window.end}",
    }

    rows_used = _count_rows(parquet_path, current_where)

    return Evidence(
        id=str(uuid.uuid4()),
        metric=metric,
        value=value,
        period=current_window.label,
        baseline_period=baseline_window.label,
        source_dataset=dataset_id,
        dataset_version_id=version_id,
        filters=filters,
        rows_used=rows_used,
        calculation=f"{metric_sql} for current vs baseline windows",
        query=f"current: {current_q}\nbaseline: {baseline_q}",
        inputs={"current_window": current_window.model_dump(), "baseline_window": baseline_window.model_dump()},
        outputs=value,
        assumption_ids=assumption_ids,
        engine_version=ENGINE_VERSION,
    )


# ---------------------------------------------------------------------------
# contribution_analysis
# ---------------------------------------------------------------------------


def contribution_analysis(
    parquet_path: str,
    dataset_id: str,
    version_id: str,
    metric: str,
    date_col: str,
    current_window: TimeWindow,
    baseline_window: TimeWindow,
    metric_definitions: Dict[str, str],
    dimension: str,
    filters: Optional[Dict[str, Any]] = None,
    assumption_ids: Optional[List[str]] = None,
) -> Evidence:
    filters = filters or {}
    assumption_ids = assumption_ids or []

    metric_sql = _resolve_metric_sql(metric, metric_definitions)
    safe_date = f'"{date_col}"'
    safe_dim = f'"{dimension}"'

    current_where = _build_window_filter(safe_date, current_window)
    baseline_where = _build_window_filter(safe_date, baseline_window)

    def _seg_query(window_where: str) -> str:
        where_str = f" WHERE {window_where}" if window_where else ""
        return f"""
            SELECT {safe_dim} AS segment,
                   {metric_sql} AS metric_value
            FROM read_parquet('{parquet_path}'){where_str}
            GROUP BY {safe_dim}
            ORDER BY metric_value DESC
        """

    conn = duckdb.connect(":memory:")
    current_df = conn.execute(_seg_query(current_where)).df()
    baseline_df = conn.execute(_seg_query(baseline_where)).df()
    conn.close()

    # Merge and compute contribution
    merged = current_df.merge(
        baseline_df, on="segment", how="outer", suffixes=("_current", "_baseline")
    ).fillna(0)
    merged["delta"] = merged["metric_value_current"] - merged["metric_value_baseline"]

    total_current = merged["metric_value_current"].sum()
    total_baseline = merged["metric_value_baseline"].sum()

    if total_baseline != 0:
        merged["baseline_share_pct"] = merged["metric_value_baseline"] / total_baseline * 100
    else:
        merged["baseline_share_pct"] = 0

    total_delta = total_current - total_baseline
    if total_delta != 0:
        merged["contribution_pct"] = merged["delta"] / abs(total_delta) * 100
    else:
        merged["contribution_pct"] = 0

    merged_sorted = merged.sort_values("delta", ascending=False)
    records = merged_sorted.to_dict(orient="records")

    value = {
        "segments": records,
        "total_current": total_current,
        "total_baseline": total_baseline,
        "total_delta": total_delta,
        "dimension": dimension,
    }

    return Evidence(
        id=str(uuid.uuid4()),
        metric=metric,
        value=value,
        period=current_window.label,
        baseline_period=baseline_window.label,
        source_dataset=dataset_id,
        dataset_version_id=version_id,
        filters=filters,
        rows_used=len(current_df),
        calculation=f"Contribution analysis of {metric} by {dimension}",
        query=_seg_query(current_where),
        inputs={"dimension": dimension},
        outputs=value,
        assumption_ids=assumption_ids,
        engine_version=ENGINE_VERSION,
    )


# ---------------------------------------------------------------------------
# volume_price_decomposition
# ---------------------------------------------------------------------------


def volume_price_decomposition(
    parquet_path: str,
    dataset_id: str,
    version_id: str,
    metric: str,
    date_col: str,
    current_window: TimeWindow,
    baseline_window: TimeWindow,
    metric_definitions: Dict[str, str],
    filters: Optional[Dict[str, Any]] = None,
    assumption_ids: Optional[List[str]] = None,
) -> Evidence:
    """
    Decompose revenue change into:
    - Volume effect = (current_units - baseline_units) × baseline_price
    - Price effect  = (current_price - baseline_price) × current_units
    - Mix effect    = residual
    """
    filters = filters or {}
    assumption_ids = assumption_ids or []

    safe_date = f'"{date_col}"'
    current_where = _build_window_filter(safe_date, current_window)
    baseline_where = _build_window_filter(safe_date, baseline_window)

    revenue_sql = _resolve_metric_sql("revenue", metric_definitions)
    units_sql = _resolve_metric_sql("units", metric_definitions)

    def _summary(window_where: str) -> dict:
        where_str = f" WHERE {window_where}" if window_where else ""
        q = f"SELECT {revenue_sql} AS revenue, {units_sql} AS units FROM read_parquet('{parquet_path}'){where_str}"
        conn = duckdb.connect(":memory:")
        row = conn.execute(q).fetchone()
        conn.close()
        rev = row[0] if row else 0
        units = row[1] if row else 0
        price = rev / units if units else 0
        return {"revenue": rev, "units": units, "price": price}

    current = _summary(current_where)
    baseline = _summary(baseline_where)

    volume_effect = (current["units"] - baseline["units"]) * baseline["price"]
    price_effect = (current["price"] - baseline["price"]) * current["units"]
    total_delta = current["revenue"] - baseline["revenue"]
    mix_effect = total_delta - volume_effect - price_effect

    value = {
        "current": current,
        "baseline": baseline,
        "total_delta": total_delta,
        "volume_effect": volume_effect,
        "price_effect": price_effect,
        "mix_effect": mix_effect,
    }

    return Evidence(
        id=str(uuid.uuid4()),
        metric=metric,
        value=value,
        period=current_window.label,
        baseline_period=baseline_window.label,
        source_dataset=dataset_id,
        dataset_version_id=version_id,
        filters=filters,
        calculation="Volume × price decomposition",
        inputs={"current": current, "baseline": baseline},
        outputs=value,
        assumption_ids=assumption_ids,
        engine_version=ENGINE_VERSION,
    )


# ---------------------------------------------------------------------------
# detect_anomalies
# ---------------------------------------------------------------------------


def detect_anomalies(
    parquet_path: str,
    dataset_id: str,
    version_id: str,
    metric: str,
    date_col: str,
    metric_definitions: Dict[str, str],
) -> Evidence:
    """IQR + z-score anomaly detection on a time series."""
    metric_sql = _resolve_metric_sql(metric, metric_definitions)
    safe_date = f'"{date_col}"'

    query = f"""
        SELECT {safe_date}::DATE AS period_date, {metric_sql} AS value
        FROM read_parquet('{parquet_path}')
        GROUP BY {safe_date}::DATE
        ORDER BY {safe_date}::DATE
    """

    conn = duckdb.connect(":memory:")
    df = conn.execute(query).df()
    conn.close()

    if df.empty:
        return Evidence(
            id=str(uuid.uuid4()),
            metric=metric,
            value={"anomalies": [], "note": "No data"},
            source_dataset=dataset_id,
            dataset_version_id=version_id,
            engine_version=ENGINE_VERSION,
        )

    values = df["value"].dropna()
    q1 = values.quantile(0.25)
    q3 = values.quantile(0.75)
    iqr = q3 - q1
    iqr_lower = q1 - 1.5 * iqr
    iqr_upper = q3 + 1.5 * iqr

    mean = values.mean()
    std = values.std()
    z_threshold = 2.5

    anomaly_mask = (
        (df["value"] < iqr_lower)
        | (df["value"] > iqr_upper)
        | (((df["value"] - mean) / std).abs() > z_threshold if std > 0 else False)
    )

    anomalies = df[anomaly_mask].to_dict(orient="records")
    for a in anomalies:
        a["period_date"] = str(a["period_date"])

    value = {
        "anomalies": anomalies,
        "total_periods": len(df),
        "anomaly_count": len(anomalies),
        "stats": {
            "mean": float(mean),
            "std": float(std),
            "q1": float(q1),
            "q3": float(q3),
            "iqr": float(iqr),
            "iqr_lower": float(iqr_lower),
            "iqr_upper": float(iqr_upper),
        },
    }

    return Evidence(
        id=str(uuid.uuid4()),
        metric=metric,
        value=value,
        source_dataset=dataset_id,
        dataset_version_id=version_id,
        rows_used=len(df),
        calculation="IQR + z-score anomaly detection",
        query=query,
        outputs=value,
        engine_version=ENGINE_VERSION,
    )


# ---------------------------------------------------------------------------
# reproduce_evidence
# ---------------------------------------------------------------------------


def reproduce_evidence(
    evidence: Evidence,
    parquet_path: str,
) -> Dict[str, Any]:
    """Re-execute the query stored in the evidence and compare results."""
    if not evidence.query:
        return {"matched": None, "original": evidence.value, "reproduced": None, "note": "No query stored"}

    try:
        # Only try to reproduce single-statement queries
        query = evidence.query.strip()
        if "\n" in query and query.startswith("current:"):
            # compare_periods multi-query
            return {"matched": None, "original": evidence.value, "reproduced": None, "note": "Multi-query evidence not directly reproducible"}

        conn = duckdb.connect(":memory:")
        result = conn.execute(query).fetchone()
        conn.close()
        reproduced_value = result[0] if result else None

        original = evidence.value
        if isinstance(original, dict):
            original = original.get("current") or original.get("value")

        if original is not None and reproduced_value is not None:
            try:
                diff = abs(float(reproduced_value) - float(original))
                tolerance = max(abs(float(original)) * 0.001, 1e-6)
                matched = diff <= tolerance
            except (TypeError, ValueError):
                matched = str(reproduced_value) == str(original)
        else:
            matched = reproduced_value == original

        return {
            "matched": matched,
            "original": original,
            "reproduced": reproduced_value,
        }
    except Exception as e:
        return {"matched": False, "original": evidence.value, "reproduced": None, "error": str(e)}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_metric_sql(metric: str, metric_definitions: Dict[str, str]) -> str:
    if metric in metric_definitions:
        return metric_definitions[metric]
    # Treat metric as a column name
    return f'SUM("{metric}")'


def _build_window_filter(safe_date_col: str, window: TimeWindow) -> str:
    parts = []
    if window.start:
        parts.append(f"{safe_date_col}::DATE >= '{window.start}'")
    if window.end:
        parts.append(f"{safe_date_col}::DATE <= '{window.end}'")
    return " AND ".join(parts)


def _build_filter_clause(filters: Dict[str, Any]) -> str:
    parts = []
    for col, val in filters.items():
        safe_col = f'"{col}"'
        if isinstance(val, list):
            escaped = ", ".join(f"'{v}'" for v in val)
            parts.append(f"{safe_col} IN ({escaped})")
        else:
            parts.append(f"{safe_col} = '{val}'")
    return " AND ".join(parts)


def _build_where(
    filters: Dict[str, Any],
    window: Optional[TimeWindow],
    date_col: Optional[str],
) -> str:
    parts = []
    if window and date_col:
        safe_date = f'"{date_col}"'
        win_filter = _build_window_filter(safe_date, window)
        if win_filter:
            parts.append(win_filter)
    filter_clause = _build_filter_clause(filters)
    if filter_clause:
        parts.append(filter_clause)
    return f" WHERE {' AND '.join(parts)}" if parts else ""


def _count_rows(parquet_path: str, where_clause: str) -> int:
    try:
        where_str = f" WHERE {where_clause}" if where_clause else ""
        conn = duckdb.connect(":memory:")
        count = conn.execute(
            f"SELECT COUNT(*) FROM read_parquet('{parquet_path}'){where_str}"
        ).fetchone()[0]  # type: ignore[index]
        conn.close()
        return int(count)
    except Exception:
        return 0
