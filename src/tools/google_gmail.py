"""Gmail tools — search, read, send, reply, archive, trash, read/unread, star, labels, download."""

from __future__ import annotations

import asyncio
import base64
import logging
import mimetypes
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from bs4 import BeautifulSoup
from pydantic import Field

from src.integrations.google_auth import GoogleAuthManager
from src.scratch import ScratchSpace
from src.tools.base import GoogleToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

_CATEGORY = "google_gmail"

GMAIL_ATTACHMENT_LIMIT = 25 * 1024 * 1024  # 25 MB per email


def _auth(account: str | None = None) -> GoogleAuthManager:
    return GoogleAuthManager.get(account)


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
    """List attachment names, sizes, and attachment IDs from message payload."""
    attachments = []
    for part in payload.get("parts", []):
        filename = part.get("filename")
        if filename:
            body = part.get("body", {})
            size = body.get("size", 0)
            attachment_id = body.get("attachmentId", "")
            attachments.append({
                "name": filename,
                "size": str(size),
                "attachment_id": attachment_id,
            })
    return attachments


def _build_message(body: str, attachments: list[str] | None = None) -> MIMEText | MIMEMultipart:
    """Build a MIME message, optionally with scratch-space file attachments.

    Raises ``FileNotFoundError`` if a scratch file doesn't exist, or
    ``ValueError`` if the total attachment size exceeds Gmail's 25 MB limit.
    """
    if not attachments:
        return MIMEText(body)

    scratch = ScratchSpace.get()
    msg = MIMEMultipart()
    msg.attach(MIMEText(body))

    total_size = 0
    for path in attachments:
        data = scratch.read_bytes(path)
        total_size += len(data)
        if total_size > GMAIL_ATTACHMENT_LIMIT:
            msg = f"Attachments too large: {total_size} bytes (max {GMAIL_ATTACHMENT_LIMIT})"
            raise ValueError(msg)

        mime_type, _ = mimetypes.guess_type(path)
        maintype, subtype = (mime_type or "application/octet-stream").split("/", 1)
        part = MIMEBase(maintype, subtype)
        part.set_payload(data)
        encoders.encode_base64(part)
        # Use just the filename, not the full scratch path
        filename = path.rsplit("/", 1)[-1] if "/" in path else path
        part.add_header("Content-Disposition", "attachment", filename=filename)
        msg.attach(part)

    return msg


# -- search_emails -----------------------------------------------------------


class SearchEmailsParams(GoogleToolParams):
    query: str = Field(description="Gmail search query (same syntax as Gmail search bar)")
    max_results: int = Field(default=10, description="Maximum number of results per page")
    page_token: str | None = Field(
        default=None,
        description="Token for fetching the next page of results (from a previous search)",
    )


@registry.tool(
    name="search_emails",
    description=(
        "Search emails using Gmail query syntax. Returns message metadata "
        "(subject, from, date, snippet). Use read_email for full body. "
        "Supports pagination — use the returned next_page_token to fetch more results."
    ),
    category=_CATEGORY,
    params_model=SearchEmailsParams,
)
async def search_emails(
    query: str,
    max_results: int = 10,
    page_token: str | None = None,
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).gmail()

    list_kwargs: dict[str, Any] = {
        "userId": "me",
        "maxResults": max_results,
        "q": query,
    }
    if page_token:
        list_kwargs["pageToken"] = page_token

    result = await asyncio.to_thread(
        lambda: service.users().messages().list(**list_kwargs).execute()
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

    data: dict[str, Any] = {
        "emails": messages,
        "count": len(messages),
        "estimated_total": result.get("resultSizeEstimate", 0),
    }
    next_token = result.get("nextPageToken")
    if next_token:
        data["next_page_token"] = next_token

    return ToolResult(data=data)


# -- read_email --------------------------------------------------------------


class ReadEmailParams(GoogleToolParams):
    message_id: str = Field(description="Gmail message ID")


@registry.tool(
    name="read_email",
    description="Read the full content of an email by message ID.",
    category=_CATEGORY,
    params_model=ReadEmailParams,
)
async def read_email(message_id: str, account: str | None = None) -> ToolResult:
    service = _auth(account).gmail()

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


class ReadThreadParams(GoogleToolParams):
    thread_id: str = Field(description="Gmail thread ID")


@registry.tool(
    name="read_thread",
    description="Read all messages in an email thread.",
    category=_CATEGORY,
    params_model=ReadThreadParams,
)
async def read_thread(thread_id: str, account: str | None = None) -> ToolResult:
    service = _auth(account).gmail()

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


class SendEmailParams(GoogleToolParams):
    to: str = Field(description="Recipient email address")
    subject: str = Field(description="Email subject line")
    body: str = Field(description="Email body text")
    cc: str | None = Field(default=None, description="CC recipients (comma-separated)")
    bcc: str | None = Field(default=None, description="BCC recipients (comma-separated)")
    attachments: list[str] | None = Field(
        default=None,
        description="Scratch-space file paths to attach (e.g. ['report.pdf'])",
    )


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
    attachments: list[str] | None = None,
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).gmail()

    try:
        message = _build_message(body, attachments)
    except (FileNotFoundError, ValueError) as exc:
        return ToolResult(error=str(exc))

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


