"""Tests for the systemd watchdog integration."""

from __future__ import annotations

import asyncio
import socket
import sys
import tempfile
from pathlib import Path

import pytest

from src.watchdog import notify_ready, sd_notify, start_watchdog, watchdog_loop

# macOS has a 104-char limit on AF_UNIX paths; pytest tmp_path is too long.
# Use /tmp directly for a short path.
_is_linux = sys.platform == "linux"


@pytest.fixture
def sock_dir():
    """Yield a short temp directory suitable for AF_UNIX sockets."""
    d = tempfile.mkdtemp(prefix="nella_wd_", dir="/tmp")
    yield Path(d)
    import shutil

    shutil.rmtree(d, ignore_errors=True)


# -- sd_notify -----------------------------------------------------------------


def test_sd_notify_noop_without_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """When NOTIFY_SOCKET is unset, sd_notify does nothing."""
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    sd_notify("READY=1")


def test_sd_notify_sends_to_socket(monkeypatch: pytest.MonkeyPatch, sock_dir) -> None:
    """sd_notify writes the state string to the unix datagram socket."""
    sock_path = str(sock_dir / "n.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(sock_path)

    monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
    try:
        sd_notify("READY=1")
        data = server.recv(256)
        assert data == b"READY=1"
    finally:
        server.close()


@pytest.mark.skipif(not _is_linux, reason="Abstract sockets are Linux-only")
def test_sd_notify_abstract_socket(monkeypatch: pytest.MonkeyPatch) -> None:
    """Abstract socket addresses (starting with @) are converted correctly."""
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind("\0test_nella_watchdog")

    monkeypatch.setenv("NOTIFY_SOCKET", "@test_nella_watchdog")
    try:
        sd_notify("WATCHDOG=1")
        data = server.recv(256)
        assert data == b"WATCHDOG=1"
    finally:
        server.close()


def test_sd_notify_logs_on_oserror(monkeypatch: pytest.MonkeyPatch, sock_dir) -> None:
    """OSError during send is caught and logged, not raised."""
    bad_path = str(sock_dir / "nonexistent.sock")
    monkeypatch.setenv("NOTIFY_SOCKET", bad_path)
    sd_notify("READY=1")


# -- notify_ready --------------------------------------------------------------


def test_notify_ready_sends_ready(monkeypatch: pytest.MonkeyPatch, sock_dir) -> None:
    """notify_ready sends READY=1 through sd_notify."""
    sock_path = str(sock_dir / "n.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(sock_path)

    monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
    try:
        notify_ready()
        data = server.recv(256)
        assert data == b"READY=1"
    finally:
        server.close()


# -- watchdog_loop -------------------------------------------------------------


async def test_watchdog_loop_sends_pings(
    monkeypatch: pytest.MonkeyPatch, sock_dir
) -> None:
    """watchdog_loop sends WATCHDOG=1 on each iteration."""
    sock_path = str(sock_dir / "n.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(sock_path)
    server.setblocking(False)

    monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
    monkeypatch.setattr("src.watchdog._WATCHDOG_INTERVAL_SECONDS", 0.01)

    try:
        task = asyncio.create_task(watchdog_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

        messages = []
        while True:
            try:
                messages.append(server.recv(256))
            except BlockingIOError:
                break

        assert len(messages) >= 2
        assert all(m == b"WATCHDOG=1" for m in messages)
    finally:
        server.close()


# -- start_watchdog ------------------------------------------------------------


def test_start_watchdog_returns_none_without_socket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When NOTIFY_SOCKET is unset, start_watchdog returns None."""
    monkeypatch.delenv("NOTIFY_SOCKET", raising=False)
    result = start_watchdog()
    assert result is None


async def test_start_watchdog_returns_task(monkeypatch: pytest.MonkeyPatch, sock_dir) -> None:
    """When NOTIFY_SOCKET is set, start_watchdog returns a running task."""
    sock_path = str(sock_dir / "n.sock")
    server = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    server.bind(sock_path)

    monkeypatch.setenv("NOTIFY_SOCKET", sock_path)
    monkeypatch.setattr("src.watchdog._WATCHDOG_INTERVAL_SECONDS", 0.01)

    try:
        task = start_watchdog()
        assert task is not None
        assert isinstance(task, asyncio.Task)
        assert not task.done()
    finally:
        if task:
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        server.close()
