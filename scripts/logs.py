#!/usr/bin/env python3
"""Query production logs from SolarWinds Observability (Papertrail).

Usage examples:
    # Latest 20 log lines
    uv run python scripts/logs.py

    # Search for errors
    uv run python scripts/logs.py --filter ERROR

    # Last hour of nella-related logs
    uv run python scripts/logs.py --filter nella --hours 1

    # Specific time window
    uv run python scripts/logs.py --start 2026-02-10T18:00:00Z --end 2026-02-10T19:00:00Z

    # Tail mode (newest first)
    uv run python scripts/logs.py --tail --limit 50

    # Filter by program name
    uv run python scripts/logs.py --filter "uv" --limit 30
"""

import argparse
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlencode

import httpx

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.config import settings

BASE_URL = settings.papertrail_api_url or "https://api.na-01.cloud.solarwinds.com"
TOKEN = settings.papertrail_api_token


def fetch_logs(
    *,
    filter_query: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    direction: str = "tail",
    page_size: int = 50,
    max_pages: int = 5,
) -> list[dict]:
    """Fetch logs from the SolarWinds Observability API."""
    if not TOKEN:
        print("ERROR: PAPERTRAIL_API_TOKEN is not set in .env", file=sys.stderr)
        sys.exit(1)

    headers = {"Authorization": f"Bearer {TOKEN}"}
    params: dict[str, str | int] = {"pageSize": page_size, "direction": direction}

    if filter_query:
        params["filter"] = filter_query
    if start_time:
        params["startTime"] = start_time
    if end_time:
        params["endTime"] = end_time

    all_logs: list[dict] = []
    url = f"{BASE_URL}/v1/logs?{urlencode(params)}"

    with httpx.Client(timeout=30) as client:
        for _ in range(max_pages):
            resp = client.get(url, headers=headers)
            if resp.status_code != 200:
                print(f"ERROR: API returned {resp.status_code}: {resp.text}", file=sys.stderr)
                sys.exit(1)

            data = resp.json()
            logs = data.get("logs", [])
            all_logs.extend(logs)

            next_page = data.get("pageInfo", {}).get("nextPage")
            if not next_page or not logs:
                break
            url = f"{BASE_URL}{next_page}"

    return all_logs


def format_log(entry: dict) -> str:
    """Format a single log entry for display."""
    time = entry.get("time", "?")
    severity = entry.get("severity", "?")
    program = entry.get("program", "?")
    message = entry.get("message", "")

    # Colorize severity
    colors = {
        "ERROR": "\033[31m",  # red
        "WARNING": "\033[33m",  # yellow
        "NOTICE": "\033[36m",  # cyan
        "DEBUG": "\033[90m",  # gray
    }
    reset = "\033[0m"
    color = colors.get(severity, "")

    return f"{time} {color}{severity:8s}{reset} [{program}] {message}"


def main() -> None:
    parser = argparse.ArgumentParser(description="Query Nella production logs")
    parser.add_argument("--filter", "-f", help="Search query string (text search in messages)")
    parser.add_argument("--start", help="Start time (ISO 8601, e.g. 2026-02-10T18:00:00Z)")
    parser.add_argument("--end", help="End time (ISO 8601, e.g. 2026-02-10T19:00:00Z)")
    parser.add_argument("--hours", type=float, help="Show logs from the last N hours")
    parser.add_argument("--minutes", type=float, help="Show logs from the last N minutes")
    parser.add_argument("--limit", "-n", type=int, default=50, help="Max log lines (default: 50)")
    parser.add_argument("--no-color", action="store_true", help="Disable color output")
    args = parser.parse_args()

    # Time range
    start_time = args.start
    end_time = args.end

    time_fmt = "%Y-%m-%dT%H:%M:%SZ"
    if args.hours:
        start_time = (datetime.now(UTC) - timedelta(hours=args.hours)).strftime(time_fmt)
    elif args.minutes:
        start_time = (datetime.now(UTC) - timedelta(minutes=args.minutes)).strftime(time_fmt)

    # SolarWinds API only reliably returns results with direction=forward;
    # tail/backward silently return empty for wide time windows.
    if not end_time:
        end_time = datetime.now(UTC).strftime(time_fmt)
    if not start_time:
        start_time = (datetime.now(UTC) - timedelta(hours=1)).strftime(time_fmt)

    direction = "forward"

    logs = fetch_logs(
        filter_query=args.filter,
        start_time=start_time,
        end_time=end_time,
        direction=direction,
        page_size=min(args.limit, 100),
        max_pages=(args.limit // 100) + 1,
    )

    # forward returns oldest-first; reverse so newest are shown first.
    logs.reverse()
    logs = logs[: args.limit]

    if not logs:
        print("No logs found matching criteria.")
        return

    print(f"--- {len(logs)} log entries ---\n")
    for entry in logs:
        if args.no_color:
            time = entry.get("time", "?")
            severity = entry.get("severity", "?")
            program = entry.get("program", "?")
            message = entry.get("message", "")
            print(f"{time} {severity:8s} [{program}] {message}")
        else:
            print(format_log(entry))


if __name__ == "__main__":
    main()
