"""Inbound SMS processing pipeline."""

from __future__ import annotations

import asyncio
import logging

from src.bot.session import get_session
from src.config import settings
from src.llm.client import generate_response
from src.memory.automatic import extract_and_save
from src.notifications.context import MessageContext
from src.sms.client import send_sms

logger = logging.getLogger(__name__)


async def handle_inbound_sms(from_number: str, body: str) -> None:
    """Process an inbound SMS and reply via Telnyx.

    Security: only processes messages from ``settings.sms_owner_phone``.
    """
    if from_number != settings.sms_owner_phone:
        logger.warning("SMS rejected: from=%s is not the owner", from_number)
        return

    if not body or not body.strip():
        logger.debug("SMS ignored: empty body from %s", from_number)
        return

    logger.info("SMS from %s: %s", from_number, body[:80])

    session = get_session(from_number)
    session.add("user", body)

    msg_context = MessageContext(
        user_id=from_number,
        source_channel="sms",
        conversation_id=from_number,
    )

    try:
        # No streaming, no confirmation support for SMS
        result_text = await generate_response(
            session.to_api_messages(),
            msg_context=msg_context,
        )

        if result_text:
            session.add("assistant", result_text)
            await send_sms(from_number, result_text)

            # Background memory extraction
            recent = session.to_api_messages()[-6:]
            asyncio.create_task(
                extract_and_save(
                    user_message=body,
                    assistant_response=result_text,
                    recent_history=recent,
                    conversation_id=from_number,
                )
            )
        else:
            await send_sms(from_number, "I got an empty response. Try again?")

    except Exception:
        logger.exception("Error processing SMS from %s", from_number)
        await send_sms(from_number, "Something went wrong. Check the logs.")
