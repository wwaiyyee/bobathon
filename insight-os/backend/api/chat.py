from __future__ import annotations

import asyncio
import json
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from agents.analysis_agent import AnalysisAgent
from agents.router import route_request, get_tier_budget
from models.core import AnalysisSession, SessionStatus
from services.session_store import get_session_store
from services.llm_client import get_llm_client

router = APIRouter()


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    session_id: Optional[str] = None
    message: str
    datasets: List[str] = []


class AnswerRequest(BaseModel):
    answer: str


# ---------------------------------------------------------------------------
# POST /chat — main SSE endpoint
# ---------------------------------------------------------------------------


@router.post("")
async def chat(request: ChatRequest):
    """
    Main chat endpoint. Streams status_update events via SSE,
    then returns the final result as a JSON event.
    """
    store = get_session_store()
    llm = get_llm_client()

    # Get or create session
    session_id = request.session_id or str(uuid.uuid4())
    session = await store.get_or_create_session(session_id)

    # Register any new datasets into the session
    for ds_id in request.datasets:
        if ds_id not in session.dataset_ids:
            version = store.get_dataset_version(ds_id)
            if version:
                session.dataset_ids.append(ds_id)
                session.dataset_versions[ds_id] = version
                session.parquet_paths[ds_id] = version.parquet_path
                dictionary = store.get_dictionary(ds_id) or []
                session.dictionaries[ds_id] = dictionary

    # Route request
    tier = route_request(request.message, session)
    session.budget = get_tier_budget(tier)
    session.status = SessionStatus.running
    await store.save_session(session)

    async def event_stream():
        agent = AnalysisAgent(llm)
        try:
            result = await agent.run(session, request.message)

            # Emit status updates
            for update in result.status_updates:
                event = json.dumps({"type": "status_update", "data": update})
                yield f"data: {event}\n\n"

            # Questions for user
            if result.questions_for_user:
                session.pending_questions = result.questions_for_user
                session.status = SessionStatus.waiting_for_user
                await store.save_session(session)
                event = json.dumps({
                    "type": "clarification_needed",
                    "data": {"questions": result.questions_for_user},
                })
                yield f"data: {event}\n\n"
            else:
                session.status = SessionStatus.complete
                await store.save_session(session)

                payload = {
                    "type": "result",
                    "data": {
                        "session_id": session_id,
                        "tier": tier,
                        "answer": result.answer_text,
                        "findings": [f.model_dump() for f in result.findings],
                        "evidence": [e.model_dump() for e in result.evidence],
                        "charts": [c.model_dump() for c in result.charts],
                        "plan": result.plan_preview.model_dump() if result.plan_preview else None,
                    },
                }
                yield f"data: {json.dumps(payload)}\n\n"

        except Exception as e:
            session.status = SessionStatus.error
            await store.save_session(session)
            error_event = json.dumps({"type": "error", "data": str(e)})
            yield f"data: {error_event}\n\n"

        yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ---------------------------------------------------------------------------
# GET /chat/{session_id}/history
# ---------------------------------------------------------------------------


@router.get("/{session_id}/history")
async def get_history(session_id: str):
    """Return the conversation history for a session."""
    store = get_session_store()
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    return {
        "session_id": session_id,
        "history": session.conversation_history,
        "pending_questions": session.pending_questions,
    }


# ---------------------------------------------------------------------------
# POST /chat/{session_id}/answer
# ---------------------------------------------------------------------------


@router.post("/{session_id}/answer")
async def post_answer(session_id: str, request: AnswerRequest):
    """
    User answers a clarification question.
    Adds the answer to conversation history and clears pending questions.
    """
    store = get_session_store()
    session = await store.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found.")

    session.conversation_history.append({"role": "user", "content": request.answer})
    session.pending_questions = []
    session.status = SessionStatus.idle
    await store.save_session(session)

    return {"status": "received", "session_id": session_id}
