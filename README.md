# Nella

Nella is an always-on personal AI assistant that interfaces through Telegram. She uses Claude as her brain, Mem0 for persistent memory, has a task scheduling system, supports webhooks for Zapier integrations, and wires up a number of tools (Gmail, Calendar, Drive, Docs, LinkedIn, Github, etc) so she can actually do things in the real world — not just talk about them. She's single-user by design: one owner, one bot, full context.

She also has access to her own logs and source code so she can help fix issues when things go awry. All you need is a VPS :)

**New here?** See [GETTING_STARTED.md](GETTING_STARTED.md) for a step-by-step guide to setting up all the services, getting your API keys, and deploying.

## Architecture

```
                         ┌──────────────────────────────────────────┐
                         │              Claude API                  │
                         │  (streaming responses + tool calls)      │
                         └──────────┬──────────────┬───────────────┘
                                    │              │
                              responses        tool calls
                                    │              │
┌──────────┐   messages   ┌────────┴──────────────┴───────────┐
│ Telegram ├─────────────►│           LLM Client              │
│  User    │◄─────────────┤  (prompt assembly, tool loop,     │
└──────────┘  streaming   │   message context forwarding)     │
              edits       └────────┬──────────────┬───────────┘
                                   │              │
                    ┌──────────────┴──┐    ┌──────┴──────────────┐
                    │  System Prompt  │    │   Tool Registry     │
                    │                 │    │                     │
                    │  SOUL.md        │    │  Google Gmail (12)  │
                    │  USER.md        │    │  Google Calendar (7)│
                    │  + current time │    │  Google Drive (7)   │
                    │  + Mem0 recall  │    │  Google Docs (4)    │
                    └─────────────────┘    │  Google People (6)  │
                                           │  Memory (4)         │
                    ┌─────────────────┐    │  Scheduler (3)      │
                    │  Memory System  │    │  Utility (4)        │
                    │                 │    │  Files (6)          │
                    │  Mem0 (semantic) │    │  Research (3)       │
                    │                 │    │  Observability (1)  │
                    │                 │    │  GitHub (8)         │
                    │                 │    │  LinkedIn (2)       │
                    │                 │    └─────────────────────┘
                    │  SQLite (notes) │    ┌─────────────────────┐
                    │  Auto-extract   │    │ Notification Router  │
                    └─────────────────┘    │                     │
                                           │  TelegramChannel    │
                    ┌─────────────────┐    │  (future: SMS, etc.)│
                    │    Scheduler    │    └─────────────────────┘
                    │                 │
                    │  APScheduler    │    ┌─────────────────────┐
                    │  SQLite (tasks) │    │  Webhook Server     │
                    └─────────────────┘    │                     │
                                           │  aiohttp on :8443   │
                                           │  /webhooks/{source} │
                    ┌─────────────────┐    └─────────────────────┘
                    │  External       │               │
                    │  Services       ├───────────────┘
                    │                 │    POST + X-Webhook-Secret
                    │  Zapier, Plaud  │
                    └─────────────────┘
```

### Modules

| Module | What it does | When to look here |
|--------|-------------|-------------------|
| `src/bot/` | Telegram bot setup, message handlers, session management, user security | You want to change how messages are received or how the bot responds |
| `src/llm/` | Claude API client, system prompt assembly, model switching | You want to change how Claude is called, what it sees, or the tool-calling loop |
| `src/memory/` | Mem0 integration, automatic memory extraction, data models | You want to change how Nella remembers things |
| `src/browser/` | Playwright browser automation — headless Chromium agent for JS-heavy sites | You want to change how interactive browsing works |
| `src/tools/` | Tool registry, all 63 tool implementations, base classes | You want to add a new tool or modify an existing one |
| `src/integrations/` | Google OAuth multi-account manager, LinkedIn OAuth | You want to add a new Google API, add an account, or fix auth issues |
| `src/notifications/` | Channel protocol, message routing, Telegram channel | You want to add a new delivery channel (SMS, voice, etc.) |
| `src/scheduler/` | APScheduler engine, task store, executor, data models | You want to change how scheduled/recurring tasks work |
| `src/webhooks/` | Inbound HTTP server, handler registry, per-integration handlers | You want to receive webhooks from external services (Zapier, Plaud, etc.) |
| `config/` | Markdown files that define personality, user profile, memory rules. `.md.EXAMPLE` files are templates checked into git; actual `.md` files are gitignored. | You want to change how Nella behaves or what she knows about you |

### How a Message Flows

Here's what happens when you send "What's on my calendar today?" in Telegram:

1. **Telegram delivers the update** to `python-telegram-bot`, which routes it to `handle_message()` in `src/bot/handlers.py`.

2. **Security check.** `is_allowed()` verifies your Telegram user ID is in `ALLOWED_USER_IDS`. If not, the message is silently ignored.

3. **Session lookup.** `get_session(chat_id)` returns your in-memory conversation history (a sliding window of the last 50 messages by default).

4. **Your message is added** to the session: `session.add("user", "What's on my calendar today?")`.

5. **A placeholder reply** (`"..."`) is sent immediately so you see Nella is thinking.

