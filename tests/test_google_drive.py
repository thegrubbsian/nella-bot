"""Tests for Google Drive tools."""

from unittest.mock import MagicMock, patch

import pytest

from src.tools.base import ToolResult


def _mock_auth():
    """Create a mock GoogleAuthManager with a mock Drive service."""
    auth = MagicMock()
    service = MagicMock()
    auth.drive.return_value = service
    return auth, service


def _make_file(
    file_id: str = "file1",
    name: str = "test.txt",
    mime_type: str = "text/plain",
):
    return {
        "id": file_id,
        "name": name,
        "mimeType": mime_type,
        "modifiedTime": "2025-01-15T10:00:00Z",
        "webViewLink": "https://drive.google.com/file/d/file1",
    }


@pytest.fixture
def drive_mock():
    auth, service = _mock_auth()
    with patch("src.tools.google_drive._auth", return_value=auth):
        yield service


class TestSearchFiles:
    @pytest.mark.asyncio
    async def test_search_files(self, drive_mock):
        from src.tools.google_drive import search_files

        drive_mock.files().list().execute.return_value = {
            "files": [_make_file()],
        }

        result = await search_files(query="test")
        assert isinstance(result, ToolResult)
        assert result.success
        assert result.data["count"] == 1
        assert result.data["files"][0]["name"] == "test.txt"

    @pytest.mark.asyncio
    async def test_search_files_empty(self, drive_mock):
        from src.tools.google_drive import search_files

        drive_mock.files().list().execute.return_value = {"files": []}

        result = await search_files(query="nonexistent")
        assert result.success
        assert result.data["count"] == 0


class TestListRecentFiles:
    @pytest.mark.asyncio
    async def test_list_recent(self, drive_mock):
        from src.tools.google_drive import list_recent_files

        drive_mock.files().list().execute.return_value = {
            "files": [_make_file(), _make_file("file2", "doc.md")],
        }

        result = await list_recent_files(max_results=5)
        assert result.success
        assert result.data["count"] == 2


class TestReadFile:
    @pytest.mark.asyncio
    async def test_read_text_file(self, drive_mock):
        from src.tools.google_drive import read_file

        drive_mock.files().get().execute.return_value = {
            **_make_file(),
            "size": "100",
        }
        drive_mock.files().get_media().execute.return_value = b"File contents here"

        result = await read_file(file_id="file1")
        assert result.success
        assert result.data["content"] == "File contents here"

    @pytest.mark.asyncio
    async def test_read_google_doc(self, drive_mock):
        from src.tools.google_drive import read_file

        drive_mock.files().get().execute.return_value = {
            **_make_file(mime_type="application/vnd.google-apps.document"),
            "size": "0",
        }

        with patch(
            "src.tools.google_docs._read_document_content",
            return_value="Doc text",
        ):
            result = await read_file(file_id="file1")

        assert result.success
        assert result.data["content"] == "Doc text"

    @pytest.mark.asyncio
    async def test_read_binary_file(self, drive_mock):
        from src.tools.google_drive import read_file

        drive_mock.files().get().execute.return_value = {
            **_make_file(mime_type="image/png", name="photo.png"),
            "size": "50000",
        }

        result = await read_file(file_id="file1")
        assert result.success
        assert "Binary file" in result.data["content"]

    @pytest.mark.asyncio
    async def test_read_spreadsheet_returns_link(self, drive_mock):
        from src.tools.google_drive import read_file

        drive_mock.files().get().execute.return_value = {
            **_make_file(mime_type="application/vnd.google-apps.spreadsheet"),
            "size": "0",
        }

        result = await read_file(file_id="file1")
        assert result.success
        assert "open in browser" in result.data["content"]


class TestDeleteFile:
    @pytest.mark.asyncio
    async def test_delete_file(self, drive_mock):
        from src.tools.google_drive import delete_file

        drive_mock.files().update().execute.return_value = {}

        result = await delete_file(file_id="file1")
        assert result.success
        assert result.data["trashed"] is True
