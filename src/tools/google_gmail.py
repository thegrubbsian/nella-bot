"""Gmail tools — search, read, send, reply, archive."""

import asyncio
import base64
import logging
from email.mime.text import MIMEText

from bs4 import BeautifulSoup
from pydantic import Field

from src.integrations.google_auth import GoogleAuthManager
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

_CATEGORY = "google_gmail"


def _auth():
    return GoogleAuthManager.get()


def _extract_headers(msg: dict) -> dict[str, str]:
    """Extract headers from a Gmail message into a flat dict."""
    return {
        h["name"]: h["value"]
        for h in msg.get("payload", {}).get("headers", [])
    }


def _extract_body(payload: dict) -> str:
    """Walk MIME parts and extract the best text body."""
    parts = payload.get("parts", [])
    if not parts:
        # Single-part message
        data = payload.get("body", {}).get("data", "")
        if data:
            text = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
            if payload.get("mimeType") == "text/html":
                return BeautifulSoup(text, "html.parser").get_text(separator="\n").strip()
            return text
        return ""

    # Multi-part: prefer text/plain, fall back to text/html
    plain = ""
    html = ""
    for part in parts:
        mime = part.get("mimeType", "")
        if mime == "multipart/alternative":
            # Recurse into nested multipart
            nested = _extract_body(part)
            if nested:
                return nested
        data = part.get("body", {}).get("data", "")
        if not data:
            continue
        decoded = base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
        if mime == "text/plain" and not plain:
            plain = decoded
        elif mime == "text/html" and not html:
            html = decoded

    if plain:
        return plain
    if html:
        return BeautifulSoup(html, "html.parser").get_text(separator="\n").strip()
    return ""


def _extract_attachments(payload: dict) -> list[dict[str, str]]:
    """List attachment names and sizes from message payload."""
    attachments = []
    for part in payload.get("parts", []):
        filename = part.get("filename")
        if filename:
            size = part.get("body", {}).get("size", 0)
            attachments.append({"name": filename, "size": str(size)})
    return attachments


# -- search_emails -----------------------------------------------------------


class SearchEmailsParams(ToolParams):
    query: str = Field(description="Gmail search query (same syntax as Gmail search bar)")
    max_results: int = Field(default=10, description="Maximum number of results")


@registry.tool(
    name="search_emails",
    description=(
        "Search emails using Gmail query syntax. Returns message metadata "
        "(subject, from, date, snippet). Use read_email for full body."
    ),
    category=_CATEGORY,
    params_model=SearchEmailsParams,
)
async def search_emails(query: str, max_results: int = 10) -> ToolResult:
    service = _auth().gmail()

    result = await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .list(userId="me", maxResults=max_results, q=query)
        .execute()
    )

    messages = []
    for msg_ref in result.get("messages", []):
        msg = await asyncio.to_thread(
            lambda mid=msg_ref["id"]: service.users()
            .messages()
            .get(userId="me", id=mid, format="metadata")
            .execute()
        )
        headers = _extract_headers(msg)
        messages.append({
            "id": msg["id"],
            "thread_id": msg.get("threadId", ""),
            "subject": headers.get("Subject", ""),
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
        })

    return ToolResult(data={"emails": messages, "count": len(messages)})


# -- read_email --------------------------------------------------------------


class ReadEmailParams(ToolParams):
    message_id: str = Field(description="Gmail message ID")


@registry.tool(
    name="read_email",
    description="Read the full content of an email by message ID.",
    category=_CATEGORY,
    params_model=ReadEmailParams,
)
async def read_email(message_id: str) -> ToolResult:
    service = _auth().gmail()

    msg = await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )

    headers = _extract_headers(msg)
    payload = msg.get("payload", {})

    return ToolResult(data={
        "id": msg["id"],
        "thread_id": msg.get("threadId", ""),
        "subject": headers.get("Subject", ""),
        "from": headers.get("From", ""),
        "to": headers.get("To", ""),
        "cc": headers.get("Cc", ""),
        "date": headers.get("Date", ""),
        "body": _extract_body(payload),
        "attachments": _extract_attachments(payload),
    })


# -- read_thread -------------------------------------------------------------


class ReadThreadParams(ToolParams):
    thread_id: str = Field(description="Gmail thread ID")