6. **A `MessageContext` is created** with your user ID, `source_channel="telegram"`, and `conversation_id`. This travels through the entire call chain so any component knows where to send output.

7. **`generate_response()` is called** in `src/llm/client.py`. This is where the real work happens:
   - **System prompt assembly** (`src/llm/prompt.py`): reads `SOUL.md` and `USER.md`, injects the current time and timezone, then searches Mem0 for memories related to your message. These are combined into a system prompt with caching so the static parts aren't re-processed on every tool-calling round.
   - **Claude API call**: sends your conversation history + system prompt + all 67 tool schemas to Claude via streaming.
   - **Streaming**: as text chunks arrive, the `on_text_delta` callback edits the placeholder message in Telegram (throttled to every 0.5 seconds to stay under rate limits).

8. **If Claude calls a tool** (in this case, probably `get_todays_schedule`):
   - The tool-calling loop picks up the `tool_use` block from Claude's response.
   - `registry.execute()` looks up the tool, validates params, and runs it. If the tool's function signature includes `msg_context`, it's injected automatically.
   - The `ToolResult` is sent back to Claude as a `tool_result` message.
   - Claude generates a new response incorporating the tool output.
   - This loop can run up to 10 rounds (for multi-step tasks).

9. **Final response** is edited into the Telegram message, replacing the streamed text.

10. **Session updated**: `session.add("assistant", result_text)`.

11. **Background memory extraction**: `extract_and_save()` fires as an async task (non-blocking). It sends the exchange to Claude Haiku with the rules from `MEMORY_RULES.md`, extracts facts/preferences/action items, and saves the important ones to Mem0.

### How the Memory System Works

Nella has two memory pathways:

**Automatic ("unconscious") memory** runs after every exchange. A separate Claude Haiku call analyzes the conversation using rules in `config/MEMORY_RULES.md` and extracts anything worth remembering — facts about you, project context, action items, decisions. Only medium and high importance items get saved. This happens in the background and never slows down your response.

**Explicit ("conscious") memory** is triggered by Claude during conversation through four tools:
- `remember_this` — "I should save this fact"
- `recall` — "Let me search my memory for this"
- `forget_this` — "Delete memories matching this query"
- `save_reference` — "Save this URL/document for later"

Both pathways store to Mem0 (a hosted semantic memory service). When building the system prompt, Nella searches Mem0 for memories relevant to your current message and includes them in the context Claude sees.

### How Task Scheduling Works

Nella can schedule tasks to run at a specific time or on a recurring schedule. Claude has three scheduling tools: `schedule_task`, `list_scheduled_tasks`, and `cancel_scheduled_task`.

**Task types:**
- **One-off** — runs once at a specific datetime, then auto-deactivates. Schedule is `{"run_at": "ISO 8601"}`.
- **Recurring** — runs on a cron schedule. Schedule is `{"cron": "0 8 * * *"}` (crontab string) or individual fields like `{"hour": 9, "minute": 0}`.

**Action types:**
- **`simple_message`** — sends a plain text message to the owner via the notification router. Good for reminders.
- **`ai_task`** — runs a prompt through the full LLM pipeline (with tool access) and sends the result. Good for tasks like "check my email and summarize anything important."

**Lifecycle:**
1. On bot startup, `SchedulerEngine.start()` loads all active tasks from SQLite and creates APScheduler jobs for each.
2. When a task fires, the executor looks it up, dispatches to the correct handler, and updates `last_run_at`.
3. One-off tasks are automatically deactivated after execution. Recurring tasks update their `next_run_at`.
4. On bot shutdown, `SchedulerEngine.stop()` shuts down APScheduler gracefully.

Tasks are persisted in the `scheduled_tasks` table in the same SQLite database used for notes. The scheduler engine uses APScheduler's `AsyncIOScheduler` with the timezone from `SCHEDULER_TIMEZONE` (default: `America/Chicago`). Notifications are routed through the same `NotificationRouter` used by the rest of the system, so tasks can target any registered channel.

### How Webhooks Work

Nella runs a lightweight HTTP server (aiohttp) alongside the Telegram polling bot, sharing the same asyncio event loop. This lets external services like Zapier, Plaud, or GitHub push data to Nella in real time.

**Request flow:**
1. An external service sends `POST /webhooks/{source}` with a JSON body and an `X-Webhook-Secret` header.
2. The server validates the secret against `WEBHOOK_SECRET` in `.env`. Invalid or missing secrets get a 401.
3. The source name (e.g., `plaud`, `github`) is looked up in the `WebhookRegistry`. If no handler is registered for that source, the server returns 404.
4. The server returns 200 immediately — the handler runs in the background via `asyncio.create_task` so the caller (Zapier, etc.) isn't kept waiting.
5. The handler processes the payload asynchronously. Any errors are logged but don't affect the HTTP response.

**Key details:**
- **Port**: configurable via `WEBHOOK_PORT` (default 8443). The VPS firewall must allow inbound traffic on this port (`sudo ufw allow 8443/tcp`).
- **Disabled by default**: if `WEBHOOK_SECRET` is empty, the server doesn't start. No open ports, no attack surface.
- **Health check**: `GET /health` returns `{"status": "ok"}` — useful for uptime monitoring.
- **Lifecycle**: starts in `_post_init` (after the Telegram app is ready), stops in `_post_shutdown` (graceful cleanup).

