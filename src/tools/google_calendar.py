"""Google Calendar tools — list, create, update, delete events, check availability."""

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from pydantic import Field

from src.integrations.google_auth import GoogleAuthManager
from src.tools.base import GoogleToolParams, ToolResult
from src.tools.registry import registry

logger = logging.getLogger(__name__)

_CATEGORY = "google_calendar"


def _auth(account: str | None = None) -> GoogleAuthManager:
    return GoogleAuthManager.get(account)


def _format_event(event: dict) -> dict:
    """Normalise a Calendar API event into a consistent dict."""
    start = event.get("start", {})
    end = event.get("end", {})

    # Extract meeting link from hangoutLink or conferenceData
    meeting_link = event.get("hangoutLink", "")
    if not meeting_link:
        conf = event.get("conferenceData", {})
        for ep in conf.get("entryPoints", []):
            if ep.get("entryPointType") == "video":
                meeting_link = ep.get("uri", "")
                break

    attendees = [
        a.get("email", "") for a in event.get("attendees", [])
    ]

    return {
        "id": event["id"],
        "title": event.get("summary", "(no title)"),
        "start": start.get("dateTime", start.get("date", "")),
        "end": end.get("dateTime", end.get("date", "")),
        "location": event.get("location", ""),
        "description": event.get("description", ""),
        "attendees": attendees,
        "meeting_link": meeting_link,
    }


# -- list_events -------------------------------------------------------------


class ListEventsParams(GoogleToolParams):
    days_ahead: int = Field(default=7, description="Number of days to look ahead")
    calendar_id: str = Field(default="primary", description="Calendar ID")


