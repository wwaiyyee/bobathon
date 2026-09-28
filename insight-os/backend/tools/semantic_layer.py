from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import duckdb

from models.core import ColumnRole, DataDictionaryEntry, TimeWindow

# ---------------------------------------------------------------------------
# Metric pack definitions
# ---------------------------------------------------------------------------

# Each value is an ordered list of fallback SQL expressions.
# The first one that can be resolved against real column names is used.
SALES_V1_METRIC_PACK: Dict[str, List[str]] = {
    "revenue": [
        'SUM("net_sales")',
        'SUM("revenue")',
        'SUM("sales")',
        'SUM("gross_sales")',
        'SUM("amount")',
    ],
    "orders": [
        'COUNT(DISTINCT "order_id")',
        'COUNT(DISTINCT "transaction_id")',
        'COUNT(DISTINCT "order_number")',
        'COUNT(*)',
    ],
    "aov": [
        'SUM("revenue") / NULLIF(COUNT(DISTINCT "order_id"), 0)',
        'SUM("net_sales") / NULLIF(COUNT(DISTINCT "order_id"), 0)',
        'SUM("sales") / NULLIF(COUNT(DISTINCT "transaction_id"), 0)',
    ],
    "gross_margin": [
        '(SUM("revenue") - SUM("cogs")) / NULLIF(SUM("revenue"), 0)',
        '(SUM("net_sales") - SUM("cost")) / NULLIF(SUM("net_sales"), 0)',
        '(SUM("sales") - SUM("cost_of_goods")) / NULLIF(SUM("sales"), 0)',
    ],
    "units": [
        'SUM("units")',
        'SUM("quantity")',
        'SUM("qty")',
        'SUM("items")',
    ],
    "customers": [
        'COUNT(DISTINCT "customer_id")',
        'COUNT(DISTINCT "customer")',
        'COUNT(DISTINCT "user_id")',
    ],
}


# ---------------------------------------------------------------------------
# Metric resolution
# ---------------------------------------------------------------------------


def resolve_metric_pack(
    dictionary: List[DataDictionaryEntry],
) -> Dict[str, str]:
    """
    Map abstract metric names → SQL expressions using real column names from *dictionary*.

    Only returns metrics where at least one fallback expression can be satisfied.
    """
    confirmed_cols = {e.column.lower(): e.column for e in dictionary}

    resolved: Dict[str, str] = {}
    for metric_name, expressions in SALES_V1_METRIC_PACK.items():
        for expr in expressions:
            # Extract quoted column names from the expression
            quoted_cols = re.findall(r'"([^"]+)"', expr)
            if all(c.lower() in confirmed_cols for c in quoted_cols):
                # Replace with real-cased column names
                real_expr = expr
                for qc in quoted_cols:
                    real_col = confirmed_cols[qc.lower()]
                    real_expr = real_expr.replace(f'"{qc}"', f'"{real_col}"')
                resolved[metric_name] = real_expr
                break  # use first match

    return resolved


# ---------------------------------------------------------------------------
# Time anchor resolution
# ---------------------------------------------------------------------------


def resolve_time_anchor(parquet_path: str, date_col: str) -> Dict[str, Any]:
    """
    Compute time-based anchors from the data: max date, last complete month,
    last complete quarter, etc.
    """
    conn = duckdb.connect(":memory:")
    conn.execute(f"CREATE VIEW data AS SELECT * FROM read_parquet('{parquet_path}')")
    safe = f'"{date_col}"'

    row = conn.execute(
        f"SELECT MIN({safe}::DATE), MAX({safe}::DATE) FROM data WHERE {safe} IS NOT NULL"
    ).fetchone()
    conn.close()

    if not row or row[0] is None:
        return {}

    min_date: date = row[0]
    max_date: date = row[1]

    # Last complete month
    last_complete_month_end = date(max_date.year, max_date.month, 1) - timedelta(days=1)
    last_complete_month_start = date(
        last_complete_month_end.year, last_complete_month_end.month, 1
    )

    # Last complete quarter
    current_q = (max_date.month - 1) // 3
    if current_q == 0:
        prev_q_start = date(max_date.year - 1, 10, 1)
        prev_q_end = date(max_date.year - 1, 12, 31)
    else:
        q_month_start = (current_q - 1) * 3 + 1
        prev_q_start = date(max_date.year, q_month_start, 1)
        q_month_end = q_month_start + 2
        last_day = _last_day_of_month(max_date.year, q_month_end)
        prev_q_end = date(max_date.year, q_month_end, last_day)

    data_spans_years = max_date.year > min_date.year

    return {
        "max_date": max_date.isoformat(),
        "min_date": min_date.isoformat(),
        "last_complete_month_start": last_complete_month_start.isoformat(),
        "last_complete_month_end": last_complete_month_end.isoformat(),
        "last_complete_quarter_start": prev_q_start.isoformat(),
        "last_complete_quarter_end": prev_q_end.isoformat(),
        "data_spans_years": data_spans_years,
    }


