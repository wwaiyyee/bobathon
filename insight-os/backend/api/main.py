from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.datasets import router as datasets_router
from api.chat import router as chat_router
from api.analysis import router as analysis_router
from api.reports import router as reports_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Create required directories and initialise the database on startup."""
    upload_dir = os.getenv("UPLOAD_DIR", "data/uploads")
    parquet_dir = os.getenv("PARQUET_DIR", "data/parquet")
    os.makedirs(upload_dir, exist_ok=True)
    os.makedirs(parquet_dir, exist_ok=True)
    os.makedirs("data", exist_ok=True)

    from services.session_store import get_session_store
    store = get_session_store()
    await store.init_db()

    yield


app = FastAPI(
    title="InsightOS API",
    description="Analytical intelligence platform API",
    version="1.0.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# CORS
# ---------------------------------------------------------------------------

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------

app.include_router(datasets_router, prefix="/datasets", tags=["datasets"])
app.include_router(chat_router, prefix="/chat", tags=["chat"])
app.include_router(analysis_router, prefix="/analysis", tags=["analysis"])
app.include_router(reports_router, prefix="/reports", tags=["reports"])


@app.exception_handler(Exception)
async def global_exception_handler(request, exc: Exception):
    import traceback
    traceback.print_exc()
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "traceback": traceback.format_exc()},
    )


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------


@app.get("/health")
async def health():
    return {"status": "ok", "version": "1.0.0"}
