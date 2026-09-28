from __future__ import annotations

import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from models.core import DataDictionaryEntry, DatasetVersion
from services.session_store import get_session_store
from tools.ingest import ingest_file
from tools.data_profiler import profile_dataset, profile_column
from tools.data_quality import check_data_quality

router = APIRouter()

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "50"))


# ---------------------------------------------------------------------------
# Request/Response models
# ---------------------------------------------------------------------------


class DictionaryUpdateRequest(BaseModel):
    entries: List[DataDictionaryEntry]


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/upload")
async def upload_dataset(file: UploadFile = File(...)):
    """
    Upload a CSV or Excel file.
    Returns DatasetVersion, transformation_log, and dictionary_proposals.
    """
    content = await file.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_UPLOAD_MB:
        raise HTTPException(
            status_code=413,
            detail=f"File too large ({size_mb:.1f} MB). Maximum is {MAX_UPLOAD_MB} MB.",
        )

    filename = file.filename or "upload.csv"
    dataset_id = str(uuid.uuid4())

    version, transformations, dictionary = ingest_file(dataset_id, content, filename)

    # Register in session store
    store = get_session_store()
    store.register_dataset(dataset_id, version)

    return {
        "dataset_id": dataset_id,
        "version": version.model_dump(),
        "transformation_log": [t.__dict__ for t in transformations],
        "dictionary_proposals": [d.model_dump() for d in dictionary],
    }


@router.get("")
async def list_datasets():
    """List all registered datasets."""
    store = get_session_store()
    datasets = store.list_datasets()
    return {"datasets": datasets}


@router.get("/{dataset_id}")
async def get_dataset(dataset_id: str):
    """Get dataset info, version, and basic profiling."""
    store = get_session_store()
    version = store.get_dataset_version(dataset_id)
    if not version:
        raise HTTPException(status_code=404, detail="Dataset not found.")

    dictionary = store.get_dictionary(dataset_id) or []
    profile = profile_dataset(version.parquet_path, version.id, dictionary)

    return {
        "dataset_id": dataset_id,
        "version": version.model_dump(),
        "profile": profile,
    }


@router.get("/{dataset_id}/profile")
async def get_full_profile(dataset_id: str):
    """Return full column-level profiling for all columns."""
    store = get_session_store()
    version = store.get_dataset_version(dataset_id)
    if not version:
        raise HTTPException(status_code=404, detail="Dataset not found.")

    dictionary = store.get_dictionary(dataset_id) or []
    overview = profile_dataset(version.parquet_path, version.id, dictionary)

    column_profiles = []
    for entry in dictionary:
        col_profile = profile_column(version.parquet_path, entry.column, entry.role)
        column_profiles.append(col_profile)

    return {
        "overview": overview,
        "columns": column_profiles,
    }


@router.get("/{dataset_id}/quality")
async def get_quality_report(dataset_id: str):
    """Return the data quality report for a dataset."""
    store = get_session_store()
    version = store.get_dataset_version(dataset_id)
    if not version:
        raise HTTPException(status_code=404, detail="Dataset not found.")

    dictionary = store.get_dictionary(dataset_id) or []
    report = check_data_quality(version.parquet_path, dictionary, dataset_id, version.id)
    return report.to_dict()


@router.post("/{dataset_id}/dictionary")
async def update_dictionary(dataset_id: str, request: DictionaryUpdateRequest):
    """Confirm or update data dictionary entries for a dataset."""
    store = get_session_store()
    version = store.get_dataset_version(dataset_id)
    if not version:
        raise HTTPException(status_code=404, detail="Dataset not found.")

    store.set_dictionary(dataset_id, request.entries)
    return {"status": "updated", "entries": [e.model_dump() for e in request.entries]}


@router.get("/{dataset_id}/rows")
async def get_rows(
    dataset_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=500),
):
    """Paginated row viewer for the data explorer panel."""
    store = get_session_store()
    version = store.get_dataset_version(dataset_id)
    if not version:
        raise HTTPException(status_code=404, detail="Dataset not found.")

    import duckdb

    offset = (page - 1) * page_size
    conn = duckdb.connect(":memory:")
    total = conn.execute(
        f"SELECT COUNT(*) FROM read_parquet('{version.parquet_path}')"
    ).fetchone()[0]  # type: ignore[index]
    rows_df = conn.execute(
        f"SELECT * FROM read_parquet('{version.parquet_path}') LIMIT {page_size} OFFSET {offset}"
    ).df()
    conn.close()

    return {
        "total_rows": total,
        "page": page,
        "page_size": page_size,
        "rows": rows_df.to_dict(orient="records"),
    }
