"""Tests for the generate_image tool."""

from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pydantic import ValidationError

from src.notifications.context import MessageContext
from src.tools.openai_image_tools import (
    GenerateImageParams,
    _get_client,
    generate_image,
)


@pytest.fixture(autouse=True)
def _ensure_scratch(scratch):
    """Auto-use the shared scratch fixture for every test in this file."""


@pytest.fixture(autouse=True)
def _reset_client():
    """Reset the module-level OpenAI client singleton between tests."""
    import src.tools.openai_image_tools as mod

    mod._client = None
    yield
    mod._client = None


# -- Param model validation ---------------------------------------------------


def test_params_defaults() -> None:
    p = GenerateImageParams(prompt="a red circle")
    assert p.prompt == "a red circle"
    assert p.size == "1024x1024"
    assert p.quality == "medium"


def test_params_custom_values() -> None:
    p = GenerateImageParams(prompt="sunset", size="1536x1024", quality="high")
    assert p.size == "1536x1024"
    assert p.quality == "high"


def test_params_requires_prompt() -> None:
    with pytest.raises(ValidationError):
        GenerateImageParams()


# -- Helpers -------------------------------------------------------------------

# Minimal 1x1 white PNG (valid file)
TINY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAAC0lEQVQI12NgAAIABQAB"
    "Nl7BcQAAAABJRU5ErkJggg=="
)
TINY_PNG_B64 = base64.b64encode(TINY_PNG).decode()


def _mock_openai_response(b64_data: str = TINY_PNG_B64) -> MagicMock:
    """Build a mock OpenAI images.generate() response."""
    image_obj = SimpleNamespace(b64_json=b64_data)
    return SimpleNamespace(data=[image_obj])


def _make_msg_context() -> MessageContext:
    return MessageContext(user_id="12345", source_channel="telegram", conversation_id="conv1")


# -- Success case --------------------------------------------------------------


async def test_generate_image_success(scratch) -> None:
    mock_client = AsyncMock()
    mock_client.images.generate = AsyncMock(return_value=_mock_openai_response())

    with patch("src.tools.openai_image_tools._get_client", return_value=mock_client):
        result = await generate_image(prompt="a red circle on white background")

    assert result.success
    assert result.data["generated"] is True
    assert result.data["path"].startswith("generated_")
    assert result.data["path"].endswith(".png")
    assert result.data["dimensions"] == "1024x1024"
    assert result.data["quality"] == "medium"
    assert result.data["prompt"] == "a red circle on white background"
    assert result.data["size_bytes"] == len(TINY_PNG)

    # Verify file was saved to scratch
    assert scratch.exists(result.data["path"])


async def test_generate_image_sends_photo_with_msg_context(scratch) -> None:
    mock_client = AsyncMock()
    mock_client.images.generate = AsyncMock(return_value=_mock_openai_response())
    ctx = _make_msg_context()

    mock_router = AsyncMock()
    mock_router.send_photo = AsyncMock(return_value=True)

    with (
        patch("src.tools.openai_image_tools._get_client", return_value=mock_client),
        patch("src.tools.openai_image_tools.NotificationRouter") as mock_nr_cls,
    ):
        mock_nr_cls.get.return_value = mock_router
        result = await generate_image(prompt="sunset over mountains", msg_context=ctx)

    assert result.success
    mock_router.send_photo.assert_awaited_once()
    call_kwargs = mock_router.send_photo.call_args
    assert call_kwargs.args[0] == "12345"  # user_id
    assert call_kwargs.kwargs["channel"] == "telegram"
    assert call_kwargs.kwargs["caption"] == "sunset over mountains"


async def test_generate_image_no_msg_context_still_saves(scratch) -> None:
    mock_client = AsyncMock()
    mock_client.images.generate = AsyncMock(return_value=_mock_openai_response())

    with patch("src.tools.openai_image_tools._get_client", return_value=mock_client):
        result = await generate_image(prompt="test image")

    assert result.success
    assert scratch.exists(result.data["path"])


async def test_generate_image_custom_size_and_quality(scratch) -> None:
    mock_client = AsyncMock()
    mock_client.images.generate = AsyncMock(return_value=_mock_openai_response())

    with patch("src.tools.openai_image_tools._get_client", return_value=mock_client):
        result = await generate_image(
            prompt="tall portrait", size="1024x1536", quality="high"
        )

    assert result.success
    assert result.data["dimensions"] == "1024x1536"
    assert result.data["quality"] == "high"

    # Verify the API was called with correct params
    mock_client.images.generate.assert_awaited_once_with(
        model="gpt-image-1",
        prompt="tall portrait",
        size="1024x1536",
        quality="high",
        n=1,
    )


async def test_caption_truncated_for_long_prompts(scratch) -> None:
    mock_client = AsyncMock()
    mock_client.images.generate = AsyncMock(return_value=_mock_openai_response())
    ctx = _make_msg_context()
    long_prompt = "x" * 2000

    mock_router = AsyncMock()
    mock_router.send_photo = AsyncMock(return_value=True)

    with (
        patch("src.tools.openai_image_tools._get_client", return_value=mock_client),
        patch("src.tools.openai_image_tools.NotificationRouter") as mock_nr_cls,
    ):
        mock_nr_cls.get.return_value = mock_router
        result = await generate_image(prompt=long_prompt, msg_context=ctx)

    assert result.success
    caption = mock_router.send_photo.call_args.kwargs["caption"]
    assert len(caption) == 1024


# -- Error cases ---------------------------------------------------------------


async def test_invalid_size() -> None:
    result = await generate_image(prompt="test", size="512x512")
    assert not result.success
    assert "Invalid size" in result.error


async def test_invalid_quality() -> None:
    result = await generate_image(prompt="test", quality="ultra")
    assert not result.success
    assert "Invalid quality" in result.error


async def test_api_failure() -> None:
    mock_client = AsyncMock()
    mock_client.images.generate = AsyncMock(side_effect=RuntimeError("API down"))

    with patch("src.tools.openai_image_tools._get_client", return_value=mock_client):
        result = await generate_image(prompt="test")

    assert not result.success
    assert "failed" in result.error.lower()


async def test_no_image_data_returned() -> None:
    response = SimpleNamespace(data=[SimpleNamespace(b64_json=None)])
    mock_client = AsyncMock()
    mock_client.images.generate = AsyncMock(return_value=response)

    with patch("src.tools.openai_image_tools._get_client", return_value=mock_client):
        result = await generate_image(prompt="test")

    assert not result.success
    assert "No image data" in result.error


async def test_scratch_quota_exceeded(scratch, monkeypatch) -> None:
    mock_client = AsyncMock()
    mock_client.images.generate = AsyncMock(return_value=_mock_openai_response())

    # Make scratch.write raise a quota error
    monkeypatch.setattr(
        scratch, "write", MagicMock(side_effect=ValueError("Total scratch space quota exceeded"))
    )

    with patch("src.tools.openai_image_tools._get_client", return_value=mock_client):
        result = await generate_image(prompt="test")

    assert not result.success
    assert "quota" in result.error.lower()


# -- Client singleton ----------------------------------------------------------


def test_get_client_creates_singleton(monkeypatch) -> None:
    monkeypatch.setattr("src.config.settings.openai_api_key", "test-key-123")

    with patch("openai.AsyncOpenAI") as mock_cls:
        mock_cls.return_value = MagicMock()
        client1 = _get_client()
        client2 = _get_client()

    assert client1 is client2
    mock_cls.assert_called_once_with(api_key="test-key-123")
