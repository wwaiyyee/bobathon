from __future__ import annotations

from typing import List, Optional, Tuple

from models.core import Evidence, Finding

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def create_evidence_from_spec_result(
    spec,  # AnalysisSpec
    result_df,  # pd.DataFrame
    query: str,
    dataset_id: str,
    version_id: str,
    filters: dict,
    assumption_ids: List[str],
) -> Evidence:
    """
    Create an Evidence record from an analysis spec result DataFrame.
    The value stored is the serialized result rows, NOT raw data for LLM.
    """
    import uuid

    value = result_df.to_dict(orient="records") if hasattr(result_df, "to_dict") else result_df
    rows_used = len(result_df) if hasattr(result_df, "__len__") else None

    return Evidence(
        id=str(uuid.uuid4()),
        metric=spec.metric,
        value=value,
        source_dataset=dataset_id,
        dataset_version_id=version_id,
        filters=filters,
        rows_used=rows_used,
        calculation=f"{spec.analysis_type} on {spec.metric}",
        query=query,
        inputs={"spec": spec.model_dump()},
        outputs={"rows": rows_used},
        assumption_ids=assumption_ids,
        engine_version="1.0",
    )


def link_evidence_to_finding(
    evidence: Evidence,
    finding: Finding,
) -> Tuple[Evidence, Finding]:
    """
    Set evidence.finding_id = finding.id and finding.evidence_id = evidence.id.
    Returns the updated (evidence, finding) pair.
    """
    evidence.finding_id = finding.id
    finding.evidence_id = evidence.id
    return evidence, finding


def mark_stale(
    finding_ids: List[str],
    new_version_id: str,
    findings: List[Finding],
) -> List[Finding]:
    """
    Mark findings as stale when data is updated to a new version.
    Returns list of affected findings.
    """
    affected: List[Finding] = []
    for finding in findings:
        if finding.id in finding_ids:
            finding.stale = True
            affected.append(finding)
    return affected
