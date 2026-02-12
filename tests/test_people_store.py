"""Tests for PeopleStore — libsql CRUD."""

import asyncio
from pathlib import Path

import pytest

from src.people.store import PeopleStore

pytestmark = pytest.mark.usefixtures("_no_turso")


@pytest.fixture
async def store(tmp_path: Path) -> PeopleStore:
    """Create a PeopleStore backed by a temp database."""
    return PeopleStore(db_path=tmp_path / "test.db")


# -- upsert / get_by_id -------------------------------------------------------


async def test_upsert_and_get(store: PeopleStore) -> None:
    await store.upsert("people/c123", "Alice Smith", "Met at conference")

    record = await store.get_by_id("people/c123")
    assert record is not None
    assert record["google_resource_id"] == "people/c123"
    assert record["display_name"] == "Alice Smith"
    assert record["notes"] == "Met at conference"
    assert record["created_at"]
    assert record["updated_at"]


async def test_upsert_updates_existing(store: PeopleStore) -> None:
    await store.upsert("people/c123", "Alice Smith", "Original notes")
    first = await store.get_by_id("people/c123")
    assert first is not None
    original_created = first["created_at"]

    # Small delay so updated_at differs
    await asyncio.sleep(0.01)
    await store.upsert("people/c123", "Alice J. Smith", "Updated notes")

    record = await store.get_by_id("people/c123")
    assert record is not None
    assert record["display_name"] == "Alice J. Smith"
    assert record["notes"] == "Updated notes"
    # created_at preserved
    assert record["created_at"] == original_created
    # updated_at changed
    assert record["updated_at"] >= original_created


# -- get_by_id not found ------------------------------------------------------


async def test_get_not_found(store: PeopleStore) -> None:
    result = await store.get_by_id("people/nonexistent")
    assert result is None


# -- search --------------------------------------------------------------------


async def test_search_by_name(store: PeopleStore) -> None:
    await store.upsert("people/c1", "Alice Smith", "notes1")
    await store.upsert("people/c2", "Bob Jones", "notes2")

    results = await store.search("Alice")
    assert len(results) == 1
    assert results[0]["display_name"] == "Alice Smith"


async def test_search_by_notes(store: PeopleStore) -> None:
    await store.upsert("people/c1", "Alice Smith", "Met at Python conference")
    await store.upsert("people/c2", "Bob Jones", "Works at Acme Corp")

    results = await store.search("conference")
    assert len(results) == 1
    assert results[0]["display_name"] == "Alice Smith"


async def test_search_no_results(store: PeopleStore) -> None:
    await store.upsert("people/c1", "Alice Smith", "notes")

    results = await store.search("zzzznonexistent")
    assert results == []


# -- delete --------------------------------------------------------------------


async def test_delete_existing(store: PeopleStore) -> None:
    await store.upsert("people/c1", "Alice Smith", "notes")

    result = await store.delete("people/c1")
    assert result is True

    record = await store.get_by_id("people/c1")
    assert record is None


async def test_delete_not_found(store: PeopleStore) -> None:
    result = await store.delete("people/nonexistent")
    assert result is False


# -- Singleton -----------------------------------------------------------------


def test_singleton_get() -> None:
    PeopleStore._reset()
    try:
        a = PeopleStore.get()
        b = PeopleStore.get()
        assert a is b
    finally:
        PeopleStore._reset()


def test_singleton_reset() -> None:
    PeopleStore._reset()
    try:
        a = PeopleStore.get()
        PeopleStore._reset()
        b = PeopleStore.get()
        assert a is not b
    finally:
        PeopleStore._reset()
