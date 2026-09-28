from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional

from models.core import Evidence, Finding


@dataclass
class RecomputeResult:
    matched: bool
    original_value: Any
    recomputed_value: Any
    tolerance: float
    passed: bool


def recompute_finding(
    finding: Finding,
    evidence: Evidence,
    parquet_path: str,
) -> RecomputeResult:
    """
    Re-execute the evidence query and compare to the stored value.
    Passes if the result matches within tolerance.
    """
    from tools.analysis_engine import reproduce_evidence

    repro = reproduce_evidence(evidence, parquet_path)

    original = repro.get("original")
    reproduced = repro.get("reproduced")

    tolerance = 0.001  # 0.1%

    if original is None or reproduced is None:
        return RecomputeResult(
            matched=False,
            original_value=original,
            recomputed_value=reproduced,
            tolerance=tolerance,
            passed=False,
        )

    try:
        orig_f = float(original)
        repro_f = float(reproduced)
        denom = max(abs(orig_f), 1e-9)
        diff_pct = abs(orig_f - repro_f) / denom
        matched = diff_pct <= tolerance
    except (TypeError, ValueError):
        matched = str(original) == str(reproduced)

    return RecomputeResult(
        matched=matched,
        original_value=original,
        recomputed_value=reproduced,
        tolerance=tolerance,
        passed=matched,
    )
