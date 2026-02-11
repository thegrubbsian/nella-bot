"""Tests for the query_logs observability tool."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.tools.log_tools import MAX_MESSAGE_LENGTH, _format_entry, query_logs


def _make_log_entry(
    message: str = "Something happened",
    severity: str = "INFO",
    program: str = "uv",
    time: str = "2026-02-11T12:00:00Z",
) -> dict:
    return {"time": time, "severity": severity, "program": program, "message": message}


def _mock_response(logs: list[dict], status_code: int = 200) -> httpx.Response:
    """Build a fake httpx.Response with the given log data."""
    return httpx.Response(
        status_code=status_code,
        json={"logs": logs, "pageInfo": {}},
        request=httpx.Request("GET", "https://example.com"),
    )


@pytest.fixture(autouse=True)
def _configure_token(monkeypatch) -> None:
    """Ensure the API token is set for most tests."""
    monkeypatch.setattr("src.config.settings.papertrail_api_token", "test-token")
    monkeypatch.setattr(
        "src.config.settings.papertrail_api_url",
        "https://api.example.com",
    )


async def test_successful_query() -> None:
    logs = [_make_log_entry(), _make_log_entry(message="Another event")]
    mock_resp = _mock_response(logs)

    with patch("src.tools.log_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await query_logs(filter_query="ERROR", limit=50)

    assert result.success
    assert result.data["count"] == 2
    assert len(result.data["logs"]) == 2
    assert "[uv]" in result.data["logs"][0]


async def test_returns_error_when_token_not_set(monkeypatch) -> None:
    monkeypatch.setattr("src.config.settings.papertrail_api_token", "")

    result = await query_logs()

    assert not result.success
    assert "not configured" in result.error


async def test_hours_param_computes_start_time() -> None:
    mock_resp = _mock_response([])

    with patch("src.tools.log_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        before = datetime.now(UTC) - timedelta(hours=2)
        await query_logs(hours=2)

        call_url = mock_client.get.call_args[0][0]
        assert "startTime=" in call_url
        # The start time should be roughly 2 hours ago
        from urllib.parse import parse_qs, urlparse

        parsed = parse_qs(urlparse(call_url).query)
        start = datetime.strptime(parsed["startTime"][0], "%Y-%m-%dT%H:%M:%SZ")
        # Allow 5 seconds of tolerance
        assert abs((start.replace(tzinfo=UTC) - before).total_seconds()) < 5


async def test_minutes_param_overrides_hours() -> None:
    mock_resp = _mock_response([])

    with patch("src.tools.log_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        before = datetime.now(UTC) - timedelta(minutes=10)
        await query_logs(hours=5, minutes=10)

        call_url = mock_client.get.call_args[0][0]
        from urllib.parse import parse_qs, urlparse

        parsed = parse_qs(urlparse(call_url).query)
        start = datetime.strptime(parsed["startTime"][0], "%Y-%m-%dT%H:%M:%SZ")
        # Should be ~10 minutes ago (minutes overrides hours)
        assert abs((start.replace(tzinfo=UTC) - before).total_seconds()) < 5


async def test_limit_caps_at_100() -> None:
    """Pydantic validation ensures limit <= 100."""
    from pydantic import ValidationError

    from src.tools.log_tools import QueryLogsParams

    with pytest.raises(ValidationError, match="less than or equal to 100"):
        QueryLogsParams(limit=150)


async def test_empty_results() -> None:
    mock_resp = _mock_response([])

    with patch("src.tools.log_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await query_logs()

    assert result.success
    assert result.data["count"] == 0
    assert result.data["logs"] == []


async def test_api_error_returns_tool_error() -> None:
    error_resp = httpx.Response(
        status_code=500,
        text="Internal Server Error",
        request=httpx.Request("GET", "https://example.com"),
    )

    with patch("src.tools.log_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = error_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await query_logs()

    assert not result.success
    assert "500" in result.error


async def test_long_messages_are_truncated() -> None:
    long_message = "x" * 1000
    logs = [_make_log_entry(message=long_message)]
    mock_resp = _mock_response(logs)

    with patch("src.tools.log_tools.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        result = await query_logs()

    assert result.success
    log_line = result.data["logs"][0]
    # The message portion should be truncated
    assert log_line.endswith("...")
    # Total line should contain the truncated message (500 chars + "...")
    assert "x" * MAX_MESSAGE_LENGTH + "..." in log_line


def test_format_entry_plain_text() -> None:
    entry = _make_log_entry(
        time="2026-02-11T12:00:00Z",
        severity="ERROR",
        program="uv",
        message="Something broke",
    )
    result = _format_entry(entry)
    assert result == "2026-02-11T12:00:00Z ERROR [uv] Something broke"
    # No ANSI escape codes
    assert "\033[" not in result
