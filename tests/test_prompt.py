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


async def test_build_system_prompt_contains_tools_guidance() -> None:
    """TOOLS.md content should be included in the static block."""
    blocks = await build_system_prompt()
    text = blocks[0]["text"]
    assert "Tool Usage Guidance" in text


async def test_build_system_prompt_contains_current_time() -> None:
    """The second block should contain the current time and timezone."""
    blocks = await build_system_prompt()
    time_block = blocks[1]["text"]
    assert "Current time:" in time_block
    assert "America/Chicago" in time_block
    # Should NOT have cache_control (changes every call)
    assert "cache_control" not in blocks[1]


async def test_build_system_prompt_with_memories() -> None:
    """When memories exist, they should appear as the third content block."""
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

    assert len(blocks) == 3
    assert "User likes coffee" in blocks[2]["text"]
    assert "[automatic/fact]" in blocks[2]["text"]


async def test_build_system_prompt_no_memories_has_time_block() -> None:
    """Without memories, static + time blocks should be returned."""
    mock_store = AsyncMock()
    mock_store.enabled = True
    mock_store.search.return_value = []

    with patch("src.memory.store.MemoryStore.get", return_value=mock_store):
        blocks = await build_system_prompt(user_message="test")

    assert len(blocks) == 2


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


# -- Notion prompt injection ------------------------------------------------


async def test_notion_config_loaded_when_api_key_set(tmp_path) -> None:
    """NOTION.md content should appear in the static block when notion_api_key is set."""
    config_file = tmp_path / "NOTION.md"
    config_file.write_text("# Notion\n\nMy databases config here.")

    with (
        patch("src.llm.prompt.CONFIG_DIR", tmp_path),
        patch("src.llm.prompt.settings") as mock_settings,
    ):
        mock_settings.get_google_accounts.return_value = []
        mock_settings.nella_source_repo = ""
        mock_settings.scheduler_timezone = "America/Chicago"
        mock_settings.notion_api_key = "ntn_test_key"

        blocks = await build_system_prompt()

    text = blocks[0]["text"]
    assert "My databases config here" in text


async def test_notion_fallback_when_no_config_file(tmp_path) -> None:
    """Fallback text when notion_api_key is set but NOTION.md doesn't exist."""
    with (
        patch("src.llm.prompt.CONFIG_DIR", tmp_path),
        patch("src.llm.prompt.settings") as mock_settings,
    ):
        mock_settings.get_google_accounts.return_value = []
        mock_settings.nella_source_repo = ""
        mock_settings.scheduler_timezone = "America/Chicago"
        mock_settings.notion_api_key = "ntn_test_key"

        blocks = await build_system_prompt()

    text = blocks[0]["text"]
    assert "Notion is connected" in text
    assert "notion_list_databases" in text


async def test_notion_not_injected_when_no_api_key(tmp_path) -> None:
    """Nothing Notion-related when notion_api_key is empty."""
    config_file = tmp_path / "NOTION.md"
    config_file.write_text("# Notion\n\nShould not appear.")

    with (
        patch("src.llm.prompt.CONFIG_DIR", tmp_path),
        patch("src.llm.prompt.settings") as mock_settings,
    ):
        mock_settings.get_google_accounts.return_value = []
        mock_settings.nella_source_repo = ""
        mock_settings.scheduler_timezone = "America/Chicago"
        mock_settings.notion_api_key = ""

        blocks = await build_system_prompt()

    text = blocks[0]["text"]
    assert "Should not appear" not in text
