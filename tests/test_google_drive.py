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

    @pytest.mark.asyncio
    async def test_search_files_with_folder_id(self, drive_mock):
        from src.tools.google_drive import search_files

        drive_mock.files().list().execute.return_value = {
            "files": [_make_file()],
        }

        result = await search_files(query="test", folder_id="folder123")
        assert result.success
        assert result.data["count"] == 1
        # Verify the query includes the parent filter
        call_args = drive_mock.files().list.call_args
        q = call_args.kwargs.get("q") or call_args[1].get("q")
        assert "'folder123' in parents" in q
        assert "fullText contains" in q

    @pytest.mark.asyncio
    async def test_search_files_escapes_quotes(self, drive_mock):
        from src.tools.google_drive import search_files

        drive_mock.files().list().execute.return_value = {"files": []}

        await search_files(query="Dean's Notes")
        call_args = drive_mock.files().list.call_args
        q = call_args.kwargs.get("q") or call_args[1].get("q")
        # The single quote should be escaped
        assert "Dean\\'s Notes" in q


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


class TestListFolder:
    @pytest.mark.asyncio
    async def test_list_folder(self, drive_mock):
        from src.tools.google_drive import list_folder

        drive_mock.files().list().execute.return_value = {
            "files": [
                _make_file("file1", "notes.txt"),
                _make_file(
                    "sub1",
                    "Subfolder",
                    mime_type="application/vnd.google-apps.folder",
                ),
            ],
        }

        result = await list_folder(folder_id="folder123")
        assert result.success
        assert result.data["count"] == 2
        assert result.data["files"][0]["name"] == "notes.txt"
        assert result.data["files"][1]["mime_type"] == "application/vnd.google-apps.folder"

    @pytest.mark.asyncio
    async def test_list_folder_empty(self, drive_mock):
        from src.tools.google_drive import list_folder

        drive_mock.files().list().execute.return_value = {"files": []}

        result = await list_folder(folder_id="empty_folder")
        assert result.success
        assert result.data["count"] == 0


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


class TestDownloadDriveFile:
    @pytest.mark.asyncio
    async def test_download_regular_file(self, drive_mock, scratch):
        from src.tools.google_drive import download_drive_file

        drive_mock.files().get().execute.return_value = {
            **_make_file(name="report.pdf", mime_type="application/pdf"),
        }
        file_data = b"%PDF-1.4 fake content"
        drive_mock.files().get_media().execute.return_value = file_data

        result = await download_drive_file(file_id="file1")
        assert result.success
        assert result.data["downloaded"] is True
        assert result.data["path"] == "report.pdf"
        assert result.data["size"] == len(file_data)
        assert result.data["mime_type"] == "application/pdf"
        assert result.data["drive_file_name"] == "report.pdf"
        assert scratch.read_bytes("report.pdf") == file_data

    @pytest.mark.asyncio
    async def test_download_google_doc_exports_pdf(self, drive_mock, scratch):
        from src.tools.google_drive import download_drive_file

        drive_mock.files().get().execute.return_value = _make_file(
            name="My Document",
            mime_type="application/vnd.google-apps.document",
        )
        exported = b"%PDF-exported"
        drive_mock.files().export().execute.return_value = exported

        result = await download_drive_file(file_id="file1")
        assert result.success
        assert result.data["path"] == "My Document.pdf"
        assert result.data["mime_type"] == "application/pdf"
        assert scratch.read_bytes("My Document.pdf") == exported

    @pytest.mark.asyncio
    async def test_download_with_custom_filename(self, drive_mock, scratch):
        from src.tools.google_drive import download_drive_file

        drive_mock.files().get().execute.return_value = _make_file()
        drive_mock.files().get_media().execute.return_value = b"content"

        result = await download_drive_file(file_id="file1", filename="custom.txt")
        assert result.success
        assert result.data["path"] == "custom.txt"
        assert scratch.read_bytes("custom.txt") == b"content"

    @pytest.mark.asyncio
    async def test_download_spreadsheet_exports_xlsx(self, drive_mock, scratch):
        from src.tools.google_drive import download_drive_file

        drive_mock.files().get().execute.return_value = _make_file(
            name="Budget",
            mime_type="application/vnd.google-apps.spreadsheet",
        )
        exported = b"PK\x03\x04xlsx-data"
        drive_mock.files().export().execute.return_value = exported

        result = await download_drive_file(file_id="file1")
        assert result.success
        assert result.data["path"] == "Budget.xlsx"
        assert "spreadsheetml" in result.data["mime_type"]


class TestUploadToDrive:
    @pytest.mark.asyncio
    async def test_upload_success(self, drive_mock, scratch):
        from src.tools.google_drive import upload_to_drive

        scratch.write("report.pdf", b"%PDF-content")
        drive_mock.files().create().execute.return_value = {
            "id": "new_file_id",
            "name": "report.pdf",
            "webViewLink": "https://drive.google.com/file/d/new_file_id",
        }

        result = await upload_to_drive(path="report.pdf")
        assert result.success
        assert result.data["uploaded"] is True
        assert result.data["file_id"] == "new_file_id"
        assert result.data["name"] == "report.pdf"
        assert result.data["size"] == len(b"%PDF-content")

    @pytest.mark.asyncio
    async def test_upload_file_not_found(self, drive_mock, scratch):
        from src.tools.google_drive import upload_to_drive

        result = await upload_to_drive(path="missing.pdf")
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_upload_with_folder_id(self, drive_mock, scratch):
        from src.tools.google_drive import upload_to_drive

        scratch.write("doc.txt", "hello")
        drive_mock.files().create().execute.return_value = {
            "id": "new_id",
            "name": "doc.txt",
            "webViewLink": "https://drive.google.com/file/d/new_id",
        }

        result = await upload_to_drive(path="doc.txt", folder_id="folder123")
        assert result.success
        # Verify create was called with parents
        call_kwargs = drive_mock.files().create.call_args
        assert call_kwargs is not None
        body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
        assert body["parents"] == ["folder123"]

    @pytest.mark.asyncio
    async def test_upload_with_custom_filename(self, drive_mock, scratch):
        from src.tools.google_drive import upload_to_drive

        scratch.write("local.txt", "data")
        drive_mock.files().create().execute.return_value = {
            "id": "new_id",
            "name": "remote.txt",
            "webViewLink": "https://drive.google.com/file/d/new_id",
        }

        result = await upload_to_drive(path="local.txt", filename="remote.txt")
        assert result.success
        call_kwargs = drive_mock.files().create.call_args
        body = call_kwargs.kwargs.get("body") or call_kwargs[1].get("body")
        assert body["name"] == "remote.txt"
