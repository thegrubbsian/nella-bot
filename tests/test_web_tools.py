"""Tests for web research tools (web_search, read_webpage)."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from src.tools.web_tools import (
    ReadWebpageParams,
    WebSearchParams,
    _is_html,
    read_webpage,
    web_search,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _configure_api_key(monkeypatch) -> None:
    """Ensure the Brave API key is set for most tests."""
    monkeypatch.setattr("src.config.settings.brave_search_api_key", "test-brave-key")


def _mock_httpx_client(mock_client_cls: MagicMock, response: httpx.Response) -> AsyncMock:
    """Wire up an AsyncClient context-manager mock that returns *response*."""
    mock_client = AsyncMock()
    mock_client.get.return_value = response
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client_cls.return_value = mock_client
    return mock_client


def _brave_response(results: list[dict], status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        json={"web": {"results": results}},
        request=httpx.Request("GET", "https://api.search.brave.com/res/v1/web/search"),
    )


def _webpage_response(
    html: str,
    status_code: int = 200,
    content_type: str = "text/html; charset=utf-8",
) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        text=html,
        headers={"content-type": content_type},
        request=httpx.Request("GET", "https://example.com/page"),
    )


# ---------------------------------------------------------------------------
# web_search tests
# ---------------------------------------------------------------------------


async def test_web_search_success() -> None:
    results = [
        {"title": "Electric Cars Guide", "url": "https://example.com/ev", "description": "A guide"},
        {
            "title": "EV Charging",
            "url": "https://example.com/charging",
            "description": "Charging info",
        },
    ]
    resp = _brave_response(results)

    with patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls:
        _mock_httpx_client(mock_cls, resp)
        result = await web_search(query="electric cars", count=5)

    assert result.success
    assert result.data["count"] == 2
    assert result.data["query"] == "electric cars"
    assert result.data["results"][0]["title"] == "Electric Cars Guide"


async def test_web_search_sends_correct_headers() -> None:
    resp = _brave_response([])

    with patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls:
        mock_client = _mock_httpx_client(mock_cls, resp)
        await web_search(query="test")

        _, kwargs = mock_client.get.call_args
        assert kwargs["headers"]["X-Subscription-Token"] == "test-brave-key"
        assert kwargs["params"]["q"] == "test"


async def test_web_search_no_api_key(monkeypatch) -> None:
    monkeypatch.setattr("src.config.settings.brave_search_api_key", "")
    result = await web_search(query="test")
    assert not result.success
    assert "not configured" in result.error


async def test_web_search_api_error() -> None:
    resp = httpx.Response(
        status_code=429,
        text="Rate limited",
        request=httpx.Request("GET", "https://api.search.brave.com"),
    )

    with patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls:
        _mock_httpx_client(mock_cls, resp)
        result = await web_search(query="test")

    assert not result.success
    assert "429" in result.error


async def test_web_search_empty_results() -> None:
    resp = _brave_response([])

    with patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls:
        _mock_httpx_client(mock_cls, resp)
        result = await web_search(query="obscure query")

    assert result.success
    assert result.data["count"] == 0
    assert result.data["results"] == []


async def test_web_search_http_transport_error() -> None:
    with patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.ConnectError("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = await web_search(query="test")

    assert not result.success
    assert "failed" in result.error.lower()


async def test_web_search_count_clipping() -> None:
    """Count should be clipped to max 20 in the API call."""
    resp = _brave_response([])

    with patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls:
        mock_client = _mock_httpx_client(mock_cls, resp)
        await web_search(query="test", count=20)

        _, kwargs = mock_client.get.call_args
        assert kwargs["params"]["count"] == 20


# ---------------------------------------------------------------------------
# read_webpage tests
# ---------------------------------------------------------------------------

SAMPLE_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
<main>
<h1>Hello World</h1>
<p>This is the main content of the page.</p>
<a href="/about">About Us</a>
<a href="https://external.com/resource">External Resource</a>
</main>
</body>
</html>
"""


async def test_read_webpage_success() -> None:
    resp = _webpage_response(SAMPLE_HTML)

    with (
        patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls,
        patch("src.tools.web_tools.trafilatura") as mock_traf,
    ):
        _mock_httpx_client(mock_cls, resp)
        mock_traf.extract.return_value = "Hello World\nThis is the main content of the page."
        mock_metadata = MagicMock()
        mock_metadata.title = "Test Page"
        mock_traf.extract_metadata.return_value = mock_metadata

        result = await read_webpage(url="https://example.com/page")

    assert result.success
    assert result.data["title"] == "Test Page"
    assert "Hello World" in result.data["content"]
    assert result.data["url"] == "https://example.com/page"
    assert isinstance(result.data["links"], list)


