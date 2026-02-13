# Slack Integration Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add Slack as a deploy-time alternative to Telegram, selectable via `CHAT_PLATFORM` env var.

**Architecture:** Move existing Telegram bot code into `src/bot/telegram/`, create a parallel `src/bot/slack/` using Slack Bolt (Socket Mode), and add a `SlackChannel` notification implementation. Everything below `src/bot/` (LLM, tools, memory, scheduler, webhooks) stays untouched.

**Tech Stack:** `slack_bolt` (Socket Mode), `slack_sdk`, existing `NotificationChannel` protocol.

**Design doc:** `docs/plans/2026-02-13-slack-integration-design.md`

---

### Task 1: Add Slack dependencies and config

**Files:**
- Modify: `pyproject.toml` (add optional `slack` dependency group)
- Modify: `src/config.py` (add `chat_platform`, `slack_bot_token`, `slack_app_token`)
- Modify: `.env.example` (add Slack env vars)
- Test: `tests/test_config.py`

**Step 1: Write the failing test**

Add to `tests/test_config.py`:

```python
def test_chat_platform_defaults_to_telegram() -> None:
    s = Settings()
    assert s.chat_platform == "telegram"


def test_chat_platform_slack() -> None:
    s = Settings(chat_platform="slack")
    assert s.chat_platform == "slack"


def test_slack_tokens_default_empty() -> None:
    s = Settings()
    assert s.slack_bot_token == ""
    assert s.slack_app_token == ""
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_config.py::test_chat_platform_defaults_to_telegram -v`
Expected: FAIL with `AttributeError` — `Settings` has no `chat_platform` field.

**Step 3: Implement config changes**

In `src/config.py`, add these fields to the `Settings` class:

```python
# Platform
chat_platform: str = Field(default="telegram")

# Slack
slack_bot_token: str = Field(default="")
slack_app_token: str = Field(default="")
```

In `pyproject.toml`, add an optional dependency group:

```toml
[project.optional-dependencies]
slack = [
    "slack-bolt>=1.20.0",
    "slack-sdk>=3.30.0",
]
dev = [
    "ruff>=0.8.0",
    "pytest>=8.0",
    "pytest-asyncio>=0.24.0",
]
```

In `.env.example`, add after the Telegram section:

```
# Platform — which chat interface to use ("telegram" or "slack")
CHAT_PLATFORM=telegram

# Slack (only needed when CHAT_PLATFORM=slack)
# Create a Slack app at https://api.slack.com/apps with Socket Mode enabled.
# Bot token (xoxb-...) — Bot User OAuth Token under OAuth & Permissions.
SLACK_BOT_TOKEN=
# App token (xapp-...) — generate under Basic Information → App-Level Tokens
# with connections:write scope.
SLACK_APP_TOKEN=
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add pyproject.toml src/config.py .env.example tests/test_config.py
git commit -m "feat: add Slack config fields and optional dependencies"
```

---

### Task 2: Relocate Telegram code to `src/bot/telegram/`

**Files:**
- Create: `src/bot/telegram/__init__.py`
- Move: `src/bot/app.py` → `src/bot/telegram/app.py`
- Move: `src/bot/handlers.py` → `src/bot/telegram/handlers.py`
- Move: `src/bot/confirmations.py` → `src/bot/telegram/confirmations.py`
- Move: `src/bot/security.py` → `src/bot/telegram/security.py`
- Modify: `src/bot/main.py` (update import)
- Modify: all files that import from `src.bot.app`, `src.bot.handlers`, `src.bot.confirmations`, `src.bot.security`

**Important:** `src/bot/session.py` stays at `src/bot/session.py` — it's shared by both platforms.

**Step 1: Create the `src/bot/telegram/` directory and `__init__.py`**

```bash
mkdir -p src/bot/telegram
touch src/bot/telegram/__init__.py
```

**Step 2: Move the four files**

```bash
git mv src/bot/app.py src/bot/telegram/app.py
git mv src/bot/handlers.py src/bot/telegram/handlers.py
git mv src/bot/confirmations.py src/bot/telegram/confirmations.py
git mv src/bot/security.py src/bot/telegram/security.py
```

**Step 3: Update internal imports in moved files**

In `src/bot/telegram/app.py`, update:
- `from src.bot.handlers import ...` → `from src.bot.telegram.handlers import ...`

