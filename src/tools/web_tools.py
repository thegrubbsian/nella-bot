"""Web research tools — search the web and read webpage content."""

import asyncio
import logging
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura
from bs4 import BeautifulSoup
from pydantic import Field

from src.config import settings
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

BRAVE_SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"
MAX_DOWNLOAD_BYTES = 5 * 1024 * 1024  # 5 MB
DEFAULT_USER_AGENT = "NellaBot/1.0 (Web Research Assistant)"


class WebSearchParams(ToolParams):
    query: str = Field(description="Search query string")
    count: int = Field(
        default=5,
        description="Number of results to return (1-20)",
        ge=1,
        le=20,
    )


class ReadWebpageParams(ToolParams):
    url: str = Field(description="URL of the webpage to read")
    max_length: int = Field(
        default=5000,
        description="Maximum character length of extracted content (100-50000)",
        ge=100,
        le=50000,
    )


def _is_html(content_type: str) -> bool:
    """Check if a Content-Type header value indicates HTML."""
    ct = content_type.lower().split(";")[0].strip()
    return ct in ("text/html", "application/xhtml+xml")


def _extract_links(html: str, base_url: str) -> list[dict[str, str]]:
    """Extract meaningful links from the main content area of an HTML page.

    Returns up to 20 links with text and absolute URL, filtering out
    navigation/footer junk by only extracting from <main>, <article>,
    or the <body> if no semantic container exists.
    """
    soup = BeautifulSoup(html, "html.parser")

    # Prefer semantic content containers
    container = soup.find("main") or soup.find("article") or soup.find("body")
    if container is None:
        return []

    seen_urls: list[str] = []
    links: list[dict[str, str]] = []

    for a_tag in container.find_all("a", href=True):
        href = a_tag["href"]
        text = a_tag.get_text(strip=True)

        # Skip empty, anchor-only, or javascript links
        if not text or not href or href.startswith(("#", "javascript:")):
            continue

        # Resolve relative URLs
        absolute_url = urljoin(base_url, href)
        parsed = urlparse(absolute_url)

        # Only keep http/https links
        if parsed.scheme not in ("http", "https"):
            continue

        # Deduplicate
        if absolute_url in seen_urls:
            continue
        seen_urls.append(absolute_url)

        links.append({"text": text, "url": absolute_url})

        if len(links) >= 20:
            break

    return links


@registry.tool(
    name="web_search",
    description=(
        "Search the web using Brave Search. Returns titles, URLs, and descriptions "
        "for matching pages. Use read_webpage to get full content of interesting results."
    ),
    category="research",
    params_model=WebSearchParams,
)
async def web_search(query: str, count: int = 5) -> ToolResult:
    api_key = settings.brave_search_api_key
    if not api_key:
        return ToolResult(error="BRAVE_SEARCH_API_KEY is not configured.")

    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": api_key,
    }
    params = {"q": query, "count": min(count, 20)}

    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(BRAVE_SEARCH_URL, headers=headers, params=params)

        if resp.status_code != 200:
            return ToolResult(
                error=f"Brave Search API returned {resp.status_code}: {resp.text[:200]}"
            )

        data = resp.json()
        web_results = data.get("web", {}).get("results", [])

        results = [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
            }
            for r in web_results
        ]

        return ToolResult(data={"results": results, "count": len(results), "query": query})
    except httpx.HTTPError as exc:
        logger.exception("Brave Search request failed")
        return ToolResult(error=f"Search request failed: {exc}")


@registry.tool(
    name="read_webpage",
    description=(
        "Fetch a URL and extract the main text content, page title, and links. "
        "Strips navigation, ads, and boilerplate. Use this to read pages found "
        "via web_search or to follow links from previously read pages."
    ),
    category="research",
    params_model=ReadWebpageParams,
)
async def read_webpage(url: str, max_length: int = 5000) -> ToolResult:
    try:
        async with httpx.AsyncClient(
            timeout=20,
            follow_redirects=True,
            headers={"User-Agent": DEFAULT_USER_AGENT},
            max_redirects=5,
        ) as client:
            resp = await client.get(url)

        if resp.status_code != 200:
            return ToolResult(error=f"HTTP {resp.status_code} fetching {url}")

        content_type = resp.headers.get("content-type", "")
        if not _is_html(content_type):
            return ToolResult(error=f"Not an HTML page (Content-Type: {content_type})")

        # Guard against huge pages
        if len(resp.content) > MAX_DOWNLOAD_BYTES:
            return ToolResult(
                error=f"Page too large ({len(resp.content)} bytes, max {MAX_DOWNLOAD_BYTES})"
            )

        html = resp.text

    except httpx.TimeoutException:
        return ToolResult(error=f"Timeout fetching {url}")
    except httpx.HTTPError as exc:
        logger.exception("Failed to fetch webpage")
        return ToolResult(error=f"Failed to fetch webpage: {exc}")

    # Extract main content via trafilatura (CPU-bound, sync library)
    content = await asyncio.to_thread(trafilatura.extract, html)

    if content is None:
        return ToolResult(error=f"Could not extract content from {url}")

    # Extract title via trafilatura metadata
    metadata = await asyncio.to_thread(trafilatura.extract_metadata, html)
    title = metadata.title if metadata and metadata.title else ""

    # Extract links from the HTML content area
    links = _extract_links(html, url)

    # Truncate content to max_length
    truncated = False
    if len(content) > max_length:
        content = content[:max_length]
        truncated = True

    result_data: dict = {
        "title": title,
        "url": url,
        "content": content + (" [Content truncated]" if truncated else ""),
        "length": len(content),
        "links": links,
    }

    return ToolResult(data=result_data)
