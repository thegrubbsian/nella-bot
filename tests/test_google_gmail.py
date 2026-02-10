"""Tests for Gmail tools."""

import base64
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