@registry.tool(
    name="read_thread",
    description="Read all messages in an email thread.",
    category=_CATEGORY,
    params_model=ReadThreadParams,
)
async def read_thread(thread_id: str) -> ToolResult:
    service = _auth().gmail()

    thread = await asyncio.to_thread(
        lambda: service.users()
        .threads()
        .get(userId="me", id=thread_id, format="full")
        .execute()
    )

    messages = []
    subject = ""
    for msg in thread.get("messages", []):
        headers = _extract_headers(msg)
        payload = msg.get("payload", {})
        if not subject:
            subject = headers.get("Subject", "")
        messages.append({
            "id": msg["id"],
            "from": headers.get("From", ""),
            "to": headers.get("To", ""),
            "date": headers.get("Date", ""),
            "body": _extract_body(payload),
        })

    return ToolResult(data={
        "thread_id": thread_id,
        "subject": subject,
        "message_count": len(messages),
        "messages": messages,
    })


# -- send_email --------------------------------------------------------------


class SendEmailParams(ToolParams):
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body text")
    cc: str | None = Field(default=None, description="CC recipients (comma-separated)")
    bcc: str | None = Field(default=None, description="BCC recipients (comma-separated)")


@registry.tool(
    name="send_email",
    description="Compose and send an email.",
    category=_CATEGORY,
    params_model=SendEmailParams,
    requires_confirmation=True,
)
async def send_email(
    to: str,
    subject: str,
    body: str,
    cc: str | None = None,
    bcc: str | None = None,
) -> ToolResult:
    service = _auth().gmail()

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject
    if cc:
        message["cc"] = cc
    if bcc:
        message["bcc"] = bcc

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    result = await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute()
    )

    logger.info("Sent email to %s: %s", to, result["id"])
    return ToolResult(data={"id": result["id"], "to": to, "subject": subject})


# -- reply_to_email ----------------------------------------------------------


class ReplyToEmailParams(ToolParams):
    message_id: str = Field(description="ID of the message to reply to")
    body: str = Field(description="Reply body text")


@registry.tool(
    name="reply_to_email",
    description="Reply to an existing email, maintaining the thread.",
    category=_CATEGORY,
    params_model=ReplyToEmailParams,
    requires_confirmation=True,
)
async def reply_to_email(message_id: str, body: str) -> ToolResult:
    service = _auth().gmail()

    # Fetch original for threading headers
    original = await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .get(userId="me", id=message_id, format="metadata")
        .execute()
    )

    headers = _extract_headers(original)
    thread_id = original.get("threadId", "")
    orig_subject = headers.get("Subject", "")
    subject = orig_subject if orig_subject.lower().startswith("re:") else f"Re: {orig_subject}"
    reply_to = headers.get("Reply-To") or headers.get("From", "")

    message = MIMEText(body)
    message["to"] = reply_to
    message["subject"] = subject
    message["In-Reply-To"] = headers.get("Message-ID", "")
    message["References"] = headers.get("Message-ID", "")

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    result = await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .send(userId="me", body={"raw": raw, "threadId": thread_id})
        .execute()
    )

    logger.info("Replied to %s in thread %s", message_id, thread_id)
    return ToolResult(data={"id": result["id"], "thread_id": thread_id, "subject": subject})


# -- archive_email -----------------------------------------------------------


class ArchiveEmailParams(ToolParams):
    message_id: str = Field(description="Gmail message ID to archive")


@registry.tool(
    name="archive_email",
    description="Archive a single email (remove from inbox).",
    category=_CATEGORY,
    params_model=ArchiveEmailParams,
    requires_confirmation=True,
)
async def archive_email(message_id: str) -> ToolResult:
    service = _auth().gmail()

    await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .modify(userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]})
        .execute()
    )

    return ToolResult(data={"archived": True, "message_id": message_id})


# -- archive_emails ----------------------------------------------------------


class ArchiveEmailsParams(ToolParams):
    message_ids: list[str] = Field(description="List of Gmail message IDs to archive")


@registry.tool(
    name="archive_emails",
    description="Archive multiple emails at once (remove from inbox).",
    category=_CATEGORY,
    params_model=ArchiveEmailsParams,
    requires_confirmation=True,
)
async def archive_emails(message_ids: list[str]) -> ToolResult:
    service = _auth().gmail()

    await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .batchModify(
            userId="me",
            body={"ids": message_ids, "removeLabelIds": ["INBOX"]},
        )
        .execute()
    )

    return ToolResult(data={"archived": True, "count": len(message_ids)})
