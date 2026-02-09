"""Tests for tool dispatch."""

import json

import pytest

from src.tools.dispatch import dispatch_tool_call


@pytest.mark.asyncio
async def test_get_current_time() -> None:
    """get_current_time should return an ISO timestamp."""
    result = json.loads(await dispatch_tool_call("get_current_time", {}))
    assert "time" in result
    assert "T" in result["time"]


@pytest.mark.asyncio
async def test_unknown_tool() -> None:
    """Unknown tools should return an error."""
    result = json.loads(await dispatch_tool_call("nonexistent_tool", {}))
    assert "error" in result
    assert "Unknown tool" in result["error"]
