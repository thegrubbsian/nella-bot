"""Tests for the Plaud webhook handler."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.tools.base import ToolResult
from src.webhooks.handlers.plaud import (
    _analyze_transcript,
    _fetch_transcript,
    _notify_owner,
    _read_transcript,
    _save_to_memory,
    _search_transcript,
    handle_plaud,
)

# -- Helpers -----------------------------------------------------------------


def _ok_result(content: str = "transcript text") -> ToolResult:
    return ToolResult(data={"content": content})


def _fail_result() -> ToolResult:
    return ToolResult(error="not found")


class _FakeSettings:
    def __init__(self, folder_id: str = "folder123", plaud_account: str = "") -> None:
        self.plaud_drive_folder_id = folder_id
        self.plaud_google_account = plaud_account
        self.allowed_user_ids = "12345"

    def get_allowed_user_ids(self) -> set[int]:
        return {12345}


# -- _read_transcript --------------------------------------------------------


async def test_read_transcript_by_file_id() -> None:
    with (
        patch("src.tools.google_drive.read_file", new_callable=AsyncMock) as mock,
        patch("src.webhooks.handlers.plaud.settings", _FakeSettings()),
    ):
        mock.return_value = _ok_result("hello")
        result = await _read_transcript("file123")
        assert result == "hello"
        mock.assert_awaited_once_with(file_id="file123", account=None)


async def test_read_transcript_returns_none_on_failure() -> None:
    with (
        patch("src.tools.google_drive.read_file", new_callable=AsyncMock) as mock,
        patch("src.webhooks.handlers.plaud.settings", _FakeSettings()),
    ):
        mock.return_value = _fail_result()
        result = await _read_transcript("file123")
        assert result is None


# -- _search_transcript ------------------------------------------------------


async def test_search_transcript_finds_file() -> None:
    mock_service = MagicMock()
    mock_service.files().list().execute.return_value = {
        "files": [{"id": "found_id"}]
    }
    mock_auth = MagicMock()
    mock_auth.drive.return_value = mock_service

    with (
        patch("src.integrations.google_auth.GoogleAuthManager.get", return_value=mock_auth),
        patch("src.tools.google_drive.read_file", new_callable=AsyncMock) as mock_read,
        patch("src.webhooks.handlers.plaud.settings", _FakeSettings()),
    ):
        mock_read.return_value = _ok_result("found it")

        result = await _search_transcript("meeting.txt")
        assert result == "found it"
        mock_read.assert_awaited_once_with(file_id="found_id", account=None)


async def test_search_transcript_returns_none_when_not_found() -> None:
    mock_service = MagicMock()
    mock_service.files().list().execute.return_value = {"files": []}
    mock_auth = MagicMock()
    mock_auth.drive.return_value = mock_service

    with (
        patch("src.integrations.google_auth.GoogleAuthManager.get", return_value=mock_auth),
        patch("src.webhooks.handlers.plaud.settings", _FakeSettings()),
    ):
        result = await _search_transcript("missing.txt")
        assert result is None


async def test_search_scopes_to_folder_when_configured() -> None:
    mock_service = MagicMock()
    mock_service.files().list().execute.return_value = {"files": []}
    mock_auth = MagicMock()
    mock_auth.drive.return_value = mock_service

    with (
        patch("src.integrations.google_auth.GoogleAuthManager.get", return_value=mock_auth),
        patch("src.webhooks.handlers.plaud.settings", _FakeSettings("my_folder")),
        patch("src.webhooks.handlers.plaud.asyncio.to_thread") as mock_thread,
    ):
        mock_thread.return_value = {"files": []}
        await _search_transcript("test.txt")
        mock_thread.assert_awaited_once()


async def test_search_transcript_orders_by_newest() -> None:
    mock_service = MagicMock()
    mock_service.files().list().execute.return_value = {"files": []}
    mock_auth = MagicMock()
    mock_auth.drive.return_value = mock_service

    with (
        patch("src.integrations.google_auth.GoogleAuthManager.get", return_value=mock_auth),
        patch("src.webhooks.handlers.plaud.settings", _FakeSettings()),
        patch("src.webhooks.handlers.plaud.asyncio.to_thread") as mock_thread,
    ):
        mock_thread.return_value = {"files": []}
        await _search_transcript("test.txt")

        # Execute the lambda that was passed to asyncio.to_thread
        # to observe the Drive API call on the mock service.
        fn = mock_thread.call_args[0][0]
        fn()
        mock_service.files().list.assert_called_with(
            q="name = 'test.txt' and 'folder123' in parents",
            pageSize=1,
            orderBy="createdTime desc",
            fields="files(id)",
        )


async def test_search_transcript_escapes_quotes_in_name() -> None:
    mock_service = MagicMock()
    mock_service.files().list().execute.return_value = {"files": []}
    mock_auth = MagicMock()
    mock_auth.drive.return_value = mock_service

    with (
        patch("src.integrations.google_auth.GoogleAuthManager.get", return_value=mock_auth),
        patch("src.webhooks.handlers.plaud.settings", _FakeSettings()),
        patch("src.webhooks.handlers.plaud.asyncio.to_thread") as mock_thread,
    ):
        mock_thread.return_value = {"files": []}
        await _search_transcript("Dean's Meeting")

        fn = mock_thread.call_args[0][0]
        fn()
        mock_service.files().list.assert_called_with(
            q="name = 'Dean\\'s Meeting' and 'folder123' in parents",
            pageSize=1,
            orderBy="createdTime desc",
            fields="files(id)",
        )


# -- _fetch_transcript -------------------------------------------------------


async def test_fetch_uses_file_id_first() -> None:
    with patch(
        "src.webhooks.handlers.plaud._read_transcript",
        new_callable=AsyncMock,
        return_value="by id",
    ):
        result = await _fetch_transcript({"file_id": "f1", "file_name": "test.txt"})
        assert result == "by id"


async def test_fetch_falls_back_to_search() -> None:
    with (
        patch(
            "src.webhooks.handlers.plaud._read_transcript",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.webhooks.handlers.plaud._search_transcript",
            new_callable=AsyncMock,
            return_value="by search",
        ),
    ):
        result = await _fetch_transcript({"file_id": "f1", "file_name": "test.txt"})
        assert result == "by search"


async def test_fetch_retries_on_failure() -> None:
    call_count = 0

    async def _read(file_id):
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            return None
        return "found on retry"

    with (
        patch("src.webhooks.handlers.plaud._read_transcript", side_effect=_read),
        patch("src.webhooks.handlers.plaud.RETRY_DELAY", 0.01),
    ):
        result = await _fetch_transcript({"file_id": "f1"})
        assert result == "found on retry"
        assert call_count == 3


async def test_fetch_returns_none_after_all_retries() -> None:
    with (
        patch(
            "src.webhooks.handlers.plaud._read_transcript",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.webhooks.handlers.plaud._search_transcript",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch("src.webhooks.handlers.plaud.RETRY_DELAY", 0.01),
    ):
        result = await _fetch_transcript({"file_id": "f1", "file_name": "test.txt"})
        assert result is None


# -- _analyze_transcript -----------------------------------------------------


async def test_analyze_calls_claude_directly() -> None:
    with patch(
        "src.llm.client.complete_text",
        new_callable=AsyncMock,
        return_value="Summary here",
    ) as mock_complete:
        result = await _analyze_transcript("some transcript")
        assert result == "Summary here"

        mock_complete.assert_awaited_once()
        call_args = mock_complete.call_args
        messages = call_args[0][0]
        assert "some transcript" in messages[0]["content"]
        # No system kwarg — avoids Mem0 contamination
        assert "system" not in call_args.kwargs


# -- _notify_owner -----------------------------------------------------------


async def test_notify_owner_sends_to_router() -> None:
    mock_router = MagicMock()
    mock_router.send = AsyncMock(return_value=True)

    with (
        patch("src.notifications.router.NotificationRouter.get", return_value=mock_router),
        patch("src.webhooks.handlers.plaud.settings", _FakeSettings()),
    ):
        await _notify_owner("hello")
        mock_router.send.assert_awaited_once_with("12345", "hello")


# -- _save_to_memory --------------------------------------------------------


async def test_save_to_memory() -> None:
    mock_store = MagicMock()
    mock_store.add = AsyncMock(return_value=None)

    with patch("src.memory.store.MemoryStore.get", return_value=mock_store):
        await _save_to_memory("summary text", "meeting.txt", "2025-01-15")
        mock_store.add.assert_awaited_once()
        call_kwargs = mock_store.add.call_args.kwargs
        assert call_kwargs["source"] == "automatic"
        assert call_kwargs["category"] == "workstream"
        assert "meeting.txt" in call_kwargs["content"]
        assert "2025-01-15" in call_kwargs["content"]
        assert call_kwargs["metadata"]["origin"] == "plaud"


async def test_save_to_memory_without_date() -> None:
    mock_store = MagicMock()
    mock_store.add = AsyncMock(return_value=None)

    with patch("src.memory.store.MemoryStore.get", return_value=mock_store):
        await _save_to_memory("summary", "file.txt", "")
        content = mock_store.add.call_args.kwargs["content"]
        assert "file.txt" in content


# -- handle_plaud (integration) ---------------------------------------------


async def test_handle_plaud_happy_path() -> None:
    with (
        patch(
            "src.webhooks.handlers.plaud._fetch_transcript",
            new_callable=AsyncMock,
            return_value="full transcript",
        ),
        patch(
            "src.webhooks.handlers.plaud._analyze_transcript",
            new_callable=AsyncMock,
            return_value="Action items: ...",
        ),
        patch(
            "src.webhooks.handlers.plaud._notify_owner",
            new_callable=AsyncMock,
        ) as mock_notify,
        patch(
            "src.webhooks.handlers.plaud._save_to_memory",
            new_callable=AsyncMock,
        ) as mock_save,
    ):
        await handle_plaud({
            "file_name": "standup.txt",
            "file_id": "abc",
            "meeting_date": "2025-01-15",
        })

        mock_notify.assert_awaited_once()
        msg = mock_notify.call_args[0][0]
        assert "standup.txt" in msg
        assert "Action items" in msg

        mock_save.assert_awaited_once_with(
            "Action items: ...", "standup.txt", "2025-01-15",
        )


async def test_handle_plaud_notifies_when_transcript_not_found() -> None:
    with (
        patch(
            "src.webhooks.handlers.plaud._fetch_transcript",
            new_callable=AsyncMock,
            return_value=None,
        ),
        patch(
            "src.webhooks.handlers.plaud._notify_owner",
            new_callable=AsyncMock,
        ) as mock_notify,
        patch(
            "src.webhooks.handlers.plaud._analyze_transcript",
            new_callable=AsyncMock,
        ) as mock_analyze,
    ):
        await handle_plaud({"file_name": "missing.txt"})

        mock_notify.assert_awaited_once()
        msg = mock_notify.call_args[0][0]
        assert "couldn't find it" in msg
        assert "missing.txt" in msg

        mock_analyze.assert_not_awaited()


async def test_handle_plaud_without_meeting_date() -> None:
    with (
        patch(
            "src.webhooks.handlers.plaud._fetch_transcript",
            new_callable=AsyncMock,
            return_value="text",
        ),
        patch(
            "src.webhooks.handlers.plaud._analyze_transcript",
            new_callable=AsyncMock,
            return_value="summary",
        ),
        patch(
            "src.webhooks.handlers.plaud._notify_owner",
            new_callable=AsyncMock,
        ) as mock_notify,
        patch(
            "src.webhooks.handlers.plaud._save_to_memory",
            new_callable=AsyncMock,
        ),
    ):
        await handle_plaud({"file_name": "call.txt", "file_id": "x"})
        msg = mock_notify.call_args[0][0]
        assert "call.txt" in msg
        # No date in header when meeting_date is absent
        assert "()" not in msg
