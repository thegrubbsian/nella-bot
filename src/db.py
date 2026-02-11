"""Async database connection abstraction over libsql.

Provides a thin async wrapper around the synchronous ``libsql`` driver using
``asyncio.to_thread()``.  Connection target is determined by settings:

- **Production**: ``TURSO_DATABASE_URL`` + ``TURSO_AUTH_TOKEN`` → remote Turso
- **Dev/test**: no Turso env vars → local SQLite file via ``database_path``
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import libsql

if TYPE_CHECKING:
    from pathlib import Path

from src.config import settings


class _AsyncCursor:
    """Thin async wrapper around a synchronous libsql cursor."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    async def fetchone(self) -> tuple | None:
        return await asyncio.to_thread(self._cursor.fetchone)

    async def fetchall(self) -> list[tuple]:
        return await asyncio.to_thread(self._cursor.fetchall)

    @property
    def rowcount(self) -> int:
        return self._cursor.rowcount


class _AsyncConnection:
    """Thin async wrapper around a synchronous libsql connection."""

    def __init__(self, conn: Any) -> None:
        self._conn = conn

    async def execute(self, sql: str, params: tuple = ()) -> _AsyncCursor:
        cursor = await asyncio.to_thread(self._conn.execute, sql, params)
        return _AsyncCursor(cursor)

    async def commit(self) -> None:
        await asyncio.to_thread(self._conn.commit)

    async def close(self) -> None:
        await asyncio.to_thread(self._conn.close)


def _open_local(path: str) -> Any:
    """Open a local libsql connection with WAL mode and busy timeout."""
    conn = libsql.connect(path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


async def get_connection(local_path_override: Path | None = None) -> _AsyncConnection:
    """Return an async-wrapped libsql connection.

    If *local_path_override* is given (test isolation), it takes priority.
    Otherwise, ``TURSO_DATABASE_URL`` triggers a remote connection, and
    ``database_path`` falls back to a local file.
    """
    if local_path_override:
        local_path_override.parent.mkdir(parents=True, exist_ok=True)
        conn = await asyncio.to_thread(_open_local, str(local_path_override))
        return _AsyncConnection(conn)

    if settings.turso_database_url:
        conn = await asyncio.to_thread(
            libsql.connect,
            database=settings.turso_database_url,
            auth_token=settings.turso_auth_token,
        )
        return _AsyncConnection(conn)

    # Local file fallback
    settings.database_path.parent.mkdir(parents=True, exist_ok=True)
    conn = await asyncio.to_thread(_open_local, str(settings.database_path))
    return _AsyncConnection(conn)
