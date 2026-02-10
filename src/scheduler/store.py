"""TaskStore — aiosqlite CRUD for scheduled tasks."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import aiosqlite

from src.config import settings
from src.scheduler.models import ScheduledTask

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS scheduled_tasks (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    task_type TEXT NOT NULL,
    schedule TEXT NOT NULL,
    action TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    notification_channel TEXT,
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    last_run_at TEXT,
    next_run_at TEXT
)
"""


class TaskStore:
    """Persists scheduled tasks in SQLite.

    Singleton accessed via ``TaskStore.get()``.  Pass an explicit *db_path*
    for test isolation (e.g. ``tmp_path / "test.db"``).
    """

    _instance: TaskStore | None = None

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or settings.database_path
        self._initialised = False

    @classmethod
    def get(cls) -> TaskStore:
        """Return the shared TaskStore instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def _reset(cls) -> None:
        """Reset the singleton (for testing)."""
        cls._instance = None

    # -- Internal helpers ------------------------------------------------------

    async def _connect(self) -> aiosqlite.Connection:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        db = await aiosqlite.connect(str(self._db_path))
        if not self._initialised:
            await db.execute(_CREATE_TABLE)
            await db.commit()
            self._initialised = True
        return db

    # -- CRUD ------------------------------------------------------------------

    async def add_task(self, task: ScheduledTask) -> ScheduledTask:
        """Insert a new task. Returns the same task object."""
        db = await self._connect()
        try:
            await db.execute(
                """
                INSERT INTO scheduled_tasks
                    (id, name, task_type, schedule, action, description,
                     notification_channel, active, created_at, last_run_at, next_run_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                task.to_row(),
            )
            await db.commit()
            logger.info("Added scheduled task: %s (%s)", task.name, task.id)
            return task
        finally:
            await db.close()

    async def get_task(self, task_id: str) -> ScheduledTask | None:
        """Fetch a task by ID, or None if not found."""
        db = await self._connect()
        try:
            cursor = await db.execute(
                "SELECT * FROM scheduled_tasks WHERE id = ?", (task_id,)
            )
            row = await cursor.fetchone()
            return ScheduledTask.from_row(row) if row else None
        finally:
            await db.close()

    async def list_active_tasks(self) -> list[ScheduledTask]:
        """Return all active tasks."""
        db = await self._connect()
        try:
            cursor = await db.execute(
                "SELECT * FROM scheduled_tasks WHERE active = 1 ORDER BY created_at"
            )
            rows = await cursor.fetchall()
            return [ScheduledTask.from_row(row) for row in rows]
        finally:
            await db.close()

    async def deactivate_task(self, task_id: str) -> bool:
        """Mark a task as inactive. Returns True if a row was updated."""
        db = await self._connect()
        try:
            cursor = await db.execute(
                "UPDATE scheduled_tasks SET active = 0 WHERE id = ?", (task_id,)
            )
            await db.commit()
            updated = cursor.rowcount > 0
            if updated:
                logger.info("Deactivated task: %s", task_id)
            return updated
        finally:
            await db.close()

    async def update_last_run(self, task_id: str, timestamp: str | None = None) -> None:
        """Set the last_run_at timestamp (defaults to now UTC)."""
        ts = timestamp or datetime.now(UTC).isoformat()
        db = await self._connect()
        try:
            await db.execute(
                "UPDATE scheduled_tasks SET last_run_at = ? WHERE id = ?",
                (ts, task_id),
            )
            await db.commit()
        finally:
            await db.close()

    async def update_next_run(self, task_id: str, timestamp: str | None) -> None:
        """Set or clear the next_run_at timestamp."""
        db = await self._connect()
        try:
            await db.execute(
                "UPDATE scheduled_tasks SET next_run_at = ? WHERE id = ?",
                (timestamp, task_id),
            )
            await db.commit()
        finally:
            await db.close()
