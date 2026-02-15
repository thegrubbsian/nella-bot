"""Tests for the Telegram upload handler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.bot.handlers import (
    MAX_UPLOAD_SIZE,
    _download_attachment,
    _format_size,
    handle_upload,
)


@pytest.fixture(autouse=True)
def _ensure_scratch(scratch):
    """Auto-use the shared scratch fixture for every test in this file."""


@pytest.fixture
def mock_update():
    """Create a mock Telegram Update with the minimum viable structure."""
    update = MagicMock()
    update.effective_chat.id = 12345
    update.effective_user.id = 12345
    update.message.reply_text = AsyncMock()
    update.message.caption = None
    update.message.photo = None
    update.message.document = None
    return update


@pytest.fixture
def mock_context():
    ctx = MagicMock()
    ctx.bot = MagicMock()
    return ctx


# -- _format_size --------------------------------------------------------------


def test_format_size_bytes() -> None:
    assert _format_size(500) == "500 B"


def test_format_size_kb() -> None:
    assert _format_size(2048) == "2.0 KB"


def test_format_size_mb() -> None:
    assert _format_size(5 * 1024 * 1024) == "5.0 MB"


# -- _download_attachment: photos ----------------------------------------------


async def test_download_photo(scratch) -> None:
    message = MagicMock()
    message.document = None

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"\xff\xd8\xff\xe0test"))

    photo = MagicMock()
    photo.file_size = 1000
    photo.get_file = AsyncMock(return_value=tg_file)

    message.photo = [MagicMock(), photo]  # multiple sizes, last is largest

    result = await _download_attachment(message)
    assert result is not None
    filename, size, mime = result
    assert filename.startswith("photo_")
    assert filename.endswith(".jpg")
    assert size == 8
    assert mime == "image/jpeg"
    # Verify file was written to scratch
    assert scratch.exists(filename)


async def test_download_photo_too_large() -> None:
    message = MagicMock()
    message.document = None

    photo = MagicMock()
    photo.file_size = MAX_UPLOAD_SIZE + 1
    message.photo = [photo]

    with pytest.raises(ValueError, match="too large"):
        await _download_attachment(message)


# -- _download_attachment: documents -------------------------------------------


async def test_download_document(scratch) -> None:
    message = MagicMock()
    message.photo = None

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"PDF content"))

    doc = MagicMock()
    doc.file_size = 500
    doc.file_name = "report.pdf"
    doc.mime_type = "application/pdf"
    doc.get_file = AsyncMock(return_value=tg_file)

    message.document = doc

    result = await _download_attachment(message)
    assert result is not None
    filename, size, mime = result
    assert filename == "report.pdf"
    assert size == 11
    assert mime == "application/pdf"
    assert scratch.exists("report.pdf")


async def test_download_document_no_filename(scratch) -> None:
    message = MagicMock()
    message.photo = None

    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"data"))

    doc = MagicMock()
    doc.file_size = 100
    doc.file_name = None
    doc.mime_type = None
    doc.get_file = AsyncMock(return_value=tg_file)

    message.document = doc

    result = await _download_attachment(message)
    assert result is not None
    filename, size, mime = result
    assert filename.startswith("document_")
    assert mime == "application/octet-stream"


async def test_download_document_too_large() -> None:
    message = MagicMock()
    message.photo = None

    doc = MagicMock()
    doc.file_size = MAX_UPLOAD_SIZE + 1
    doc.file_name = "huge.zip"
    message.document = doc

    with pytest.raises(ValueError, match="too large"):
        await _download_attachment(message)


# -- _download_attachment: no attachment ---------------------------------------


async def test_download_no_attachment() -> None:
    message = MagicMock()
    message.photo = None
    message.document = None

    result = await _download_attachment(message)
    assert result is None


# -- handle_upload integration -------------------------------------------------


async def test_handle_upload_photo(mock_update, mock_context) -> None:
    """Photo upload calls _process_message with descriptive text."""
    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"\xff\xd8\xff\xe0img"))

    photo = MagicMock()
    photo.file_size = 500
    photo.get_file = AsyncMock(return_value=tg_file)
    mock_update.message.photo = [photo]

    with (
        patch("src.bot.handlers.is_allowed", return_value=True),
        patch("src.bot.handlers._process_message", new_callable=AsyncMock) as mock_pm,
    ):
        await handle_upload(mock_update, mock_context)

    mock_pm.assert_called_once()
    user_msg = mock_pm.call_args.args[2]
    assert "[File uploaded:" in user_msg
    assert "image/jpeg" in user_msg


async def test_handle_upload_with_caption(mock_update, mock_context) -> None:
    """Caption is appended to the descriptive text."""
    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"\xff\xd8\xff\xe0img"))

    photo = MagicMock()
    photo.file_size = 500
    photo.get_file = AsyncMock(return_value=tg_file)
    mock_update.message.photo = [photo]
    mock_update.message.caption = "What's in this photo?"

    with (
        patch("src.bot.handlers.is_allowed", return_value=True),
        patch("src.bot.handlers._process_message", new_callable=AsyncMock) as mock_pm,
    ):
        await handle_upload(mock_update, mock_context)

    user_msg = mock_pm.call_args.args[2]
    assert "What's in this photo?" in user_msg


async def test_handle_upload_too_large(mock_update, mock_context) -> None:
    """Oversized file sends an error reply without calling _process_message."""
    photo = MagicMock()
    photo.file_size = MAX_UPLOAD_SIZE + 1
    mock_update.message.photo = [photo]

    with (
        patch("src.bot.handlers.is_allowed", return_value=True),
        patch("src.bot.handlers._process_message", new_callable=AsyncMock) as mock_pm,
    ):
        await handle_upload(mock_update, mock_context)

    mock_pm.assert_not_called()
    mock_update.message.reply_text.assert_called_once()
    assert "too large" in mock_update.message.reply_text.call_args.args[0].lower()


async def test_handle_upload_not_allowed(mock_update, mock_context) -> None:
    """Unauthorized users are silently ignored."""
    with patch("src.bot.handlers.is_allowed", return_value=False):
        await handle_upload(mock_update, mock_context)

    mock_update.message.reply_text.assert_not_called()


async def test_handle_upload_generic_error(mock_update, mock_context) -> None:
    """Generic download failure sends an error reply."""
    photo = MagicMock()
    photo.file_size = 100
    photo.get_file = AsyncMock(side_effect=RuntimeError("Telegram API down"))
    mock_update.message.photo = [photo]

    with (
        patch("src.bot.handlers.is_allowed", return_value=True),
        patch("src.bot.handlers._process_message", new_callable=AsyncMock) as mock_pm,
    ):
        await handle_upload(mock_update, mock_context)

    mock_pm.assert_not_called()
    mock_update.message.reply_text.assert_called_once()
    assert "something went wrong" in mock_update.message.reply_text.call_args.args[0].lower()


async def test_handle_upload_document(mock_update, mock_context) -> None:
    """Document upload preserves original filename."""
    tg_file = AsyncMock()
    tg_file.download_as_bytearray = AsyncMock(return_value=bytearray(b"CSV data here"))

    doc = MagicMock()
    doc.file_size = 100
    doc.file_name = "data.csv"
    doc.mime_type = "text/csv"
    doc.get_file = AsyncMock(return_value=tg_file)
    mock_update.message.document = doc

    with (
        patch("src.bot.handlers.is_allowed", return_value=True),
        patch("src.bot.handlers._process_message", new_callable=AsyncMock) as mock_pm,
    ):
        await handle_upload(mock_update, mock_context)

    mock_pm.assert_called_once()
    user_msg = mock_pm.call_args.args[2]
    assert "data.csv" in user_msg
    assert "text/csv" in user_msg
