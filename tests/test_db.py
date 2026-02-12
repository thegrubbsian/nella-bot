"""Tests for async database connection abstraction."""

from pathlib import Path

import pytest

from src.db import _AsyncConnection, get_connection

pytestmark = pytest.mark.usefixtures("_no_turso")


class TestGetConnection:
    async def test_returns_async_connection(self, tmp_path: Path):
        conn = await get_connection(local_path_override=tmp_path / "test.db")
        assert isinstance(conn, _AsyncConnection)
        await conn.close()

    async def test_creates_parent_dirs(self, tmp_path: Path):
        db_path = tmp_path / "nested" / "dir" / "test.db"
        conn = await get_connection(local_path_override=db_path)
        assert db_path.parent.exists()
        await conn.close()


class TestAsyncConnection:
    async def test_execute_and_fetchall(self, tmp_path: Path):
        conn = await get_connection(local_path_override=tmp_path / "test.db")
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        await conn.execute("INSERT INTO t (name) VALUES (?)", ("alice",))
        await conn.commit()

        cursor = await conn.execute("SELECT name FROM t")
        rows = await cursor.fetchall()
        assert rows == [("alice",)]
        await conn.close()

    async def test_execute_and_fetchone(self, tmp_path: Path):
        conn = await get_connection(local_path_override=tmp_path / "test.db")
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, val TEXT)")
        await conn.execute("INSERT INTO t (val) VALUES (?)", ("hello",))
        await conn.commit()

        cursor = await conn.execute("SELECT val FROM t WHERE id = 1")
        row = await cursor.fetchone()
        assert row == ("hello",)
        await conn.close()

    async def test_fetchone_returns_none_when_empty(self, tmp_path: Path):
        conn = await get_connection(local_path_override=tmp_path / "test.db")
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY)")

        cursor = await conn.execute("SELECT * FROM t WHERE id = 999")
        row = await cursor.fetchone()
        assert row is None
        await conn.close()

    async def test_rowcount(self, tmp_path: Path):
        conn = await get_connection(local_path_override=tmp_path / "test.db")
        await conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, name TEXT)")
        await conn.execute("INSERT INTO t (name) VALUES (?)", ("a",))
        await conn.execute("INSERT INTO t (name) VALUES (?)", ("b",))
        await conn.commit()

        cursor = await conn.execute("DELETE FROM t")
        assert cursor.rowcount == 2
        await conn.close()