In `src/bot/telegram/handlers.py`, update:
- `from src.bot.confirmations import ...` → `from src.bot.telegram.confirmations import ...`
- `from src.bot.security import ...` → `from src.bot.telegram.security import ...`
- `from src.bot.session import ...` stays the same (session didn't move)

In `src/bot/main.py`, update:
- `from src.bot.app import create_app` → `from src.bot.telegram.app import create_app`

**Step 4: Update test imports**

The following test files import from `src.bot.confirmations`, `src.bot.handlers`, or `src.bot.app` and need updating:

- `tests/test_confirmations.py`: `from src.bot.confirmations import ...` → `from src.bot.telegram.confirmations import ...`
- `tests/test_callback_query.py`:
  - `from src.bot.confirmations import ...` → `from src.bot.telegram.confirmations import ...`
  - `from src.bot.handlers import ...` → `from src.bot.telegram.handlers import ...`
- `tests/test_missed_tasks.py`:
  - `from src.bot.handlers import handle_callback_query` → `from src.bot.telegram.handlers import handle_callback_query`
- `tests/test_scheduler_wiring.py`:
  - `from src.bot.app import _init_scheduler` → `from src.bot.telegram.app import _init_scheduler`
  - `import src.bot.app as app_module` → `import src.bot.telegram.app as app_module`

**Step 5: Run all tests to verify nothing broke**

Run: `uv run pytest -v`
Expected: all existing tests PASS with no changes to behavior.

**Step 6: Commit**

```bash
git add -A
git commit -m "refactor: move Telegram bot code to src/bot/telegram/"
```

---

### Task 3: Update entry point for platform switching

**Files:**
- Modify: `src/bot/main.py`

**Step 1: Update `main.py` to support platform switching**

Replace the content of `src/bot/main.py` with:

```python
"""Nella bot entry point."""

import logging

from src.config import settings

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=getattr(logging, settings.log_level),
)
logger = logging.getLogger(__name__)


def main() -> None:
    """Start the bot on the configured platform."""
    if settings.chat_platform == "slack":
        from src.bot.slack.app import run_slack

        logger.info("Starting Nella on Slack...")
        run_slack()
    else:
        from src.bot.telegram.app import create_app

        allowed = settings.get_allowed_user_ids()
        if not allowed:
            logger.warning("ALLOWED_USER_IDS is empty — bot will reject all messages")
        else:
            logger.info("Allowed user IDs: %s", allowed)

        logger.info("Starting Nella on Telegram with model %s...", settings.claude_model)
        app = create_app()
        app.run_polling()


if __name__ == "__main__":
    main()
```

**Step 2: Verify Telegram path still works**

Run: `uv run pytest -v`
Expected: all PASS (Slack import only happens when `chat_platform == "slack"`, so no import error)

**Step 3: Commit**

```bash
git add src/bot/main.py
git commit -m "feat: add platform switching in entry point"
```

---

### Task 4: Widen `session.py` to accept string keys

**Files:**
- Modify: `src/bot/session.py`
- Modify: `tests/test_session.py`

Slack channel IDs are strings (e.g., `"D01ABC123"`). The current `get_session()` takes `chat_id: int`. We need to widen this to accept both.

**Step 1: Write the failing test**

Add to `tests/test_session.py`:

```python
def test_get_session_string_key() -> None:
    """Slack DM channel IDs are strings."""
    s = get_session("D01ABC123")
    assert isinstance(s, Session)
    assert get_session("D01ABC123") is s
```

**Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_session.py::test_get_session_string_key -v`
Expected: FAIL — `get_session()` expects `int`, not `str`.

**Step 3: Update `session.py`**

Change the type of `_sessions` and `get_session`:

```python
# Global session store keyed by chat_id (int for Telegram, str for Slack)
_sessions: dict[int | str, Session] = {}


def get_session(chat_id: int | str) -> Session:
    """Get or create a session for a chat."""
    if chat_id not in _sessions:
        _sessions[chat_id] = Session()
    return _sessions[chat_id]
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_session.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/bot/session.py tests/test_session.py
git commit -m "feat: widen session key to accept str for Slack channel IDs"
```

---

### Task 5: Implement `SlackChannel` notification channel

**Files:**
- Create: `src/notifications/slack_channel.py`
- Modify: `src/notifications/__init__.py`
- Create: `tests/test_slack_channel.py`

**Step 1: Write the failing tests**

Create `tests/test_slack_channel.py`:

```python
"""Tests for SlackChannel and protocol conformance."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.notifications.channels import NotificationChannel
from src.notifications.slack_channel import SlackChannel


def _make_mock_client() -> AsyncMock:
    """Create a mock slack_sdk.web.async_client.AsyncWebClient."""
    client = AsyncMock()
    client.conversations_open = AsyncMock(
        return_value={"channel": {"id": "D01ABC123"}}
    )
    client.chat_postMessage = AsyncMock(return_value={"ok": True})
    return client


def test_slack_channel_satisfies_protocol() -> None:
    client = _make_mock_client()
    ch = SlackChannel(client)
    assert isinstance(ch, NotificationChannel)


def test_name_property() -> None:
    client = _make_mock_client()
    ch = SlackChannel(client)
    assert ch.name == "slack"


async def test_send_opens_dm_and_posts() -> None:
    client = _make_mock_client()
    ch = SlackChannel(client)

    ok = await ch.send("U01XYZ", "Hello there")
    assert ok is True
    client.conversations_open.assert_awaited_once_with(users=["U01XYZ"])
    client.chat_postMessage.assert_awaited_once_with(
        channel="D01ABC123", text="Hello there"
    )


async def test_send_returns_false_on_error() -> None:
    client = _make_mock_client()
    client.conversations_open.side_effect = RuntimeError("network down")
    ch = SlackChannel(client)

    ok = await ch.send("U01XYZ", "hi")
    assert ok is False


async def test_send_rich_without_buttons() -> None:
    client = _make_mock_client()
    ch = SlackChannel(client)

    ok = await ch.send_rich("U01XYZ", "Hello")
    assert ok is True
    client.chat_postMessage.assert_awaited_once()
    call_kwargs = client.chat_postMessage.call_args.kwargs
    assert call_kwargs["text"] == "Hello"
    assert "blocks" not in call_kwargs


async def test_send_rich_with_buttons() -> None:
    client = _make_mock_client()
    ch = SlackChannel(client)

    buttons = [
        [{"text": "Yes", "callback_data": "yes"}, {"text": "No", "callback_data": "no"}],
    ]

    ok = await ch.send_rich("U01XYZ", "Pick one", buttons=buttons)
    assert ok is True
    call_kwargs = client.chat_postMessage.call_args.kwargs
    assert "blocks" in call_kwargs


async def test_send_rich_returns_false_on_error() -> None:
    client = _make_mock_client()
    client.conversations_open.side_effect = RuntimeError("boom")
    ch = SlackChannel(client)

    ok = await ch.send_rich("U01XYZ", "hi")
    assert ok is False
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_slack_channel.py -v`
Expected: FAIL — `src.notifications.slack_channel` doesn't exist yet.

**Step 3: Implement `SlackChannel`**

Create `src/notifications/slack_channel.py`:

```python
"""Slack implementation of the NotificationChannel protocol."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)


class SlackChannel:
    """Sends notifications via the Slack API."""

    def __init__(self, client: AsyncWebClient) -> None:
        self._client = client

    @property
    def name(self) -> str:
        return "slack"

    async def _open_dm(self, user_id: str) -> str | None:
        """Open (or retrieve) a DM channel with a user. Returns channel ID."""
        try:
            resp = await self._client.conversations_open(users=[user_id])
            return resp["channel"]["id"]
        except Exception:
            logger.exception("SlackChannel: failed to open DM for user_id=%s", user_id)
            return None

    async def send(self, user_id: str, message: str) -> bool:
        """Send a plain text message to a Slack user via DM."""
        channel_id = await self._open_dm(user_id)
        if not channel_id:
            return False
        try:
            await self._client.chat_postMessage(channel=channel_id, text=message)
            return True
        except Exception:
            logger.exception("SlackChannel.send failed for user_id=%s", user_id)
            return False

    async def send_rich(
        self,
        user_id: str,
        message: str,
        *,
        buttons: list[list[dict[str, str]]] | None = None,
        parse_mode: str | None = None,
    ) -> bool:
        """Send a message with optional Block Kit buttons."""
        channel_id = await self._open_dm(user_id)
        if not channel_id:
            return False
        try:
            kwargs: dict[str, Any] = {"channel": channel_id, "text": message}
            if buttons:
                elements = []
                for row in buttons:
                    for btn in row:
                        elements.append({
                            "type": "button",
                            "text": {"type": "plain_text", "text": btn["text"]},
                            "action_id": btn.get("callback_data", btn["text"]),
                            "value": btn.get("callback_data", ""),
                        })
                kwargs["blocks"] = [
                    {"type": "section", "text": {"type": "mrkdwn", "text": message}},
                    {"type": "actions", "elements": elements},
                ]
            await self._client.chat_postMessage(**kwargs)
            return True
        except Exception:
            logger.exception("SlackChannel.send_rich failed for user_id=%s", user_id)
            return False
```

Update `src/notifications/__init__.py` to include `SlackChannel`:

```python
"""Notification channel abstraction layer."""

from src.notifications.channels import NotificationChannel
from src.notifications.context import MessageContext
from src.notifications.router import NotificationRouter
from src.notifications.telegram_channel import TelegramChannel

__all__ = [
    "MessageContext",
    "NotificationChannel",
    "NotificationRouter",
    "TelegramChannel",
]

# SlackChannel is importable but not in __all__ — it's only used when CHAT_PLATFORM=slack.
# Import it directly: from src.notifications.slack_channel import SlackChannel
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_slack_channel.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/notifications/slack_channel.py src/notifications/__init__.py tests/test_slack_channel.py
git commit -m "feat: add SlackChannel notification implementation"
```

---

### Task 6: Implement Slack confirmations

**Files:**
- Create: `src/bot/slack/confirmations.py`
- Create: `tests/test_slack_confirmations.py`

**Step 1: Write the failing tests**

Create `tests/test_slack_confirmations.py`:

```python
"""Tests for Slack tool confirmations."""

import asyncio
from unittest.mock import AsyncMock

from src.bot.slack.confirmations import (
    _pending,
    get_pending,
    request_confirmation,
    resolve_confirmation,
)
from src.llm.client import PendingToolCall


def _make_pending_tool(
    name: str = "send_email",
    tool_input: dict | None = None,
    description: str = "Send an email",
) -> PendingToolCall:
    return PendingToolCall(
        tool_use_id="toolu_abc123",
        tool_name=name,
        tool_input=tool_input or {},
        description=description,
    )


def _make_mock_client() -> AsyncMock:
    client = AsyncMock()
    client.chat_postMessage = AsyncMock(
        return_value={"ts": "1234567890.123456", "channel": "D01ABC123"}
    )
    client.chat_update = AsyncMock()
    return client


def test_resolve_sets_future_true() -> None:
    loop = asyncio.new_event_loop()
    future: asyncio.Future[bool] = loop.create_future()
    from src.bot.slack.confirmations import PendingConfirmation

    pc = PendingConfirmation(
        id="aabb1122",
        channel_id="D01ABC123",
        tool_name="send_email",
        description="d",
        future=future,
    )
    _pending["aabb1122"] = pc
    try:
        ok = resolve_confirmation("aabb1122", approved=True)
        assert ok is True
        assert future.result() is True
    finally:
        _pending.pop("aabb1122", None)
        loop.close()


def test_resolve_sets_future_false() -> None:
    loop = asyncio.new_event_loop()
    future: asyncio.Future[bool] = loop.create_future()
    from src.bot.slack.confirmations import PendingConfirmation

    pc = PendingConfirmation(
        id="cc112233",
        channel_id="D01ABC123",
        tool_name="send_email",
        description="d",
        future=future,
    )
    _pending["cc112233"] = pc
    try:
        ok = resolve_confirmation("cc112233", approved=False)
        assert ok is True
        assert future.result() is False
    finally:
        _pending.pop("cc112233", None)
        loop.close()


def test_resolve_unknown_id_returns_false() -> None:
    assert resolve_confirmation("nonexistent", approved=True) is False


def test_get_pending_returns_none_for_missing() -> None:
    assert get_pending("nope") is None


async def test_request_approved() -> None:
    client = _make_mock_client()
    pending_tool = _make_pending_tool(
        tool_input={"to": "a@b.com", "subject": "Hi", "body": "Hello"}
    )

    async def _approve_soon():
        await asyncio.sleep(0.05)
        for cid, pc in list(_pending.items()):
            if pc.tool_name == "send_email":
                resolve_confirmation(cid, approved=True)
                break

    task = asyncio.create_task(_approve_soon())
    result = await request_confirmation(client, channel_id="D01ABC123", pending_tool=pending_tool)
    await task

    assert result is True
    client.chat_postMessage.assert_awaited_once()


async def test_request_denied() -> None:
    client = _make_mock_client()
    pending_tool = _make_pending_tool(name="delete_event", tool_input={"event_id": "e1"})

    async def _deny_soon():
        await asyncio.sleep(0.05)
        for cid, pc in list(_pending.items()):
            if pc.tool_name == "delete_event":
                resolve_confirmation(cid, approved=False)
                break

    task = asyncio.create_task(_deny_soon())
    result = await request_confirmation(client, channel_id="D01ABC123", pending_tool=pending_tool)
    await task

    assert result is False


async def test_request_timeout_returns_false() -> None:
    client = _make_mock_client()
    pending_tool = _make_pending_tool()

    result = await request_confirmation(
        client, channel_id="D01ABC123", pending_tool=pending_tool, timeout=0.05,
    )
    assert result is False
    client.chat_update.assert_awaited_once()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_slack_confirmations.py -v`
Expected: FAIL — module doesn't exist.

**Step 3: Implement Slack confirmations**

Create `src/bot/slack/__init__.py` (empty) and `src/bot/slack/confirmations.py`:

```python
"""Slack Block Kit confirmation for tool calls.

When Claude invokes a tool that has ``requires_confirmation=True``, the
bot sends a Block Kit message with Approve / Deny buttons and waits for
the user to click before allowing execution.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

    from src.llm.client import PendingToolCall

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 120.0


@dataclass
class PendingConfirmation:
    """An in-flight confirmation prompt waiting for the user to respond."""

    id: str
    channel_id: str
    tool_name: str
    description: str
    future: asyncio.Future[bool]
    message_ts: str | None = None
    created_at: float = field(default_factory=time.monotonic)


_pending: dict[str, PendingConfirmation] = {}


def generate_confirmation_id() -> str:
    """Return an 8-character hex string suitable for action IDs."""
    return uuid.uuid4().hex[:8]


def get_pending(confirmation_id: str) -> PendingConfirmation | None:
    """Look up a pending confirmation by ID."""
    return _pending.get(confirmation_id)


def resolve_confirmation(confirmation_id: str, *, approved: bool) -> bool:
    """Resolve a pending confirmation.

    Returns True if the confirmation was found and resolved, False otherwise.
    """
    pc = _pending.get(confirmation_id)
    if pc is None:
        return False
    if pc.future.done():
        return False
    pc.future.set_result(approved)
    return True


async def request_confirmation(
    client: AsyncWebClient,
    channel_id: str,
    pending_tool: PendingToolCall,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> bool:
    """Send a Block Kit confirmation and wait for the user's click.

    Returns True if the user approved, False on deny or timeout.
    """
    # Reuse the Telegram formatter for the summary text
    from src.bot.telegram.confirmations import format_tool_summary

    conf_id = generate_confirmation_id()
    summary = format_tool_summary(
        pending_tool.tool_name,
        pending_tool.tool_input,
        pending_tool.description,
    )

    blocks: list[dict[str, Any]] = [
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Confirm action:*\n{summary}"},
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Approve"},
                    "style": "primary",
                    "action_id": f"cfm:{conf_id}:y",
                    "value": "approve",
                },
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Deny"},
                    "style": "danger",
                    "action_id": f"cfm:{conf_id}:n",
                    "value": "deny",
                },
            ],
        },
    ]

    resp = await client.chat_postMessage(
        channel=channel_id,
        text=f"Confirm action: {summary}",
        blocks=blocks,
    )

    loop = asyncio.get_running_loop()
    future: asyncio.Future[bool] = loop.create_future()

    pc = PendingConfirmation(
        id=conf_id,
        channel_id=channel_id,
        tool_name=pending_tool.tool_name,
        description=pending_tool.description,
        future=future,
        message_ts=resp.get("ts"),
    )
    _pending[conf_id] = pc

    try:
        return await asyncio.wait_for(future, timeout=timeout)
    except TimeoutError:
        logger.info("Confirmation %s timed out", conf_id)
        try:
            await client.chat_update(
                channel=channel_id,
                ts=resp["ts"],
                text=f"Confirm action: (timed out)\n{summary}",
                blocks=[],
            )
        except Exception:
            logger.debug("Could not edit timed-out confirmation message", exc_info=True)
        return False
    finally:
        _pending.pop(conf_id, None)
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_slack_confirmations.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/bot/slack/ tests/test_slack_confirmations.py
git commit -m "feat: add Slack Block Kit tool confirmations"
```

---

### Task 7: Implement Slack message and command handlers

**Files:**
- Create: `src/bot/slack/handlers.py`
- Create: `tests/test_slack_handlers.py`

**Step 1: Write the failing tests**

Create `tests/test_slack_handlers.py`:

```python
"""Tests for Slack message handlers."""

from unittest.mock import AsyncMock, MagicMock, patch

from src.bot.slack.handlers import handle_message


def _make_say() -> AsyncMock:
    """Create a mock say() that returns a Slack message response."""
    say = AsyncMock(return_value={"ts": "1234567890.123456", "channel": "D01ABC123"})
    return say


def _make_client() -> AsyncMock:
    client = AsyncMock()
    client.chat_update = AsyncMock()
    return client


async def test_handle_message_calls_generate_response() -> None:
    event = {"text": "Hello Nella", "user": "U01XYZ", "channel": "D01ABC123"}
    say = _make_say()
    client = _make_client()

    with patch("src.bot.slack.handlers.generate_response", new_callable=AsyncMock) as mock_gen, \
         patch("src.bot.slack.handlers.extract_and_save", new_callable=AsyncMock):
        mock_gen.return_value = "Hi there!"
        await handle_message(event=event, say=say, client=client)

    say.assert_awaited_once_with("...")
    mock_gen.assert_awaited_once()


async def test_handle_message_updates_placeholder() -> None:
    event = {"text": "Hello", "user": "U01XYZ", "channel": "D01ABC123"}
    say = _make_say()
    client = _make_client()

    with patch("src.bot.slack.handlers.generate_response", new_callable=AsyncMock) as mock_gen, \
         patch("src.bot.slack.handlers.extract_and_save", new_callable=AsyncMock):
        mock_gen.return_value = "Final response"
        await handle_message(event=event, say=say, client=client)

    # Final edit with the complete response
    client.chat_update.assert_awaited()


async def test_handle_message_creates_message_context() -> None:
    event = {"text": "Hello", "user": "U01XYZ", "channel": "D01ABC123"}
    say = _make_say()
    client = _make_client()

    with patch("src.bot.slack.handlers.generate_response", new_callable=AsyncMock) as mock_gen, \
         patch("src.bot.slack.handlers.extract_and_save", new_callable=AsyncMock):
        mock_gen.return_value = "Hi"
        await handle_message(event=event, say=say, client=client)

    call_kwargs = mock_gen.call_args
    msg_context = call_kwargs.kwargs["msg_context"]
    assert msg_context.source_channel == "slack"
    assert msg_context.user_id == "U01XYZ"
    assert msg_context.conversation_id == "D01ABC123"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_slack_handlers.py -v`
Expected: FAIL — module doesn't exist.

**Step 3: Implement Slack handlers**

Create `src/bot/slack/handlers.py`:

```python
"""Slack message handlers with streaming responses."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING, Any

from src.bot.session import get_session
from src.bot.slack.confirmations import request_confirmation
from src.llm.client import generate_response
from src.llm.models import MODEL_MAP, ModelManager, friendly
from src.memory.automatic import extract_and_save
from src.notifications.context import MessageContext

if TYPE_CHECKING:
    from slack_sdk.web.async_client import AsyncWebClient

logger = logging.getLogger(__name__)

# Slack rate limits: ~1 message update per second per channel
STREAM_UPDATE_INTERVAL = 1.0


async def handle_message(
    event: dict[str, Any],
    say: Any,
    client: AsyncWebClient,
) -> None:
    """Handle an incoming DM message."""
    user_message = event.get("text", "")
    user_id = event["user"]
    channel_id = event["channel"]

    logger.info("Message from %s: %s", user_id, user_message[:80])

    session = get_session(channel_id)
    session.add("user", user_message)

    # Send placeholder
    resp = await say("...")
    msg_ts = resp["ts"]
    msg_channel = resp["channel"]
    last_edit = 0.0
    streamed_text = ""

    async def on_text_delta(delta: str) -> None:
        nonlocal streamed_text, last_edit
        streamed_text += delta
        now = time.monotonic()
        if now - last_edit >= STREAM_UPDATE_INTERVAL:
            with contextlib.suppress(Exception):
                await client.chat_update(
                    channel=msg_channel, ts=msg_ts, text=streamed_text,
                )
            last_edit = now

    msg_context = MessageContext(
        user_id=user_id,
        source_channel="slack",
        conversation_id=channel_id,
    )

    async def on_confirm(pending_tool: Any) -> bool:
        return await request_confirmation(
            client, channel_id=channel_id, pending_tool=pending_tool,
        )

    try:
        result_text = await generate_response(
            session.to_api_messages(),
            on_text_delta=on_text_delta,
            on_confirm=on_confirm,
            msg_context=msg_context,
        )

        if result_text:
            with contextlib.suppress(Exception):
                await client.chat_update(
                    channel=msg_channel, ts=msg_ts, text=result_text,
                )
            session.add("assistant", result_text)

            recent = session.to_api_messages()[-6:]
            asyncio.create_task(
                extract_and_save(
                    user_message=user_message,
                    assistant_response=result_text,
                    recent_history=recent,
                    conversation_id=channel_id,
                )
            )
        else:
            await client.chat_update(
                channel=msg_channel, ts=msg_ts, text="I got an empty response. Try again?",
            )

    except Exception:
        logger.exception("Error generating response")
        with contextlib.suppress(Exception):
            await client.chat_update(
                channel=msg_channel, ts=msg_ts, text="Something went wrong. Check the logs.",
            )


async def handle_clear_command(ack: Any, command: dict[str, Any], say: Any) -> None:
    """Handle /nella-clear — reset conversation history."""
    await ack()
    channel_id = command["channel_id"]
    session = get_session(channel_id)
    count = session.clear()
    await say(f"Cleared {count} messages. Starting fresh.")


async def handle_status_command(ack: Any, command: dict[str, Any], say: Any) -> None:
    """Handle /nella-status — show bot health info."""
    await ack()
    channel_id = command["channel_id"]
    session = get_session(channel_id)
    msg_count = len(session.messages)
    window = session.window_size
    mm = ModelManager.get()

    lines = [
        "*Nella Status*",
        f"Chat model: {friendly(mm.get_chat_model())}",
        f"Memory model: {friendly(mm.get_memory_model())}",
        f"Messages in context: {msg_count}/{window}",
        f"User: {command['user_id']}",
        "Status: online",
    ]
    await say("\n".join(lines))


async def handle_model_command(ack: Any, command: dict[str, Any], say: Any) -> None:
    """Handle /nella-model — view or switch the chat model."""
    await ack()
    mm = ModelManager.get()
    args = command.get("text", "").strip()

    if not args:
        lines = [
            f"Chat model: *{friendly(mm.get_chat_model())}*",
            f"Memory model: *{friendly(mm.get_memory_model())}*",
            f"Options: {', '.join(MODEL_MAP)}",
        ]
        await say("\n".join(lines))
        return

    name = args.lower()
    result = mm.set_chat_model(name)
    if not result:
        await say(f"Unknown model '{name}'. Valid options: {', '.join(MODEL_MAP)}")
        return

    lines = [
        f"Chat model → *{friendly(mm.get_chat_model())}*",
        f"Memory model: *{friendly(mm.get_memory_model())}*",
    ]
    await say("\n".join(lines))
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_slack_handlers.py -v`
Expected: all PASS

**Step 5: Commit**

```bash
git add src/bot/slack/handlers.py tests/test_slack_handlers.py
git commit -m "feat: add Slack message and command handlers"
```

---

### Task 8: Implement Slack app factory and lifecycle

**Files:**
- Create: `src/bot/slack/app.py`
- Create: `tests/test_slack_app.py`

**Step 1: Write the failing tests**

Create `tests/test_slack_app.py`:

```python
"""Tests for Slack app factory."""

from unittest.mock import AsyncMock, MagicMock, patch


def test_create_slack_app_returns_app() -> None:
    with patch("src.bot.slack.app.App") as MockApp, \
         patch("src.bot.slack.app.AsyncWebClient") as MockClient, \
         patch("src.bot.slack.app.settings") as mock_settings:
        mock_settings.slack_bot_token = "xoxb-test"
        mock_settings.default_notification_channel = "slack"
        mock_app = MagicMock()
        MockApp.return_value = mock_app
        MockClient.return_value = AsyncMock()

        from src.bot.slack.app import create_slack_app

        app = create_slack_app()
        assert app is mock_app
        MockApp.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_slack_app.py -v`
Expected: FAIL — module doesn't exist.

**Step 3: Implement Slack app factory**

Create `src/bot/slack/app.py`:

```python
"""Slack Bolt application factory."""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

from slack_bolt.app.async_app import AsyncApp as App
from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
from slack_sdk.web.async_client import AsyncWebClient

from src.bot.slack.confirmations import get_pending, resolve_confirmation
from src.bot.slack.handlers import (
    handle_clear_command,
    handle_message,
    handle_model_command,
    handle_status_command,
)
from src.config import settings
from src.notifications.router import NotificationRouter
from src.notifications.slack_channel import SlackChannel

if TYPE_CHECKING:
    from src.scheduler.engine import SchedulerEngine
    from src.webhooks.server import WebhookServer

logger = logging.getLogger(__name__)

_scheduler_engine: SchedulerEngine | None = None
_webhook_server: WebhookServer | None = None


def _init_notifications(client: AsyncWebClient) -> None:
    """Register notification channels and set the default."""
    router = NotificationRouter.get()
    slack_channel = SlackChannel(client)
    router.register_channel(slack_channel)
    router.set_default_channel(settings.default_notification_channel)
    logger.info(
        "Notifications initialized: channels=%s, default=%s",
        router.list_channels(),
        router.default_channel_name,
    )


def _init_scheduler() -> SchedulerEngine:
    """Create the scheduler engine — same as Telegram's version."""
    from src.llm.client import generate_response
    from src.scheduler.engine import SchedulerEngine
    from src.scheduler.executor import TaskExecutor
    from src.scheduler.missed import init_missed_task_recovery
    from src.scheduler.store import TaskStore

    store = TaskStore.get()
    router = NotificationRouter.get()

    # For Slack, there's no single "owner" — anyone in the workspace can use Nella.
    # Use empty string; scheduler tasks will need an explicit user_id.
    owner_user_id = ""

    async def _scheduler_generate(messages: list[dict]) -> str:
        return await generate_response(messages)

    executor = TaskExecutor(
        router=router,
        generate_response=_scheduler_generate,
        store=store,
        owner_user_id=owner_user_id,
    )
    engine = SchedulerEngine(store=store, executor=executor)

    from src.tools.scheduler_tools import init_scheduler_tools
    init_scheduler_tools(engine)

    init_missed_task_recovery(engine, executor, owner_user_id)

    return engine


def create_slack_app() -> App:
    """Build and configure the Slack Bolt application."""
    client = AsyncWebClient(token=settings.slack_bot_token)
    app = App(token=settings.slack_bot_token, client=client)

    _init_notifications(client)

    # Message handler — only DMs (im), ignore bot messages and message edits
    @app.event("message")
    async def _on_message(event, say, client):
        # Skip bot messages, message_changed, etc.
        if event.get("subtype"):
            return
        # Only handle DMs (channel type "im")
        if event.get("channel_type") != "im":
            return
        await handle_message(event=event, say=say, client=client)

    # Slash commands
    app.command("/nella-clear")(handle_clear_command)
    app.command("/nella-status")(handle_status_command)
    app.command("/nella-model")(handle_model_command)

    # Confirmation button handler
    _CONFIRM_RE = re.compile(r"^cfm:([a-f0-9]+):(y|n)$")

    @app.action(_CONFIRM_RE)
    async def _on_confirm_action(ack, action, say):
        await ack()
        action_id = action["action_id"]
        m = _CONFIRM_RE.match(action_id)
        if not m:
            return
        conf_id, choice = m.group(1), m.group(2)
        pc = get_pending(conf_id)
        if pc is None:
            return
        if pc.future.done():
            return
        approved = choice == "y"
        resolve_confirmation(conf_id, approved=approved)

    return app


def run_slack() -> None:
    """Start the Slack bot with Socket Mode (blocking)."""

    async def _run() -> None:
        global _scheduler_engine, _webhook_server  # noqa: PLW0603

        app = create_slack_app()

        # Start scheduler
        _scheduler_engine = _init_scheduler()
        await _scheduler_engine.start()

        from src.scheduler.missed import check_and_notify_missed_tasks
        asyncio.create_task(check_and_notify_missed_tasks())

        # Start webhook server
        from src.webhooks.server import WebhookServer
        _webhook_server = WebhookServer()
        await _webhook_server.start()

        # Start Socket Mode
        handler = AsyncSocketModeHandler(app, settings.slack_app_token)
        try:
            await handler.start_async()
        finally:
            if _webhook_server is not None:
                await _webhook_server.stop()
            if _scheduler_engine is not None:
                await _scheduler_engine.stop()

    asyncio.run(_run())
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_slack_app.py -v`
Expected: all PASS

Note: This test requires `slack_bolt` and `slack_sdk` to be installed. Install them first:
```bash
uv pip install slack-bolt slack-sdk
```

**Step 5: Commit**

```bash
git add src/bot/slack/app.py tests/test_slack_app.py
git commit -m "feat: add Slack Bolt app factory and lifecycle"
```

---

### Task 9: Update documentation

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md`
- Modify: `.env.example` (already done in Task 1)
- Modify: `scripts/functional_test_prompt.md` (if it exists — add Slack-specific test cases)

**Step 1: Update CLAUDE.md**

Add `src/bot/telegram/` and `src/bot/slack/` to the architecture tree. Update the entry point docs. Add a note about `CHAT_PLATFORM`.

**Step 2: Update README.md**

- Update the architecture diagram to show Slack as an alternative to Telegram.
- Update the Modules table: change `src/bot/` description to mention both platforms.
- Add a "Slack Setup" section under the existing Telegram setup content explaining:
  - How to create a Slack app with Socket Mode
  - Required OAuth scopes (`chat:write`, `im:history`, `im:read`, `im:write`, `commands`)
  - App-level token with `connections:write` scope
  - Setting `CHAT_PLATFORM=slack` in `.env`
- Update the "How a Message Flows" section to mention the Slack path or add a brief parallel section.
- Update the project structure tree.

**Step 3: Update functional test prompt if it exists**

Check for `scripts/functional_test_prompt.md` and add Slack test scenarios.

**Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs: add Slack integration documentation"
```

---

### Task 10: Run full test suite and verify

**Step 1: Install Slack dependencies**

```bash
uv pip install slack-bolt slack-sdk
```

**Step 2: Run the full test suite**

```bash
uv run pytest -v
```

Expected: all tests PASS, including new Slack tests and existing Telegram tests.

**Step 3: Run ruff**

```bash
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/
```

Expected: no lint or format errors.

**Step 4: Final commit (if any fixes needed)**

```bash
git add -A
git commit -m "chore: fix lint/format issues"
```
