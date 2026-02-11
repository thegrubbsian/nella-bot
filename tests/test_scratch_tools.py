"""Tests for scratch space tools (write_file, read_file, list_files, delete_file, download_file)."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from src.tools.scratch_tools import (
    DeleteFileParams,
    DownloadFileParams,
    ListFilesParams,
    ReadFileParams,
    WriteFileParams,
    delete_file,
    download_file,
    list_files,
    read_file,
    write_file,
)


@pytest.fixture(autouse=True)
def _ensure_scratch(scratch):
    """Auto-use the shared scratch fixture for every test in this file."""


# ---------------------------------------------------------------------------
# write_file
# ---------------------------------------------------------------------------


async def test_write_file_success() -> None:
    result = await write_file(path="notes.txt", content="Hello, Nella!")
    assert result.success
    assert result.data["written"] is True
    assert result.data["path"] == "notes.txt"
    assert result.data["size"] > 0


async def test_write_file_traversal_rejected() -> None:
    result = await write_file(path="../../etc/passwd", content="evil")
    assert not result.success
    assert "empty after sanitization" in result.error


# ---------------------------------------------------------------------------
# read_file
# ---------------------------------------------------------------------------


async def test_read_file_success(scratch) -> None:
    scratch.write("hello.txt", "world")
    result = await read_file(path="hello.txt")
    assert result.success
    assert result.data["content"] == "world"
    assert result.data["path"] == "hello.txt"
    assert result.data["size"] == 5


async def test_read_file_not_found() -> None:
    result = await read_file(path="nope.txt")
    assert not result.success
    assert "not found" in result.error.lower()


async def test_read_file_binary_returns_metadata(scratch) -> None:
    scratch.write("photo.jpg", b"\xff\xd8\xff\xe0\x00\x10JFIF")
    result = await read_file(path="photo.jpg")
    assert result.success
    assert result.data["binary"] is True
    assert result.data["mime_type"] == "image/jpeg"
    assert "Reference" in result.data["message"]


# ---------------------------------------------------------------------------
# list_files
# ---------------------------------------------------------------------------


async def test_list_files_empty() -> None:
    result = await list_files()
    assert result.success
    assert result.data["count"] == 0
    assert result.data["files"] == []
    assert result.data["total_size"] == 0


async def test_list_files_with_files(scratch) -> None:
    scratch.write("a.txt", "aaa")
    scratch.write("b.txt", "bbbbb")
    result = await list_files()
    assert result.success
    assert result.data["count"] == 2
    assert result.data["total_size"] == 8


# ---------------------------------------------------------------------------
# delete_file
# ---------------------------------------------------------------------------


async def test_delete_file_success(scratch) -> None:
    scratch.write("bye.txt", "gone")
    result = await delete_file(path="bye.txt")
    assert result.success
    assert result.data["deleted"] is True


async def test_delete_file_not_found() -> None:
    result = await delete_file(path="nope.txt")
    assert not result.success
    assert "not found" in result.error.lower()


# ---------------------------------------------------------------------------
# download_file — helpers
# ---------------------------------------------------------------------------


def _make_mock_httpx(mock_cls):
    """Create a mock httpx module with the real exception classes."""
    return type("MockHttpx", (), {
        "AsyncClient": mock_cls,
        "TimeoutException": httpx.TimeoutException,
        "HTTPStatusError": httpx.HTTPStatusError,
        "HTTPError": httpx.HTTPError,
    })()


def _mock_streaming_client(mock_cls, chunks, status_code=200, headers=None):
    """Wire up an httpx.AsyncClient mock for streaming downloads."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.headers = headers or {}
    mock_response.raise_for_status = MagicMock()
    if status_code >= 400:
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=httpx.Request("GET", "https://example.com/file"),
            response=httpx.Response(status_code),
        )

    async def aiter_bytes(chunk_size=65536):
        for chunk in chunks:
            yield chunk

    mock_response.aiter_bytes = aiter_bytes
    mock_response.__aenter__ = AsyncMock(return_value=mock_response)
    mock_response.__aexit__ = AsyncMock(return_value=False)

    # client.stream() must return the context manager directly (not a coroutine)
    mock_client = MagicMock()
    mock_client.stream.return_value = mock_response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_cls.return_value = mock_client
    return mock_client


# ---------------------------------------------------------------------------
# download_file
# ---------------------------------------------------------------------------


