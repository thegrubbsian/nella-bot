"""Tests for prompt assembly."""

import pytest

from src.llm.prompt import build_system_prompt


@pytest.mark.asyncio
async def test_build_system_prompt_contains_soul() -> None:
    """System prompt should include the SOUL.md content."""
    prompt = await build_system_prompt()
    assert "Nella" in prompt
    assert "personal AI assistant" in prompt


@pytest.mark.asyncio
async def test_build_system_prompt_contains_sections() -> None:
    """System prompt should contain all config sections."""
    prompt = await build_system_prompt()
    assert "Owner Profile" in prompt
    assert "Persistent Memory" in prompt
    assert "Available Tools" in prompt
