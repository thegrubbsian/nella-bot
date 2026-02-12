"""Tests for Google People tools."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.people.store import PeopleStore
from src.tools.base import ToolResult


def _mock_auth():
    """Create a mock GoogleAuthManager with a mock People API service."""
    auth = MagicMock()
    service = MagicMock()
    auth.people.return_value = service
    return auth, service


def _make_person(
    resource_name: str = "people/c123",
    given_name: str = "Alice",
    family_name: str = "Smith",
    email: str = "alice@example.com",
    phone: str = "+1234567890",
    organization: str = "Acme Corp",
    title: str = "Engineer",
    biography: str = "",
    etag: str = "etag123",
):
    """Build a minimal People API person dict."""
    person = {
        "resourceName": resource_name,
        "etag": etag,
        "names": [
            {
                "displayName": f"{given_name} {family_name}",
                "givenName": given_name,
                "familyName": family_name,
            }
        ],
        "emailAddresses": [{"value": email}],
        "phoneNumbers": [{"value": phone}],
        "organizations": [{"name": organization, "title": title}],
        "biographies": [],
        "metadata": {},
    }
    if biography:
        person["biographies"] = [{"value": biography}]
    return person


@pytest.fixture(autouse=True)
def _no_turso(monkeypatch: pytest.MonkeyPatch) -> None:
    """Ensure tests use local file, not remote Turso."""
    monkeypatch.setattr("src.config.settings.turso_database_url", "")


@pytest.fixture
def people_mock():
    auth, service = _mock_auth()
    with patch("src.tools.google_people._auth", return_value=auth):
        yield service


@pytest.fixture
async def people_store(tmp_path: Path) -> PeopleStore:
    """Create a temp PeopleStore and set it as the singleton."""
    store = PeopleStore(db_path=tmp_path / "test.db")
    PeopleStore._instance = store
    yield store
    PeopleStore._reset()


class TestSearchContacts:
    @pytest.mark.asyncio
    async def test_search_returns_results(self, people_mock):
        from src.tools.google_people import search_contacts

        people_mock.people().searchContacts().execute.return_value = {
            "results": [{"person": _make_person()}],
        }

        result = await search_contacts(query="Alice")
        assert isinstance(result, ToolResult)
        assert result.success
        assert result.data["count"] == 1
        assert result.data["contacts"][0]["name"] == "Alice Smith"
        assert result.data["contacts"][0]["email"] == "alice@example.com"

    @pytest.mark.asyncio
    async def test_search_empty_results(self, people_mock):
        from src.tools.google_people import search_contacts

        people_mock.people().searchContacts().execute.return_value = {}

        result = await search_contacts(query="nonexistent")
        assert result.success
        assert result.data["count"] == 0
        assert result.data["contacts"] == []


class TestGetContact:
    @pytest.mark.asyncio
    async def test_get_contact_without_notes(self, people_mock, people_store):
        from src.tools.google_people import get_contact

        people_mock.people().get().execute.return_value = _make_person()

        result = await get_contact(resource_name="people/c123")
        assert result.success
        assert result.data["name"] == "Alice Smith"
        assert result.data["email"] == "alice@example.com"
        assert "notes" not in result.data

    @pytest.mark.asyncio
    async def test_get_contact_with_notes(self, people_mock, people_store):
        from src.tools.google_people import get_contact

        people_mock.people().get().execute.return_value = _make_person()

        # Pre-populate notes
        await people_store.upsert("people/c123", "Alice Smith", "Met at PyCon")

        result = await get_contact(resource_name="people/c123")
        assert result.success
        assert result.data["name"] == "Alice Smith"
        assert result.data["notes"] == "Met at PyCon"
        assert "notes_updated_at" in result.data


class TestCreateContact:
    @pytest.mark.asyncio
    async def test_create_contact(self, people_mock):
        from src.tools.google_people import create_contact

        people_mock.people().createContact().execute.return_value = _make_person()

        result = await create_contact(given_name="Alice", family_name="Smith")
        assert result.success
        assert result.data["created"] is True
        assert result.data["resource_name"] == "people/c123"
        assert result.data["name"] == "Alice Smith"

    @pytest.mark.asyncio
    async def test_create_contact_with_notes(self, people_mock, people_store):
        from src.tools.google_people import create_contact

        people_mock.people().createContact().execute.return_value = _make_person()

        result = await create_contact(
            given_name="Alice", family_name="Smith", notes="Important contact"
        )
        assert result.success

        # Verify notes were saved
        record = await people_store.get_by_id("people/c123")
        assert record is not None
        assert record["notes"] == "Important contact"


class TestUpdateContact:
    @pytest.mark.asyncio
    async def test_update_contact(self, people_mock):
        from src.tools.google_people import update_contact

        people_mock.people().get().execute.return_value = _make_person()
        people_mock.people().updateContact().execute.return_value = _make_person(
            given_name="Alicia"
        )

        result = await update_contact(resource_name="people/c123", given_name="Alicia")
        assert result.success
        assert result.data["updated"] is True
        assert result.data["resource_name"] == "people/c123"

    @pytest.mark.asyncio
    async def test_update_contact_no_fields(self, people_mock):
        from src.tools.google_people import update_contact

        people_mock.people().get().execute.return_value = _make_person()

        result = await update_contact(resource_name="people/c123")
        assert not result.success
        assert "No fields to update" in result.error


class TestUpdateContactNotes:
    @pytest.mark.asyncio
    async def test_new_note_fetches_name(self, people_mock, people_store):
        from src.tools.google_people import update_contact_notes

        people_mock.people().get().execute.return_value = _make_person()

        result = await update_contact_notes(
            resource_name="people/c123", notes="New note about Alice"
        )
        assert result.success
        assert result.data["updated"] is True
        assert result.data["display_name"] == "Alice Smith"

        # Verify stored
        record = await people_store.get_by_id("people/c123")
        assert record is not None
        assert record["notes"] == "New note about Alice"

    @pytest.mark.asyncio
    async def test_update_existing_note(self, people_mock, people_store):
        from src.tools.google_people import update_contact_notes

        # Pre-populate
        await people_store.upsert("people/c123", "Alice Smith", "Old note")

        result = await update_contact_notes(
            resource_name="people/c123", notes="Updated note"
        )
        assert result.success
        assert result.data["display_name"] == "Alice Smith"

        record = await people_store.get_by_id("people/c123")
        assert record is not None
        assert record["notes"] == "Updated note"


class TestSearchContactNotes:
    @pytest.mark.asyncio
    async def test_search_found(self, people_store):
        from src.tools.google_people import search_contact_notes

        await people_store.upsert("people/c1", "Alice Smith", "Met at PyCon")
        await people_store.upsert("people/c2", "Bob Jones", "Works at Acme")

        result = await search_contact_notes(query="PyCon")
        assert result.success
        assert result.data["count"] == 1
        assert result.data["results"][0]["display_name"] == "Alice Smith"

    @pytest.mark.asyncio
    async def test_search_no_matches(self, people_store):
        from src.tools.google_people import search_contact_notes

        await people_store.upsert("people/c1", "Alice Smith", "notes")

        result = await search_contact_notes(query="zzzznonexistent")
        assert result.success
        assert result.data["count"] == 0
        assert result.data["results"] == []
