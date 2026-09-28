from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd

from models.core import ColumnRole, DataDictionaryEntry

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def profile_dataset(
    parquet_path: str,
    version_id: str,
    dictionary: List[DataDictionaryEntry],
) -> Dict[str, Any]:
    """Return high-level schema overview for a dataset."""
    conn = duckdb.connect(":memory:")
    conn.execute(f"CREATE VIEW data AS SELECT * FROM read_parquet('{parquet_path}')")

    row_count = conn.execute("SELECT COUNT(*) FROM data").fetchone()[0]  # type: ignore[index]
    col_info = conn.execute("DESCRIBE data").fetchall()

    col_names = [c[0] for c in col_info]
    col_types = {c[0]: c[1] for c in col_info}

    date_range: Optional[Dict[str, Any]] = None
    date_cols = [e.column for e in dictionary if e.role == ColumnRole.date and e.column in col_names]
    if date_cols:
        dc = date_cols[0]
        safe = f'"{dc}"'
        try:
            result = conn.execute(
                f"SELECT MIN({safe}), MAX({safe}) FROM data"
            ).fetchone()
            date_range = {"column": dc, "min": str(result[0]), "max": str(result[1])}  # type: ignore[index]
        except Exception:
            pass

    pii_cols: List[str] = []
    try:
        df_sample = conn.execute("SELECT * FROM data LIMIT 200").df()
        pii_cols = detect_pii_columns(df_sample)
    except Exception:
        pass

    conn.close()
    return {
        "version_id": version_id,
        "row_count": row_count,
        "column_count": len(col_names),
        "columns": col_names,
        "column_types": col_types,
        "date_range": date_range,
        "pii_columns": pii_cols,
    }


def profile_column(
    parquet_path: str,
    column: str,
    role: ColumnRole,
) -> Dict[str, Any]:
    """Return per-column profiling stats."""
    conn = duckdb.connect(":memory:")
    conn.execute(f"CREATE VIEW data AS SELECT * FROM read_parquet('{parquet_path}')")
    safe_col = f'"{column}"'

    total = conn.execute("SELECT COUNT(*) FROM data").fetchone()[0]  # type: ignore[index]
    missing_count = conn.execute(
        f"SELECT COUNT(*) FROM data WHERE {safe_col} IS NULL"
    ).fetchone()[0]  # type: ignore[index]
    unique_count = conn.execute(
        f"SELECT COUNT(DISTINCT {safe_col}) FROM data"
    ).fetchone()[0]  # type: ignore[index]

    result: Dict[str, Any] = {
        "column": column,
        "role": role,
        "total_rows": total,
        "missing_count": missing_count,
        "missing_pct": round(missing_count / total * 100, 2) if total else 0,
        "unique_count": unique_count,
    }

    if role == ColumnRole.measure:
        try:
            stats = conn.execute(
                f"""
                SELECT
                    MIN({safe_col}::DOUBLE),
                    MAX({safe_col}::DOUBLE),
                    AVG({safe_col}::DOUBLE),
                    MEDIAN({safe_col}::DOUBLE),
                    STDDEV({safe_col}::DOUBLE)
                FROM data
                WHERE {safe_col} IS NOT NULL
                """
            ).fetchone()
            result.update(
                {
                    "min": stats[0],
                    "max": stats[1],
                    "mean": stats[2],
                    "median": stats[3],
                    "std": stats[4],
                }
            )
        except Exception:
            pass
        sample = conn.execute(
            f"SELECT {safe_col} FROM data WHERE {safe_col} IS NOT NULL LIMIT 5"
        ).fetchall()
        result["sample_values"] = [r[0] for r in sample]

    elif role == ColumnRole.dimension:
        top = conn.execute(
            f"""
            SELECT {safe_col}, COUNT(*) as cnt
            FROM data
            WHERE {safe_col} IS NOT NULL
            GROUP BY {safe_col}
            ORDER BY cnt DESC
            LIMIT 10
            """
        ).fetchall()
        result["top_categories"] = [{"value": r[0], "count": r[1]} for r in top]
        sample = conn.execute(
            f"SELECT DISTINCT {safe_col} FROM data WHERE {safe_col} IS NOT NULL LIMIT 5"
        ).fetchall()
        result["sample_values"] = [r[0] for r in sample]

    elif role == ColumnRole.date:
        try:
            date_stats = conn.execute(
                f"SELECT MIN({safe_col}), MAX({safe_col}) FROM data WHERE {safe_col} IS NOT NULL"
            ).fetchone()
            result["date_range"] = {"min": str(date_stats[0]), "max": str(date_stats[1])}
        except Exception:
            pass

    conn.close()
    return result


def detect_pii_columns(df: pd.DataFrame) -> List[str]:
    """Return column names that likely contain PII."""
    pii_cols: List[str] = []

    email_re = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
    phone_re = re.compile(r"(\+?\d[\d\s\-().]{7,}\d)")
    name_keywords = {"name", "first", "last", "surname", "forename", "fullname", "customer"}

    for col in df.columns:
        col_lower = col.lower()

        # Name heuristic
        if any(k in col_lower for k in name_keywords):
            pii_cols.append(col)
            continue

        sample = df[col].dropna().astype(str).head(100)
        email_hits = sample.apply(lambda x: bool(email_re.search(x))).mean()
        phone_hits = sample.apply(lambda x: bool(phone_re.search(x))).mean()

        if email_hits > 0.3 or phone_hits > 0.3:
            pii_cols.append(col)

    return list(dict.fromkeys(pii_cols))  # deduplicate preserving order