class ReplyToEmailParams(GoogleToolParams):
    message_id: str = Field(description="ID of the message to reply to")
    body: str = Field(description="Reply body text")
    attachments: list[str] | None = Field(
        default=None,
        description="Scratch-space file paths to attach (e.g. ['report.pdf'])",
    )


@registry.tool(
    name="reply_to_email",
    description="Reply to an existing email, maintaining the thread.",
    category=_CATEGORY,
    params_model=ReplyToEmailParams,
    requires_confirmation=True,
)
async def reply_to_email(
    message_id: str,
    body: str,
    attachments: list[str] | None = None,
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).gmail()

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

    try:
        message = _build_message(body, attachments)
    except (FileNotFoundError, ValueError) as exc:
        return ToolResult(error=str(exc))

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


class ArchiveEmailParams(GoogleToolParams):
    message_id: str = Field(description="Gmail message ID to archive")


@registry.tool(
    name="archive_email",
    description="Archive a single email (remove from inbox).",
    category=_CATEGORY,
    params_model=ArchiveEmailParams,
    requires_confirmation=True,
)
async def archive_email(message_id: str, account: str | None = None) -> ToolResult:
    service = _auth(account).gmail()

    await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .modify(userId="me", id=message_id, body={"removeLabelIds": ["INBOX"]})
        .execute()
    )

    return ToolResult(data={"archived": True, "message_id": message_id})


# -- archive_emails ----------------------------------------------------------


class ArchiveEmailsParams(GoogleToolParams):
    message_ids: list[str] = Field(description="List of Gmail message IDs to archive")


@registry.tool(
    name="archive_emails",
    description="Archive multiple emails at once (remove from inbox).",
    category=_CATEGORY,
    params_model=ArchiveEmailsParams,
    requires_confirmation=True,
)
async def archive_emails(message_ids: list[str], account: str | None = None) -> ToolResult:
    service = _auth(account).gmail()

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


# -- trash_email -------------------------------------------------------------


class TrashEmailParams(GoogleToolParams):
    message_id: str = Field(description="Gmail message ID to trash/delete")


@registry.tool(
    name="trash_email",
    description=(
        "Move an email to the trash (delete it). "
        "Trashed emails are permanently deleted after 30 days."
    ),
    category=_CATEGORY,
    params_model=TrashEmailParams,
    requires_confirmation=True,
)
async def trash_email(message_id: str, account: str | None = None) -> ToolResult:
    service = _auth(account).gmail()

    await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .trash(userId="me", id=message_id)
        .execute()
    )

    return ToolResult(data={"trashed": True, "message_id": message_id})


# -- mark_as_read ------------------------------------------------------------


class MarkAsReadParams(GoogleToolParams):
    message_id: str = Field(description="Gmail message ID to mark as read")


@registry.tool(
    name="mark_as_read",
    description="Mark an email as read.",
    category=_CATEGORY,
    params_model=MarkAsReadParams,
)
async def mark_as_read(message_id: str, account: str | None = None) -> ToolResult:
    service = _auth(account).gmail()

    await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .modify(userId="me", id=message_id, body={"removeLabelIds": ["UNREAD"]})
        .execute()
    )

    return ToolResult(data={"marked_read": True, "message_id": message_id})


# -- mark_as_unread ----------------------------------------------------------


class MarkAsUnreadParams(GoogleToolParams):
    message_id: str = Field(description="Gmail message ID to mark as unread")


