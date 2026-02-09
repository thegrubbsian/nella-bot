"""Google Calendar integration."""

import logging
from datetime import UTC, datetime, timedelta

from googleapiclient.discovery import build

from src.integrations.google_auth import get_google_credentials

logger = logging.getLogger(__name__)


def _get_service():
    """Build the Calendar API service."""
    creds = get_google_credentials()
    return build("calendar", "v3", credentials=creds)


async def get_todays_events() -> list[dict]:
    """Get all events for today."""
    return await get_upcoming_events(days=1)


async def get_upcoming_events(days: int = 7) -> list[dict]:
    """Get events for the next N days."""
    service = _get_service()
    now = datetime.now(UTC)
    time_max = now + timedelta(days=days)

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    return [
        {
            "id": event["id"],
            "summary": event.get("summary", "(no title)"),
            "start": event["start"].get("dateTime", event["start"].get("date")),
            "end": event["end"].get("dateTime", event["end"].get("date")),
            "description": event.get("description", ""),
        }
        for event in result.get("items", [])
    ]


async def create_event(
    summary: str,
    start: str,
    end: str,
    description: str = "",
    attendees: list[str] | None = None,
) -> dict:
    """Create a new calendar event."""
    service = _get_service()

    body: dict = {
        "summary": summary,
        "start": {"dateTime": start},
        "end": {"dateTime": end},
    }
    if description:
        body["description"] = description
    if attendees:
        body["attendees"] = [{"email": email} for email in attendees]

    event = service.events().insert(calendarId="primary", body=body).execute()
    logger.info("Created event: %s", event["id"])
    return {"id": event["id"], "summary": summary, "link": event.get("htmlLink", "")}