**Adding a new webhook handler:**

Create a file in `src/webhooks/handlers/` (e.g., `plaud.py`):

```python
from src.webhooks.registry import webhook_registry

@webhook_registry.handler("plaud")
async def handle_plaud(payload: dict) -> None:
    # Process the incoming data
    ...
```

Then import it in `src/webhooks/handlers/__init__.py` so it registers on startup. The handler will receive any POST to `/webhooks/plaud` that passes secret validation.

### How Plaud Transcript Processing Works

Nella's first webhook integration processes meeting transcripts from Plaud (a meeting recorder). The flow is: Plaud records a meeting → transcript lands in Google Drive → Zapier detects the new file and POSTs to `/webhooks/plaud` → Nella processes it.

**What the handler does:**
1. Receives the payload from Zapier (contains `file_id`, `file_name`, `folder_name`, `meeting_date`).
2. Reads the transcript from Google Drive — tries `file_id` first, falls back to searching by `file_name` in the configured `PLAUD_DRIVE_FOLDER_ID` folder.
3. If Drive hasn't synced yet (race condition with Zapier), retries up to 3 times with 30-second delays.
4. Sends the transcript to Claude with a prompt that asks for: a brief summary, action items organized by owner, decisions made, and follow-ups/deadlines.
5. Sends the formatted result to the owner via Telegram.
6. Saves the summary to Mem0 (category: `workstream`, origin: `plaud`) so Nella has context for future conversations about the meeting.

If the transcript isn't found after all retries, the owner gets a notification explaining the issue.

**Setup:**
1. Set `PLAUD_DRIVE_FOLDER_ID` in `.env` to the Google Drive folder where Zapier drops transcripts.
2. Set `WEBHOOK_SECRET` in `.env` (the Zapier webhook must send this in the `X-Webhook-Secret` header).
3. Create a Zapier zap: trigger on new file in the Plaud Drive folder → POST to `https://your-vps:8443/webhooks/plaud` with the file metadata as JSON.

### How Tool Calling Works

Claude has access to 63 tools organized into categories. When Claude decides it needs to call a tool:

1. Claude returns a `tool_use` content block with the tool name and arguments.
2. The registry validates the arguments against a Pydantic model (if one is defined).
3. The tool handler runs asynchronously. Google API calls are wrapped in `asyncio.to_thread()` because the Google client library is synchronous.
4. The result (`ToolResult`) is serialized to JSON and sent back to Claude.
5. Claude incorporates the result into its response.

Tools opt into receiving `MessageContext` by adding it to their function signature — the registry uses introspection to detect this. Existing tools don't need any changes.

**Tool confirmation.** Tools that perform destructive or externally-visible actions (sending email, deleting files, creating calendar events, etc.) set `requires_confirmation=True`. When Claude calls one of these tools, the bot sends a separate Telegram message with an inline keyboard showing **Approve** and **Deny** buttons. The user has 120 seconds to tap; if they don't, the action is automatically denied. Any text Claude generated alongside the tool call is retracted from the final response — since Claude writes that text before knowing the outcome, it often claims premature success. After the tool executes, Claude generates a fresh response reflecting the actual result.

### Configuration Files

The `config/` directory contains markdown files that shape Nella's behavior:

| File | Purpose | Effect |
|------|---------|--------|
| `SOUL.md` | Nella's personality, tone, and behavioral rules | Loaded into every system prompt. Changing this changes how Nella talks and acts. |
| `USER.md` | Owner profile — your name, timezone, preferences, work info | Loaded into every system prompt. Fill this in so Nella knows about you. |
| `MEMORY.md` | Explicit long-term facts you want Nella to always know | Human-editable memory store. Edit directly when you want to add/remove persistent facts. |
| `MEMORY_RULES.md` | Rules for the automatic memory extraction system | Controls what the background extraction picks up. Change this if Nella is remembering too much or too little. |

The actual `.md` files are gitignored (they contain personal data). The repo ships `.md.EXAMPLE` templates — copy them to get started:

```bash
for f in config/*.md.EXAMPLE; do cp "$f" "${f%.EXAMPLE}"; done
```

These are just markdown files. Edit them in any text editor. Changes take effect on the next message (no restart needed for `SOUL.md`, `USER.md`, `MEMORY_RULES.md`; the bot reads them fresh each time).

## Project Structure

