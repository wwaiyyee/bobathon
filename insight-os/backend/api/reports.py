from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel

from agents.report_agent import generate_report, render_markdown, render_html, ReportDocument
from services.session_store import get_session_store
from services.llm_client import get_llm_client

router = APIRouter()

# In-memory report store: session_id -> ReportDocument
_report_cache: dict[str, ReportDocument] = {}


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class GenerateReportRequest(BaseModel):
    session_id: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/generate")
async def generate_report_endpoint(request: GenerateReportRequest):
    """Generate a full 10-section report for a session."""
    store = get_session_store()
    session = await store.get_session(request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    llm = get_llm_client()

    report = await generate_report(
        session=session,
        findings=session.findings,
        evidence=session.evidence,
        charts=session.charts,
        assumptions=session.assumptions,
        transformations=session.transformations,
        llm_client=llm,
    )

    _report_cache[request.session_id] = report

    return {
        "session_id": request.session_id,
        "report": report.to_dict(),
    }


@router.get("/{session_id}")
async def get_report(session_id: str):
    """Get the existing report for a session."""
    report = _report_cache.get(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="No report found for this session.")

    return {
        "session_id": session_id,
        "report": report.to_dict(),
    }


@router.get("/{session_id}/markdown")
async def get_report_markdown(session_id: str):
    """Download the report as a Markdown file."""
    report = _report_cache.get(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="No report found for this session.")

    md_text = render_markdown(report)
    return PlainTextResponse(
        content=md_text,
        media_type="text/markdown",
        headers={"Content-Disposition": f"attachment; filename=report_{session_id[:8]}.md"},
    )


@router.get("/{session_id}/html")
async def get_report_html(session_id: str):
    """Download the report as an HTML file."""
    report = _report_cache.get(session_id)
    if not report:
        raise HTTPException(status_code=404, detail="No report found for this session.")

    html_text = render_html(report)
    return HTMLResponse(
        content=html_text,
        headers={"Content-Disposition": f"attachment; filename=report_{session_id[:8]}.html"},
    )
