"""Observability tools — query production logs from SolarWinds/Papertrail."""

import logging
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

import httpx
from pydantic import Field

from src.config import settings
from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

MAX_MESSAGE_LENGTH = 500


class QueryLogsParams(ToolParams):
    filter_query: str | None = Field(
        default=None,
        description="Text search across log messages (e.g. 'ERROR', task name, tool name)",
    )
    hours: float | None = Field(
        default=None,
        description="Lookback window in hours. Default: 1",
    )
    minutes: float | None = Field(
        default=None,
        description="Lookback window in minutes. Overrides hours if set.",
    )
    limit: int = Field(
        default=50,
        description="Max log entries to return (max 100)",
        ge=1,
        le=100,
    )


def _format_entry(entry: dict) -> str:
    """Format a single log entry as a plain-text line (no ANSI colors)."""
    time = entry.get("time", "?")
    severity = entry.get("severity", "?")
    program = entry.get("program", "?")
    message = entry.get("message", "")
    if len(message) > MAX_MESSAGE_LENGTH:
        message = message[:MAX_MESSAGE_LENGTH] + "..."
    return f"{time} {severity} [{program}] {message}"


@registry.tool(
    name="query_logs",
    description=(
        "Search Nella's production logs from SolarWinds/Papertrail. "
        "Use this to diagnose issues, check for errors, or inspect recent activity. "
        "Read-only — does not modify anything."
    ),
    category="observability",
    params_model=QueryLogsParams,
)
async def query_logs(
    filter_query: str | None = None,
    hours: float | None = None,
    minutes: float | None = None,
    limit: int = 50,
) -> ToolResult:
    token = settings.papertrail_api_token
    if not token:
        return ToolResult(error="PAPERTRAIL_API_TOKEN is not configured.")

    base_url = settings.papertrail_api_url or "https://api.na-01.cloud.solarwinds.com"

    # Compute time window — the SolarWinds API requires both startTime and
    # endTime when using direction=tail, otherwise it returns empty results.
    now = datetime.now(UTC)
    time_fmt = "%Y-%m-%dT%H:%M:%SZ"
    if minutes is not None:
        start_time = (now - timedelta(minutes=minutes)).strftime(time_fmt)
    elif hours is not None:
        start_time = (now - timedelta(hours=hours)).strftime(time_fmt)
    else:
        start_time = (now - timedelta(hours=1)).strftime(time_fmt)
    end_time = now.strftime(time_fmt)

    # Use direction=forward (the only reliable mode for the SolarWinds API
    # across arbitrary time windows) and reverse results to show newest first.
    params: dict[str, str | int] = {
        "pageSize": min(limit, 100),
        "direction": "forward",
        "startTime": start_time,
        "endTime": end_time,
    }
    if filter_query:
        params["filter"] = filter_query

    url = f"{base_url}/v1/logs?{urlencode(params)}"
    headers = {"Authorization": f"Bearer {token}"}

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(url, headers=headers)

        if resp.status_code != 200:
            return ToolResult(error=f"Log API returned {resp.status_code}: {resp.text[:200]}")

        data = resp.json()
        # forward returns oldest-first; reverse so newest entries come first.
        logs = data.get("logs", [])
        logs.reverse()
        logs = logs[:limit]

        formatted = [_format_entry(entry) for entry in logs]
        return ToolResult(data={"logs": formatted, "count": len(formatted)})
    except httpx.HTTPError as exc:
        logger.exception("Failed to query logs")
        return ToolResult(error=f"Failed to query logs: {exc}")
