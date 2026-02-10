"""Tests for Google Docs tools."""

from unittest.mock import MagicMock, patch

import pytest

from src.tools.base import ToolResult


def _mock_auth():
    """Create a mock GoogleAuthManager with a mock Docs service."""
    auth = MagicMock()
    service = MagicMock()
    auth.docs.return_value = service
    return auth, service


def _make_doc(
    doc_id: str = "doc1",
    title: str = "Test Doc",
    body_text: str = "Hello world",
):
    """Build a minimal Docs API document dict."""
    return {
        "documentId": doc_id,
        "title": title,
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {"textRun": {"content": body_text}},
                        ],
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    },
                    "endIndex": len(body_text) + 1,
                },
            ],
        },
    }


def _make_doc_with_headings():
    """Build a document with headings, lists, and paragraphs."""
    return {
        "documentId": "doc2",
        "title": "Structured Doc",
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [{"textRun": {"content": "Main Title\n"}}],
                        "paragraphStyle": {"namedStyleType": "HEADING_1"},
                    },
                    "endIndex": 12,
                },
                {
                    "paragraph": {
                        "elements": [{"textRun": {"content": "Section\n"}}],
                        "paragraphStyle": {"namedStyleType": "HEADING_2"},
                    },
                    "endIndex": 20,
                },
                {
                    "paragraph": {
                        "elements": [{"textRun": {"content": "Item one\n"}}],
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                        "bullet": {"listId": "list1"},
                    },
                    "endIndex": 30,
                },
                {
                    "paragraph": {
                        "elements": [{"textRun": {"content": "Regular paragraph\n"}}],
                        "paragraphStyle": {"namedStyleType": "NORMAL_TEXT"},
                    },
                    "endIndex": 49,
                },
            ],
        },
    }


@pytest.fixture
def docs_mock():
    auth, service = _mock_auth()
    with patch("src.tools.google_docs._auth", return_value=auth):
        yield service


class TestReadDocument:
    @pytest.mark.asyncio
    async def test_read_document(self, docs_mock):
        from src.tools.google_docs import read_document

        docs_mock.documents().get().execute.return_value = _make_doc()

        result = await read_document(document_id="doc1")
        assert isinstance(result, ToolResult)
        assert result.success
        assert result.data["title"] == "Test Doc"
        assert "Hello world" in result.data["content"]
        assert result.data["document_id"] == "doc1"

    @pytest.mark.asyncio
    async def test_read_document_with_structure(self, docs_mock):
        from src.tools.google_docs import read_document

        docs_mock.documents().get().execute.return_value = _make_doc_with_headings()

        result = await read_document(document_id="doc2")
        assert result.success
        content = result.data["content"]
        assert "# Main Title" in content
        assert "## Section" in content
        assert "- Item one" in content
        assert "Regular paragraph" in content


class TestCreateDocument:
    @pytest.mark.asyncio
    async def test_create_empty_document(self, docs_mock):
        from src.tools.google_docs import create_document

        docs_mock.documents().create().execute.return_value = {
            "documentId": "new_doc",
        }

        result = await create_document(title="New Doc")
        assert result.success
        assert result.data["document_id"] == "new_doc"
        assert result.data["title"] == "New Doc"
        # No batchUpdate should be called for empty content
        docs_mock.documents().batchUpdate.assert_not_called()

    @pytest.mark.asyncio
    async def test_create_document_with_content(self, docs_mock):
        from src.tools.google_docs import create_document

        docs_mock.documents().create().execute.return_value = {
            "documentId": "new_doc",
        }
        docs_mock.documents().batchUpdate().execute.return_value = {}

        result = await create_document(title="New Doc", content="Initial content")
        assert result.success
        assert result.data["document_id"] == "new_doc"


class TestUpdateDocument:
    @pytest.mark.asyncio
    async def test_update_document(self, docs_mock):
        from src.tools.google_docs import update_document

        docs_mock.documents().get().execute.return_value = _make_doc()
        docs_mock.documents().batchUpdate().execute.return_value = {}

        result = await update_document(document_id="doc1", content="New content")
        assert result.success
        assert result.data["document_id"] == "doc1"


class TestAppendToDocument:
    @pytest.mark.asyncio
    async def test_append_to_document(self, docs_mock):
        from src.tools.google_docs import append_to_document

        docs_mock.documents().get().execute.return_value = _make_doc()
        docs_mock.documents().batchUpdate().execute.return_value = {}

        result = await append_to_document(document_id="doc1", content="\nMore text")
        assert result.success
        assert result.data["document_id"] == "doc1"