@registry.tool(
    name="mark_as_unread",
    description="Mark an email as unread.",
    category=_CATEGORY,
    params_model=MarkAsUnreadParams,
)
async def mark_as_unread(message_id: str, account: str | None = None) -> ToolResult:
    service = _auth(account).gmail()

    await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .modify(userId="me", id=message_id, body={"addLabelIds": ["UNREAD"]})
        .execute()
    )

    return ToolResult(data={"marked_unread": True, "message_id": message_id})


# -- star_email --------------------------------------------------------------


class StarEmailParams(GoogleToolParams):
    message_id: str = Field(description="Gmail message ID to star")


@registry.tool(
    name="star_email",
    description="Star an email.",
    category=_CATEGORY,
    params_model=StarEmailParams,
)
async def star_email(message_id: str, account: str | None = None) -> ToolResult:
    service = _auth(account).gmail()

    await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .modify(userId="me", id=message_id, body={"addLabelIds": ["STARRED"]})
        .execute()
    )

    return ToolResult(data={"starred": True, "message_id": message_id})


# -- unstar_email ------------------------------------------------------------


class UnstarEmailParams(GoogleToolParams):
    message_id: str = Field(description="Gmail message ID to unstar")


@registry.tool(
    name="unstar_email",
    description="Remove the star from an email.",
    category=_CATEGORY,
    params_model=UnstarEmailParams,
)
async def unstar_email(message_id: str, account: str | None = None) -> ToolResult:
    service = _auth(account).gmail()

    await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .modify(userId="me", id=message_id, body={"removeLabelIds": ["STARRED"]})
        .execute()
    )

    return ToolResult(data={"unstarred": True, "message_id": message_id})


# -- add_label ---------------------------------------------------------------


class AddLabelParams(GoogleToolParams):
    message_id: str = Field(description="Gmail message ID")
    label_name: str = Field(
        description="Label name to add (e.g. 'STARRED', 'IMPORTANT', or a user-created label name)"
    )


async def _resolve_label_id(service: Any, label_name: str) -> str | None:
    """Resolve a label name to its Gmail label ID.

    System labels (INBOX, UNREAD, STARRED, etc.) use their name as the ID.
    User-created labels require a lookup via labels.list().
    """
    # System labels use their name as the ID
    system_labels = {
        "INBOX", "UNREAD", "STARRED", "IMPORTANT", "SPAM", "TRASH",
        "SENT", "DRAFT", "CATEGORY_PERSONAL", "CATEGORY_SOCIAL",
        "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS",
    }
    upper = label_name.upper()
    if upper in system_labels:
        return upper

    # Look up user-created labels
    result = await asyncio.to_thread(
        lambda: service.users().labels().list(userId="me").execute()
    )
    for label in result.get("labels", []):
        if label["name"].lower() == label_name.lower():
            return label["id"]
    return None


@registry.tool(
    name="add_label",
    description=(
        "Add a label to an email. Works with system labels "
        "(STARRED, IMPORTANT) and user-created labels."
    ),
    category=_CATEGORY,
    params_model=AddLabelParams,
)
async def add_label(
    message_id: str, label_name: str, account: str | None = None
) -> ToolResult:
    service = _auth(account).gmail()

    label_id = await _resolve_label_id(service, label_name)
    if not label_id:
        return ToolResult(error=f"Label not found: {label_name}")

    await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .modify(userId="me", id=message_id, body={"addLabelIds": [label_id]})
        .execute()
    )

    return ToolResult(data={"label_added": True, "message_id": message_id, "label": label_name})


# -- remove_label ------------------------------------------------------------


class RemoveLabelParams(GoogleToolParams):
    message_id: str = Field(description="Gmail message ID")
    label_name: str = Field(
        description=(
            "Label name to remove (e.g. 'STARRED', 'IMPORTANT', "
            "or a user-created label name)"
        ),
    )


@registry.tool(
    name="remove_label",
    description=(
        "Remove a label from an email. Works with system labels "
        "(STARRED, IMPORTANT) and user-created labels."
    ),
    category=_CATEGORY,
    params_model=RemoveLabelParams,
)
async def remove_label(
    message_id: str, label_name: str, account: str | None = None
) -> ToolResult:
    service = _auth(account).gmail()

    label_id = await _resolve_label_id(service, label_name)
    if not label_id:
        return ToolResult(error=f"Label not found: {label_name}")

    await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .modify(userId="me", id=message_id, body={"removeLabelIds": [label_id]})
        .execute()
    )

    return ToolResult(data={"label_removed": True, "message_id": message_id, "label": label_name})


# -- create_label ------------------------------------------------------------


