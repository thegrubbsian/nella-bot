"""Inbound Slack DM processing pipeline."""

from __future__ import annotations

import asyncio
import logging
import re

from src.bot.session import get_session
from src.llm.client import generate_response
from src.memory.automatic import extract_and_save
from src.notifications.context import MessageContext
from src.slack.client import send_slack_message

logger = logging.getLogger(__name__)


def _clean_slack_text(text: str) -> str:
    """Strip Slack-specific formatting from message text.

    Handles:
    - ``<@U123>`` user mentions → removed
    - ``<url|label>`` links → label (or url if no label)
    - ``&amp;`` ``&lt;`` ``&gt;`` HTML entities
    """
    # User/channel mentions: <@U123> or <#C123|channel-name>
    text = re.sub(r"<@\w+>", "", text)
    text = re.sub(r"<#\w+\|([^>]+)>", r"#\1", text)

    # Links: <url|label> → label, or <url> → url
    text = re.sub(r"<([^|>]+)\|([^>]+)>", r"\2", text)
    text = re.sub(r"<([^>]+)>", r"\1", text)

    # HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")

    return text.strip()


async def handle_inbound_slack_dm(
    workspace: str,
    user_id: str,
    channel: str,
    text: str,
    *,
    thread_ts: str | None = None,
) -> None:
    """Process an inbound Slack DM and reply."""
    cleaned = _clean_slack_text(text)
    if not cleaned:
        logger.debug("Slack DM ignored: empty after cleaning from %s", user_id)
        return

    logger.info("Slack DM from %s in %s: %s", user_id, workspace, cleaned[:80])

    session_key = f"slack:{workspace}:{user_id}"
    session = get_session(session_key)
    session.add("user", cleaned)

    msg_context = MessageContext(
        user_id=user_id,
        source_channel="slack",
        conversation_id=session_key,
        metadata={"workspace": workspace, "channel": channel},
    )

    try:
        # No streaming, no confirmation support for Slack (same as SMS)
        result_text = await generate_response(
            session.to_api_messages(),
            msg_context=msg_context,
        )

        if result_text:
            session.add("assistant", result_text)
            await send_slack_message(
                channel, result_text, workspace=workspace, thread_ts=thread_ts
            )

            # Background memory extraction
            recent = session.to_api_messages()[-6:]
            asyncio.create_task(
                extract_and_save(
                    user_message=cleaned,
                    assistant_response=result_text,
                    recent_history=recent,
                    conversation_id=session_key,
                )
            )
        else:
            await send_slack_message(
                channel,
                "I got an empty response. Try again?",
                workspace=workspace,
                thread_ts=thread_ts,
            )

    except Exception:
        logger.exception("Error processing Slack DM from %s", user_id)
        await send_slack_message(
            channel,
            "Something went wrong. Check the logs.",
            workspace=workspace,
            thread_ts=thread_ts,
        )
