"""Tests for LinkedIn tools (linkedin_create_post, linkedin_post_comment)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.integrations.linkedin_auth import LinkedInAuthError
from src.tools.linkedin_tools import (
    CreatePostParams,
    PostCommentParams,
    _extract_activity_id,
    linkedin_create_post,
    linkedin_post_comment,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

MOCK_HEADERS = {
    "Authorization": "Bearer test-token",
    "LinkedIn-Version": "202401",
    "Content-Type": "application/json",
    "X-Restli-Protocol-Version": "2.0.0",
}
MOCK_PERSON_URN = "urn:li:person:abc123"


@pytest.fixture(autouse=True)
def _mock_linkedin_auth():
    """Patch _auth() to return a mock LinkedInAuth for all tests."""
    mock_auth = MagicMock()
    mock_auth.get_headers.return_value = MOCK_HEADERS
    mock_auth.get_person_urn.return_value = MOCK_PERSON_URN

    with patch("src.tools.linkedin_tools._auth", return_value=mock_auth):
        yield mock_auth


def _mock_httpx_client(mock_client_cls: MagicMock, response: httpx.Response) -> AsyncMock:
    """Wire up an AsyncClient context-manager mock that returns *response*."""
    mock_client = AsyncMock()
    mock_client.post.return_value = response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client
    return mock_client


# ---------------------------------------------------------------------------
# _extract_activity_id tests
# ---------------------------------------------------------------------------


class TestExtractActivityId:
    def test_urn_format(self) -> None:
        url = "https://www.linkedin.com/feed/update/urn:li:activity:7654321098765432100/"
        assert _extract_activity_id(url) == "7654321098765432100"

    def test_urn_format_no_trailing_slash(self) -> None:
        url = "https://www.linkedin.com/feed/update/urn:li:activity:123456"
        assert _extract_activity_id(url) == "123456"

    def test_slug_format(self) -> None:
        url = "https://www.linkedin.com/posts/johndoe_some-slug-activity-7654321098765432100-abcd"
        assert _extract_activity_id(url) == "7654321098765432100"

    def test_profile_url_invalid(self) -> None:
        url = "https://www.linkedin.com/in/johndoe/"
        assert _extract_activity_id(url) is None

    def test_empty_string(self) -> None:
        assert _extract_activity_id("") is None

    def test_random_string(self) -> None:
        assert _extract_activity_id("not-a-url-at-all") is None


# ---------------------------------------------------------------------------
# linkedin_create_post tests
# ---------------------------------------------------------------------------


class TestCreatePost:
    async def test_success(self) -> None:
        resp = httpx.Response(
            status_code=201,
            text="",
            headers={"x-restli-id": "urn:li:share:123"},
            request=httpx.Request("POST", "https://api.linkedin.com/rest/posts"),
        )

        with patch("src.tools.linkedin_tools.httpx.AsyncClient") as mock_cls:
            _mock_httpx_client(mock_cls, resp)
            result = await linkedin_create_post(text="Hello LinkedIn!")

        assert result.success
        assert result.data["created"] is True
        assert result.data["post_urn"] == "urn:li:share:123"
        assert result.data["visibility"] == "PUBLIC"
        assert result.data["text_length"] == len("Hello LinkedIn!")

    async def test_custom_visibility(self) -> None:
        resp = httpx.Response(
            status_code=201,
            text="",
            headers={"x-restli-id": "urn:li:share:456"},
            request=httpx.Request("POST", "https://api.linkedin.com/rest/posts"),
        )

        with patch("src.tools.linkedin_tools.httpx.AsyncClient") as mock_cls:
            _mock_httpx_client(mock_cls, resp)
            result = await linkedin_create_post(text="Private post", visibility="CONNECTIONS")

        assert result.success
        assert result.data["visibility"] == "CONNECTIONS"

    async def test_correct_body(self) -> None:
        resp = httpx.Response(
            status_code=201,
            text="",
            headers={},
            request=httpx.Request("POST", "https://api.linkedin.com/rest/posts"),
        )

        with patch("src.tools.linkedin_tools.httpx.AsyncClient") as mock_cls:
            mock_client = _mock_httpx_client(mock_cls, resp)
            await linkedin_create_post(text="Test post")

            _, kwargs = mock_client.post.call_args
            body = kwargs["json"]
            assert body["author"] == MOCK_PERSON_URN
            assert body["commentary"] == "Test post"
            assert body["visibility"] == "PUBLIC"
            assert body["lifecycleState"] == "PUBLISHED"

    async def test_api_error(self) -> None:
        resp = httpx.Response(
            status_code=403,
            text="Forbidden: insufficient permissions",
            request=httpx.Request("POST", "https://api.linkedin.com/rest/posts"),
        )

        with patch("src.tools.linkedin_tools.httpx.AsyncClient") as mock_cls:
            _mock_httpx_client(mock_cls, resp)
            result = await linkedin_create_post(text="Should fail")

        assert not result.success
        assert "403" in result.error

    async def test_network_error(self) -> None:
        with patch("src.tools.linkedin_tools.httpx.AsyncClient") as mock_cls:
            mock_client = AsyncMock()
            mock_client.post.side_effect = httpx.ConnectError("Connection refused")
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_cls.return_value = mock_client

            result = await linkedin_create_post(text="Should fail")

        assert not result.success
        assert "failed" in result.error.lower()

    async def test_auth_error(self, _mock_linkedin_auth) -> None:
        _mock_linkedin_auth.get_headers.side_effect = LinkedInAuthError("Token expired")

        result = await linkedin_create_post(text="Should fail")

        assert not result.success
        assert "Token expired" in result.error


# ---------------------------------------------------------------------------
# linkedin_post_comment tests
# ---------------------------------------------------------------------------


class TestPostComment:
    async def test_success(self) -> None:
        resp = httpx.Response(
            status_code=201,
            json={"$URN": "urn:li:comment:789"},
            request=httpx.Request("POST", "https://api.linkedin.com/rest/socialActions/x/comments"),
        )

        with patch("src.tools.linkedin_tools.httpx.AsyncClient") as mock_cls:
            _mock_httpx_client(mock_cls, resp)
            result = await linkedin_post_comment(
                post_url="https://www.linkedin.com/feed/update/urn:li:activity:123/",
                text="Great post!",
            )

        assert result.success
        assert result.data["commented"] is True
        assert result.data["activity_urn"] == "urn:li:activity:123"
        assert result.data["comment_urn"] == "urn:li:comment:789"
        assert result.data["text_length"] == len("Great post!")

    async def test_correct_url_encoding_and_body(self) -> None:
        resp = httpx.Response(
            status_code=201,
            json={},
            request=httpx.Request("POST", "https://api.linkedin.com/rest/socialActions/x/comments"),
        )

        with patch("src.tools.linkedin_tools.httpx.AsyncClient") as mock_cls:
            mock_client = _mock_httpx_client(mock_cls, resp)
            await linkedin_post_comment(
                post_url="https://www.linkedin.com/feed/update/urn:li:activity:999/",
                text="Nice!",
            )

            call_args = mock_client.post.call_args
            url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
            # The URN should be URL-encoded in the path
            assert "urn%3Ali%3Aactivity%3A999" in url

            body = call_args[1]["json"]
            assert body["actor"] == MOCK_PERSON_URN
            assert body["message"]["text"] == "Nice!"

    async def test_invalid_url(self) -> None:
        result = await linkedin_post_comment(
            post_url="https://www.linkedin.com/in/johndoe/",
            text="This won't work",
        )

        assert not result.success
        assert "Could not extract activity ID" in result.error

    async def test_slug_format_url(self) -> None:
        resp = httpx.Response(
            status_code=201,
            json={"$URN": "urn:li:comment:321"},
            request=httpx.Request("POST", "https://api.linkedin.com/rest/socialActions/x/comments"),
        )

        with patch("src.tools.linkedin_tools.httpx.AsyncClient") as mock_cls:
            _mock_httpx_client(mock_cls, resp)
            result = await linkedin_post_comment(
                post_url="https://www.linkedin.com/posts/user_title-activity-555-abcd",
                text="Comment!",
            )

        assert result.success
        assert result.data["activity_urn"] == "urn:li:activity:555"

    async def test_api_error(self) -> None:
        resp = httpx.Response(
            status_code=422,
            text="Unprocessable Entity",
            request=httpx.Request("POST", "https://api.linkedin.com/rest/socialActions/x/comments"),
        )

        with patch("src.tools.linkedin_tools.httpx.AsyncClient") as mock_cls:
            _mock_httpx_client(mock_cls, resp)
            result = await linkedin_post_comment(
                post_url="https://www.linkedin.com/feed/update/urn:li:activity:123/",
                text="Fail",
            )

        assert not result.success
        assert "422" in result.error


# ---------------------------------------------------------------------------
# Params validation tests
# ---------------------------------------------------------------------------


class TestParams:
    def test_create_post_defaults(self) -> None:
        p = CreatePostParams(text="Hello")
        assert p.text == "Hello"
        assert p.visibility == "PUBLIC"

    def test_create_post_required_text(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            CreatePostParams()  # type: ignore[call-arg]

    def test_post_comment_required_fields(self) -> None:
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            PostCommentParams()  # type: ignore[call-arg]

        with pytest.raises(ValidationError):
            PostCommentParams(post_url="https://example.com")  # type: ignore[call-arg]

    def test_post_comment_valid(self) -> None:
        url = "https://linkedin.com/feed/update/urn:li:activity:1/"
        p = PostCommentParams(post_url=url, text="Hi")
        assert p.post_url.startswith("https://")
        assert p.text == "Hi"
