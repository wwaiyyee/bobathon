from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from models.core import Assumption
from services.session_store import get_session_store

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class AssumptionUpdateRequest(BaseModel):
    text: str
    confirmed: bool = True


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.get("/{session_id}/findings")
async def get_findings(session_id: str):
    """Return all findings with evidence status for a session."""
    store = get_session_store()
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    findings_with_status = []
    for finding in session.findings:
        evidence = session.get_evidence_by_id(finding.evidence_id or "")
        findings_with_status.append({
            "finding": finding.model_dump(),
            "evidence_status": finding.evidence_status,
            "stale": finding.stale,
            "evidence_id": finding.evidence_id,
        })

    return {
        "session_id": session_id,
        "findings": findings_with_status,
        "total": len(session.findings),
    }


@router.get("/{session_id}/findings/{finding_id}/evidence")
async def get_finding_evidence(session_id: str, finding_id: str):
    """Return full evidence panel data for a specific finding."""
    store = get_session_store()
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    finding = session.get_finding_by_id(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found.")

    evidence = session.get_evidence_by_id(finding.evidence_id or "")

    return {
        "finding": finding.model_dump(),
        "evidence": evidence.model_dump() if evidence else None,
        "validation_results": finding.validation_results,
    }


@router.post("/{session_id}/findings/{finding_id}/prove")
async def prove_finding(session_id: str, finding_id: str):
    """Re-run computation for a finding and return the match result."""
    store = get_session_store()
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    finding = session.get_finding_by_id(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found.")

    evidence = session.get_evidence_by_id(finding.evidence_id or "")
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found for this finding.")

    primary_dataset_id = session.dataset_ids[0] if session.dataset_ids else None
    if not primary_dataset_id:
        raise HTTPException(status_code=400, detail="No dataset in session.")

    parquet_path = session.parquet_paths.get(primary_dataset_id, "")

    from validators.recompute import recompute_finding
    result = recompute_finding(finding, evidence, parquet_path)

    return {
        "finding_id": finding_id,
        "matched": result.matched,
        "original_value": result.original_value,
        "recomputed_value": result.recomputed_value,
        "tolerance": result.tolerance,
        "passed": result.passed,
    }


@router.get("/{session_id}/findings/{finding_id}/rows")
async def get_finding_rows(session_id: str, finding_id: str):
    """Return the filtered rows that back a specific finding."""
    store = get_session_store()
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    finding = session.get_finding_by_id(finding_id)
    if not finding:
        raise HTTPException(status_code=404, detail="Finding not found.")

    evidence = session.get_evidence_by_id(finding.evidence_id or "")
    if not evidence:
        raise HTTPException(status_code=404, detail="Evidence not found.")

    primary_dataset_id = session.dataset_ids[0] if session.dataset_ids else None
    parquet_path = session.parquet_paths.get(primary_dataset_id or "", "")
    if not parquet_path:
        raise HTTPException(status_code=400, detail="No parquet path available.")

    import duckdb
    from tools.analysis_engine import _build_filter_clause

    filter_clause = _build_filter_clause(evidence.filters)
    where_str = f" WHERE {filter_clause}" if filter_clause else ""

    conn = duckdb.connect(":memory:")
    rows_df = conn.execute(
        f"SELECT * FROM read_parquet('{parquet_path}'){where_str} LIMIT 100"
    ).df()
    conn.close()

    return {
        "finding_id": finding_id,
        "rows": rows_df.to_dict(orient="records"),
        "filters_applied": evidence.filters,
    }


@router.post("/{session_id}/assumptions/{assumption_id}/update")
async def update_assumption(
    session_id: str, assumption_id: str, request: AssumptionUpdateRequest
):
    """
    Change an assumption and mark dependent findings as stale.
    """
    store = get_session_store()
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    assumption = next((a for a in session.assumptions if a.id == assumption_id), None)
    if not assumption:
        raise HTTPException(status_code=404, detail="Assumption not found.")

    assumption.text = request.text
    assumption.confirmed = request.confirmed

    # Mark dependent findings as stale
    stale_findings = []
    for finding in session.findings:
        evidence = session.get_evidence_by_id(finding.evidence_id or "")
        if evidence and assumption_id in evidence.assumption_ids:
            finding.stale = True
            stale_findings.append(finding.id)

    await store.save_session(session)

    return {
        "assumption_id": assumption_id,
        "updated": True,
        "stale_findings": stale_findings,
    }


@router.get("/{session_id}/plan")
async def get_plan(session_id: str):
    """Return the current analysis plan for a session."""
    store = get_session_store()
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    latest_plan = session.plans[-1] if session.plans else None
    return {
        "session_id": session_id,
        "plan": latest_plan.model_dump() if latest_plan else None,
    }
