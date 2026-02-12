"""Tests for built-in utility tools."""

import pytest

from src.tools.utility import delete_note, get_current_datetime, save_note, search_notes


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch) -> None:
    """Route the database to a temp file for test isolation."""
    monkeypatch.setattr("src.config.settings.database_path", tmp_path / "test.db")
    monkeypatch.setattr("src.config.settings.turso_database_url", "")


async def test_get_current_datetime() -> None:
    result = await get_current_datetime()
    assert result.success
    assert "datetime" in result.data
    assert "date" in result.data
    assert "time" in result.data
    assert "day_of_week" in result.data
    assert result.data["timezone"] == "UTC"


async def test_save_note() -> None:
    result = await save_note(title="Test Note", content="Hello world")
    assert result.success
    assert result.data["saved"] is True
    assert result.data["title"] == "Test Note"


async def test_search_notes_finds_match() -> None:
    await save_note(title="Groceries", content="Buy milk and eggs")
    await save_note(title="Work", content="Finish the report")

    result = await search_notes(query="milk")
    assert result.success
    assert result.data["count"] == 1
    assert result.data["notes"][0]["title"] == "Groceries"


async def test_search_notes_no_results() -> None:
    result = await search_notes(query="nonexistent_xyz")
    assert result.success
    assert result.data["count"] == 0
    assert result.data["notes"] == []


async def test_search_notes_matches_title() -> None:
    await save_note(title="Important Meeting", content="Discuss budget")

    result = await search_notes(query="Important")
    assert result.success
    assert result.data["count"] == 1


async def test_save_and_search_multiple() -> None:
    await save_note(title="Note 1", content="Python is great")
    await save_note(title="Note 2", content="Python is awesome")
    await save_note(title="Note 3", content="Rust is fast")

    result = await search_notes(query="Python")
    assert result.success
    assert result.data["count"] == 2


async def test_delete_note() -> None:
    await save_note(title="To Delete", content="Goodbye")
    found = await search_notes(query="To Delete")
    note_id = found.data["notes"][0]["id"]

    result = await delete_note(note_id=note_id)
    assert result.success
    assert result.data["deleted"] is True
    assert result.data["title"] == "To Delete"

    # Verify it's gone
    after = await search_notes(query="To Delete")
    assert after.data["count"] == 0


async def test_delete_note_not_found() -> None:
    result = await delete_note(note_id=99999)
    assert not result.success
    assert "not found" in result.error
