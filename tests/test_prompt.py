"""Tests for prompt assembly."""

from unittest.mock import AsyncMock, patch

from src.llm.prompt import _format_memories, build_system_prompt
from src.memory.models import MemoryEntry


async def test_build_system_prompt_returns_content_blocks() -> None:
    blocks = await build_system_prompt()
    assert isinstance(blocks, list)
    assert len(blocks) >= 1
    assert blocks[0]["type"] == "text"


async def test_build_system_prompt_has_cache_control() -> None:
    blocks = await build_system_prompt()
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


async def test_build_system_prompt_contains_soul() -> None:
    blocks = await build_system_prompt()
    text = blocks[0]["text"]
    assert "Nella" in text
    assert "personal AI assistant" in text


async def test_build_system_prompt_contains_user_profile() -> None:
    blocks = await build_system_prompt()
    text = blocks[0]["text"]
    assert "Owner Profile" in text


async def test_build_system_prompt_with_memories() -> None:
    """When memories exist, they should appear as a second content block."""
    mock_store = AsyncMock()
    mock_store.enabled = True
    mock_store.search.return_value = [
        MemoryEntry(
            id="1",
            content="User likes coffee",
            source="automatic",
            category="fact",
        ),
    ]

    with patch("src.memory.store.MemoryStore.get", return_value=mock_store):
        blocks = await build_system_prompt(user_message="coffee")

    assert len(blocks) == 2
    assert "User likes coffee" in blocks[1]["text"]
    assert "[automatic/fact]" in blocks[1]["text"]


async def test_build_system_prompt_no_memories_single_block() -> None:
    """Without memories, only one content block should be returned."""
    mock_store = AsyncMock()
    mock_store.enabled = True
    mock_store.search.return_value = []

    with patch("src.memory.store.MemoryStore.get", return_value=mock_store):
        blocks = await build_system_prompt(user_message="test")

    assert len(blocks) == 1


def test_format_memories_empty() -> None:
    assert _format_memories([]) == ""


def test_format_memories_with_entries() -> None:
    entries = [
        MemoryEntry(id="1", content="Likes coffee", source="automatic", category="preference"),
        MemoryEntry(id="2", content="Phone: 555-1234", source="explicit", category="contact"),
    ]
    result = _format_memories(entries)
    assert "[automatic/preference]" in result
    assert "[explicit/contact]" in result
    assert "Likes coffee" in result
    assert "555-1234" in result
