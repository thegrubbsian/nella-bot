"""Tests for Gmail tools."""

import base64
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from unittest.mock import MagicMock, patch

import pytest

from src.tools.base import ToolResult


def _mock_auth():
    """Create a mock GoogleAuthManager with a mock Gmail service."""
    auth = MagicMock()
    service = MagicMock()
    auth.gmail.return_value = service
    return auth, service


def _make_message(msg_id: str = "msg1", subject: str = "Test", sender: str = "a@b.com"):
    """Build a minimal Gmail API message dict."""
    return {
        "id": msg_id,
        "threadId": "thread1",
        "snippet": "preview text",
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": sender},
                {"name": "To", "value": "me@test.com"},
                {"name": "Date", "value": "Mon, 1 Jan 2025 00:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {
                "data": base64.urlsafe_b64encode(b"Hello world").decode(),
            },
            "parts": [],
        },
    }


@pytest.fixture
def gmail_mock():
    auth, service = _mock_auth()
    with patch("src.tools.google_gmail._auth", return_value=auth):
        yield service


class TestSearchEmails:
    @pytest.mark.asyncio
    async def test_search_returns_results(self, gmail_mock):
        from src.tools.google_gmail import search_emails

        gmail_mock.users().messages().list().execute.return_value = {
            "messages": [{"id": "msg1"}],
        }
        gmail_mock.users().messages().get().execute.return_value = _make_message()

        result = await search_emails(query="test")
        assert isinstance(result, ToolResult)
        assert result.success
        assert result.data["count"] == 1
        assert result.data["emails"][0]["subject"] == "Test"

    @pytest.mark.asyncio
    async def test_search_empty_results(self, gmail_mock):
        from src.tools.google_gmail import search_emails

        gmail_mock.users().messages().list().execute.return_value = {}

        result = await search_emails(query="nonexistent")
        assert result.success
        assert result.data["count"] == 0


class TestReadEmail:
    @pytest.mark.asyncio
    async def test_read_email(self, gmail_mock):
        from src.tools.google_gmail import read_email

        gmail_mock.users().messages().get().execute.return_value = _make_message()

        result = await read_email(message_id="msg1")
        assert result.success
        assert result.data["subject"] == "Test"
        assert result.data["body"] == "Hello world"

    @pytest.mark.asyncio
    async def test_read_email_html_body(self, gmail_mock):
        from src.tools.google_gmail import read_email

        msg = _make_message()
        msg["payload"]["mimeType"] = "text/html"
        html = "<p>Hello <b>world</b></p>"
        msg["payload"]["body"]["data"] = base64.urlsafe_b64encode(html.encode()).decode()
        gmail_mock.users().messages().get().execute.return_value = msg

        result = await read_email(message_id="msg1")
        assert result.success
        assert "Hello" in result.data["body"]
        assert "<p>" not in result.data["body"]


class TestReadThread:
    @pytest.mark.asyncio
    async def test_read_thread(self, gmail_mock):
        from src.tools.google_gmail import read_thread

        gmail_mock.users().threads().get().execute.return_value = {
            "messages": [_make_message("msg1"), _make_message("msg2")],
        }

        result = await read_thread(thread_id="thread1")
        assert result.success
        assert result.data["message_count"] == 2
        assert result.data["subject"] == "Test"


class TestSendEmail:
    @pytest.mark.asyncio
    async def test_send_email(self, gmail_mock):
        from src.tools.google_gmail import send_email

        gmail_mock.users().messages().send().execute.return_value = {"id": "sent1"}

        result = await send_email(to="test@test.com", subject="Hi", body="Hello")
        assert result.success
        assert result.data["id"] == "sent1"
        assert result.data["to"] == "test@test.com"


class TestReplyToEmail:
    @pytest.mark.asyncio
    async def test_reply(self, gmail_mock):
        from src.tools.google_gmail import reply_to_email

        original = _make_message()
        original["payload"]["headers"].append(
            {"name": "Message-ID", "value": "<original@test.com>"}
        )
        gmail_mock.users().messages().get().execute.return_value = original
        gmail_mock.users().messages().send().execute.return_value = {"id": "reply1"}

        result = await reply_to_email(message_id="msg1", body="Thanks!")
        assert result.success
        assert result.data["id"] == "reply1"
        assert result.data["subject"].startswith("Re:")


