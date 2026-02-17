# Nella — Personal AI Assistant Bot

## Overview

Nella is an always-on personal AI assistant with Telegram as the primary chat interface.
She uses Claude as the reasoning engine, Mem0 for persistent memory, and integrates
with Google APIs (Calendar, Gmail, Drive, Docs) for real-world actions.

## Tech Stack

- **Python 3.12** — minimum version
- **uv** — package manager and virtual environment
- **async throughout** — all I/O operations use async/await
- **Type hints everywhere** — strict typing, no `Any` unless unavoidable

## Architecture

```
src/
├── bot/          # Telegram bot handlers, command routing, message lifecycle
├── llm/          # Claude API client, prompt assembly, tool dispatch
├── memory/       # Mem0 integration, SQLite conversation store, file-based memory
├── integrations/ # Google OAuth multi-account manager
├── tools/        # Tool definitions for Claude function calling
└── webhooks/     # Inbound webhook HTTP server + handler registry

config/
├── SOUL.md.EXAMPLE       # Nella's personality, tone, behavioral rules (template)
├── USER.md.EXAMPLE       # Owner profile — preferences, context, routines (template)
├── MEMORY.md.EXAMPLE     # Long-term memory notes (template)
└── MEMORY_RULES.md.EXAMPLE  # Auto-extraction rules (template)
# .md files are gitignored — copy .EXAMPLE to .md and customize

tests/            # pytest + pytest-asyncio
```

## Key Principles

1. **Single-user bot** — Nella serves one owner. No multi-tenancy.
2. **Memory-first** — Every conversation is stored. Mem0 handles semantic retrieval.
3. **Tool-augmented** — Claude sees tool definitions and can call them via function calling.
4. **Config as markdown** — Personality, user profile, and memory are `.md` files that
   the owner can edit directly. `.md.EXAMPLE` files are checked into git as
   templates; the actual `.md` files are gitignored (personal data).
5. **Graceful degradation** — If an integration is down, Nella says so instead of crashing.

## Conventions

- Use `ruff` for linting and formatting.
- Tests go in `tests/` mirroring `src/` structure.
- Environment variables in `.env`, never committed.
- All database access through `libsql` (wrapped async in `src/db.py`).
- Pydantic models for all structured data crossing boundaries.
- Tool confirmation is configured via `config/TOOL_CONFIRMATIONS.toml` (not
  in code). Copy `.EXAMPLE` to `.toml` and set tools to `true`/`false`. Changes
  take effect immediately (no restart). See `src/bot/confirmations.py`.
- Google tools use `GoogleToolParams` (from `src/tools/base.py`) as their param
  base class. This adds an optional `account` parameter to every Google tool.
  Named accounts are configured via `GOOGLE_ACCOUNTS` in `.env`, with token
  files at `auth_tokens/google_{account}_auth_token.json`. Claude picks the right account from
  conversational context; the system prompt lists available accounts.
- Webhook handlers go in `src/webhooks/handlers/`, one file per integration.
  Register them with `@webhook_registry.handler("source_name")`. The HTTP
  server runs alongside Telegram on `WEBHOOK_PORT` (default 8443), validates
  `X-Webhook-Secret`, and is disabled when `WEBHOOK_SECRET` is empty.
- `src/llm/client.py` exposes two calling patterns for the Claude API:
  - **`generate_response()`** — full pipeline: system prompt, Mem0 memories,
    tool schemas, streaming, multi-round tool-calling loop. Used by the main
    chat handler and `ai_task` scheduler jobs.
  - **`complete_text()`** — bare single-shot call: no memory, no tools, no
    streaming. Used for isolated LLM tasks (summarization, extraction, etc.).
  Both share the same lazy `AsyncAnthropic` singleton. New code that needs
  Claude should use one of these — do not create standalone `AsyncAnthropic`
  instances elsewhere.

## Maintenance, Housekeeping, Code Health

- **Tool changes** — When adding, updating, or removing tools, always update
  the tool catalog in `README.md` and `scripts/functional_test_prompt.md`.
- **Functional tests** — When adding, updating, or removing tools OR making
  significant behavioral changes, update `scripts/functional_test_prompt.md`
  so the functional test suite stays current.
- **Test suite** - It's good to occasionally run through the test suite to see
  if there are any tests for dead code and to at least do some sampling on 'is
  this test still needed'.
- **Code comments** - Comments are a great place to stash context but comments
  also become stale. When you touch a file, it's good to review comments from
  time-to-time.
- **README accuracy** — At the end of every coding session, review `README.md`
  for anything that needs updating. It serves as context for future development
  sessions and must always reflect the current state of the code.
- **Open source** - This is an open source project, at the end of every codiing
  session, review the changes and consider anything we might be sending to
  source control that violates basic open source best practices.
- **Cross-cutting concerns** - Whenever touching cross-cutting concerns like LLM
  interactions, or messages/notifications, or memory, do a review and make sure
  we're not breaking something somewhere else.

## Running

```bash
uv run python -m src.bot.main
```

## Testing

```bash
uv run pytest
```
