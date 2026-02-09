"""Built-in utility tools."""

import logging
from datetime import UTC, datetime

import aiosqlite
from pydantic import Field

from src.config import settings
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# get_current_datetime
# ---------------------------------------------------------------------------


@registry.tool(
    name="get_current_datetime",
    description="Get the current date, time, and day of the week in UTC.",
    category="utility",
)
async def get_current_datetime() -> ToolResult:
    now = datetime.now(UTC)
    return ToolResult(data={
        "datetime": now.isoformat(),
        "date": now.strftime("%Y-%m-%d"),
        "time": now.strftime("%H:%M:%S"),
        "day_of_week": now.strftime("%A"),
        "timezone": "UTC",
    })


# ---------------------------------------------------------------------------
# save_note / search_notes
# ---------------------------------------------------------------------------


async def _ensure_notes_table() -> aiosqlite.Connection:
    """Open the DB and ensure the notes table exists."""
    db_path = settings.database_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = await aiosqlite.connect(str(db_path))
    db.row_factory = aiosqlite.Row
    await db.execute("""
        CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)
    await db.commit()
    return db


class SaveNoteParams(ToolParams):
    title: str = Field(description="Short title for the note")
    content: str = Field(description="The note body text")


@registry.tool(
    name="save_note",
    description="Save a note to the local database for future reference.",
    category="utility",
    params_model=SaveNoteParams,
)
async def save_note(title: str, content: str) -> ToolResult:
    db = await _ensure_notes_table()
    try:
        await db.execute(
            "INSERT INTO notes (title, content, created_at) VALUES (?, ?, ?)",
            (title, content, datetime.now(UTC).isoformat()),
        )
        await db.commit()
        logger.info("Saved note: %s", title)
        return ToolResult(data={"saved": True, "title": title})
    finally:
        await db.close()


class SearchNotesParams(ToolParams):
    query: str = Field(description="Text to search for in note titles and content")


@registry.tool(
    name="search_notes",
    description="Search saved notes by title or content.",
    category="utility",
    params_model=SearchNotesParams,
)
async def search_notes(query: str) -> ToolResult:
    db = await _ensure_notes_table()
    try:
        pattern = f"%{query}%"
        cursor = await db.execute(
            """
            SELECT id, title, content, created_at FROM notes
            WHERE title LIKE ? OR content LIKE ?
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (pattern, pattern),
        )
        rows = await cursor.fetchall()
        notes = [
            {
                "id": row["id"],
                "title": row["title"],
                "content": row["content"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]
        return ToolResult(data={"notes": notes, "count": len(notes)})
    finally:
        await db.close()