async def test_download_file_success(monkeypatch) -> None:
    import src.tools.scratch_tools as st

    mock_cls = MagicMock()
    monkeypatch.setattr(st, "httpx", _make_mock_httpx(mock_cls))
    _mock_streaming_client(mock_cls, [b"PDF content here"])

    result = await download_file(url="https://example.com/doc.pdf")
    assert result.success
    assert result.data["downloaded"] is True
    assert result.data["path"] == "doc.pdf"
    assert result.data["size"] == len(b"PDF content here")
    assert result.data["source_url"] == "https://example.com/doc.pdf"


async def test_download_file_auto_filename_from_url(monkeypatch) -> None:
    import src.tools.scratch_tools as st

    mock_cls = MagicMock()
    monkeypatch.setattr(st, "httpx", _make_mock_httpx(mock_cls))
    _mock_streaming_client(mock_cls, [b"data"])

    result = await download_file(
        url="https://example.com/path/to/report.csv",
    )
    assert result.success
    assert result.data["path"] == "report.csv"


async def test_download_file_custom_filename(monkeypatch) -> None:
    import src.tools.scratch_tools as st

    mock_cls = MagicMock()
    monkeypatch.setattr(st, "httpx", _make_mock_httpx(mock_cls))
    _mock_streaming_client(mock_cls, [b"data"])

    result = await download_file(
        url="https://example.com/blob", filename="custom.txt",
    )
    assert result.success
    assert result.data["path"] == "custom.txt"


async def test_download_file_http_error(monkeypatch) -> None:
    import src.tools.scratch_tools as st

    mock_cls = MagicMock()
    monkeypatch.setattr(st, "httpx", _make_mock_httpx(mock_cls))
    _mock_streaming_client(mock_cls, [], status_code=404)

    result = await download_file(url="https://example.com/missing.pdf")
    assert not result.success
    assert "404" in result.error


async def test_download_file_timeout(monkeypatch) -> None:
    import src.tools.scratch_tools as st

    mock_cls = MagicMock()
    monkeypatch.setattr(st, "httpx", _make_mock_httpx(mock_cls))

    # Make the stream context manager raise TimeoutException on __aenter__
    mock_client = MagicMock()
    mock_stream_cm = MagicMock()
    mock_stream_cm.__aenter__ = AsyncMock(
        side_effect=httpx.TimeoutException("timed out"),
    )
    mock_stream_cm.__aexit__ = AsyncMock(return_value=False)
    mock_client.stream.return_value = mock_stream_cm
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_cls.return_value = mock_client

    result = await download_file(
        url="https://slow.example.com/big.zip",
    )
    assert not result.success
    assert "Timeout" in result.error


async def test_download_file_too_large_content_length(monkeypatch) -> None:
    import src.tools.scratch_tools as st

    mock_cls = MagicMock()
    monkeypatch.setattr(st, "httpx", _make_mock_httpx(mock_cls))
    _mock_streaming_client(
        mock_cls,
        [b"data"],
        headers={"content-length": str(100 * 1024 * 1024)},
    )

    result = await download_file(url="https://example.com/huge.zip")
    assert not result.success
    assert "too large" in result.error.lower()


async def test_download_file_too_large_mid_stream(monkeypatch) -> None:
    import src.tools.scratch_tools as st

    mock_cls = MagicMock()
    monkeypatch.setattr(st, "httpx", _make_mock_httpx(mock_cls))
    monkeypatch.setattr(st, "MAX_FILE_SIZE", 100)

    _mock_streaming_client(mock_cls, [b"x" * 50, b"x" * 60])

    result = await download_file(url="https://example.com/stream.bin")
    assert not result.success
    assert "too large" in result.error.lower()


# ---------------------------------------------------------------------------
# Params models
# ---------------------------------------------------------------------------


def test_write_file_params_required_fields() -> None:
    p = WriteFileParams(path="test.txt", content="hello")
    assert p.path == "test.txt"
    assert p.content == "hello"


def test_read_file_params_required_fields() -> None:
    p = ReadFileParams(path="test.txt")
    assert p.path == "test.txt"


def test_list_files_params_no_fields() -> None:
    p = ListFilesParams()
    assert p is not None


def test_delete_file_params_required_fields() -> None:
    p = DeleteFileParams(path="test.txt")
    assert p.path == "test.txt"


def test_download_file_params() -> None:
    p = DownloadFileParams(url="https://example.com/file.pdf")
    assert p.url == "https://example.com/file.pdf"
    assert p.filename is None

    p2 = DownloadFileParams(
        url="https://example.com/file.pdf", filename="custom.pdf",
    )
    assert p2.filename == "custom.pdf"