class CreateLabelParams(GoogleToolParams):
    label_name: str = Field(description="Name for the new label (e.g. 'Projects/Alpha')")


@registry.tool(
    name="create_label",
    description=(
        "Create a new Gmail label. Supports nested labels "
        "using '/' separator (e.g. 'Work/Projects')."
    ),
    category=_CATEGORY,
    params_model=CreateLabelParams,
)
async def create_label(
    label_name: str, account: str | None = None
) -> ToolResult:
    service = _auth(account).gmail()

    label_body = {
        "name": label_name,
        "labelListVisibility": "labelShow",
        "messageListVisibility": "show",
    }

    result = await asyncio.to_thread(
        lambda: service.users()
        .labels()
        .create(userId="me", body=label_body)
        .execute()
    )

    return ToolResult(data={
        "created": True,
        "label_id": result["id"],
        "label_name": result["name"],
    })


# -- delete_label ------------------------------------------------------------


class DeleteLabelParams(GoogleToolParams):
    label_name: str = Field(
        description="Name of the label to delete (user-created labels only)",
    )


@registry.tool(
    name="delete_label",
    description=(
        "Delete a user-created Gmail label. System labels "
        "(INBOX, STARRED, etc.) cannot be deleted."
    ),
    category=_CATEGORY,
    params_model=DeleteLabelParams,
    requires_confirmation=True,
)
async def delete_label(
    label_name: str, account: str | None = None
) -> ToolResult:
    service = _auth(account).gmail()

    label_id = await _resolve_label_id(service, label_name)
    if not label_id:
        return ToolResult(error=f"Label not found: {label_name}")

    # Prevent deleting system labels
    system_labels = {
        "INBOX", "UNREAD", "STARRED", "IMPORTANT", "SPAM", "TRASH",
        "SENT", "DRAFT", "CATEGORY_PERSONAL", "CATEGORY_SOCIAL",
        "CATEGORY_PROMOTIONS", "CATEGORY_UPDATES", "CATEGORY_FORUMS",
    }
    if label_id in system_labels:
        return ToolResult(error=f"Cannot delete system label: {label_name}")

    await asyncio.to_thread(
        lambda: service.users()
        .labels()
        .delete(userId="me", id=label_id)
        .execute()
    )

    return ToolResult(data={"deleted": True, "label_name": label_name})


# -- list_labels -------------------------------------------------------------


class ListLabelsParams(GoogleToolParams):
    pass


@registry.tool(
    name="list_labels",
    description="List all Gmail labels (both system and user-created).",
    category=_CATEGORY,
    params_model=ListLabelsParams,
)
async def list_labels(account: str | None = None) -> ToolResult:
    service = _auth(account).gmail()

    result = await asyncio.to_thread(
        lambda: service.users().labels().list(userId="me").execute()
    )

    labels = []
    for label in result.get("labels", []):
        labels.append({
            "id": label["id"],
            "name": label["name"],
            "type": label.get("type", "user"),
        })

    # Sort: user labels first (alphabetical), then system
    labels.sort(key=lambda lbl: (lbl["type"] != "user", lbl["name"].lower()))

    return ToolResult(data={"labels": labels, "count": len(labels)})


# -- download_email_attachment -----------------------------------------------


class DownloadEmailAttachmentParams(GoogleToolParams):
    message_id: str = Field(description="Gmail message ID containing the attachment")
    attachment_id: str = Field(description="Attachment ID (from read_email response)")
    filename: str = Field(description="Filename to save as in scratch space")


@registry.tool(
    name="download_email_attachment",
    description=(
        "Download an email attachment to scratch space. Use read_email first "
        "to get the attachment_id, then download it here."
    ),
    category=_CATEGORY,
    params_model=DownloadEmailAttachmentParams,
)
async def download_email_attachment(
    message_id: str,
    attachment_id: str,
    filename: str,
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).gmail()

    result = await asyncio.to_thread(
        lambda: service.users()
        .messages()
        .attachments()
        .get(userId="me", messageId=message_id, id=attachment_id)
        .execute()
    )

    data = base64.urlsafe_b64decode(result["data"])

    try:
        scratch = ScratchSpace.get()
        scratch.write(filename, data)
    except (ValueError, OSError) as exc:
        return ToolResult(error=str(exc))

    mime_type, _ = mimetypes.guess_type(filename)

    return ToolResult(data={
        "downloaded": True,
        "path": filename,
        "size": len(data),
        "mime_type": mime_type or "application/octet-stream",
    })
