"""Slack workspace tools — query users, channels, etc."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from pydantic import Field

from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Client management
# ---------------------------------------------------------------------------

_slack_client: AsyncWebClient | None = None


def init_slack_tools(client: AsyncWebClient) -> None:
    """Store a reference to the Slack web client for tool use."""
    global _slack_client  # noqa: PLW0603
    _slack_client = client
    logger.info("Slack tools initialized")


def _get_client() -> AsyncWebClient:
    """Return the Slack client or raise a ToolResult-friendly error."""
    if _slack_client is None:
        raise _SlackToolError("Slack client not initialized. Is CHAT_PLATFORM=slack?")
    return _slack_client


class _SlackToolError(Exception):
    """Raised when the Slack client is unavailable."""


# ---------------------------------------------------------------------------
# slack_list_users
# ---------------------------------------------------------------------------


class SlackListUsersParams(ToolParams):
    include_bots: bool = Field(
        default=False,
        description="Include bot users in the results. Defaults to false.",
    )


@registry.tool(
    name="slack_list_users",
    description=(
        "List all users in the Slack workspace. "
        "Returns each user's ID, name, real name, display name, and role info."
    ),
    category="slack",
    params_model=SlackListUsersParams,
)
async def slack_list_users(include_bots: bool = False) -> ToolResult:
    try:
        client = _get_client()
    except _SlackToolError as exc:
        return ToolResult(error=str(exc))

    try:
        users: list[dict] = []
        cursor: str | None = None

        while True:
            kwargs: dict = {}
            if cursor:
                kwargs["cursor"] = cursor

            response = await client.users_list(**kwargs)

            for member in response.get("members", []):
                is_bot = member.get("is_bot", False) or member.get("id") == "USLACKBOT"
                if not include_bots and is_bot:
                    continue

                profile = member.get("profile", {})
                users.append(
                    {
                        "id": member.get("id"),
                        "name": member.get("name"),
                        "real_name": member.get("real_name", ""),
                        "display_name": profile.get("display_name", ""),
                        "is_bot": is_bot,
                        "is_admin": member.get("is_admin", False),
                    }
                )

            next_cursor = response.get("response_metadata", {}).get("next_cursor", "")
            if not next_cursor:
                break
            cursor = next_cursor

        return ToolResult(data={"users": users, "count": len(users)})
    except Exception as exc:
        logger.exception("slack_list_users failed")
        return ToolResult(error=f"Slack API error: {exc}")


# ---------------------------------------------------------------------------
# slack_get_user_profile
# ---------------------------------------------------------------------------


class SlackGetUserProfileParams(ToolParams):
    user_id: str = Field(
        description="The Slack user ID (e.g. 'U01ABCDEF') to fetch the profile for.",
    )


@registry.tool(
    name="slack_get_user_profile",
    description=(
        "Get a Slack user's full profile including email, title, phone, "
        "status, and timezone. Requires a user ID from slack_list_users."
    ),
    category="slack",
    params_model=SlackGetUserProfileParams,
)
async def slack_get_user_profile(user_id: str) -> ToolResult:
    try:
        client = _get_client()
    except _SlackToolError as exc:
        return ToolResult(error=str(exc))

    try:
        response = await client.users_profile_get(user=user_id)
        profile = response.get("profile", {})

        return ToolResult(
            data={
                "user_id": user_id,
                "real_name": profile.get("real_name", ""),
                "display_name": profile.get("display_name", ""),
                "email": profile.get("email", ""),
                "title": profile.get("title", ""),
                "phone": profile.get("phone", ""),
                "status_text": profile.get("status_text", ""),
                "status_emoji": profile.get("status_emoji", ""),
                "timezone": profile.get("tz", ""),
                "image_url": profile.get("image_192", ""),
            }
        )
    except Exception as exc:
        logger.exception("slack_get_user_profile failed")
        return ToolResult(error=f"Slack API error: {exc}")
