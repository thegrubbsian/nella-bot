"""LinkedIn tools — create posts and comment on posts."""

import logging
import re
from urllib.parse import quote

import httpx
from pydantic import Field

from src.integrations.linkedin_auth import LinkedInAuth, LinkedInAuthError
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

POSTS_URL = "https://api.linkedin.com/rest/posts"
SOCIAL_ACTIONS_URL = "https://api.linkedin.com/rest/socialActions"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_activity_id(url: str) -> str | None:
    """Extract a LinkedIn activity ID from a post URL.

    Supports two common URL formats:
    - https://www.linkedin.com/feed/update/urn:li:activity:123456/
    - https://www.linkedin.com/posts/user_slug-activity-123456-xxxx
    """
    # Format 1: /feed/update/urn:li:activity:<id>
    m = re.search(r"urn:li:activity:(\d+)", url)
    if m:
        return m.group(1)

    # Format 2: /posts/...-activity-<id>-...
    m = re.search(r"-activity-(\d+)-", url)
    if m:
        return m.group(1)

    return None


def _auth() -> LinkedInAuth:
    """Return the LinkedInAuth singleton."""
    return LinkedInAuth.get()


# ---------------------------------------------------------------------------
# Param models
# ---------------------------------------------------------------------------


class CreatePostParams(ToolParams):
    text: str = Field(description="The text content of the LinkedIn post")
    visibility: str = Field(
        default="PUBLIC",
        description="Post visibility: 'PUBLIC' (anyone) or 'CONNECTIONS' (connections only)",
    )


class PostCommentParams(ToolParams):
    post_url: str = Field(description="URL of the LinkedIn post to comment on")
    text: str = Field(description="The text content of the comment")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@registry.tool(
    name="linkedin_create_post",
    description=(
        "Create a new LinkedIn post on behalf of the user. "
        "Supports PUBLIC or CONNECTIONS visibility."
    ),
    category="linkedin",
    requires_confirmation=True,
    params_model=CreatePostParams,
)
async def linkedin_create_post(
    text: str,
    visibility: str = "PUBLIC",
) -> ToolResult:
    try:
        auth = _auth()
        headers = auth.get_headers()
        person_urn = auth.get_person_urn()
    except LinkedInAuthError as exc:
        return ToolResult(error=str(exc))

    body = {
        "author": person_urn,
        "commentary": text,
        "visibility": visibility,
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(POSTS_URL, headers=headers, json=body)

        if resp.status_code not in (200, 201):
            return ToolResult(error=f"LinkedIn API returned {resp.status_code}: {resp.text[:300]}")

        post_urn = resp.headers.get("x-restli-id", "")
        return ToolResult(
            data={
                "created": True,
                "post_urn": post_urn,
                "visibility": visibility,
                "text_length": len(text),
            }
        )
    except httpx.HTTPError as exc:
        logger.exception("LinkedIn create post failed")
        return ToolResult(error=f"LinkedIn request failed: {exc}")


@registry.tool(
    name="linkedin_post_comment",
    description=(
        "Post a comment on an existing LinkedIn post. "
        "Provide the LinkedIn post URL and the comment text."
    ),
    category="linkedin",
    requires_confirmation=True,
    params_model=PostCommentParams,
)
async def linkedin_post_comment(
    post_url: str,
    text: str,
) -> ToolResult:
    activity_id = _extract_activity_id(post_url)
    if not activity_id:
        return ToolResult(
            error=(
                f"Could not extract activity ID from URL: {post_url}. "
                "Expected a LinkedIn post URL like "
                "https://www.linkedin.com/feed/update/urn:li:activity:123456/"
            )
        )

    try:
        auth = _auth()
        headers = auth.get_headers()
        person_urn = auth.get_person_urn()
    except LinkedInAuthError as exc:
        return ToolResult(error=str(exc))

    activity_urn = f"urn:li:activity:{activity_id}"
    encoded_urn = quote(activity_urn, safe="")
    comment_url = f"{SOCIAL_ACTIONS_URL}/{encoded_urn}/comments"

    body = {
        "actor": person_urn,
        "message": {
            "text": text,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.post(comment_url, headers=headers, json=body)

        if resp.status_code not in (200, 201):
            return ToolResult(error=f"LinkedIn API returned {resp.status_code}: {resp.text[:300]}")

        resp_data = resp.json() if resp.text else {}
        comment_urn = resp_data.get("$URN", resp_data.get("urn", ""))
        return ToolResult(
            data={
                "commented": True,
                "activity_urn": activity_urn,
                "comment_urn": comment_urn,
                "text_length": len(text),
            }
        )
    except httpx.HTTPError as exc:
        logger.exception("LinkedIn post comment failed")
        return ToolResult(error=f"LinkedIn request failed: {exc}")