```
nellabot/
├── src/
│   ├── bot/
│   │   ├── main.py                  # Entry point — starts the bot
│   │   ├── app.py                   # Telegram Application factory, handler registration
│   │   ├── handlers.py              # /start, /clear, /status, /model, message handler
│   │   ├── confirmations.py         # Inline keyboard tool confirmation (Approve/Deny)
│   │   ├── session.py               # In-memory conversation history (sliding window)
│   │   └── security.py              # User allowlist check
│   ├── llm/
│   │   ├── client.py                # Claude API: generate_response() (full pipeline) + complete_text() (bare call)
│   │   ├── prompt.py                # System prompt builder (SOUL + USER + current time + memories)
│   │   └── models.py                # ModelManager — runtime model switching
│   ├── memory/
│   │   ├── store.py                 # MemoryStore singleton (Mem0 client wrapper)
│   │   ├── automatic.py             # Background memory extraction pipeline
│   │   └── models.py                # MemoryEntry, ConversationMessage pydantic models
│   ├── integrations/
│   │   ├── google_auth.py           # GoogleAuthManager multi-account registry (OAuth + service builders)
│   │   └── linkedin_auth.py         # LinkedInAuth single-account manager (OAuth + token refresh)
│   ├── people/
│   │   ├── __init__.py              # Package init
│   │   └── store.py                 # PeopleStore — libsql CRUD for people_notes
│   ├── browser/
│   │   ├── __init__.py              # Package init
│   │   ├── session.py               # BrowserSession — Playwright lifecycle (headless Chromium)
│   │   └── agent.py                 # BrowserAgent — autonomous vision-based navigation loop
│   ├── watchdog.py                      # Systemd watchdog integration (sd_notify, READY, WATCHDOG pings)
│   ├── db.py                            # Async wrapper over libsql (local SQLite or remote Turso)
│   ├── scratch.py                       # ScratchSpace — sandboxed local filesystem for temp files
│   ├── tools/
│   │   ├── __init__.py              # Imports all tool modules (conditional Google loading)
│   │   ├── registry.py              # ToolRegistry — decorator & class-based registration
│   │   ├── base.py                  # ToolResult, ToolParams, GoogleToolParams, BaseTool
│   │   ├── google_gmail.py          # 12 tools: search, read, read_thread, send, reply, archive, archive_emails, mark_as_read, mark_as_unread, add_label, remove_label, download_attachment
│   │   ├── google_calendar.py       # 7 tools: list, today, date_range, create, update, delete, availability
│   │   ├── google_drive.py          # 7 tools: search, list recent, list folder, read, delete, download, upload
│   │   ├── google_docs.py           # 4 tools: read, create, update, append
│   │   ├── google_people.py         # 6 tools: search, get, create, update contacts + local notes
│   │   ├── memory_tools.py          # 4 tools: remember, forget, recall, save_reference
│   │   ├── scheduler_tools.py       # 3 tools: schedule, list, cancel scheduled tasks
│   │   ├── scratch_tools.py         # 6 tools: scratch_write, scratch_read, scratch_list, scratch_delete, scratch_wipe, scratch_download
│   │   ├── github_tools.py          # 8 tools: get_repo, list_directory, read_file, search_code, list_commits, get_commit, list_issues, get_issue
│   │   ├── linkedin_tools.py        # 2 tools: create_post, post_comment
│   │   ├── log_tools.py             # 1 tool: query production logs (SolarWinds/Papertrail)
│   │   ├── browser_tools.py          # 1 tool: browse_web (Playwright interactive browsing)
│   │   ├── web_tools.py             # 2 tools: web_search (Brave), read_webpage (content extraction)
│   │   └── utility.py               # 4 tools: get_current_datetime, save_note, search_notes, delete_note
│   ├── notifications/
│   │   ├── __init__.py              # Package exports
│   │   ├── channels.py              # NotificationChannel protocol
│   │   ├── context.py               # MessageContext dataclass
│   │   ├── router.py                # NotificationRouter singleton
│   │   └── telegram_channel.py      # Telegram implementation
│   ├── scheduler/
│   │   ├── __init__.py              # Package exports
│   │   ├── models.py                # ScheduledTask dataclass, make_task_id()
│   │   ├── store.py                 # TaskStore — libsql CRUD for scheduled_tasks
│   │   ├── executor.py              # TaskExecutor — dispatches simple_message and ai_task
│   │   ├── engine.py                # SchedulerEngine — APScheduler lifecycle and job management
│   │   └── missed.py                # Missed task recovery — detect and notify on startup
│   ├── webhooks/
│   │   ├── __init__.py              # Package exports
│   │   ├── server.py                # aiohttp server — lifecycle, routing, secret validation
│   │   ├── registry.py              # WebhookRegistry — @handler decorator for named sources
│   │   └── handlers/                # One file per integration
│   │       ├── __init__.py          # Imports handler modules so they auto-register
│   │       └── plaud.py             # Plaud transcript processing (Drive → Claude → Telegram)
│   └── config.py                    # Settings class (pydantic-settings, loads .env)
│
├── config/
│   ├── SOUL.md.EXAMPLE              # Nella's personality (template)
│   ├── USER.md.EXAMPLE              # Owner profile (template — fill this in)
│   ├── MEMORY.md.EXAMPLE            # Explicit long-term facts (template)
│   └── MEMORY_RULES.md.EXAMPLE      # Auto-extraction rules (template)
│   # Copy .EXAMPLE → .md and customize. Actual .md files are gitignored.
│
├── tests/                           # 606 tests
│   ├── test_google_*.py             # Google auth + integrations (6 files)
│   ├── test_linkedin_*.py           # LinkedIn tools
│   ├── test_github_*.py             # GitHub tools
│   ├── test_people_store.py         # PeopleStore CRUD
│   ├── test_notification_*.py       # Notification system (3 files)
│   ├── test_memory_*.py             # Memory system (2 files)
│   ├── test_scheduler_*.py          # Scheduler system (7 files, includes missed tasks)
│   ├── test_complete_text.py         # Bare LLM call (complete_text)
│   ├── test_generate_response.py    # Full LLM pipeline (text retraction, confirmation rounds)
│   ├── test_config.py               # Settings (pydantic-settings)
│   ├── test_db.py                   # Database connection wrapper
│   ├── test_confirmations.py        # Tool confirmation flow + enrichers
│   ├── test_callback_query.py       # Inline keyboard callbacks
│   ├── test_webhook_*.py            # Webhook registry + server (2 files)
│   ├── test_plaud_handler.py        # Plaud transcript processing
│   ├── test_registry.py             # Tool registry
│   ├── test_automatic.py            # Memory extraction
│   ├── test_prompt.py               # System prompt + current time injection
│   ├── test_session.py              # Conversation sessions
│   ├── test_security.py             # User allowlist
│   ├── test_models.py               # Model switching
│   ├── test_log_tools.py            # Log query tool
│   ├── test_browser_session.py       # Browser session lifecycle
│   ├── test_browser_agent.py        # Browser agent navigation loop
│   ├── test_browser_tools.py        # Browser automation tool
│   ├── test_watchdog.py             # Systemd watchdog integration
│   ├── test_web_tools.py            # Web research tools
│   ├── test_scratch.py              # ScratchSpace filesystem
│   ├── test_scratch_tools.py        # Scratch space tools
│   └── test_utility.py              # Utility tools
│
├── scripts/
│   ├── google_auth.py               # One-time OAuth browser flow (--account flag required)
│   ├── linkedin_auth.py             # One-time OAuth browser flow for LinkedIn
│   ├── functional_test_prompt.md    # Live functional test — paste into Telegram after code changes
│   ├── init_mem0_dir.py             # Pre-create Mem0 config dir for systemd
│   ├── deploy.sh                    # Automated deploy to VPS (full or --quick)
│   ├── logs.py                      # Query production logs via SolarWinds Observability API
│   └── test_mem0.py                 # Diagnostic script for Mem0 connectivity
│
├── nella.service                    # systemd unit file for deployment
├── pyproject.toml                   # Dependencies, build config, tool settings
├── CLAUDE.md                        # Instructions for Claude Code
├── .env.example                     # Template for environment variables
└── data/
    ├── nella.db                     # SQLite database (notes + scheduled_tasks, created at runtime)
    └── scratch/                     # Temporary working files (created at runtime)
```