@registry.tool(
    name="list_events",
    description="List upcoming calendar events for the next N days.",
    category=_CATEGORY,
    params_model=ListEventsParams,
)
async def list_events(
    days_ahead: int = 7,
    calendar_id: str = "primary",
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).calendar()
    now = datetime.now(UTC)
    time_max = now + timedelta(days=days_ahead)

    result = await asyncio.to_thread(
        lambda: service.events()
        .list(
            calendarId=calendar_id,
            timeMin=now.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = [_format_event(e) for e in result.get("items", [])]
    return ToolResult(data={"events": events, "count": len(events)})


# -- get_todays_schedule -----------------------------------------------------


class TodaysScheduleParams(GoogleToolParams):
    calendar_id: str = Field(default="primary", description="Calendar ID")


@registry.tool(
    name="get_todays_schedule",
    description="Get all events for today.",
    category=_CATEGORY,
    params_model=TodaysScheduleParams,
)
async def get_todays_schedule(
    calendar_id: str = "primary", account: str | None = None
) -> ToolResult:
    service = _auth(account).calendar()
    now = datetime.now(UTC)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_of_day = start_of_day + timedelta(days=1)

    result = await asyncio.to_thread(
        lambda: service.events()
        .list(
            calendarId=calendar_id,
            timeMin=start_of_day.isoformat(),
            timeMax=end_of_day.isoformat(),
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = [_format_event(e) for e in result.get("items", [])]
    return ToolResult(data={"events": events, "count": len(events)})


# -- create_event ------------------------------------------------------------


class CreateEventParams(GoogleToolParams):
    title: str = Field(description="Event title")
    start_time: str = Field(description="Start time in ISO 8601 format")
    end_time: str = Field(description="End time in ISO 8601 format")
    description: str | None = Field(default=None, description="Event description")
    attendees: list[str] | None = Field(default=None, description="Attendee email addresses")
    location: str | None = Field(default=None, description="Event location")
    calendar_id: str = Field(default="primary", description="Calendar ID")


@registry.tool(
    name="create_event",
    description="Create a new calendar event.",
    category=_CATEGORY,
    params_model=CreateEventParams,
    requires_confirmation=True,
)
async def create_event(
    title: str,
    start_time: str,
    end_time: str,
    description: str | None = None,
    attendees: list[str] | None = None,
    location: str | None = None,
    calendar_id: str = "primary",
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).calendar()

    body: dict = {
        "summary": title,
        "start": {"dateTime": start_time},
        "end": {"dateTime": end_time},
    }
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if attendees:
        body["attendees"] = [{"email": e} for e in attendees]

    event = await asyncio.to_thread(
        lambda: service.events()
        .insert(calendarId=calendar_id, body=body)
        .execute()
    )

    logger.info("Created event: %s", event["id"])
    return ToolResult(data={
        "id": event["id"],
        "title": title,
        "link": event.get("htmlLink", ""),
    })


# -- update_event ------------------------------------------------------------


class UpdateEventParams(GoogleToolParams):
    event_id: str = Field(description="Event ID to update")
    calendar_id: str = Field(default="primary", description="Calendar ID")
    title: str | None = Field(default=None, description="New event title")
    start_time: str | None = Field(default=None, description="New start time (ISO 8601)")
    end_time: str | None = Field(default=None, description="New end time (ISO 8601)")
    description: str | None = Field(default=None, description="New description")
    attendees: list[str] | None = Field(default=None, description="New attendee list")
    location: str | None = Field(default=None, description="New location")


@registry.tool(
    name="update_event",
    description="Update an existing calendar event. Only specified fields are changed.",
    category=_CATEGORY,
    params_model=UpdateEventParams,
    requires_confirmation=True,
)
async def update_event(
    event_id: str,
    calendar_id: str = "primary",
    title: str | None = None,
    start_time: str | None = None,
    end_time: str | None = None,
    description: str | None = None,
    attendees: list[str] | None = None,
    location: str | None = None,
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).calendar()

    # Fetch existing event
    existing = await asyncio.to_thread(
        lambda: service.events()
        .get(calendarId=calendar_id, eventId=event_id)
        .execute()
    )

    # Merge only non-None fields
    if title is not None:
        existing["summary"] = title
    if start_time is not None:
        existing["start"] = {"dateTime": start_time}
    if end_time is not None:
        existing["end"] = {"dateTime": end_time}
    if description is not None:
        existing["description"] = description
    if location is not None:
        existing["location"] = location
    if attendees is not None:
        existing["attendees"] = [{"email": e} for e in attendees]

    updated = await asyncio.to_thread(
        lambda: service.events()
        .patch(calendarId=calendar_id, eventId=event_id, body=existing)
        .execute()
    )

    return ToolResult(data={
        "id": updated["id"],
        "title": updated.get("summary", ""),
        "link": updated.get("htmlLink", ""),
    })


# -- delete_event ------------------------------------------------------------


class DeleteEventParams(GoogleToolParams):
    event_id: str = Field(description="Event ID to delete")
    calendar_id: str = Field(default="primary", description="Calendar ID")


@registry.tool(
    name="delete_event",
    description="Delete a calendar event.",
    category=_CATEGORY,
    params_model=DeleteEventParams,
    requires_confirmation=True,
)
async def delete_event(
    event_id: str,
    calendar_id: str = "primary",
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).calendar()

    await asyncio.to_thread(
        lambda: service.events()
        .delete(calendarId=calendar_id, eventId=event_id)
        .execute()
    )

    return ToolResult(data={"deleted": True, "event_id": event_id})


# -- check_availability ------------------------------------------------------


class CheckAvailabilityParams(GoogleToolParams):
    date: str = Field(description="Date to check in YYYY-MM-DD format")
    calendar_id: str = Field(default="primary", description="Calendar ID")


@registry.tool(
    name="check_availability",
    description="Check free/busy status for a given date.",
    category=_CATEGORY,
    params_model=CheckAvailabilityParams,
)
async def check_availability(
    date: str,
    calendar_id: str = "primary",
    account: str | None = None,
) -> ToolResult:
    service = _auth(account).calendar()

    # Parse date and build midnight-to-midnight range
    day = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=UTC)
    day_end = day + timedelta(days=1)

    result = await asyncio.to_thread(
        lambda: service.freebusy()
        .query(
            body={
                "timeMin": day.isoformat(),
                "timeMax": day_end.isoformat(),
                "items": [{"id": calendar_id}],
            }
        )
        .execute()
    )

    busy_periods = result.get("calendars", {}).get(calendar_id, {}).get("busy", [])

    # Compute free periods (gaps between busy blocks)
    free_periods: list[dict[str, str]] = []
    current = day
    for period in busy_periods:
        busy_start = datetime.fromisoformat(period["start"])
        if current < busy_start:
            free_periods.append({
                "start": current.isoformat(),
                "end": busy_start.isoformat(),
            })
        current = datetime.fromisoformat(period["end"])
    if current < day_end:
        free_periods.append({
            "start": current.isoformat(),
            "end": day_end.isoformat(),
        })

    return ToolResult(data={
        "date": date,
        "busy_periods": busy_periods,
        "free_periods": free_periods,
    })
