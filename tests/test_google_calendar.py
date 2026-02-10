"""Tests for Google Calendar tools."""

from unittest.mock import MagicMock, patch

import pytest

from src.tools.base import ToolResult


def _mock_auth():
    """Create a mock GoogleAuthManager with a mock Calendar service."""
    auth = MagicMock()
    service = MagicMock()
    auth.calendar.return_value = service
    return auth, service


def _make_event(event_id: str = "ev1", summary: str = "Meeting"):
    """Build a minimal Calendar API event dict."""
    return {
        "id": event_id,
        "summary": summary,
        "start": {"dateTime": "2025-01-15T10:00:00Z"},
        "end": {"dateTime": "2025-01-15T11:00:00Z"},
        "description": "Team sync",
        "location": "Room A",
        "attendees": [{"email": "a@b.com"}],
        "hangoutLink": "https://meet.google.com/abc",
        "htmlLink": "https://calendar.google.com/event/ev1",
    }


@pytest.fixture
def cal_mock():
    auth, service = _mock_auth()
    with patch("src.tools.google_calendar._auth", return_value=auth):
        yield service


class TestListEvents:
    @pytest.mark.asyncio
    async def test_list_events(self, cal_mock):
        from src.tools.google_calendar import list_events

        cal_mock.events().list().execute.return_value = {
            "items": [_make_event()],
        }

        result = await list_events(days_ahead=7)
        assert isinstance(result, ToolResult)
        assert result.success
        assert result.data["count"] == 1
        assert result.data["events"][0]["title"] == "Meeting"
        assert result.data["events"][0]["meeting_link"] == "https://meet.google.com/abc"

    @pytest.mark.asyncio
    async def test_list_events_empty(self, cal_mock):
        from src.tools.google_calendar import list_events

        cal_mock.events().list().execute.return_value = {"items": []}

        result = await list_events()
        assert result.success
        assert result.data["count"] == 0


class TestGetTodaysSchedule:
    @pytest.mark.asyncio
    async def test_todays_schedule(self, cal_mock):
        from src.tools.google_calendar import get_todays_schedule

        cal_mock.events().list().execute.return_value = {
            "items": [_make_event()],
        }

        result = await get_todays_schedule()
        assert result.success
        assert result.data["count"] == 1


class TestCreateEvent:
    @pytest.mark.asyncio
    async def test_create_event(self, cal_mock):
        from src.tools.google_calendar import create_event

        cal_mock.events().insert().execute.return_value = {
            "id": "new_ev",
            "htmlLink": "https://calendar.google.com/event/new_ev",
        }

        result = await create_event(
            title="Lunch",
            start_time="2025-01-15T12:00:00Z",
            end_time="2025-01-15T13:00:00Z",
            description="Team lunch",
            attendees=["bob@test.com"],
            location="Cafe",
        )
        assert result.success
        assert result.data["id"] == "new_ev"
        assert result.data["title"] == "Lunch"


class TestUpdateEvent:
    @pytest.mark.asyncio
    async def test_update_event(self, cal_mock):
        from src.tools.google_calendar import update_event

        cal_mock.events().get().execute.return_value = _make_event()
        cal_mock.events().patch().execute.return_value = {
            "id": "ev1",
            "summary": "Updated Meeting",
            "htmlLink": "https://calendar.google.com/event/ev1",
        }

        result = await update_event(event_id="ev1", title="Updated Meeting")
        assert result.success
        assert result.data["title"] == "Updated Meeting"

    @pytest.mark.asyncio
    async def test_update_partial(self, cal_mock):
        from src.tools.google_calendar import update_event

        existing = _make_event()
        cal_mock.events().get().execute.return_value = existing
        cal_mock.events().patch().execute.return_value = {
            "id": "ev1",
            "summary": "Meeting",
            "htmlLink": "https://calendar.google.com/event/ev1",
        }

        # Only update location, rest should stay the same
        result = await update_event(event_id="ev1", location="Room B")
        assert result.success


class TestDeleteEvent:
    @pytest.mark.asyncio
    async def test_delete_event(self, cal_mock):
        from src.tools.google_calendar import delete_event

        cal_mock.events().delete().execute.return_value = None

        result = await delete_event(event_id="ev1")
        assert result.success
        assert result.data["deleted"] is True


class TestCheckAvailability:
    @pytest.mark.asyncio
    async def test_check_availability(self, cal_mock):
        from src.tools.google_calendar import check_availability

        cal_mock.freebusy().query().execute.return_value = {
            "calendars": {
                "primary": {
                    "busy": [
                        {"start": "2025-01-15T10:00:00+00:00", "end": "2025-01-15T11:00:00+00:00"}
                    ],
                },
            },
        }

        result = await check_availability(date="2025-01-15")
        assert result.success
        assert result.data["date"] == "2025-01-15"
        assert len(result.data["busy_periods"]) == 1
        assert len(result.data["free_periods"]) == 2  # Before and after busy block

    @pytest.mark.asyncio
    async def test_check_availability_all_free(self, cal_mock):
        from src.tools.google_calendar import check_availability

        cal_mock.freebusy().query().execute.return_value = {
            "calendars": {"primary": {"busy": []}},
        }

        result = await check_availability(date="2025-01-15")
        assert result.success
        assert len(result.data["busy_periods"]) == 0
        assert len(result.data["free_periods"]) == 1  # Whole day free
