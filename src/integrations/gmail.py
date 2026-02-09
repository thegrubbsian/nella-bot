"""Gmail integration."""

import base64
import logging
from email.mime.text import MIMEText

from googleapiclient.discovery import build

from src.integrations.google_auth import get_google_credentials

logger = logging.getLogger(__name__)


def _get_service():
    """Build the Gmail API service."""
    creds = get_google_credentials()
    return build("gmail", "v1", credentials=creds)


async def get_recent_emails(
    max_results: int = 10,
    query: str = "",
) -> list[dict]:
    """Fetch recent emails, optionally filtered by Gmail search query."""
    service = _get_service()

    result = (
        service.users()
        .messages()
        .list(userId="me", maxResults=max_results, q=query)
        .execute()
    )

    messages = []
    for msg_ref in result.get("messages", []):
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_ref["id"], format="metadata")
            .execute()
        )
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        messages.append({
            "id": msg["id"],
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "snippet": msg.get("snippet", ""),
        })

    return messages


async def send_email(to: str, subject: str, body: str) -> dict:
    """Send an email."""
    service = _get_service()

    message = MIMEText(body)
    message["to"] = to
    message["subject"] = subject

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    result = (
        service.users()
        .messages()
        .send(userId="me", body={"raw": raw})
        .execute()
    )

    logger.info("Sent email to %s: %s", to, result["id"])
    return {"id": result["id"], "to": to, "subject": subject}
