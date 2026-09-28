from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

import aiosqlite

from models.core import AnalysisSession, DataDictionaryEntry, DatasetVersion

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///data/insightos.db")
# Strip SQLAlchemy prefix for raw aiosqlite usage
_DB_PATH = DATABASE_URL.replace("sqlite+aiosqlite:///", "")

# ---------------------------------------------------------------------------
# In-memory registry
# ---------------------------------------------------------------------------

_dataset_registry: Dict[str, DatasetVersion] = {}
_dictionary_registry: Dict[str, List[DataDictionaryEntry]] = {}


class SessionStore:
    """
    Combined in-memory + SQLite session store.
    - Sessions are held in memory (fast access during a request).
    - SQLite provides persistence for restarts (JSON blob per session).
    - Dataset registry (dataset_id → version + path) is in-memory only.
    """

    def __init__(self):
        self._sessions: Dict[str, AnalysisSession] = {}

    async def init_db(self) -> None:
        """Create the sessions table if it doesn't exist."""
        os.makedirs(os.path.dirname(_DB_PATH) if os.path.dirname(_DB_PATH) else ".", exist_ok=True)
        async with aiosqlite.connect(_DB_PATH) as db:
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    data TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            await db.commit()

    async def get_session(self, session_id: str) -> Optional[AnalysisSession]:
        """Get a session from memory, falling back to SQLite."""
        if session_id in self._sessions:
            return self._sessions[session_id]

        # Try SQLite
        try:
            async with aiosqlite.connect(_DB_PATH) as db:
                async with db.execute(
                    "SELECT data FROM sessions WHERE id = ?", (session_id,)
                ) as cursor:
                    row = await cursor.fetchone()
                    if row:
                        data = json.loads(row[0])
                        session = AnalysisSession.model_validate(data)
                        self._sessions[session_id] = session
                        return session
        except Exception:
            pass

        return None

    async def get_or_create_session(self, session_id: str) -> AnalysisSession:
        """Get a session or create a new one if it doesn't exist."""
        session = await self.get_session(session_id)
        if session is None:
            session = AnalysisSession(id=session_id)
            self._sessions[session_id] = session
            await self.save_session(session)
        return session

    async def create_session(self, session_id: Optional[str] = None) -> AnalysisSession:
        """Create and persist a new session."""
        import uuid
        sid = session_id or str(uuid.uuid4())
        session = AnalysisSession(id=sid)
        self._sessions[sid] = session
        await self.save_session(session)
        return session

    async def save_session(self, session: AnalysisSession) -> None:
        """Persist session to SQLite."""
        from datetime import datetime
        session.updated_at = datetime.utcnow()
        self._sessions[session.id] = session
        try:
            data_json = session.model_dump_json()
            async with aiosqlite.connect(_DB_PATH) as db:
                await db.execute(
                    """
                    INSERT INTO sessions (id, data, updated_at)
                    VALUES (?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET data=excluded.data, updated_at=excluded.updated_at
                    """,
                    (session.id, data_json, session.updated_at.isoformat()),
                )
                await db.commit()
        except Exception:
            pass  # Memory cache still has the session

    async def delete_session(self, session_id: str) -> None:
        """Delete a session from memory and SQLite."""
        self._sessions.pop(session_id, None)
        try:
            async with aiosqlite.connect(_DB_PATH) as db:
                await db.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                await db.commit()
        except Exception:
            pass

    def register_dataset(self, dataset_id: str, version: DatasetVersion) -> None:
        """Register a dataset version in the in-memory registry."""
        _dataset_registry[dataset_id] = version

    def get_dataset_version(self, dataset_id: str) -> Optional[DatasetVersion]:
        return _dataset_registry.get(dataset_id)

    def list_datasets(self) -> List[Dict[str, Any]]:
        return [
            {"dataset_id": k, "version": v.model_dump()}
            for k, v in _dataset_registry.items()
        ]

    def set_dictionary(self, dataset_id: str, entries: List[DataDictionaryEntry]) -> None:
        _dictionary_registry[dataset_id] = entries

    def get_dictionary(self, dataset_id: str) -> Optional[List[DataDictionaryEntry]]:
        return _dictionary_registry.get(dataset_id)


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_store: Optional[SessionStore] = None


def get_session_store() -> SessionStore:
    global _store
    if _store is None:
        _store = SessionStore()
    return _store
