"""Tests for explicit memory tools."""

from unittest.mock import AsyncMock, patch

from src.memory.models import MemoryEntry
from src.tools.memory_tools import forget_this, recall, remember_this, save_reference


def _mock_store(enabled: bool = True, search_results: list | None = None):
    """Create a mock MemoryStore."""
    store = AsyncMock()
    store.enabled = enabled
    store.search.return_value = search_results or []
    store.add.return_value = {"id": "mem_new"}
    store.delete.return_value = True
    return store


# -- remember_this -----------------------------------------------------------


async def test_remember_this_stores_explicit() -> None:
    mock = _mock_store()
    with patch("src.tools.memory_tools.MemoryStore.get", return_value=mock):
        result = await remember_this(content="My phone is 555-1234", category="contact")

    assert result.success
    assert result.data["remembered"] is True
    mock.add.assert_called_once()
    _, kwargs = mock.add.call_args
    assert kwargs["source"] == "explicit"
    assert kwargs["category"] == "contact"


async def test_remember_this_disabled_store() -> None:
    mock = _mock_store(enabled=False)
    mock.add.return_value = None
    with patch("src.tools.memory_tools.MemoryStore.get", return_value=mock):
        result = await remember_this(content="test")

    assert not result.success
    assert "not configured" in result.error


# -- forget_this -------------------------------------------------------------


async def test_forget_this_deletes_matches() -> None:
    entries = [
        MemoryEntry(id="m1", content="Old phone number", source="explicit", category="contact"),
        MemoryEntry(id="m2", content="Phone preference", source="automatic", category="preference"),
    ]
    mock = _mock_store(search_results=entries)
    with patch("src.tools.memory_tools.MemoryStore.get", return_value=mock):
        result = await forget_this(query="phone number")

    assert result.success
    assert result.data["deleted"] == 2
    assert mock.delete.call_count == 2


async def test_forget_this_no_matches() -> None:
    mock = _mock_store(search_results=[])
    with patch("src.tools.memory_tools.MemoryStore.get", return_value=mock):
        result = await forget_this(query="nonexistent")

    assert result.success
    assert result.data["deleted"] == 0


# -- recall ------------------------------------------------------------------


async def test_recall_returns_formatted_results() -> None:
    entries = [
        MemoryEntry(id="m1", content="Likes coffee", source="automatic", category="preference"),
    ]
    mock = _mock_store(search_results=entries)
    with patch("src.tools.memory_tools.MemoryStore.get", return_value=mock):
        result = await recall(query="coffee")

    assert result.success
    assert result.data["count"] == 1
    assert result.data["results"][0]["content"] == "Likes coffee"
    assert result.data["results"][0]["source"] == "automatic"


async def test_recall_empty() -> None:
    mock = _mock_store(search_results=[])
    with patch("src.tools.memory_tools.MemoryStore.get", return_value=mock):
        result = await recall(query="nothing")

    assert result.success
    assert result.data["count"] == 0


# -- save_reference ----------------------------------------------------------


async def test_save_reference_stores_with_url() -> None:
    mock = _mock_store()
    with patch("src.tools.memory_tools.MemoryStore.get", return_value=mock):
        result = await save_reference(
            url="https://example.com/article",
            title="Great Article",
            summary="About AI things",
        )

    assert result.success
    assert result.data["saved"] is True
    mock.add.assert_called_once()
    content_arg = mock.add.call_args[1]["content"]
    assert "https://example.com/article" in content_arg
    assert "Great Article" in content_arg
    _, kwargs = mock.add.call_args
    assert kwargs["source"] == "explicit"
    assert kwargs["category"] == "reference"
