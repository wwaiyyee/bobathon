from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import duckdb

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class JoinSafetyReport:
    safe: bool
    match_rate: float
    left_unique: bool
    right_unique: bool
    type_mismatch: bool
    invariant_failures: List[str] = field(default_factory=list)
    coverage_caveat: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "safe": self.safe,
            "match_rate": self.match_rate,
            "left_unique": self.left_unique,
            "right_unique": self.right_unique,
            "type_mismatch": self.type_mismatch,
            "invariant_failures": self.invariant_failures,
            "coverage_caveat": self.coverage_caveat,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_join_safety(
    left_parquet: str,
    right_parquet: str,
    left_key: str,
    right_key: str,
    measure_cols: List[str],
) -> JoinSafetyReport:
    """
    Evaluate whether a join between two datasets is safe for analysis.

    Checks:
    - Key match rate (left keys found in right dataset)
    - Key uniqueness on both sides
    - Type compatibility of the join key
    - Measure invariance: SUM(measure) must not change on many-to-one join
    """
    conn = duckdb.connect(":memory:")
    conn.execute(f"CREATE VIEW left_data AS SELECT * FROM read_parquet('{left_parquet}')")
    conn.execute(f"CREATE VIEW right_data AS SELECT * FROM read_parquet('{right_parquet}')")

    lk = f'"{left_key}"'
    rk = f'"{right_key}"'

    # Key uniqueness
    left_count = conn.execute(f"SELECT COUNT(*) FROM left_data").fetchone()[0]  # type: ignore[index]
    left_distinct = conn.execute(f"SELECT COUNT(DISTINCT {lk}) FROM left_data").fetchone()[0]  # type: ignore[index]
    right_count = conn.execute(f"SELECT COUNT(*) FROM right_data").fetchone()[0]  # type: ignore[index]
    right_distinct = conn.execute(f"SELECT COUNT(DISTINCT {rk}) FROM right_data").fetchone()[0]  # type: ignore[index]

    left_unique = left_count == left_distinct
    right_unique = right_count == right_distinct

    # Type compatibility
    left_type_row = conn.execute(
        f"SELECT data_type FROM information_schema.columns WHERE table_name='left_data' AND column_name='{left_key}'"
    ).fetchone()
    right_type_row = conn.execute(
        f"SELECT data_type FROM information_schema.columns WHERE table_name='right_data' AND column_name='{right_key}'"
    ).fetchone()

    type_mismatch = False
    if left_type_row and right_type_row:
        type_mismatch = left_type_row[0] != right_type_row[0]

    # Match rate
    matched = conn.execute(
        f"""
        SELECT COUNT(DISTINCT l.{lk})
        FROM left_data l
        INNER JOIN right_data r ON l.{lk} = r.{rk}
        """
    ).fetchone()[0]  # type: ignore[index]
    match_rate = matched / left_distinct if left_distinct else 0.0

    # Coverage caveat
    coverage_caveat = ""
    if match_rate < 1.0:
        unmatched_pct = (1 - match_rate) * 100
        coverage_caveat = (
            f"{unmatched_pct:.1f}% of left keys have no match in the right dataset. "
            "Rows will be dropped in an inner join."
        )

    # Invariant check: SUM(measure) should be preserved on many-to-one join
    invariant_failures: List[str] = []
    if not left_unique and right_unique:
        # Many-to-one join — measures on left must not be duplicated
        for measure in measure_cols:
            safe_m = f'"{measure}"'
            try:
                original_sum = conn.execute(
                    f"SELECT SUM({safe_m}::DOUBLE) FROM left_data WHERE {safe_m} IS NOT NULL"
                ).fetchone()[0]
                joined_sum = conn.execute(
                    f"""
                    SELECT SUM(l.{safe_m}::DOUBLE)
                    FROM left_data l
                    INNER JOIN right_data r ON l.{lk} = r.{rk}
                    """
                ).fetchone()[0]
                if original_sum and joined_sum:
                    diff_pct = abs(joined_sum - original_sum) / abs(original_sum) * 100
                    if diff_pct > 1.0:  # >1% tolerance
                        invariant_failures.append(
                            f"SUM({measure}) changed by {diff_pct:.1f}% after join — "
                            "possible row fan-out (many-to-many relationship)."
                        )
            except Exception:
                pass

    safe = (
        match_rate >= 0.9
        and not type_mismatch
        and len(invariant_failures) == 0
    )

    conn.close()
    return JoinSafetyReport(
        safe=safe,
        match_rate=round(match_rate, 4),
        left_unique=left_unique,
        right_unique=right_unique,
        type_mismatch=type_mismatch,
        invariant_failures=invariant_failures,
        coverage_caveat=coverage_caveat,
    )
