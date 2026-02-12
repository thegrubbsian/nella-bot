"""PeopleStore — CRUD for people_notes via libsql."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from src.db import get_connection

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS people_notes (
    google_resource_id TEXT PRIMARY KEY,
    display_name       TEXT NOT NULL,
    notes              TEXT NOT NULL DEFAULT '',
    created_at         TEXT NOT NULL,
    updated_at         TEXT NOT NULL
)
"""


class PeopleStore:
    """Persists per-person notes in SQLite / Turso.

    Singleton accessed via ``PeopleStore.get()``.  Pass an explicit *db_path*
    for test isolation (e.g. ``tmp_path / "test.db"``).
    """

    _instance: PeopleStore | None = None

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        self._initialised = False

    @classmethod
    def get(cls) -> PeopleStore:
        """Return the shared PeopleStore instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    # -- Internal helpers ------------------------------------------------------

    async def _connect(self):  # noqa: ANN201
        db = await get_connection(local_path_override=self._db_path)
        if not self._initialised:
            await db.execute(_CREATE_TABLE)
            await db.commit()
            self._initialised = True
        return db

    # -- CRUD ------------------------------------------------------------------

    async def upsert(
        self, google_resource_id: str, display_name: str, notes: str
    ) -> dict:
        """Insert or update a people_notes record. Returns the row as a dict."""
        now = datetime.now(UTC).isoformat()
        db = await self._connect()
        try:
            # Check if record exists to preserve created_at
            cursor = await db.execute(
                "SELECT created_at FROM people_notes WHERE google_resource_id = ?",
                (google_resource_id,),
            )
            existing = await cursor.fetchone()
            created_at = existing[0] if existing else now

            await db.execute(
                """
                INSERT OR REPLACE INTO people_notes
                    (google_resource_id, display_name, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (google_resource_id, display_name, notes, created_at, now),
            )
            await db.commit()
            return {
                "google_resource_id": google_resource_id,
                "display_name": display_name,
                "notes": notes,
                "created_at": created_at,
                "updated_at": now,
            }
        finally:
            await db.close()

    async def get_by_id(self, google_resource_id: str) -> dict | None:
        """Fetch one row by resource ID, or None if not found."""
        db = await self._connect()
        try:
            cursor = await db.execute(
                "SELECT * FROM people_notes WHERE google_resource_id = ?",
                (google_resource_id,),
            )
            row = await cursor.fetchone()
            if not row:
                return None
            return {
                "google_resource_id": row[0],
                "display_name": row[1],
                "notes": row[2],
                "created_at": row[3],
                "updated_at": row[4],
            }
        finally:
            await db.close()

    async def search(self, query: str) -> list[dict]:
        """Search by display_name or notes content (case-insensitive LIKE)."""
        db = await self._connect()
        try:
            pattern = f"%{query}%"
            cursor = await db.execute(
                """
                SELECT * FROM people_notes
                WHERE display_name LIKE ? OR notes LIKE ?
                ORDER BY updated_at DESC
                LIMIT 20
                """,
                (pattern, pattern),
            )
            rows = await cursor.fetchall()
            return [
                {
                    "google_resource_id": row[0],
                    "display_name": row[1],
                    "notes": row[2],
                    "created_at": row[3],
                    "updated_at": row[4],
                }
                for row in rows
            ]
        finally:
            await db.close()

    async def delete(self, google_resource_id: str) -> bool:
        """Delete a record. Returns True if a row was removed."""
        db = await self._connect()
        try:
            cursor = await db.execute(
                "DELETE FROM people_notes WHERE google_resource_id = ?",
                (google_resource_id,),
            )
            await db.commit()
            return cursor.rowcount > 0
        finally:
            await db.close()
