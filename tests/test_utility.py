"""Tests for built-in utility tools."""

import pytest

from src.tools.utility import get_current_datetime, save_note, search_notes


@pytest.fixture(autouse=True)
def _temp_db(tmp_path, monkeypatch) -> None:
    """Route the database to a temp file for test isolation."""
    monkeypatch.setattr("src.config.settings.database_path", tmp_path / "test.db")


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
