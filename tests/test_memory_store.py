"""Tests for the shared memory store."""

from unittest.mock import AsyncMock

import pytest

from src.memory.models import MemoryEntry
from src.memory.store import MemoryStore


@pytest.fixture
def store() -> MemoryStore:
    """Create a MemoryStore with a mocked Mem0 client."""
    s = MemoryStore.__new__(MemoryStore)
    s._client = AsyncMock()
    s._enabled = True
    s._user_id = "owner"
    return s


@pytest.fixture
def disabled_store() -> MemoryStore:
    """Create a disabled MemoryStore."""
    s = MemoryStore.__new__(MemoryStore)
    s._client = None
    s._enabled = False
    s._user_id = "owner"
    return s


# -- add ---------------------------------------------------------------------


async def test_add_calls_client_with_metadata(store: MemoryStore) -> None:
    store._client.add.return_value = [{"id": "mem_1"}]

    await store.add(content="Likes coffee", source="automatic", category="preference")

    store._client.add.assert_called_once()
    _, kwargs = store._client.add.call_args
    assert kwargs["user_id"] == "owner"
    assert kwargs["metadata"]["source"] == "automatic"
    assert kwargs["metadata"]["category"] == "preference"
    assert "created_at" in kwargs["metadata"]


async def test_add_extra_metadata(store: MemoryStore) -> None:
    store._client.add.return_value = [{"id": "mem_1"}]

    await store.add(
        content="test",
        source="explicit",
        category="fact",
        metadata={"conversation_id": "conv_123"},
    )

    _, kwargs = store._client.add.call_args
    assert kwargs["metadata"]["conversation_id"] == "conv_123"


async def test_add_disabled_returns_none(disabled_store: MemoryStore) -> None:
    result = await disabled_store.add("test", "explicit", "fact")
    assert result is None


# -- search ------------------------------------------------------------------


async def test_search_returns_memory_entries(store: MemoryStore) -> None:
    store._client.search.return_value = {
        "results": [
            {
                "id": "mem_1",
                "memory": "Likes coffee",
                "score": 0.9,
                "metadata": {
                    "source": "automatic",
                    "category": "preference",
                    "created_at": "2024-01-01T00:00:00",
                },
            },
            {
                "id": "mem_2",
                "memory": "Birthday is Jan 15",
                "score": 0.7,
                "metadata": {
                    "source": "explicit",
                    "category": "fact",
                    "created_at": "2024-01-02T00:00:00",
                },
            },
        ]
    }

    results = await store.search("coffee")
    assert len(results) == 2
    assert isinstance(results[0], MemoryEntry)
    assert results[0].content == "Likes coffee"
    assert results[0].source == "automatic"
    assert results[1].source == "explicit"


async def test_search_disabled_returns_empty(disabled_store: MemoryStore) -> None:
    results = await disabled_store.search("anything")
    assert results == []


# -- delete ------------------------------------------------------------------


async def test_delete_calls_client(store: MemoryStore) -> None:
    result = await store.delete("mem_1")
    store._client.delete.assert_called_once_with("mem_1")
    assert result is True


async def test_delete_disabled_returns_false(disabled_store: MemoryStore) -> None:
    result = await disabled_store.delete("mem_1")
    assert result is False


# -- normalize ---------------------------------------------------------------


def test_normalize_hosted_format() -> None:
    raw = {
        "results": [
            {
                "id": "mem_1",
                "memory": "Test memory",
                "score": 0.85,
                "metadata": {"source": "automatic", "category": "fact"},
            }
        ]
    }
    entries = MemoryStore._normalize(raw)
    assert len(entries) == 1
    assert entries[0].content == "Test memory"
    assert entries[0].source == "automatic"


def test_normalize_list_format() -> None:
    """Mem0 local mode returns a plain list."""
    raw = [
        {
            "id": "mem_1",
            "memory": "Test memory",
            "score": 0.85,
            "metadata": {"source": "explicit", "category": "contact"},
        }
    ]
    entries = MemoryStore._normalize(raw)
    assert len(entries) == 1
    assert entries[0].source == "explicit"


def test_normalize_empty() -> None:
    assert MemoryStore._normalize({}) == []
    assert MemoryStore._normalize([]) == []
    assert MemoryStore._normalize(None) == []


def test_normalize_missing_metadata() -> None:
    raw = {"results": [{"id": "1", "memory": "test", "metadata": None}]}
    entries = MemoryStore._normalize(raw)
    assert entries[0].source == "unknown"
    assert entries[0].category == "general"