class TestArchiveEmail:
    @pytest.mark.asyncio
    async def test_archive_single(self, gmail_mock):
        from src.tools.google_gmail import archive_email

        gmail_mock.users().messages().modify().execute.return_value = {}

        result = await archive_email(message_id="msg1")
        assert result.success
        assert result.data["archived"] is True

    @pytest.mark.asyncio
    async def test_archive_batch(self, gmail_mock):
        from src.tools.google_gmail import archive_emails

        gmail_mock.users().messages().batchModify().execute.return_value = {}

        result = await archive_emails(message_ids=["msg1", "msg2"])
        assert result.success
        assert result.data["count"] == 2


class TestBuildMessage:
    def test_plain_text_returns_mimetext(self):
        from src.tools.google_gmail import _build_message

        msg = _build_message("Hello")
        assert isinstance(msg, MIMEText)

    def test_with_attachments_returns_multipart(self, scratch):
        from src.tools.google_gmail import _build_message

        scratch.write("doc.pdf", b"%PDF-fake-content")
        msg = _build_message("See attached", ["doc.pdf"])
        assert isinstance(msg, MIMEMultipart)
        parts = msg.get_payload()
        assert len(parts) == 2  # text body + 1 attachment
        assert parts[0].get_content_type() == "text/plain"
        assert parts[1].get_filename() == "doc.pdf"

    def test_multiple_attachments(self, scratch):
        from src.tools.google_gmail import _build_message

        scratch.write("a.txt", "aaa")
        scratch.write("b.txt", "bbb")
        msg = _build_message("body", ["a.txt", "b.txt"])
        parts = msg.get_payload()
        assert len(parts) == 3  # body + 2 attachments

    def test_missing_file_raises(self):
        from src.tools.google_gmail import _build_message

        with pytest.raises(FileNotFoundError):
            _build_message("body", ["nonexistent.pdf"])

    def test_size_limit_raises(self, scratch):
        from src.tools.google_gmail import GMAIL_ATTACHMENT_LIMIT, _build_message

        # Write a file just over the limit
        scratch.write("big.bin", b"x" * (GMAIL_ATTACHMENT_LIMIT + 1))
        with pytest.raises(ValueError, match="too large"):
            _build_message("body", ["big.bin"])


class TestSendEmailWithAttachments:
    @pytest.mark.asyncio
    async def test_send_with_attachment(self, gmail_mock, scratch):
        from src.tools.google_gmail import send_email

        scratch.write("report.pdf", b"%PDF-content")
        gmail_mock.users().messages().send().execute.return_value = {"id": "sent1"}

        result = await send_email(
            to="bob@test.com",
            subject="Report",
            body="Here's the report",
            attachments=["report.pdf"],
        )
        assert result.success
        assert result.data["id"] == "sent1"

    @pytest.mark.asyncio
    async def test_send_missing_attachment_returns_error(self, gmail_mock):
        from src.tools.google_gmail import send_email

        result = await send_email(
            to="bob@test.com",
            subject="Report",
            body="Here's the report",
            attachments=["missing.pdf"],
        )
        assert not result.success
        assert "not found" in result.error.lower()


class TestReplyWithAttachments:
    @pytest.mark.asyncio
    async def test_reply_with_attachment(self, gmail_mock, scratch):
        from src.tools.google_gmail import reply_to_email

        scratch.write("data.csv", "col1,col2\na,b")
        original = _make_message()
        original["payload"]["headers"].append({"name": "Message-ID", "value": "<orig@test.com>"})
        gmail_mock.users().messages().get().execute.return_value = original
        gmail_mock.users().messages().send().execute.return_value = {"id": "reply1"}

        result = await reply_to_email(
            message_id="msg1", body="Here's the data", attachments=["data.csv"]
        )
        assert result.success
        assert result.data["id"] == "reply1"


class TestTrashEmail:
    @pytest.mark.asyncio
    async def test_trash_email(self, gmail_mock):
        from src.tools.google_gmail import trash_email

        gmail_mock.users().messages().trash().execute.return_value = {}

        result = await trash_email(message_id="msg1")
        assert result.success
        assert result.data["trashed"] is True
        assert result.data["message_id"] == "msg1"


class TestMarkAsRead:
    @pytest.mark.asyncio
    async def test_mark_as_read(self, gmail_mock):
        from src.tools.google_gmail import mark_as_read

        gmail_mock.users().messages().modify().execute.return_value = {}

        result = await mark_as_read(message_id="msg1")
        assert result.success
        assert result.data["marked_read"] is True
        assert result.data["message_id"] == "msg1"


