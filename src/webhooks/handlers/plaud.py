"""Plaud webhook handler — processes new meeting transcripts.

When a Plaud transcript lands in Google Drive (via Zapier), this handler:
1. Reads the transcript from Drive
2. Sends it to Claude for summarization and action-item extraction
3. Notifies the owner via Telegram
4. Saves a summary to long-term memory
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.config import settings
from src.webhooks.registry import webhook_registry

logger = logging.getLogger(__name__)

RETRY_ATTEMPTS = 3
RETRY_DELAY = 30  # seconds

ANALYSIS_PROMPT = """\
I just finished a meeting. Here's the transcript:

---
{transcript}
---

Please:
1. Give me a brief summary (3-4 sentences max)
2. List all action items, organized by who owns them
3. Flag any decisions that were made
4. Note any follow-ups or deadlines mentioned
Format this clearly for a Telegram message."""


async def _read_transcript(file_id: str) -> str | None:
    """Read transcript text from Google Drive by file ID."""
    from src.tools.google_drive import read_file

    account = settings.plaud_google_account or None
    try:
        result = await read_file(file_id=file_id, account=account)
    except Exception:
        logger.debug("read_file raised for file_id=%s", file_id, exc_info=True)
        return None
    if not result.success:
        return None
    return result.data.get("content")


async def _search_transcript(file_name: str) -> str | None:
    """Search for a transcript by name in the configured Plaud folder."""
    from src.integrations.google_auth import GoogleAuthManager
    from src.tools.google_drive import _escape_query, read_file

    account = settings.plaud_google_account or None
    service = GoogleAuthManager.get(account).drive()

    # Build query: name match, scoped to the Plaud folder if configured
    parts = [f"name = '{_escape_query(file_name)}'"]
    folder_id = settings.plaud_drive_folder_id
    if folder_id:
        parts.append(f"'{folder_id}' in parents")
    q = " and ".join(parts)

    result = await asyncio.to_thread(
        lambda: (
            service.files()
            .list(q=q, pageSize=1, orderBy="createdTime desc", fields="files(id)")
            .execute()
        )
    )

    files = result.get("files", [])
    if not files:
        return None

    found_id = files[0]["id"]
    try:
        read_result = await read_file(file_id=found_id, account=account)
    except Exception:
        logger.debug("read_file raised for found_id=%s", found_id, exc_info=True)
        return None
    if not read_result.success:
        return None
    return read_result.data.get("content")


async def _fetch_transcript(payload: dict[str, Any]) -> str | None:
    """Try to read the transcript, retrying if Drive hasn't synced yet."""
    file_id = payload.get("file_id")
    file_name = payload.get("file_name", "")

    for attempt in range(1, RETRY_ATTEMPTS + 1):
        logger.info(
            "Fetching transcript (attempt %d/%d): file_id=%s, file_name=%s",
            attempt,
            RETRY_ATTEMPTS,
            file_id,
            file_name,
        )

        content = None
        if file_id:
            content = await _read_transcript(file_id)
        if content is None and file_name:
            content = await _search_transcript(file_name)

        if content:
            return content

        if attempt < RETRY_ATTEMPTS:
            logger.info("Transcript not found, retrying in %ds...", RETRY_DELAY)
            await asyncio.sleep(RETRY_DELAY)

    return None


async def _analyze_transcript(transcript: str) -> str:
    """Send the transcript to Claude for summarization.

    Uses complete_text() (no system prompt, no Mem0 memories) to avoid
    contaminating the summary with facts from previous meetings.
    """
    from src.llm.client import complete_text

    prompt = ANALYSIS_PROMPT.format(transcript=transcript)
    return await complete_text([{"role": "user", "content": prompt}])


async def _notify_owner(message: str) -> None:
    """Send a message to the bot owner via the default notification channel."""
    from src.notifications.router import NotificationRouter

    router = NotificationRouter.get()
    allowed = settings.get_allowed_user_ids()
    owner_id = str(next(iter(allowed))) if allowed else ""
    if not owner_id:
        logger.warning("No owner user ID configured — cannot send notification")
        return
    await router.send(owner_id, message)


async def _save_to_memory(summary: str, file_name: str, meeting_date: str) -> None:
    """Save the meeting summary to Nella's long-term memory."""
    from src.memory.store import MemoryStore

    store = MemoryStore.get()
    content = f"Meeting transcript summary ({file_name}"
    if meeting_date:
        content += f", {meeting_date}"
    content += f"):\n{summary}"

    await store.add(
        content=content,
        source="automatic",
        category="workstream",
        metadata={"origin": "plaud", "file_name": file_name},
    )


@webhook_registry.handler("plaud")
async def handle_plaud(payload: dict[str, Any]) -> None:
    """Process a new Plaud transcript from Zapier."""
    file_name = payload.get("file_name", "unknown")
    meeting_date = payload.get("meeting_date", "")
    logger.info(
        "Plaud transcript received: file_name=%s, meeting_date=%s",
        file_name,
        meeting_date,
    )

    transcript = await _fetch_transcript(payload)
    if transcript is None:
        await _notify_owner(
            f"A Plaud transcript was received ({file_name}) "
            "but I couldn't find it in Google Drive after several retries. "
            "You may need to check the Zapier integration."
        )
        return

    summary = await _analyze_transcript(transcript)

    header = f"*Meeting notes: {file_name}*"
    if meeting_date:
        header += f" ({meeting_date})"
    await _notify_owner(f"{header}\n\n{summary}")

    await _save_to_memory(summary, file_name, meeting_date)
    logger.info("Plaud transcript processed: %s", file_name)
