# Getting Started

This guide walks you through everything you need to do before you can run
`scripts/deploy.sh` and have a working Nella instance with all tools enabled.

Nella is modular — the only truly **required** services are Telegram and
Anthropic. Everything else (Google, Mem0, GitHub, LinkedIn, etc.) is optional
and enables additional tools. Skip what you don't need.

---

## Prerequisites

- **Python 3.12+** — `python3 --version` to check
- **uv** — Python package manager: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **A Linux VPS** — any provider works (Hetzner, DigitalOcean, Linode, etc.).
  Ubuntu 22.04+ recommended. Nella runs as a systemd service.

## 1. Clone and Install

```bash
git clone <your-fork-url> nellabot
cd nellabot
uv sync --all-extras
cp .env.example .env

# Create config files from templates
for f in config/*.md.EXAMPLE; do cp "$f" "${f%.EXAMPLE}"; done
```

Now open `.env` in your editor. The rest of this guide tells you where to get
each value.

---

## 2. Required Services

### Telegram Bot

This is how you talk to Nella.

1. Open Telegram and message [@BotFather](https://t.me/BotFather).
2. Send `/newbot`, follow the prompts to name your bot.
3. Copy the bot token BotFather gives you.
4. Message [@userinfobot](https://t.me/userinfobot) to get your numeric Telegram
   user ID.

```env
TELEGRAM_BOT_TOKEN=<bot-token-from-botfather>
ALLOWED_USER_IDS=<your-numeric-user-id>
```

`ALLOWED_USER_IDS` is a security gate — Nella silently ignores messages from
anyone not in this list. Comma-separate multiple IDs if needed.

### Anthropic (Claude API)

This is Nella's brain.

1. Sign up at [console.anthropic.com](https://console.anthropic.com).
2. Create an API key under **Settings > API Keys**.
3. Add billing (Claude API is pay-per-use).

```env
ANTHROPIC_API_KEY=sk-ant-...
```

Optional model settings (defaults are fine to start):

```env
CLAUDE_MODEL=claude-sonnet-4-6
DEFAULT_CHAT_MODEL=sonnet
DEFAULT_MEMORY_MODEL=haiku
```

`DEFAULT_CHAT_MODEL` controls the default model for conversations (`haiku`,
`sonnet`, or `opus`). You can switch at runtime in Telegram with `/model opus`.
`DEFAULT_MEMORY_MODEL` controls the model used for background memory extraction.

---

## 3. Optional Services

### Mem0 (Long-Term Memory)

Gives Nella persistent memory across conversations. Without it, she still works
but forgets everything between restarts.

1. Sign up at [app.mem0.ai](https://app.mem0.ai).
2. Create a project and grab your API key.

```env
MEM0_API_KEY=m0-...
```

### Google Workspace (Gmail, Calendar, Drive, Docs, Contacts)

Enables 32 tools. All five APIs use a single OAuth credential.

**Create OAuth credentials:**

1. Go to [Google Cloud Console](https://console.cloud.google.com).
2. Create a new project (or use an existing one).
3. Go to **APIs & Services > Library** and enable all five:
   - Gmail API
   - Google Calendar API
   - Google Drive API
   - Google Docs API
   - People API (for Contacts)
4. Go to **APIs & Services > Credentials**.
5. Click **Create Credentials > OAuth client ID**.
6. Application type: **Desktop app**.
7. Download the JSON file and save it as `credentials.json` in the project root.

> **Note:** If your project is in "Testing" mode (the default), Google limits
> OAuth to test users you explicitly add. Go to **OAuth consent screen > Test
> users** and add each Google account you want to connect. For production use,
> you'd publish the app, but for a personal assistant "Testing" mode works fine.

**Configure accounts:**

Nella supports multiple Google accounts (e.g. work + personal). Set the names
in `.env`:

```env
GOOGLE_ACCOUNTS=work,personal
GOOGLE_DEFAULT_ACCOUNT=work
```

**Run the auth flow for each account:**

```bash
uv run python scripts/google_auth.py --account work
uv run python scripts/google_auth.py --account personal
```

Each command opens a browser where you sign into the corresponding Google
account and grant permissions. Tokens are saved to
`auth_tokens/google_<name>_auth_token.json`.

If you only have one Google account, that's fine too:

```env
GOOGLE_ACCOUNTS=default
GOOGLE_DEFAULT_ACCOUNT=default
```

```bash
uv run python scripts/google_auth.py --account default
```

### Brave Search (Web Research)

Enables `web_search` and `read_webpage` tools.

1. Go to [brave.com/search/api](https://brave.com/search/api/).
2. Sign up for the free tier (2,000 queries/month).
3. Create an API key.

```env
BRAVE_SEARCH_API_KEY=BSA...
```

### GitHub (Repo Exploration)

Enables 8 read-only GitHub tools (browse repos, read code, list issues, etc.).

1. Go to [github.com/settings/tokens?type=beta](https://github.com/settings/tokens?type=beta).
2. Create a **fine-grained personal access token**.
3. Under **Repository permissions**, grant:
   - **Contents**: Read-only
   - **Issues**: Read-only
4. Scope it to the repos you want Nella to access (or all repositories).

```env
GITHUB_TOKEN=github_pat_...
NELLA_SOURCE_REPO=your-username/nellabot
```

`NELLA_SOURCE_REPO` tells Nella where her own source code lives, so she can
browse it when debugging herself.

### LinkedIn (Post & Comment)

Enables `linkedin_create_post` and `linkedin_post_comment` tools.

1. Go to [linkedin.com/developers/apps](https://www.linkedin.com/developers/apps)
   and create an app.
2. Under **Products**, request access to:
   - **Sign In with LinkedIn using OpenID Connect**
   - **Share on LinkedIn**
3. Under **Auth > OAuth 2.0 settings**, add redirect URL:
   `http://localhost:8585/callback`
4. Copy your Client ID and Client Secret.

```env
LINKEDIN_CLIENT_ID=...
LINKEDIN_CLIENT_SECRET=...
```

**Run the auth flow:**

```bash
uv run python scripts/linkedin_auth.py
```

This opens a browser for LinkedIn OAuth consent. The token is saved to
`auth_tokens/linkedin_default_auth_token.json`. LinkedIn tokens expire after
~60 days — you'll need to re-run this when they do.

### Turso (Hosted Database)

By default Nella uses a local SQLite file (`data/nella.db`). If you want the
database to persist on a hosted service (useful if you want to separate data
from the VPS):

1. Sign up at [turso.tech](https://turso.tech) (generous free tier).
2. Create a database.
3. Create an auth token.

```env
TURSO_DATABASE_URL=libsql://your-db-name-your-org.turso.io
TURSO_AUTH_TOKEN=...
```

When these are set, Nella ignores `DATABASE_PATH` and connects to Turso instead.

### SolarWinds Observability (Log Aggregation)

Enables the `query_logs` tool (Nella can search her own production logs) and
centralizes VPS syslog.

1. Sign up at [SolarWinds Observability](https://www.solarwinds.com/solarwinds-observability)
   (free tier available).
2. Create an **API Access token** (for the query_logs tool).
3. Create an **Ingestion token** (for syslog forwarding from the VPS).

```env
PAPERTRAIL_API_TOKEN=<api-access-token>
PAPERTRAIL_INGESTION_TOKEN=<ingestion-token>
```

The deploy script automatically configures rsyslog on the VPS to forward logs to
SolarWinds when the ingestion token is set.

### ngrok (Webhook HTTPS Tunnel)

Required only if you use webhooks (Zapier, Plaud, etc.). Gives your VPS a
public HTTPS endpoint without configuring TLS yourself.

1. Sign up at [dashboard.ngrok.com](https://dashboard.ngrok.com).
2. Copy your **Authtoken** from the dashboard.
3. Go to [dashboard.ngrok.com/domains](https://dashboard.ngrok.com/domains) and
   claim a free static domain (e.g. `your-name.ngrok-free.app`).

```env
NGROK_AUTHTOKEN=...
NGROK_DOMAIN=your-name.ngrok-free.app
WEBHOOK_SECRET=<any-random-string>
```

`WEBHOOK_SECRET` is a shared secret you define. External services (Zapier, etc.)
must send it in the `X-Webhook-Secret` header. Generate something random:

```bash
openssl rand -hex 32
```

The deploy script installs and configures ngrok as a systemd service
automatically.

### SMS via Telnyx (Conversational Texting)

Enables conversational SMS as an alternative to Telegram. SMS uses separate
sessions but shares the same memory, config, and tool access. Tools that
require confirmation are auto-denied (SMS can't do inline keyboards).

1. Create an account at [telnyx.com](https://telnyx.com).
2. Complete 10DLC sole proprietor registration (~$4 brand + $15 campaign
   one-time, $2/month ongoing).
3. Buy a phone number ($1.10/month).
4. In your messaging profile, set the webhook URL to
   `https://<NGROK_DOMAIN>/sms/inbound`.
5. Set the env vars:

```env
TELNYX_API_KEY=KEY...
TELNYX_PHONE_NUMBER=+15551234567
SMS_OWNER_PHONE=+15559876543
```

`SMS_OWNER_PHONE` is a security gate — only messages from this number are
processed (similar to `ALLOWED_USER_IDS` for Telegram). Use E.164 format
(country code + number, e.g. `+1` for US).

Cost is roughly $0.004 per message segment (160 chars). Nella caps responses
at ~1,600 chars (~10 segments) to keep costs low.

---

## 4. Customize Nella

The repo ships `.md.EXAMPLE` templates in `config/`. The clone step above
already copied them to the actual `.md` files. Now edit them:

| File | What to edit |
|------|-------------|
| `config/SOUL.md` | Nella's personality, tone, and behavioral rules. Make her your own. |
| `config/USER.md` | Your name, timezone, preferences, work context. Fill this in so Nella knows about you. |
| `config/MEMORY.md` | Facts you want Nella to always know (loaded into every prompt). |
| `config/MEMORY_RULES.md` | Rules for automatic memory extraction. Controls what she remembers. |

The actual `.md` files are gitignored so your personal data stays out of source
control. The `.EXAMPLE` templates are what's checked in. These are read fresh on
every message — no restart needed after editing.

---

## 5. Test Locally

Before deploying, verify everything works on your machine:

```bash
# Run the bot
uv run python -m src.bot.main

# In another terminal, run the test suite
uv run pytest
```

Send Nella a message on Telegram. If she responds, the core is working. Try
asking about your calendar or email to verify Google tools are connected.

> **Note:** Only one instance of the bot can run at a time per bot token
> (Telegram limitation). Stop your local instance before deploying to the VPS.

---

## 6. Deploy

Make sure your `.env` and `auth_tokens/` directory are in the project root,
then:

```bash
# First deploy (sets up the VPS from scratch)
bash scripts/deploy.sh root@your-vps-ip

# Subsequent deploys (code-only, faster)
bash scripts/deploy.sh root@your-vps-ip --quick
```

The deploy script:
1. Creates a `nella` system user on the VPS
2. Installs Python 3.12, uv, and ngrok
3. Syncs your code via rsync
4. Copies `.env` and `auth_tokens/` with locked-down permissions
5. Installs Python dependencies
6. Initializes the database and Mem0 directory
7. Installs the systemd service
8. Configures ngrok and syslog forwarding (if tokens are set)
9. Restarts the service and runs a health check

You need SSH key-based root access to the VPS. The script uses `rsync` and
`scp` under the hood.

---

## 7. Verify

After deploying:

```bash
# Check service status
ssh root@your-vps-ip systemctl status nella

# Follow live logs
ssh root@your-vps-ip journalctl -u nella -f
```

Send Nella a message on Telegram. If she responds, you're done.

---

## Quick Reference: What Enables What

| Service | Tools enabled | Required? |
|---------|--------------|-----------|
| Telegram | Chat interface | Yes |
| Anthropic | Claude reasoning | Yes |
| Mem0 | `remember_this`, `recall`, `forget_this`, `save_reference` + auto-extraction | No |
| Google Workspace | 32 tools (Gmail, Calendar, Drive, Docs, Contacts) | No |
| Brave Search | `web_search`, `read_webpage` | No |
| GitHub | 8 tools (repo browsing, code search, issues) | No |
| LinkedIn | `linkedin_create_post`, `linkedin_post_comment` | No |
| SolarWinds | `query_logs` | No |
| Turso | Hosted database (replaces local SQLite) | No |
| ngrok | HTTPS webhooks for external services | No |
| Telnyx | SMS conversational channel (alternative to Telegram) | No |

Tools that aren't configured are simply not loaded — Nella works fine without
them and won't show errors. Add services incrementally as you need them.