class TestMarkAsUnread:
    @pytest.mark.asyncio
    async def test_mark_as_unread(self, gmail_mock):
        from src.tools.google_gmail import mark_as_unread

        gmail_mock.users().messages().modify().execute.return_value = {}

        result = await mark_as_unread(message_id="msg1")
        assert result.success
        assert result.data["marked_unread"] is True
        assert result.data["message_id"] == "msg1"


class TestStarEmail:
    @pytest.mark.asyncio
    async def test_star_email(self, gmail_mock):
        from src.tools.google_gmail import star_email

        gmail_mock.users().messages().modify().execute.return_value = {}

        result = await star_email(message_id="msg1")
        assert result.success
        assert result.data["starred"] is True
        assert result.data["message_id"] == "msg1"


class TestUnstarEmail:
    @pytest.mark.asyncio
    async def test_unstar_email(self, gmail_mock):
        from src.tools.google_gmail import unstar_email

        gmail_mock.users().messages().modify().execute.return_value = {}

        result = await unstar_email(message_id="msg1")
        assert result.success
        assert result.data["unstarred"] is True
        assert result.data["message_id"] == "msg1"


class TestAddLabel:
    @pytest.mark.asyncio
    async def test_add_system_label(self, gmail_mock):
        from src.tools.google_gmail import add_label

        gmail_mock.users().messages().modify().execute.return_value = {}

        result = await add_label(message_id="msg1", label_name="STARRED")
        assert result.success
        assert result.data["label_added"] is True
        assert result.data["label"] == "STARRED"

    @pytest.mark.asyncio
    async def test_add_user_label(self, gmail_mock):
        from src.tools.google_gmail import add_label

        gmail_mock.users().labels().list().execute.return_value = {
            "labels": [
                {"id": "Label_1", "name": "Projects"},
                {"id": "Label_2", "name": "Receipts"},
            ]
        }
        gmail_mock.users().messages().modify().execute.return_value = {}

        result = await add_label(message_id="msg1", label_name="Projects")
        assert result.success
        assert result.data["label_added"] is True

    @pytest.mark.asyncio
    async def test_add_label_not_found(self, gmail_mock):
        from src.tools.google_gmail import add_label

        gmail_mock.users().labels().list().execute.return_value = {"labels": []}

        result = await add_label(message_id="msg1", label_name="Nonexistent")
        assert not result.success
        assert "not found" in result.error.lower()


class TestRemoveLabel:
    @pytest.mark.asyncio
    async def test_remove_system_label(self, gmail_mock):
        from src.tools.google_gmail import remove_label

        gmail_mock.users().messages().modify().execute.return_value = {}

        result = await remove_label(message_id="msg1", label_name="STARRED")
        assert result.success
        assert result.data["label_removed"] is True

    @pytest.mark.asyncio
    async def test_remove_user_label(self, gmail_mock):
        from src.tools.google_gmail import remove_label

        gmail_mock.users().labels().list().execute.return_value = {
            "labels": [{"id": "Label_5", "name": "Archive/2024"}]
        }
        gmail_mock.users().messages().modify().execute.return_value = {}

        result = await remove_label(message_id="msg1", label_name="Archive/2024")
        assert result.success
        assert result.data["label_removed"] is True

    @pytest.mark.asyncio
    async def test_remove_label_not_found(self, gmail_mock):
        from src.tools.google_gmail import remove_label

        gmail_mock.users().labels().list().execute.return_value = {"labels": []}

        result = await remove_label(message_id="msg1", label_name="Nonexistent")
        assert not result.success
        assert "not found" in result.error.lower()


class TestResolveLabelId:
    @pytest.mark.asyncio
    async def test_system_label_no_api_call(self, gmail_mock):
        from src.tools.google_gmail import _resolve_label_id

        service = gmail_mock
        result = await _resolve_label_id(service, "INBOX")
        assert result == "INBOX"
        # labels().list() should NOT have been called for system labels
        service.users().labels().list.assert_not_called()

    @pytest.mark.asyncio
    async def test_case_insensitive_user_label(self, gmail_mock):
        from src.tools.google_gmail import _resolve_label_id

        gmail_mock.users().labels().list().execute.return_value = {
            "labels": [{"id": "Label_1", "name": "Work"}]
        }
        result = await _resolve_label_id(gmail_mock, "work")
        assert result == "Label_1"

    @pytest.mark.asyncio
    async def test_returns_none_when_not_found(self, gmail_mock):
        from src.tools.google_gmail import _resolve_label_id

        gmail_mock.users().labels().list().execute.return_value = {"labels": []}
        result = await _resolve_label_id(gmail_mock, "missing")
        assert result is None