def _last_day_of_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


# ---------------------------------------------------------------------------
# Relative time expression resolution
# ---------------------------------------------------------------------------


def resolve_relative_time(expression: str, time_anchor: Dict[str, Any]) -> TimeWindow:
    """
    Map natural-language time expressions to concrete TimeWindow dates.

    Examples: "last month", "this quarter", "Q3 2024", "last year", "YTD"
    """
    expr = expression.strip().lower()
    anchor_max = time_anchor.get("max_date", date.today().isoformat())
    max_dt = date.fromisoformat(anchor_max)

    # Last month
    if expr in ("last month", "previous month"):
        return TimeWindow(
            start=time_anchor.get("last_complete_month_start"),
            end=time_anchor.get("last_complete_month_end"),
            label=expression,
        )

    # This month
    if expr == "this month":
        start = date(max_dt.year, max_dt.month, 1).isoformat()
        return TimeWindow(start=start, end=anchor_max, label=expression)

    # Last quarter / previous quarter
    if expr in ("last quarter", "previous quarter", "last complete quarter"):
        return TimeWindow(
            start=time_anchor.get("last_complete_quarter_start"),
            end=time_anchor.get("last_complete_quarter_end"),
            label=expression,
        )

    # Last year
    if expr in ("last year", "previous year"):
        prev_year = max_dt.year - 1
        return TimeWindow(
            start=f"{prev_year}-01-01",
            end=f"{prev_year}-12-31",
            label=expression,
        )

    # YTD
    if expr in ("ytd", "year to date", "this year"):
        return TimeWindow(
            start=f"{max_dt.year}-01-01",
            end=anchor_max,
            label=expression,
        )

    # Qn YYYY pattern — e.g. "Q3 2023"
    q_match = re.match(r"q([1-4])\s*(\d{4})", expr)
    if q_match:
        q = int(q_match.group(1))
        year = int(q_match.group(2))
        q_start_month = (q - 1) * 3 + 1
        q_end_month = q_start_month + 2
        last_day = _last_day_of_month(year, q_end_month)
        return TimeWindow(
            start=f"{year}-{q_start_month:02d}-01",
            end=f"{year}-{q_end_month:02d}-{last_day:02d}",
            label=expression,
        )

    # Last N days
    days_match = re.match(r"last (\d+) days?", expr)
    if days_match:
        n = int(days_match.group(1))
        start = (max_dt - timedelta(days=n - 1)).isoformat()
        return TimeWindow(start=start, end=anchor_max, label=expression)

    # Last N months
    months_match = re.match(r"last (\d+) months?", expr)
    if months_match:
        n = int(months_match.group(1))
        m = max_dt.month - n
        y = max_dt.year
        while m <= 0:
            m += 12
            y -= 1
        start = date(y, m, 1).isoformat()
        return TimeWindow(start=start, end=anchor_max, label=expression)

    # Fallback: treat as a year
    year_match = re.match(r"(\d{4})", expr)
    if year_match:
        year = int(year_match.group(1))
        return TimeWindow(
            start=f"{year}-01-01",
            end=f"{year}-12-31",
            label=expression,
        )

    # Cannot resolve — return open window
    return TimeWindow(label=expression)
