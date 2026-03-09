"""Slack tools — read/write messages, search, find users."""

from __future__ import annotations

import logging

from pydantic import Field

from src.integrations.slack_auth import SlackAuthManager
from src.tools.base import SlackToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _user_client(workspace: str | None = None):
    """Get the user-token AsyncWebClient for the given workspace."""
    return SlackAuthManager.get(workspace).user_client()


def _bot_client(workspace: str | None = None):
    """Get the bot-token AsyncWebClient for the given workspace."""
    return SlackAuthManager.get(workspace).bot_client()


# ---------------------------------------------------------------------------
# Param models
# ---------------------------------------------------------------------------


class ListChannelsParams(SlackToolParams):
    types: str = Field(
        default="public_channel,private_channel",
        description="Comma-separated channel types: public_channel, private_channel",
    )
    limit: int = Field(default=100, description="Max channels to return (1-1000)")


class ListDmsParams(SlackToolParams):
    limit: int = Field(default=50, description="Max DM conversations to return (1-1000)")


class ReadMessagesParams(SlackToolParams):
    channel: str = Field(description="Channel or DM ID (e.g. C123, D456)")
    limit: int = Field(default=20, description="Number of messages to fetch (1-100)")
    thread_ts: str | None = Field(
        default=None,
        description="Thread timestamp to read replies from a specific thread",
    )


class SendMessageParams(SlackToolParams):
    target: str = Field(
        description="User ID (U...) to open a DM with, or channel ID (C.../D...) to post in"
    )
    text: str = Field(description="Message text to send")


class ReplyToThreadParams(SlackToolParams):
    channel: str = Field(description="Channel or DM ID where the thread lives")
    thread_ts: str = Field(description="Timestamp of the parent message")
    text: str = Field(description="Reply text")


class SearchMessagesParams(SlackToolParams):
    query: str = Field(
        description="Search query using Slack search syntax (e.g. 'from:@user budget')"
    )
    count: int = Field(default=20, description="Max results to return (1-100)")


class FindUserParams(SlackToolParams):
    query: str = Field(description="Name or email to search for")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@registry.tool(
    name="slack_list_channels",
    description=(
        "List public and private Slack channels with member counts and topics. "
        "Use to discover channels before reading or posting."
    ),
    category="slack",
    params_model=ListChannelsParams,
)
async def slack_list_channels(
    workspace: str | None = None,
    types: str = "public_channel,private_channel",
    limit: int = 100,
) -> ToolResult:
    try:
        client = _user_client(workspace)
        resp = await client.conversations_list(types=types, limit=limit, exclude_archived=True)
        channels = resp.get("channels", [])
        return ToolResult(data={
            "channels": [
                {
                    "id": ch["id"],
                    "name": ch.get("name", ""),
                    "topic": ch.get("topic", {}).get("value", ""),
                    "purpose": ch.get("purpose", {}).get("value", ""),
                    "num_members": ch.get("num_members", 0),
                    "is_private": ch.get("is_private", False),
                }
                for ch in channels
            ],
            "count": len(channels),
        })
    except Exception as exc:
        logger.exception("slack_list_channels failed")
        return ToolResult(error=f"Failed to list channels: {exc}")


@registry.tool(
    name="slack_list_dms",
    description=(
        "List direct message conversations with unread counts and last message preview. "
        "Shows who you have open DMs with."
    ),
    category="slack",
    params_model=ListDmsParams,
)
async def slack_list_dms(
    workspace: str | None = None,
    limit: int = 50,
) -> ToolResult:
    try:
        client = _user_client(workspace)
        resp = await client.conversations_list(types="im", limit=limit)
        ims = resp.get("channels", [])

        # Resolve user names for each DM
        user_ids = [im["user"] for im in ims if im.get("user")]
        user_names: dict[str, str] = {}
        if user_ids:
            try:
                users_resp = await client.users_list()
                for member in users_resp.get("members", []):
                    if member["id"] in user_ids:
                        user_names[member["id"]] = (
                            member.get("real_name") or member.get("name", member["id"])
                        )
            except Exception:
                logger.debug("Could not resolve user names for DMs")

        return ToolResult(data={
            "conversations": [
                {
                    "channel_id": im["id"],
                    "user_id": im.get("user", ""),
                    "user_name": user_names.get(im.get("user", ""), ""),
                    "is_open": im.get("is_open", False),
                }
                for im in ims
            ],
            "count": len(ims),
        })
    except Exception as exc:
        logger.exception("slack_list_dms failed")
        return ToolResult(error=f"Failed to list DMs: {exc}")


@registry.tool(
    name="slack_read_messages",
    description=(
        "Read recent messages from a channel or DM conversation. "
        "Can also read thread replies by providing thread_ts. "
        "Resolves user names automatically."
    ),
    category="slack",
    params_model=ReadMessagesParams,
)
async def slack_read_messages(
    channel: str,
    workspace: str | None = None,
    limit: int = 20,
    thread_ts: str | None = None,
) -> ToolResult:
    try:
        client = _user_client(workspace)

        if thread_ts:
            resp = await client.conversations_replies(
                channel=channel, ts=thread_ts, limit=limit
            )
        else:
            resp = await client.conversations_history(channel=channel, limit=limit)

        messages = resp.get("messages", [])

        # Collect user IDs for name resolution
        user_ids = {m.get("user", "") for m in messages if m.get("user")}
        user_names: dict[str, str] = {}
        if user_ids:
            try:
                for uid in user_ids:
                    user_resp = await client.users_info(user=uid)
                    user_obj = user_resp.get("user", {})
                    user_names[uid] = (
                        user_obj.get("real_name") or user_obj.get("name", uid)
                    )
            except Exception:
                logger.debug("Could not resolve some user names")

        return ToolResult(data={
            "messages": [
                {
                    "user": m.get("user", ""),
                    "user_name": user_names.get(m.get("user", ""), ""),
                    "text": m.get("text", ""),
                    "ts": m.get("ts", ""),
                    "thread_ts": m.get("thread_ts"),
                    "reply_count": m.get("reply_count", 0),
                }
                for m in messages
            ],
            "count": len(messages),
            "has_more": resp.get("has_more", False),
        })
    except Exception as exc:
        logger.exception("slack_read_messages failed")
        return ToolResult(error=f"Failed to read messages: {exc}")


