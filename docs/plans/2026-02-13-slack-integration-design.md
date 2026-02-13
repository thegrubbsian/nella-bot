# Slack Integration Design

## Goal

Add Slack as an optional, deploy-time alternative to Telegram. The owner picks one
platform via `CHAT_PLATFORM` env var. All downstream systems (LLM, tools, memory,
scheduler, webhooks) are unaffected.

## Approach

**Chat Platform Abstraction Layer** — Extract the Telegram-specific bot code into
`src/bot/telegram/`, add a parallel `src/bot/slack/` implementation, and switch
between them at startup based on config. Mirrors the existing `NotificationChannel`
pattern in `src/notifications/`.

## Configuration

New env vars:

| Variable | Required when | Description |
|----------|--------------|-------------|
| `CHAT_PLATFORM` | Always (default: `telegram`) | `"telegram"` or `"slack"` |
| `SLACK_BOT_TOKEN` | `CHAT_PLATFORM=slack` | Slack bot OAuth token (`xoxb-...`) |
| `SLACK_APP_TOKEN` | `CHAT_PLATFORM=slack` | Slack app-level token for Socket Mode (`xapp-...`) |

Existing Telegram env vars (`TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_IDS`) are only
required when `CHAT_PLATFORM=telegram`.

## File Structure

### Relocated (Telegram)

Existing `src/bot/` files move to `src/bot/telegram/`:

- `app.py` → `src/bot/telegram/app.py`
- `handlers.py` → `src/bot/telegram/handlers.py`
- `confirmations.py` → `src/bot/telegram/confirmations.py`
- `security.py` → `src/bot/telegram/security.py`

### Shared (stay at `src/bot/`)

- `main.py` — entry point, platform switch
- `session.py` — conversation history (platform-agnostic)

### New (Slack)

```
src/bot/slack/
├── __init__.py
├── app.py              # Slack Bolt app factory + run_slack()
├── handlers.py         # Message + slash command handlers
└── confirmations.py    # Block Kit approve/deny buttons

src/notifications/
└── slack_channel.py    # NotificationChannel implementation
```

## Entry Point

```python
# src/bot/main.py
def main() -> None:
    if settings.chat_platform == "slack":
        from src.bot.slack.app import run_slack
        run_slack()
    else:
        from src.bot.telegram.app import create_app
        app = create_app()
        app.run_polling()
```

## Slack Message Flow

1. User sends a DM to the Nella bot in Slack.
2. Slack Bolt (Socket Mode) receives the event — no public URL needed.
3. `handle_message()` posts a "..." placeholder via `say()`.
4. Creates `MessageContext(source_channel="slack")`.
5. Calls `generate_response()` with `on_text_delta` callback that edits the
   placeholder via `client.chat_update()` (throttled to ~1s for Slack rate limits).
6. Final edit with the complete response.
7. Background `extract_and_save()` fires.

## Commands

Slack slash commands prefixed with `nella-` to avoid collisions:

| Telegram | Slack | Behavior |
|----------|-------|----------|
| `/start` | (DM open) | No equivalent needed |
| `/clear` | `/nella-clear` | Reset conversation history |
| `/status` | `/nella-status` | Show bot status |
| `/model` | `/nella-model` | View/switch Claude model |

`ack()` called immediately on each command (Slack requires 3-second acknowledgment).

## Security

No user allowlisting for Slack. The workspace itself is the security boundary —
anyone in the workspace can DM Nella. `ALLOWED_USER_IDS` / `is_allowed()` is
Telegram-only.

Each workspace user gets their own session (keyed by DM channel ID), so
conversations are isolated per person.

## Tool Confirmations

Same pattern as Telegram but with Slack Block Kit:

- Destructive tools post a message with Approve/Deny Block Kit buttons.
- Slack Bolt `action` handler resolves an `asyncio.Future` on button click.
- 120-second timeout with auto-deny.

## Notifications

New `SlackChannel` implements `NotificationChannel`:

```python
class SlackChannel:
    name = "slack"
    
    async def send(self, user_id: str, message: str) -> bool:
        # Opens/reuses a DM and posts the message

    async def send_rich(self, user_id: str, message: str, *, buttons=None, ...) -> bool:
        # Posts with Block Kit buttons if provided
```

Registered in the Slack app factory. `DEFAULT_NOTIFICATION_CHANNEL` set to `"slack"`
when running in Slack mode.

## Slack App Lifecycle

`src/bot/slack/app.py`:

- `create_slack_app()` builds the Bolt `App`, registers handlers, initializes
  notifications (`SlackChannel` + router), starts scheduler, starts webhook server.
- `run_slack()` creates a `SocketModeHandler` and calls `handler.start()` (blocks
  like Telegram's `run_polling()`).
- Graceful shutdown stops scheduler and webhook server.

## Dependencies

`slack_bolt` and `slack_sdk` added as optional dependencies in `pyproject.toml`
(only installed when needed for Slack mode).

## What Stays Untouched

Everything below `src/bot/`:

- `src/llm/` — Claude client, prompt assembly, tool dispatch
- `src/tools/` — all tool definitions
- `src/memory/` — Mem0, automatic extraction
- `src/scheduler/` — APScheduler engine
- `src/webhooks/` — inbound webhook server
- `src/integrations/` — Google/LinkedIn OAuth
- `src/notifications/router.py` — notification routing (gains a new channel, no changes)
- `src/notifications/channels.py` — protocol definition (unchanged)