## Prerequisites

**Python 3.12 or newer.** Check with `python3 --version`. If you're on a Mac, `brew install python@3.12` works. On Ubuntu/Debian: `sudo apt install python3.12`.

**uv** — the package manager. Think of it as the Python equivalent of `bundler` (Ruby) or `npm` (JS). It handles virtual environments and dependency installation in one tool.

```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh
```

After installing, restart your terminal so `uv` is on your PATH.

**A quick note on virtual environments:** Python doesn't install packages globally by default (well, it shouldn't). A virtual environment is an isolated set of installed packages for your project — like `node_modules` but for Python. `uv` creates and manages this automatically in a `.venv/` directory. You never need to activate it manually; `uv run` handles that.

## Local Development Setup

### 1. Clone and install dependencies

```bash
git clone <your-repo-url> nellabot
cd nellabot
uv sync --all-extras
```

`uv sync` reads `pyproject.toml` (think `package.json` or `Gemfile`), creates a virtual environment in `.venv/`, and installs everything. The `--all-extras` flag also installs dev dependencies (ruff, pytest).

### 2. Set up environment variables

```bash
cp .env.example .env
```

Then edit `.env` with your actual values:

| Variable | Required | Description |
|----------|----------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | Get this from [@BotFather](https://t.me/BotFather) on Telegram |
| `ALLOWED_USER_IDS` | Yes | Comma-separated Telegram user IDs. Only these users can talk to Nella. Find yours by messaging [@userinfobot](https://t.me/userinfobot) |
| `ANTHROPIC_API_KEY` | Yes | Your Claude API key from [console.anthropic.com](https://console.anthropic.com) |
| `CLAUDE_MODEL` | No | Full model ID. Default: `claude-sonnet-4-5-20250929` |
| `DEFAULT_CHAT_MODEL` | No | Friendly name: `haiku`, `sonnet`, or `opus`. Default: `sonnet` |
| `DEFAULT_MEMORY_MODEL` | No | Model for memory extraction. Default: `haiku` |
| `GOOGLE_CREDENTIALS_PATH` | No | Path to Google OAuth credentials file. Default: `credentials.json` |
| `GOOGLE_ACCOUNTS` | No | Comma-separated named accounts (e.g. `work,personal`). Token files: `auth_tokens/google_{name}_auth_token.json`. Google tools are disabled when empty. |
| `GOOGLE_DEFAULT_ACCOUNT` | No | Account used when a tool call omits `account`. Defaults to the first entry in `GOOGLE_ACCOUNTS`. |
| `PLAUD_GOOGLE_ACCOUNT` | No | Which Google account to use for Plaud transcript access (webhook handler runs without Claude reasoning). |
| `MEM0_API_KEY` | No | Mem0 API key from [app.mem0.ai](https://app.mem0.ai). If empty, memory features are disabled (Nella still works, just without long-term memory) |
| `DATABASE_PATH` | No | SQLite database path. Default: `data/nella.db` |
| `TURSO_DATABASE_URL` | No | Remote libSQL database URL. When set, overrides local `DATABASE_PATH`. Create at [turso.tech](https://turso.tech). |
| `TURSO_AUTH_TOKEN` | No | Auth token for remote Turso database. |
| `CONVERSATION_WINDOW_SIZE` | No | Max messages kept in context. Default: `50` |
| `MEMORY_EXTRACTION_ENABLED` | No | Enable background memory extraction. Default: `true` |
| `DEFAULT_NOTIFICATION_CHANNEL` | No | Default channel for outbound messages. Default: `telegram` |
| `SCHEDULER_TIMEZONE` | No | IANA timezone for scheduled tasks. Default: `America/Chicago` |
| `WEBHOOK_PORT` | No | Port for the inbound webhook HTTP server. Default: `8443` |
| `WEBHOOK_SECRET` | No | Shared secret for webhook authentication (checked via `X-Webhook-Secret` header). Server is disabled when empty. |
| `NGROK_AUTHTOKEN` | No | ngrok auth token from [dashboard.ngrok.com](https://dashboard.ngrok.com). Used by the deploy script to set up an HTTPS tunnel for webhooks. |
| `NGROK_DOMAIN` | No | ngrok free static domain (e.g. `your-subdomain.ngrok-free.dev`). Claim one at [dashboard.ngrok.com/domains](https://dashboard.ngrok.com/domains). |
| `PLAUD_DRIVE_FOLDER_ID` | No | Google Drive folder ID where Zapier drops Plaud transcripts. Used to scope transcript search. |
| `SCRATCH_DIR` | No | Directory for temporary working files. Default: `data/scratch` |
| `BRAVE_SEARCH_API_KEY` | No | Brave Search API key. Enables `web_search` and `read_webpage` tools. Get a free key at [brave.com/search/api](https://brave.com/search/api/) (2,000 queries/month free tier). |
| `PAPERTRAIL_API_TOKEN` | No | SolarWinds Observability API Access token. Enables the `query_logs` tool. Get from [SolarWinds Observability](https://my.na-01.cloud.solarwinds.com). |
| `PAPERTRAIL_API_URL` | No | SolarWinds API base URL. Default: `https://api.na-01.cloud.solarwinds.com` |
| `PAPERTRAIL_INGESTION_TOKEN` | No | SolarWinds Observability Ingestion token. Used by the deploy script to configure rsyslog forwarding. Different from the API token — create one under API Tokens → Ingestion. |
| `GITHUB_TOKEN` | No | Fine-grained GitHub PAT. Enables 8 read-only GitHub tools. Needs "Contents" read + "Issues" read. Get one at [github.com/settings/tokens](https://github.com/settings/tokens?type=beta). |
| `NELLA_SOURCE_REPO` | No | Nella's own source code repo (`owner/repo` format). Injected into the system prompt for self-debugging. |
| `LINKEDIN_CLIENT_ID` | No | LinkedIn OAuth client ID. Required for LinkedIn tools (`create_post`, `post_comment`). Create an app at [linkedin.com/developers](https://www.linkedin.com/developers/apps). |
| `LINKEDIN_CLIENT_SECRET` | No | LinkedIn OAuth client secret. |
| `BROWSER_ENABLED` | No | Enable the `browse_web` tool (Playwright). Requires Chromium: `uv run playwright install chromium`. Default: `false` |
| `BROWSER_MODEL` | No | Claude model for browser vision agent (friendly name). Default: `sonnet` |
| `BROWSER_TIMEOUT_MS` | No | Page navigation timeout in milliseconds. Default: `30000` |
| `BROWSER_MAX_STEPS` | No | Max navigation steps per browse_web call. Default: `15` |
| `LOG_LEVEL` | No | `DEBUG`, `INFO`, `WARNING`, or `ERROR`. Default: `INFO` |

### 3. Set up Google OAuth (optional)

If you want Gmail, Calendar, Drive, Docs, and Contacts access:

1. Go to [Google Cloud Console](https://console.cloud.google.com), create a project.
2. Enable the Gmail API, Calendar API, Drive API, Docs API, and People API.
3. Create OAuth 2.0 credentials (Desktop application type).
4. Download the credentials JSON file and save it as `credentials.json` in the project root.
5. Set `GOOGLE_ACCOUNTS` in your `.env` (e.g. `GOOGLE_ACCOUNTS=work,personal`).
6. Run the auth flow for each account:

```bash
uv run python scripts/google_auth.py --account work
uv run python scripts/google_auth.py --account personal
```

Each command opens a browser for you to authorize the corresponding Google account. Tokens are saved to `auth_tokens/google_work_auth_token.json`, `auth_tokens/google_personal_auth_token.json`, etc. Google tools automatically load when at least one token file exists.

All 32 Google tools accept an optional `account` parameter. Claude picks the right account based on conversational context (the system prompt tells it which accounts are available). When `account` is omitted, the default from `GOOGLE_DEFAULT_ACCOUNT` is used.

If you skip this step, Nella works fine — she just won't have Google tools available.

### 4. Run the bot

```bash
uv run python -m src.bot.main
```

The `-m` flag tells Python to run `src.bot.main` as a module. This matters because of how Python resolves imports — without it, the `src.` prefix in imports wouldn't work. Think of it like `bundle exec` in Ruby.

You should see log output confirming the bot started. Send it a message on Telegram.

### 5. Run tests

```bash
uv run pytest
```

For verbose output (shows each test name):

```bash
uv run pytest -v
```

To run a specific test file:

```bash
uv run pytest tests/test_registry.py
```

Tests use `pytest-asyncio` with `asyncio_mode = "auto"`, which means async test functions are automatically detected and run with an event loop. You don't need to decorate them.

### 6. Functional testing

After major code changes (especially tool changes), you can run a live functional test by sending Nella the prompt in `scripts/functional_test_prompt.md`. Copy everything below the `---` line and paste it into Telegram.

The prompt exercises all 67 tools one at a time, cleaning up after itself (deleting test notes, events, files, etc.). Tools that require confirmation will pop up Approve/Deny buttons — approve them all. If a tool is disabled (missing API key or token), Nella reports "DISABLED" and moves on. At the end she produces a summary table with PASS/FAIL/DISABLED for each scenario.

LinkedIn tools are skipped (posts are public and can't be undone). `scratch_wipe` is also skipped to avoid deleting real working files.

### 7. Lint

```bash
uv run ruff check src/ tests/
```

To auto-fix what it can:

```bash
uv run ruff check --fix src/ tests/
```

Ruff is a Python linter (like rubocop or eslint). The rules are configured in `pyproject.toml` under `[tool.ruff.lint]`.

## Deployment

Nella runs on a Linux VPS as a systemd service.

### Automated deploy

The deploy script handles everything — system setup, code sync, secrets, dependencies, service install, ngrok configuration, and restart with health check:

```bash
# Full deploy (first time or after system changes)
bash scripts/deploy.sh root@your-vps

# Quick deploy (code-only — skips system setup and deps)
bash scripts/deploy.sh root@your-vps --quick
```

The script reads `.env` and `auth_tokens/` from the project root.

If `NGROK_AUTHTOKEN` and `NGROK_DOMAIN` are set in your `.env`, the script automatically configures ngrok as a systemd service to provide an HTTPS tunnel for webhooks (so external services like Zapier can reach the webhook server).

### The systemd service

The file `nella.service` is a unit file that tells Linux how to run Nella as a background service. It's like a process manager (think `pm2` for Node or `foreman` for Ruby).

```bash
# Copy the service file
sudo cp nella.service /etc/systemd/system/
sudo systemctl daemon-reload

# Enable (start on boot) and start
sudo systemctl enable nella
sudo systemctl start nella

# Pre-create Mem0 config (required — the SDK can't write under ProtectHome)
sudo -u nella MEM0_DIR=/home/nella/app/data/.mem0 /home/nella/.local/bin/uv run python scripts/init_mem0_dir.py
```

### Deploying changes

```bash
# On the VPS
cd /home/nella/app
git pull
uv sync                    # In case dependencies changed
sudo systemctl restart nella
```

### Where secrets live on the server

- `/home/nella/app/.env` — environment variables (loaded by systemd via `EnvironmentFile`)
- `/home/nella/app/auth_tokens/google_work_auth_token.json` — Google OAuth token (work account)
- `/home/nella/app/auth_tokens/google_personal_auth_token.json` — Google OAuth token (personal account)
- `/home/nella/app/auth_tokens/linkedin_default_auth_token.json` — LinkedIn OAuth token

These are **not** in the git repo. If you're setting up a new server, you need to copy them manually.

### Checking logs

```bash
# Follow live logs
sudo journalctl -u nella -f

# Last 100 lines
sudo journalctl -u nella -n 100

# Logs since last restart
sudo journalctl -u nella --since "$(systemctl show -p ActiveEnterTimestamp nella | cut -d= -f2)"
```

### Security hardening

The service file includes several restrictions:
- Runs as a dedicated `nella` user (not root)
- Read-only home directory except for the app directory and cache
- Private /tmp, restricted system access
- `Type=notify` — systemd waits for the bot to signal readiness before considering it healthy
- `WatchdogSec=60` — if the bot hangs (no watchdog ping for 60s), systemd kills and restarts it
- Auto-restarts on crash (up to 5 times per 10 minutes)

## Adding New Tools

Here's how to add a new tool to Nella. There are two styles — use the decorator for simple stateless tools (most cases), or a class for tools that need initialization.

### Style 1: Decorator (simple)

Create a new file `src/tools/my_tool.py`:

```python
"""My cool new tool."""

from pydantic import Field

from src.tools.base import ToolParams, ToolResult
from src.tools.registry import registry


# Define parameters as a Pydantic model (like a JSON schema)
class MyToolParams(ToolParams):
    query: str = Field(description="What to search for")
    limit: int = Field(default=5, description="Max results")


@registry.tool(
    name="my_tool",
    description="Does something useful. Claude sees this description.",
    category="custom",
    params_model=MyToolParams,
)
async def my_tool(query: str, limit: int = 5) -> ToolResult:
    # Do the thing
    results = [f"Result for {query}"]
    return ToolResult(data={"results": results, "count": len(results)})
```

Then register it by adding an import in `src/tools/__init__.py`:

```python
from src.tools import memory_tools, utility, my_tool  # noqa: F401
```

That's it. The `@registry.tool()` decorator runs when the module is imported, which registers the tool. Claude will see it on the next message.

If the tool performs a destructive or externally-visible action (sends messages, creates/deletes resources, etc.), add `requires_confirmation=True` to the decorator. This makes the bot prompt the user with inline Approve/Deny buttons before executing.

### Accessing MessageContext (optional)

If your tool needs to know about the current user or channel, add `msg_context` to the function signature:

```python
from src.notifications.context import MessageContext

@registry.tool(name="my_tool", description="...", category="custom")
async def my_tool(msg_context: MessageContext | None = None) -> ToolResult:
    if msg_context:
        user_id = msg_context.user_id
        channel = msg_context.source_channel
    return ToolResult(data={"user": user_id})
```

The registry detects this via introspection and injects it automatically. Existing tools that don't declare this parameter are unaffected.

## Common Tasks

### Switching Claude models

In Telegram:
```
/model              # Show current model
/model opus         # Switch to Opus
/model sonnet       # Switch to Sonnet
/model haiku        # Switch to Haiku
```

This changes the model at runtime — no restart needed. It resets when the bot restarts (defaults come from `DEFAULT_CHAT_MODEL` in `.env`).

### Checking bot status

```
/status
```

Shows the current model, message count in context, and your user ID.

### Clearing conversation history

```
/clear
```

Resets the in-memory conversation window. Doesn't affect long-term memory in Mem0.

### Re-authenticating Google

If Google API calls start failing with auth errors, the token may have expired:

```bash
# Run locally (needs a browser) — specify which account
uv run python scripts/google_auth.py --account work

# Copy the new token to your VPS
scp auth_tokens/google_work_auth_token.json your-vps:/home/nella/app/auth_tokens/google_work_auth_token.json

# Restart the bot
ssh your-vps sudo systemctl restart nella
```

## Troubleshooting

### "command not found: uv"

You need to install uv first:
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```
Then restart your terminal (or `source ~/.bashrc` / `source ~/.zshrc`).

### Bot starts but ignores all messages

Check `ALLOWED_USER_IDS` in your `.env`. The bot silently ignores messages from any user ID not in this list. The log will show a warning if the list is empty.

### "Only one bot instance can run at a time"

Telegram's polling API only allows one connection per bot token. If you're running the bot locally **and** on your VPS, one of them will fail. Stop one before starting the other.

```bash
# Stop the VPS instance
ssh your-vps sudo systemctl stop nella
```

### Google tools not showing up

Google tools only load if `GOOGLE_ACCOUNTS` is set in `.env` and at least one `auth_tokens/google_{name}_auth_token.json` file exists. Run the auth flow first (see setup above). Check the logs — if `GOOGLE_ACCOUNTS` is empty you'll see a warning: "GOOGLE_ACCOUNTS is not configured — Google tools disabled".

### Google OAuth token expiry

Google OAuth tokens expire. The code auto-refreshes them using the refresh token, but if the refresh token itself is revoked (you changed your Google password, revoked access, etc.), you need to re-run the auth flow.

### Cache directory permissions (VPS)

The systemd service restricts filesystem access. If you see permission errors related to cache directories, make sure `/home/nella/.cache` is writable by the `nella` user:

```bash
sudo mkdir -p /home/nella/.cache
sudo chown nella:nella /home/nella/.cache
```

### Memory features not working

If `MEM0_API_KEY` is empty or not set, memory features degrade gracefully — search returns empty, add is a no-op. Nella still works, she just won't remember between conversations. Check the logs for "Memory retrieval failed" if something else is wrong.

### Mem0 "Read-only file system" error on VPS

The Mem0 SDK tries to create a `~/.mem0/config.json` file when it first imports. Under systemd's `ProtectHome=read-only`, this write is blocked. The service file sets `MEM0_DIR=/home/nella/app/data/.mem0` to redirect it, but you need to pre-create the directory and config **before the first run**:

```bash
sudo -u nella MEM0_DIR=/home/nella/app/data/.mem0 /home/nella/.local/bin/uv run python scripts/init_mem0_dir.py
sudo systemctl restart nella
```

You can verify Mem0 independently with the diagnostic script:

```bash
sudo -u nella MEM0_DIR=/home/nella/app/data/.mem0 /home/nella/.local/bin/uv run python scripts/test_mem0.py
```

### systemd service file location

The service file should be at `/etc/systemd/system/nella.service`. After copying or editing it:

```bash
sudo systemctl daemon-reload
sudo systemctl restart nella
```