class TestCreateLabel:
    @pytest.mark.asyncio
    async def test_create_label(self, gmail_mock):
        from src.tools.google_gmail import create_label

        gmail_mock.users().labels().create().execute.return_value = {
            "id": "Label_99",
            "name": "Projects/Alpha",
        }

        result = await create_label(label_name="Projects/Alpha")
        assert result.success
        assert result.data["created"] is True
        assert result.data["label_id"] == "Label_99"
        assert result.data["label_name"] == "Projects/Alpha"


class TestDeleteLabel:
    @pytest.mark.asyncio
    async def test_delete_user_label(self, gmail_mock):
        from src.tools.google_gmail import delete_label

        gmail_mock.users().labels().list().execute.return_value = {
            "labels": [{"id": "Label_5", "name": "Old Stuff"}]
        }
        gmail_mock.users().labels().delete().execute.return_value = {}

        result = await delete_label(label_name="Old Stuff")
        assert result.success
        assert result.data["deleted"] is True

    @pytest.mark.asyncio
    async def test_delete_system_label_rejected(self, gmail_mock):
        from src.tools.google_gmail import delete_label

        result = await delete_label(label_name="INBOX")
        assert not result.success
        assert "system label" in result.error.lower()

    @pytest.mark.asyncio
    async def test_delete_label_not_found(self, gmail_mock):
        from src.tools.google_gmail import delete_label

        gmail_mock.users().labels().list().execute.return_value = {"labels": []}

        result = await delete_label(label_name="Nonexistent")
        assert not result.success
        assert "not found" in result.error.lower()


class TestListLabels:
    @pytest.mark.asyncio
    async def test_list_labels(self, gmail_mock):
        from src.tools.google_gmail import list_labels

        gmail_mock.users().labels().list().execute.return_value = {
            "labels": [
                {"id": "INBOX", "name": "INBOX", "type": "system"},
                {"id": "Label_1", "name": "Work", "type": "user"},
                {"id": "STARRED", "name": "STARRED", "type": "system"},
            ]
        }

        result = await list_labels()
        assert result.success
        assert result.data["count"] == 3
        # User labels sort first
        assert result.data["labels"][0]["name"] == "Work"

    @pytest.mark.asyncio
    async def test_list_labels_empty(self, gmail_mock):
        from src.tools.google_gmail import list_labels

        gmail_mock.users().labels().list().execute.return_value = {"labels": []}

        result = await list_labels()
        assert result.success
        assert result.data["count"] == 0


class TestExtractAttachments:
    def test_includes_attachment_id(self):
        from src.tools.google_gmail import _extract_attachments

        payload = {
            "parts": [
                {
                    "filename": "invoice.pdf",
                    "body": {"size": 12345, "attachmentId": "ATT_ID_123"},
                },
                {
                    "filename": "",
                    "body": {"size": 0},
                },
            ]
        }
        result = _extract_attachments(payload)
        assert len(result) == 1
        assert result[0]["name"] == "invoice.pdf"
        assert result[0]["size"] == "12345"
        assert result[0]["attachment_id"] == "ATT_ID_123"


class TestDownloadEmailAttachment:
    @pytest.mark.asyncio
    async def test_download_success(self, gmail_mock, scratch):
        from src.tools.google_gmail import download_email_attachment

        file_data = b"PDF binary content here"
        encoded = base64.urlsafe_b64encode(file_data).decode()
        gmail_mock.users().messages().attachments().get().execute.return_value = {
            "data": encoded,
        }

        result = await download_email_attachment(
            message_id="msg1",
            attachment_id="att123",
            filename="invoice.pdf",
        )
        assert result.success
        assert result.data["downloaded"] is True
        assert result.data["path"] == "invoice.pdf"
        assert result.data["size"] == len(file_data)
        assert result.data["mime_type"] == "application/pdf"

        # Verify file actually landed in scratch
        assert scratch.read_bytes("invoice.pdf") == file_data
