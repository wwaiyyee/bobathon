from __future__ import annotations

from typing import Any, Dict, List, Optional

import duckdb
import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
# Benjamini-Hochberg FDR correction
# ---------------------------------------------------------------------------


def benjamini_hochberg(p_values: List[float], alpha: float = 0.05) -> List[bool]:
    """
    Apply Benjamini-Hochberg procedure for multiple testing correction.
    Returns a list of booleans indicating which hypotheses are rejected.
    """
    n = len(p_values)
    if n == 0:
        return []

    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    rejected = [False] * n

    for rank, (orig_idx, p) in enumerate(indexed, start=1):
        threshold = (rank / n) * alpha
        if p <= threshold:
            rejected[orig_idx] = True

    # Enforce monotonicity: once we stop rejecting, stop
    found_non_reject = False
    for i in range(n - 1, -1, -1):
        orig_idx = indexed[i][0]
        if not rejected[orig_idx]:
            found_non_reject = True
        if found_non_reject:
            rejected[orig_idx] = False

    return rejected


# ---------------------------------------------------------------------------
# Simpson's Paradox check
# ---------------------------------------------------------------------------


def check_simpsons_paradox(
    parquet_path: str,
    metric: str,
    dimension: str,
    date_col: str,
    metric_defs: Dict[str, str],
) -> Dict[str, Any]:
    """
    Check whether a trend reverses when stratified by *dimension*.
    Returns: {detected: bool, overall_trend: str, segment_trends: dict, description: str}
    """
    from tools.analysis_engine import _resolve_metric_sql

    metric_sql = _resolve_metric_sql(metric, metric_defs)
    safe_date = f'"{date_col}"'
    safe_dim = f'"{dimension}"'

    conn = duckdb.connect(":memory:")

    # Overall trend
    overall_q = f"""
        SELECT DATE_TRUNC('month', {safe_date}::TIMESTAMP) AS period,
               {metric_sql} AS value
        FROM read_parquet('{parquet_path}')
        GROUP BY period
        ORDER BY period
    """
    overall_df = conn.execute(overall_q).df()
    overall_trend = _compute_trend(overall_df["value"].tolist())

    # Per-segment trends
    seg_q = f"""
        SELECT {safe_dim} AS segment,
               DATE_TRUNC('month', {safe_date}::TIMESTAMP) AS period,
               {metric_sql} AS value
        FROM read_parquet('{parquet_path}')
        GROUP BY segment, period
        ORDER BY segment, period
    """
    seg_df = conn.execute(seg_q).df()
    conn.close()

    segment_trends: Dict[str, str] = {}
    for seg, group in seg_df.groupby("segment"):
        segment_trends[str(seg)] = _compute_trend(group["value"].tolist())

    # Simpson's paradox: overall trend differs from majority of segment trends
    trend_counts: Dict[str, int] = {}
    for t in segment_trends.values():
        trend_counts[t] = trend_counts.get(t, 0) + 1
    majority_trend = max(trend_counts, key=trend_counts.get)  # type: ignore[arg-type]

    detected = majority_trend != overall_trend and overall_trend != "flat"

    description = ""
    if detected:
        description = (
            f"Potential Simpson's paradox: overall {metric} is {overall_trend}, "
            f"but most segments show {majority_trend} trend. "
            f"Segment composition may be driving the aggregate result."
        )

    return {
        "detected": detected,
        "overall_trend": overall_trend,
        "segment_trends": segment_trends,
        "description": description,
    }


def _compute_trend(values: List[float]) -> str:
    if len(values) < 2:
        return "flat"
    xs = list(range(len(values)))
    try:
        slope = np.polyfit(xs, values, 1)[0]
        std = np.std(values)
        if std == 0:
            return "flat"
        rel = abs(slope) / std
        if rel < 0.1:
            return "flat"
        return "increasing" if slope > 0 else "decreasing"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Stability check
# ---------------------------------------------------------------------------


def stability_check(
    parquet_path: str,
    metric: str,
    date_col: str,
    metric_defs: Dict[str, str],
    split: str = "halves",
) -> Dict[str, Any]:
    """
    Split the time series in half and compare aggregate values.
    Returns: {stable: bool, first_half: float, second_half: float}
    """
    from tools.analysis_engine import _resolve_metric_sql

    metric_sql = _resolve_metric_sql(metric, metric_defs)
    safe_date = f'"{date_col}"'

    conn = duckdb.connect(":memory:")
    df = conn.execute(
        f"""
        SELECT {safe_date}::DATE AS period_date, {metric_sql} AS value
        FROM read_parquet('{parquet_path}')
        GROUP BY period_date
        ORDER BY period_date
        """
    ).df()
    conn.close()

    if len(df) < 4:
        return {"stable": True, "first_half": None, "second_half": None, "note": "Insufficient periods"}

    mid = len(df) // 2
    first_half = float(df.iloc[:mid]["value"].mean())
    second_half = float(df.iloc[mid:]["value"].mean())

    avg = (abs(first_half) + abs(second_half)) / 2
    if avg == 0:
        stable = True
    else:
        pct_diff = abs(first_half - second_half) / avg * 100
        stable = pct_diff < 20

    return {
        "stable": stable,
        "first_half": first_half,
        "second_half": second_half,
    }