@registry.tool(
    name="slack_send_message",
    description=(
        "Send a direct message to a Slack user or post in a channel. "
        "If a user ID (U...) is given, opens/finds the DM first. "
        "If a channel ID (C.../D...) is given, posts directly."
    ),
    category="slack",
    params_model=SendMessageParams,
)
async def slack_send_message(
    target: str,
    text: str,
    workspace: str | None = None,
) -> ToolResult:
    try:
        client = _user_client(workspace)

        # If target looks like a user ID, open a DM channel first
        channel = target
        if target.startswith("U"):
            dm_resp = await client.conversations_open(users=[target])
            channel = dm_resp["channel"]["id"]

        resp = await client.chat_postMessage(channel=channel, text=text)
        return ToolResult(data={
            "sent": True,
            "channel": channel,
            "ts": resp.get("ts", ""),
            "text_length": len(text),
        })
    except Exception as exc:
        logger.exception("slack_send_message failed")
        return ToolResult(error=f"Failed to send message: {exc}")


@registry.tool(
    name="slack_reply_to_thread",
    description="Reply to a specific thread in a channel or DM.",
    category="slack",
    params_model=ReplyToThreadParams,
)
async def slack_reply_to_thread(
    channel: str,
    thread_ts: str,
    text: str,
    workspace: str | None = None,
) -> ToolResult:
    try:
        client = _user_client(workspace)
        resp = await client.chat_postMessage(
            channel=channel, text=text, thread_ts=thread_ts
        )
        return ToolResult(data={
            "sent": True,
            "channel": channel,
            "thread_ts": thread_ts,
            "ts": resp.get("ts", ""),
            "text_length": len(text),
        })
    except Exception as exc:
        logger.exception("slack_reply_to_thread failed")
        return ToolResult(error=f"Failed to reply to thread: {exc}")


@registry.tool(
    name="slack_search_messages",
    description=(
        "Full-text search across Slack messages using Slack search syntax. "
        "Supports operators like from:@user, in:#channel, has:link, before:, after:."
    ),
    category="slack",
    params_model=SearchMessagesParams,
)
async def slack_search_messages(
    query: str,
    workspace: str | None = None,
    count: int = 20,
) -> ToolResult:
    try:
        client = _user_client(workspace)
        resp = await client.search_messages(query=query, count=count)
        messages_data = resp.get("messages", {})
        matches = messages_data.get("matches", [])
        return ToolResult(data={
            "matches": [
                {
                    "text": m.get("text", ""),
                    "user": m.get("username", ""),
                    "channel": m.get("channel", {}).get("name", ""),
                    "channel_id": m.get("channel", {}).get("id", ""),
                    "ts": m.get("ts", ""),
                    "permalink": m.get("permalink", ""),
                }
                for m in matches
            ],
            "total": messages_data.get("total", 0),
            "count": len(matches),
        })
    except Exception as exc:
        logger.exception("slack_search_messages failed")
        return ToolResult(error=f"Failed to search messages: {exc}")


@registry.tool(
    name="slack_find_user",
    description=(
        "Look up a Slack user by name or email. "
        "Searches across display names, real names, and email addresses."
    ),
    category="slack",
    params_model=FindUserParams,
)
async def slack_find_user(
    query: str,
    workspace: str | None = None,
) -> ToolResult:
    try:
        client = _user_client(workspace)

        # Try email lookup first
        if "@" in query:
            try:
                resp = await client.users_lookupByEmail(email=query)
                user = resp.get("user", {})
                return ToolResult(data={
                    "users": [_format_user(user)],
                    "count": 1,
                    "match_type": "email",
                })
            except Exception:
                pass  # Fall through to name search

        # Search by listing users and filtering by name
        resp = await client.users_list()
        members = resp.get("members", [])
        query_lower = query.lower()
        matches = [
            _format_user(m)
            for m in members
            if not m.get("deleted")
            and not m.get("is_bot")
            and (
                query_lower in (m.get("real_name", "") or "").lower()
                or query_lower in (m.get("name", "") or "").lower()
                or query_lower in (m.get("profile", {}).get("display_name", "") or "").lower()
            )
        ]
        return ToolResult(data={
            "users": matches[:10],
            "count": len(matches),
            "match_type": "name",
        })
    except Exception as exc:
        logger.exception("slack_find_user failed")
        return ToolResult(error=f"Failed to find user: {exc}")


def _format_user(user: dict) -> dict:
    """Format a Slack user object for tool output."""
    profile = user.get("profile", {})
    return {
        "id": user.get("id", ""),
        "name": user.get("name", ""),
        "real_name": user.get("real_name", ""),
        "display_name": profile.get("display_name", ""),
        "email": profile.get("email", ""),
        "title": profile.get("title", ""),
        "is_admin": user.get("is_admin", False),
    }
