from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import duckdb
import pandas as pd

from models.core import ColumnRole, DataDictionaryEntry

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class QualityIssue:
    column: str
    issue_type: str  # missing_values|duplicates|outliers|type_mismatch|mixed_currency|suspicious_values
    severity: str  # warning|error
    description: str
    affected_rows: int
    affected_findings: List[str] = field(default_factory=list)


@dataclass
class QualityReport:
    dataset_id: Optional[str]
    version_id: Optional[str]
    total_rows: int
    total_columns: int
    issues: List[QualityIssue] = field(default_factory=list)
    passed: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "version_id": self.version_id,
            "total_rows": self.total_rows,
            "total_columns": self.total_columns,
            "passed": self.passed,
            "issues": [
                {
                    "column": i.column,
                    "issue_type": i.issue_type,
                    "severity": i.severity,
                    "description": i.description,
                    "affected_rows": i.affected_rows,
                    "affected_findings": i.affected_findings,
                }
                for i in self.issues
            ],
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_data_quality(
    parquet_path: str,
    dictionary: List[DataDictionaryEntry],
    dataset_id: Optional[str] = None,
    version_id: Optional[str] = None,
) -> QualityReport:
    conn = duckdb.connect(":memory:")
    conn.execute(f"CREATE VIEW data AS SELECT * FROM read_parquet('{parquet_path}')")

    total_rows = conn.execute("SELECT COUNT(*) FROM data").fetchone()[0]  # type: ignore[index]
    col_info = conn.execute("DESCRIBE data").fetchall()
    total_columns = len(col_info)
    col_names = [c[0] for c in col_info]

    issues: List[QualityIssue] = []

    col_role_map = {e.column: e for e in dictionary}

    for col in col_names:
        entry = col_role_map.get(col)
        role = entry.role if entry else ColumnRole.other
        safe_col = f'"{col}"'

        # Missing values
        missing = conn.execute(
            f"SELECT COUNT(*) FROM data WHERE {safe_col} IS NULL"
        ).fetchone()[0]  # type: ignore[index]
        if missing > 0:
            pct = missing / total_rows * 100 if total_rows else 0
            severity = "error" if pct > 20 else "warning"
            issues.append(
                QualityIssue(
                    column=col,
                    issue_type="missing_values",
                    severity=severity,
                    description=f"{missing} missing values ({pct:.1f}%)",
                    affected_rows=missing,
                )
            )

        if role == ColumnRole.measure:
            # Outlier detection (IQR)
            try:
                stats = conn.execute(
                    f"""
                    SELECT
                        PERCENTILE_CONT(0.25) WITHIN GROUP (ORDER BY {safe_col}::DOUBLE) AS q1,
                        PERCENTILE_CONT(0.75) WITHIN GROUP (ORDER BY {safe_col}::DOUBLE) AS q3
                    FROM data WHERE {safe_col} IS NOT NULL
                    """
                ).fetchone()
                if stats and stats[0] is not None and stats[1] is not None:
                    q1, q3 = stats
                    iqr = q3 - q1
                    lower, upper = q1 - 3 * iqr, q3 + 3 * iqr
                    outlier_count = conn.execute(
                        f"""
                        SELECT COUNT(*) FROM data
                        WHERE {safe_col}::DOUBLE < {lower} OR {safe_col}::DOUBLE > {upper}
                        """
                    ).fetchone()[0]  # type: ignore[index]
                    if outlier_count > 0:
                        issues.append(
                            QualityIssue(
                                column=col,
                                issue_type="outliers",
                                severity="warning",
                                description=f"{outlier_count} extreme outliers (beyond 3×IQR: [{lower:.2f}, {upper:.2f}])",
                                affected_rows=outlier_count,
                            )
                        )
            except Exception:
                pass

            # Suspicious values (negative where unexpected)
            try:
                neg_count = conn.execute(
                    f"SELECT COUNT(*) FROM data WHERE {safe_col}::DOUBLE < 0"
                ).fetchone()[0]  # type: ignore[index]
                if neg_count > 0 and any(
                    kw in col.lower()
                    for kw in ("revenue", "sales", "price", "cost", "quantity", "qty")
                ):
                    issues.append(
                        QualityIssue(
                            column=col,
                            issue_type="suspicious_values",
                            severity="warning",
                            description=f"{neg_count} negative values in '{col}' — verify if returns/credits are expected.",
                            affected_rows=neg_count,
                        )
                    )
            except Exception:
                pass

            # Mixed currency detection
            if entry and entry.currency_symbol is None:
                try:
                    sample_df = conn.execute(
                        f"SELECT {safe_col} FROM data LIMIT 200"
                    ).df()
                    raw_vals = sample_df.iloc[:, 0].astype(str)
                    currencies_found = set()
                    for sym in ["$", "€", "£", "¥", "₹"]:
                        if raw_vals.str.contains(sym, regex=False).any():
                            currencies_found.add(sym)
                    if len(currencies_found) > 1:
                        issues.append(
                            QualityIssue(
                                column=col,
                                issue_type="mixed_currency",
                                severity="error",
                                description=f"Mixed currency symbols detected: {currencies_found}. Values may not be comparable.",
                                affected_rows=total_rows,
                            )
                        )
                except Exception:
                    pass

    # Duplicate rows
    try:
        dup_count = conn.execute(
            f"SELECT COUNT(*) - COUNT(*) OVER () + COUNT(DISTINCT *) FROM data"
        ).fetchone()
        # Simpler approach
        total = conn.execute("SELECT COUNT(*) FROM data").fetchone()[0]  # type: ignore[index]
        distinct = conn.execute(
            "SELECT COUNT(*) FROM (SELECT DISTINCT * FROM data)"
        ).fetchone()[0]  # type: ignore[index]
        dups = total - distinct
        if dups > 0:
            issues.append(
                QualityIssue(
                    column="(all columns)",
                    issue_type="duplicates",
                    severity="warning",
                    description=f"{dups} duplicate rows detected.",
                    affected_rows=dups,
                )
            )
    except Exception:
        pass

    conn.close()
    error_count = sum(1 for i in issues if i.severity == "error")
    return QualityReport(
        dataset_id=dataset_id,
        version_id=version_id,
        total_rows=total_rows,
        total_columns=total_columns,
        issues=issues,
        passed=error_count == 0,
    )