# ---------------------------------------------------------------------------
# Minimum group size check
# ---------------------------------------------------------------------------


def minimum_group_size_check(
    parquet_path: str,
    dimension: str,
    metric: str,
    min_rows: int = 30,
    min_share: float = 0.01,
) -> Dict[str, Any]:
    """
    Return which groups have sufficient sample size and which are excluded.
    """
    safe_dim = f'"{dimension}"'
    conn = duckdb.connect(":memory:")
    total = conn.execute(f"SELECT COUNT(*) FROM read_parquet('{parquet_path}')").fetchone()[0]  # type: ignore[index]

    df = conn.execute(
        f"""
        SELECT {safe_dim} AS group_val, COUNT(*) AS row_count
        FROM read_parquet('{parquet_path}')
        WHERE {safe_dim} IS NOT NULL
        GROUP BY {safe_dim}
        ORDER BY row_count DESC
        """
    ).df()
    conn.close()

    df["share"] = df["row_count"] / total

    passed = df[(df["row_count"] >= min_rows) & (df["share"] >= min_share)]
    excluded = df[~((df["row_count"] >= min_rows) & (df["share"] >= min_share))]

    return {
        "passed_groups": passed["group_val"].tolist(),
        "excluded_groups": [
            {
                "group": row["group_val"],
                "row_count": int(row["row_count"]),
                "share": float(row["share"]),
                "reason": "below min_rows" if row["row_count"] < min_rows else "below min_share",
            }
            for _, row in excluded.iterrows()
        ],
    }


# ---------------------------------------------------------------------------
# Outlier sensitivity
# ---------------------------------------------------------------------------


def outlier_sensitivity(
    parquet_path: str,
    metric: str,
    metric_defs: Dict[str, str],
    top_pct: float = 0.01,
) -> Dict[str, Any]:
    """
    Compare aggregate metric with and without top *top_pct* outlier rows.
    Returns: {with_outliers: float, without_outliers: float, sensitive: bool}
    """
    from tools.analysis_engine import _resolve_metric_sql

    metric_sql = _resolve_metric_sql(metric, metric_defs)

    conn = duckdb.connect(":memory:")

    full_val = conn.execute(
        f"SELECT {metric_sql} FROM read_parquet('{parquet_path}')"
    ).fetchone()[0]  # type: ignore[index]

    # Determine threshold for top top_pct rows
    total_rows = conn.execute(
        f"SELECT COUNT(*) FROM read_parquet('{parquet_path}')"
    ).fetchone()[0]  # type: ignore[index]
    cutoff_rank = max(1, int(total_rows * (1 - top_pct)))

    # Get the threshold value
    # Use the raw metric column for outlier detection
    raw_col = _extract_first_column(metric_sql)
    if raw_col:
        threshold_val = conn.execute(
            f"""
            SELECT {raw_col}
            FROM read_parquet('{parquet_path}')
            WHERE {raw_col} IS NOT NULL
            ORDER BY {raw_col}::DOUBLE DESC
            LIMIT 1 OFFSET {cutoff_rank}
            """
        ).fetchone()
        threshold = threshold_val[0] if threshold_val else None

        if threshold is not None:
            filtered_val = conn.execute(
                f"""
                SELECT {metric_sql}
                FROM read_parquet('{parquet_path}')
                WHERE {raw_col}::DOUBLE <= {threshold}
                """
            ).fetchone()[0]  # type: ignore[index]
        else:
            filtered_val = full_val
    else:
        filtered_val = full_val

    conn.close()

    if full_val and full_val != 0:
        diff_pct = abs(full_val - filtered_val) / abs(full_val) * 100
        sensitive = diff_pct > 10
    else:
        sensitive = False
        diff_pct = 0

    return {
        "with_outliers": full_val,
        "without_outliers": filtered_val,
        "sensitive": sensitive,
        "difference_pct": round(diff_pct, 2),
    }


def _extract_first_column(metric_sql: str) -> Optional[str]:
    """Extract the first quoted column name from a SQL expression."""
    import re
    match = re.search(r'"([^"]+)"', metric_sql)
    return f'"{match.group(1)}"' if match else None
