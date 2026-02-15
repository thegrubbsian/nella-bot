"""Tests for the analyze_image tool."""

from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from src.tools.image_tools import (
    AnalyzeImageParams,
    analyze_image,
)


@pytest.fixture(autouse=True)
def _ensure_scratch(scratch):
    """Auto-use the shared scratch fixture for every test in this file."""


# -- Param model validation ---------------------------------------------------


def test_params_defaults() -> None:
    p = AnalyzeImageParams(path="photo.jpg")
    assert p.path == "photo.jpg"
    assert "Describe" in p.prompt


def test_params_custom_prompt() -> None:
    p = AnalyzeImageParams(path="chart.png", prompt="What data is shown?")
    assert p.prompt == "What data is shown?"


def test_params_requires_path() -> None:
    with pytest.raises(ValidationError):
        AnalyzeImageParams()


# -- Success case --------------------------------------------------------------


TINY_JPEG = (
    b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
    b"\xff\xd9"
)


async def test_analyze_image_success(scratch) -> None:
    scratch.write("photo.jpg", TINY_JPEG)

    with patch("src.llm.client.complete_text", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = "A small test image."
        result = await analyze_image(path="photo.jpg")

    assert result.success
    assert result.data["path"] == "photo.jpg"
    assert result.data["analysis"] == "A small test image."

    # Verify the vision message structure
    call_args = mock_ct.call_args
    messages = call_args.args[0]
    assert len(messages) == 1
    content = messages[0]["content"]
    assert content[0]["type"] == "image"
    assert content[0]["source"]["media_type"] == "image/jpeg"
    assert content[1]["type"] == "text"


async def test_analyze_image_custom_prompt(scratch) -> None:
    # .png MIME type matters — write a valid PNG header
    png_header = b"\x89PNG\r\n\x1a\n" + b"\x00" * 20
    scratch.write("chart.png", png_header)

    with patch("src.llm.client.complete_text", new_callable=AsyncMock) as mock_ct:
        mock_ct.return_value = "A bar chart showing revenue."
        result = await analyze_image(path="chart.png", prompt="What data is shown?")

    assert result.success
    assert result.data["analysis"] == "A bar chart showing revenue."

    # Verify custom prompt was forwarded
    messages = mock_ct.call_args.args[0]
    assert messages[0]["content"][1]["text"] == "What data is shown?"


# -- Error cases ---------------------------------------------------------------


async def test_file_not_found() -> None:
    result = await analyze_image(path="nonexistent.jpg")
    assert not result.success
    assert "not found" in result.error.lower()


async def test_unsupported_type(scratch) -> None:
    scratch.write("notes.txt", "hello world")
    result = await analyze_image(path="notes.txt")
    assert not result.success
    assert "Unsupported" in result.error


async def test_unsupported_type_pdf(scratch) -> None:
    scratch.write("doc.pdf", b"%PDF-1.4 test content")
    result = await analyze_image(path="doc.pdf")
    assert not result.success
    assert "Unsupported" in result.error


async def test_image_too_large(scratch, monkeypatch) -> None:
    monkeypatch.setattr("src.tools.image_tools.MAX_IMAGE_SIZE", 10)
    scratch.write("big.jpg", TINY_JPEG)
    result = await analyze_image(path="big.jpg")
    assert not result.success
    assert "too large" in result.error.lower()


async def test_api_failure(scratch) -> None:
    scratch.write("photo.jpg", TINY_JPEG)

    with patch("src.llm.client.complete_text", new_callable=AsyncMock) as mock_ct:
        mock_ct.side_effect = RuntimeError("API down")
        result = await analyze_image(path="photo.jpg")

    assert not result.success
    assert "failed" in result.error.lower()


async def test_path_traversal(scratch) -> None:
    result = await analyze_image(path="../../etc/passwd")
    assert not result.success
