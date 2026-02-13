"""Built-in utility tools."""

import logging
from datetime import UTC, datetime

from pydantic import Field

from src.db import get_connection
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
    return ToolResult(
        data={
            "datetime": now.isoformat(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "day_of_week": now.strftime("%A"),
            "timezone": "UTC",
        }
    )


# ---------------------------------------------------------------------------
# save_note / search_notes / delete_note
# ---------------------------------------------------------------------------


async def _ensure_notes_table():
    """Open the DB and ensure the notes table exists."""
    db = await get_connection()
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
        # libsql returns tuples — use positional indexing matching SELECT order
        notes = [
            {
                "id": row[0],
                "title": row[1],
                "content": row[2],
                "created_at": row[3],
            }
            for row in rows
        ]
        return ToolResult(data={"notes": notes, "count": len(notes)})
    finally:
        await db.close()


class DeleteNoteParams(ToolParams):
    note_id: int = Field(description="ID of the note to delete (from search_notes results)")


@registry.tool(
    name="delete_note",
    description="Delete a saved note by its ID.",
    category="utility",
    params_model=DeleteNoteParams,
    requires_confirmation=True,
)
async def delete_note(note_id: int) -> ToolResult:
    db = await _ensure_notes_table()
    try:
        cursor = await db.execute("SELECT id, title FROM notes WHERE id = ?", (note_id,))
        row = await cursor.fetchone()
        if row is None:
            return ToolResult(error=f"Note with id {note_id} not found.")
        await db.execute("DELETE FROM notes WHERE id = ?", (note_id,))
        await db.commit()
        logger.info("Deleted note %d: %s", row[0], row[1])
        return ToolResult(data={"deleted": True, "id": row[0], "title": row[1]})
    finally:
        await db.close()
