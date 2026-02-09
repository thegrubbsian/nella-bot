"""Tests for prompt assembly."""

from src.llm.prompt import build_system_prompt


def test_build_system_prompt_returns_content_blocks() -> None:
    """System prompt should return a list of content blocks."""
    blocks = build_system_prompt()
    assert isinstance(blocks, list)
    assert len(blocks) == 1
    assert blocks[0]["type"] == "text"


def test_build_system_prompt_has_cache_control() -> None:
    """System prompt block should have cache_control set."""
    blocks = build_system_prompt()
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_build_system_prompt_contains_soul() -> None:
    """System prompt should include the SOUL.md content."""
    blocks = build_system_prompt()
    text = blocks[0]["text"]
    assert "Nella" in text
    assert "personal AI assistant" in text


def test_build_system_prompt_contains_user_profile() -> None:
    """System prompt should include the USER.md content."""
    blocks = build_system_prompt()
    text = blocks[0]["text"]
    assert "Owner Profile" in text
