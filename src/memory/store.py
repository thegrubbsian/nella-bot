"""Conversation storage using SQLite."""

import logging
from datetime import UTC, datetime

import aiosqlite

from src.config import settings
from src.memory.models import Message

logger = logging.getLogger(__name__)

_DB_INITIALIZED = False


async def _get_db() -> aiosqlite.Connection:
    """Get a database connection, initializing the schema if needed."""
    global _DB_INITIALIZED  # noqa: PLW0603

    db_path = settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)

    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row

    if not _DB_INITIALIZED:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                chat_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE INDEX IF NOT EXISTS idx_messages_chat_id
            ON messages (chat_id, created_at)
        """)
        await db.commit()
        _DB_INITIALIZED = True

    return db


async def save_message(chat_id: str, role: str, content: str) -> None:
    """Persist a message to the database."""
    db = await _get_db()
    try:
        await db.execute(
            "INSERT INTO messages (chat_id, role, content, created_at) VALUES (?, ?, ?, ?)",
            (chat_id, role, content, datetime.now(UTC).isoformat()),
        )
        await db.commit()
    finally:
        await db.close()


async def get_recent_messages(chat_id: str, limit: int = 50) -> list[Message]:
    """Retrieve the most recent messages for a chat."""
    db = await _get_db()
    try:
        cursor = await db.execute(
            """
            SELECT role, content, created_at FROM messages
            WHERE chat_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (chat_id, limit),
        )
        rows = await cursor.fetchall()
        return [
            Message(role=row["role"], content=row["content"], created_at=row["created_at"])
            for row in reversed(rows)
        ]
    finally:
        await db.close()
