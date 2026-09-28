from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import duckdb

from models.core import ColumnRole, DataDictionaryEntry, SufficiencyVerdict, TimeWindow

# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


@dataclass
class RequirementCheck:
    check_type: str  # presence|coverage|granularity|time_span|sample_size|comparability
    role_needed: str
    satisfied: bool
    message: str


@dataclass
class SufficiencyResult:
    verdict: SufficiencyVerdict
    missing: List[str] = field(default_factory=list)
    caveats: List[str] = field(default_factory=list)
    partial_answerable_parts: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "verdict": self.verdict,
            "missing": self.missing,
            "caveats": self.caveats,
            "partial_answerable_parts": self.partial_answerable_parts,
        }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def check_sufficiency(
    question_requirements: Dict[str, Any],
    dictionary: List[DataDictionaryEntry],
    parquet_path: str,
    time_anchor: Dict[str, Any],
) -> SufficiencyResult:
    """
    Evaluate whether the data is sufficient to answer the question's requirements.

    *question_requirements* is a dict with keys:
      - required_roles: list of ColumnRole values (str)
      - required_metrics: list of metric names
      - time_expression: optional str like "last month"
      - min_rows: optional int
      - dimensions: optional list of column names
    """
    checks = run_all_checks(question_requirements, dictionary, parquet_path)
    verdict = tiered_verdict(checks)

    missing = [c.message for c in checks if not c.satisfied and c.check_type == "presence"]
    caveats = [c.message for c in checks if not c.satisfied and c.check_type != "presence"]
    partial_parts: List[str] = []

    if verdict == SufficiencyVerdict.partial:
        partial_parts = [
            c.role_needed for c in checks if c.satisfied
        ]

    return SufficiencyResult(
        verdict=verdict,
        missing=missing,
        caveats=caveats,
        partial_answerable_parts=partial_parts,
    )


def run_all_checks(
    requirements: Dict[str, Any],
    dictionary: List[DataDictionaryEntry],
    parquet_path: str,
) -> List[RequirementCheck]:
    checks: List[RequirementCheck] = []
    col_role_map = {e.column: e.role for e in dictionary}
    col_names = set(e.column for e in dictionary)

    # --- Presence checks ---
    for role_str in requirements.get("required_roles", []):
        has_role = any(str(r) == role_str for r in col_role_map.values())
        checks.append(
            RequirementCheck(
                check_type="presence",
                role_needed=role_str,
                satisfied=has_role,
                message=f"No column with role '{role_str}' found." if not has_role else f"Role '{role_str}' present.",
            )
        )

    for metric in requirements.get("required_metrics", []):
        has_metric = metric in col_names or any(
            metric.lower() in c.lower() for c in col_names
        )
        checks.append(
            RequirementCheck(
                check_type="presence",
                role_needed=metric,
                satisfied=has_metric,
                message=f"Required metric '{metric}' not found." if not has_metric else f"Metric '{metric}' available.",
            )
        )

    # --- Sample size check ---
    min_rows = requirements.get("min_rows", 30)
    try:
        conn = duckdb.connect(":memory:")
        conn.execute(f"CREATE VIEW data AS SELECT * FROM read_parquet('{parquet_path}')")
        row_count = conn.execute("SELECT COUNT(*) FROM data").fetchone()[0]  # type: ignore[index]
        conn.close()
        sufficient_rows = row_count >= min_rows
        checks.append(
            RequirementCheck(
                check_type="sample_size",
                role_needed="rows",
                satisfied=sufficient_rows,
                message=f"Row count {row_count} {'≥' if sufficient_rows else '<'} minimum {min_rows}.",
            )
        )
    except Exception as e:
        checks.append(
            RequirementCheck(
                check_type="sample_size",
                role_needed="rows",
                satisfied=False,
                message=f"Could not count rows: {e}",
            )
        )

    # --- Coverage / dimension check ---
    for dim in requirements.get("dimensions", []):
        has_dim = dim in col_names or any(dim.lower() in c.lower() for c in col_names)
        checks.append(
            RequirementCheck(
                check_type="coverage",
                role_needed=dim,
                satisfied=has_dim,
                message=f"Dimension '{dim}' not found." if not has_dim else f"Dimension '{dim}' available.",
            )
        )

    # --- Time span check ---
    time_expr = requirements.get("time_expression")
    if time_expr:
        has_date = any(r == ColumnRole.date for r in col_role_map.values())
        checks.append(
            RequirementCheck(
                check_type="time_span",
                role_needed="date",
                satisfied=has_date,
                message="No date column found for time-based analysis." if not has_date else "Date column present.",
            )
        )

    return checks


def tiered_verdict(checks: List[RequirementCheck]) -> SufficiencyVerdict:
    """
    - All checks pass → sufficient
    - Some presence checks fail → insufficient
    - Only non-critical checks fail → partial
    """
    if not checks:
        return SufficiencyVerdict.sufficient

    presence_failures = [c for c in checks if c.check_type == "presence" and not c.satisfied]
    all_failures = [c for c in checks if not c.satisfied]

    if presence_failures:
        return SufficiencyVerdict.insufficient
    if all_failures:
        return SufficiencyVerdict.partial
    return SufficiencyVerdict.sufficient


# ---------------------------------------------------------------------------
# Interpretation sensitivity test
# ---------------------------------------------------------------------------


def interpretation_sensitivity_test(
    spec_a: Dict[str, Any],
    spec_b: Dict[str, Any],
    parquet_path: str,
    metric_defs: Dict[str, str],
) -> Dict[str, Any]:
    """
    Run two slightly different specs (e.g. different time windows or aggregations)
    and check whether conclusions agree.
    """
    from tools.analysis_engine import run_analysis_spec
    from models.core import AnalysisSpec

    def _run(spec_dict: Dict[str, Any]) -> Optional[float]:
        try:
            spec_obj = AnalysisSpec(**spec_dict)
            evidence = run_analysis_spec(
                spec_obj, parquet_path, spec_dict.get("dataset_id", ""), spec_dict.get("version_id", ""), metric_defs
            )
            val = evidence.value
            if isinstance(val, dict):
                val = val.get("current") or val.get("value")
            return float(val) if val is not None else None
        except Exception:
            return None

    result_a = _run(spec_a)
    result_b = _run(spec_b)

    if result_a is None or result_b is None:
        return {"agrees": False, "result_a": result_a, "result_b": result_b, "divergence_pct": None}

    avg = (abs(result_a) + abs(result_b)) / 2
    divergence_pct = abs(result_a - result_b) / avg * 100 if avg != 0 else 0
    agrees = divergence_pct < 10  # < 10% difference considered agreeing

    return {
        "agrees": agrees,
        "result_a": result_a,
        "result_b": result_b,
        "divergence_pct": round(divergence_pct, 2),
    }