async def test_read_webpage_truncation() -> None:
    long_content = "x" * 10000
    resp = _webpage_response(SAMPLE_HTML)

    with (
        patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls,
        patch("src.tools.web_tools.trafilatura") as mock_traf,
    ):
        _mock_httpx_client(mock_cls, resp)
        mock_traf.extract.return_value = long_content
        mock_metadata = MagicMock()
        mock_metadata.title = "Test"
        mock_traf.extract_metadata.return_value = mock_metadata

        result = await read_webpage(url="https://example.com/page", max_length=500)

    assert result.success
    assert result.data["content"].endswith("[Content truncated]")
    assert result.data["length"] == 500


async def test_read_webpage_non_html_rejected() -> None:
    resp = _webpage_response("not html", content_type="application/pdf")

    with patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls:
        _mock_httpx_client(mock_cls, resp)
        result = await read_webpage(url="https://example.com/file.pdf")

    assert not result.success
    assert "Not an HTML page" in result.error


async def test_read_webpage_extraction_failure() -> None:
    resp = _webpage_response("<html><body></body></html>")

    with (
        patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls,
        patch("src.tools.web_tools.trafilatura") as mock_traf,
    ):
        _mock_httpx_client(mock_cls, resp)
        mock_traf.extract.return_value = None

        result = await read_webpage(url="https://example.com/empty")

    assert not result.success
    assert "Could not extract" in result.error


async def test_read_webpage_http_404() -> None:
    resp = _webpage_response("Not Found", status_code=404)

    with patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls:
        _mock_httpx_client(mock_cls, resp)
        result = await read_webpage(url="https://example.com/missing")

    assert not result.success
    assert "404" in result.error


async def test_read_webpage_timeout() -> None:
    with patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls:
        mock_client = AsyncMock()
        mock_client.get.side_effect = httpx.TimeoutException("timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_cls.return_value = mock_client

        result = await read_webpage(url="https://slow.example.com")

    assert not result.success
    assert "Timeout" in result.error


async def test_read_webpage_missing_title_metadata() -> None:
    resp = _webpage_response(SAMPLE_HTML)

    with (
        patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls,
        patch("src.tools.web_tools.trafilatura") as mock_traf,
    ):
        _mock_httpx_client(mock_cls, resp)
        mock_traf.extract.return_value = "Some content"
        mock_traf.extract_metadata.return_value = None

        result = await read_webpage(url="https://example.com/page")

    assert result.success
    assert result.data["title"] == ""


async def test_read_webpage_link_extraction() -> None:
    html = """
    <html><body><main>
    <p>Content here.</p>
    <a href="https://example.com/page1">Page One</a>
    <a href="/relative">Relative Link</a>
    <a href="#">Skip This</a>
    <a href="javascript:void(0)">Skip JS</a>
    <a href="">Skip Empty</a>
    </main></body></html>
    """
    resp = _webpage_response(html)

    with (
        patch("src.tools.web_tools.httpx.AsyncClient") as mock_cls,
        patch("src.tools.web_tools.trafilatura") as mock_traf,
    ):
        _mock_httpx_client(mock_cls, resp)
        mock_traf.extract.return_value = "Content here."
        mock_metadata = MagicMock()
        mock_metadata.title = "Links Test"
        mock_traf.extract_metadata.return_value = mock_metadata

        result = await read_webpage(url="https://example.com/base")

    assert result.success
    links = result.data["links"]
    assert len(links) == 2
    assert links[0]["text"] == "Page One"
    assert links[0]["url"] == "https://example.com/page1"
    assert links[1]["url"] == "https://example.com/relative"


# ---------------------------------------------------------------------------
# Params validation tests
# ---------------------------------------------------------------------------


def test_web_search_params_count_bounds() -> None:
    from pydantic import ValidationError

    # Valid
    p = WebSearchParams(query="test", count=1)
    assert p.count == 1
    p = WebSearchParams(query="test", count=20)
    assert p.count == 20

    # Invalid
    with pytest.raises(ValidationError, match="greater than or equal to 1"):
        WebSearchParams(query="test", count=0)
    with pytest.raises(ValidationError, match="less than or equal to 20"):
        WebSearchParams(query="test", count=21)


def test_read_webpage_params_max_length_bounds() -> None:
    from pydantic import ValidationError

    p = ReadWebpageParams(url="https://example.com", max_length=100)
    assert p.max_length == 100
    p = ReadWebpageParams(url="https://example.com", max_length=50000)
    assert p.max_length == 50000

    with pytest.raises(ValidationError, match="greater than or equal to 100"):
        ReadWebpageParams(url="https://example.com", max_length=50)
    with pytest.raises(ValidationError, match="less than or equal to 50000"):
        ReadWebpageParams(url="https://example.com", max_length=60000)


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


def test_is_html_positive() -> None:
    assert _is_html("text/html") is True
    assert _is_html("text/html; charset=utf-8") is True
    assert _is_html("application/xhtml+xml") is True
    assert _is_html("TEXT/HTML") is True


def test_is_html_negative() -> None:
    assert _is_html("application/json") is False
    assert _is_html("application/pdf") is False
    assert _is_html("text/plain") is False
    assert _is_html("image/png") is False
