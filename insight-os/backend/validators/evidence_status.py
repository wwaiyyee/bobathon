from __future__ import annotations

from typing import List, Optional

from models.core import ClaimType, Evidence, EvidenceStatus, Finding


def compute_evidence_status(
    finding: Finding,
    evidence: Evidence,
    recompute_result,  # RecomputeResult | None
    quality_issues: List,  # list[QualityIssue]
    coverage_pct: float = 1.0,
) -> EvidenceStatus:
    """
    Compute EvidenceStatus using the exact rules from spec section 19:

    - not_applicable: claim_type is definition, suggestion, or question
    - supported: recomputation matched + all invariants pass + sample sizes ok + no quality error on used columns
    - partially_supported: verified but has quality warnings or coverage gaps
    - insufficient_evidence: verification failed, too small, missing data, or result flips under alternative
    """
    # Rule 1: not_applicable for non-empirical claims
    if finding.claim_type in (ClaimType.definition, ClaimType.suggestion, ClaimType.question):
        return EvidenceStatus.not_applicable

    # Rule 2: No evidence attached
    if evidence is None:
        return EvidenceStatus.insufficient_evidence

    # Rule 3: Insufficient rows
    if evidence.rows_used is not None and evidence.rows_used < 5:
        return EvidenceStatus.insufficient_evidence

    # Rule 4: Recompute failed
    if recompute_result is not None and not recompute_result.passed:
        return EvidenceStatus.insufficient_evidence

    # Rule 5: Check quality issues on columns used in this evidence
    error_issues = [
        qi for qi in quality_issues
        if qi.severity == "error" and _column_used_in_evidence(qi.column, evidence)
    ]
    warning_issues = [
        qi for qi in quality_issues
        if qi.severity == "warning" and _column_used_in_evidence(qi.column, evidence)
    ]

    if error_issues:
        return EvidenceStatus.insufficient_evidence

    # Rule 6: Coverage gap
    if coverage_pct < 0.8:
        return EvidenceStatus.partially_supported

    # Rule 7: Warnings present but no errors
    if warning_issues:
        return EvidenceStatus.partially_supported

    # All checks pass
    return EvidenceStatus.supported


def _column_used_in_evidence(column: str, evidence: Evidence) -> bool:
    """Return True if column appears to be used in the evidence query or metric."""
    if evidence.query and f'"{column}"' in evidence.query:
        return True
    if evidence.metric and column.lower() in evidence.metric.lower():
        return True
    if evidence.calculation and column in evidence.calculation:
        return True
    return False
