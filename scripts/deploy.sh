#!/usr/bin/env bash
set -euo pipefail
trap 'echo "ERROR: Deploy failed at line $LINENO" >&2' ERR

# ---------------------------------------------------------------------------
# Self-locate project root
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$PROJECT_ROOT"

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
REMOTE_USER="nella"
APP_DIR="/home/nella/app"
UV_BIN="/home/nella/.local/bin/uv"
RSYNC_EXCLUDES=(
    .git/ __pycache__/ "*.pyc" .venv/ .env ".env.*"
    auth_tokens/ credentials.json data/ .DS_Store .ruff_cache/
    .pytest_cache/ "*.db" "*.db-journal" .claude/
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
log() { echo "==> $*"; }

run_remote() {
    # Run a command on the VPS as root
    ssh "$SSH_TARGET" "$@"
}

# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------
QUICK=false
SSH_TARGET=""

usage() {
    cat <<EOF
Usage: $0 <ssh-target> [--quick]

  ssh-target   e.g. root@203.0.113.5
  --quick      skip system setup and dependency install (code-only update)

Reads .env and auth_tokens/ from the project root.

Examples:
  $0 root@203.0.113.5
  $0 root@203.0.113.5 --quick
EOF
    exit 1
}

parse_args() {
    [[ $# -lt 1 ]] && usage

    SSH_TARGET="$1"
    shift

    while [[ $# -gt 0 ]]; do
        case "$1" in
            --quick) QUICK=true ;;
            *) echo "Unknown option: $1" >&2; usage ;;
        esac
        shift
    done
}

# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
validate_args() {
    # Must be in the project root
    if [[ ! -f "pyproject.toml" ]]; then
        echo "ERROR: pyproject.toml not found. Run this from the project root." >&2
        exit 1
    fi

    # .env must exist in project root
    if [[ ! -f ".env" ]]; then
        echo "ERROR: .env not found in project root." >&2
        exit 1
    fi

    # Warn about optional auth tokens
    if [[ ! -d "auth_tokens" ]] || ! ls auth_tokens/*.json &>/dev/null; then
        log "WARNING: No auth token files found in auth_tokens/ (Google/LinkedIn tools will be disabled)"
    fi

    # SSH connectivity
    log "Testing SSH connectivity..."
    if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$SSH_TARGET" true 2>/dev/null; then
        echo "ERROR: Cannot connect to $SSH_TARGET. Check SSH config/keys." >&2
        exit 1
    fi
    log "SSH connection OK"
}

# ---------------------------------------------------------------------------
# Phase 1: System Setup (skipped with --quick)
# ---------------------------------------------------------------------------
phase_system_setup() {
    log "Phase 1: System setup"
    run_remote bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive

# Create nella user (idempotent)
if ! id -u nella &>/dev/null; then
    useradd --system -m -s /bin/bash nella
    echo "  Created user: nella"
else
    echo "  User nella already exists"
fi

# Install Python 3.12
if python3.12 --version &>/dev/null; then
    echo "  Python 3.12 already installed"
else
    echo "  Installing Python 3.12..."
    . /etc/os-release
    if [[ "$VERSION_ID" == "22.04" ]]; then
        apt-get -o DPkg::Lock::Timeout=60 update -qq
        apt-get -o DPkg::Lock::Timeout=60 install -y -qq software-properties-common
        add-apt-repository -y ppa:deadsnakes/ppa
    fi
    apt-get -o DPkg::Lock::Timeout=60 update -qq
    apt-get -o DPkg::Lock::Timeout=60 install -y -qq python3.12 python3.12-venv
fi

# Install uv
UV_BIN="/home/nella/.local/bin/uv"
if [[ -x "$UV_BIN" ]]; then
    echo "  uv already installed"
else
    echo "  Installing uv..."
    sudo -u nella bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
fi

# Install ngrok
if command -v ngrok &>/dev/null; then
    echo "  ngrok already installed"
else
    echo "  Installing ngrok..."
    curl -sSf https://ngrok-agent.s3.amazonaws.com/ngrok.asc \
        | tee /etc/apt/trusted.gpg.d/ngrok.asc >/dev/null
    echo "deb https://ngrok-agent.s3.amazonaws.com buster main" \
        | tee /etc/apt/sources.list.d/ngrok.list >/dev/null
    apt-get -o DPkg::Lock::Timeout=60 update -qq
    apt-get -o DPkg::Lock::Timeout=60 install -y -qq ngrok
fi

# Firewall
echo "  Configuring firewall..."
ufw allow OpenSSH >/dev/null
ufw allow 8443/tcp >/dev/null
ufw --force enable >/dev/null
echo "  Firewall configured"

# Directories
mkdir -p /home/nella/app /home/nella/.cache
chown nella:nella /home/nella/app /home/nella/.cache
echo "  Directories ready"
REMOTE_SCRIPT
}

# ---------------------------------------------------------------------------
# Phase 2: Sync Code
# ---------------------------------------------------------------------------
phase_sync_code() {
    log "Phase 2: Syncing code"

    # Build rsync exclude args
    local exclude_args=()
    for pattern in "${RSYNC_EXCLUDES[@]}"; do
        exclude_args+=(--exclude "$pattern")
    done

    rsync -az --delete "${exclude_args[@]}" \
        "$PROJECT_ROOT/" "$SSH_TARGET:$APP_DIR/"

    run_remote chown -R nella:nella "$APP_DIR"
    log "Code synced"
}

# ---------------------------------------------------------------------------
# Phase 3: Sync Secrets
# ---------------------------------------------------------------------------
phase_sync_secrets() {
    log "Phase 3: Syncing secrets"

    # .env (required — already validated)
    scp -q ".env" "$SSH_TARGET:$APP_DIR/.env"

    # auth_tokens/ directory (optional)
    if ls auth_tokens/*.json &>/dev/null; then
        run_remote mkdir -p "$APP_DIR/auth_tokens"
        scp -q auth_tokens/*.json "$SSH_TARGET:$APP_DIR/auth_tokens/"
    fi

    # Lock down permissions
    run_remote bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
cd /home/nella/app
chmod 600 .env
chown nella:nella .env
if [[ -d auth_tokens ]]; then
    chmod 700 auth_tokens
    chown nella:nella auth_tokens
    for f in auth_tokens/*.json; do
        [[ -f "$f" ]] && chmod 600 "$f" && chown nella:nella "$f"
    done
fi
REMOTE_SCRIPT

    log "Secrets synced"
}

# ---------------------------------------------------------------------------
# Phase 4: Install Dependencies (skipped with --quick)
# ---------------------------------------------------------------------------
phase_install_deps() {
    log "Phase 4: Installing dependencies"
    run_remote bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
sudo -u nella bash -c 'cd /home/nella/app && /home/nella/.local/bin/uv sync --frozen --no-dev'

# Install Playwright Chromium if browser automation is enabled
if grep -q '^BROWSER_ENABLED=true' /home/nella/app/.env 2>/dev/null; then
    echo "  Installing Playwright Chromium..."
    sudo -u nella bash -c 'cd /home/nella/app && /home/nella/.local/bin/uv run playwright install --with-deps chromium'
    echo "  Playwright Chromium installed"
fi
REMOTE_SCRIPT
    log "Dependencies installed"
}

# ---------------------------------------------------------------------------
# Phase 5: Initialize App
# ---------------------------------------------------------------------------
phase_init_app() {
    log "Phase 5: Initializing app"
    run_remote bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
mkdir -p /home/nella/app/data
chown nella:nella /home/nella/app/data

mkdir -p /home/nella/app/data/scratch
chown nella:nella /home/nella/app/data/scratch

# Create config files from .EXAMPLE templates if they don't exist
for example in /home/nella/app/config/*.md.EXAMPLE; do
    target="${example%.EXAMPLE}"
    if [[ ! -f "$target" ]]; then
        cp "$example" "$target"
        chown nella:nella "$target"
        echo "  Created $(basename "$target") from template"
    fi
done

# Run Mem0 dir init
sudo -u nella bash -c 'cd /home/nella/app && MEM0_DIR=/home/nella/app/data/.mem0 /home/nella/.local/bin/uv run python scripts/init_mem0_dir.py'
REMOTE_SCRIPT
    log "App initialized"
}

# ---------------------------------------------------------------------------
# Phase 6: Install Service
# ---------------------------------------------------------------------------
phase_install_service() {
    log "Phase 6: Installing systemd service"
    run_remote bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
cp /home/nella/app/nella.service /etc/systemd/system/nella.service
systemctl daemon-reload
systemctl enable nella
REMOTE_SCRIPT
    log "Service installed"
}

# ---------------------------------------------------------------------------
# Phase 7: Configure ngrok
# ---------------------------------------------------------------------------
phase_configure_ngrok() {
    log "Phase 7: Configuring ngrok"

    # Read NGROK_AUTHTOKEN and NGROK_DOMAIN from the deployed .env
    local ngrok_authtoken ngrok_domain
    ngrok_authtoken=$(run_remote grep -s '^NGROK_AUTHTOKEN=' "$APP_DIR/.env" | cut -d= -f2- || true)
    ngrok_domain=$(run_remote grep -s '^NGROK_DOMAIN=' "$APP_DIR/.env" | cut -d= -f2- || true)

    if [[ -z "$ngrok_authtoken" || -z "$ngrok_domain" ]]; then
        log "WARNING: NGROK_AUTHTOKEN or NGROK_DOMAIN not set in .env — skipping ngrok setup"
        return 0
    fi

    run_remote bash -s -- "$ngrok_authtoken" "$ngrok_domain" <<'REMOTE_SCRIPT'
set -euo pipefail
AUTHTOKEN="$1"
DOMAIN="$2"

mkdir -p /root/.config/ngrok

cat > /root/.config/ngrok/ngrok.yml <<NGROK_EOF
version: "2"
authtoken: ${AUTHTOKEN}
tunnels:
  nella-webhooks:
    proto: http
    addr: 8443
    domain: ${DOMAIN}
NGROK_EOF

echo "  ngrok config written"

# Install ngrok as a systemd service (idempotent)
if [[ -f /etc/systemd/system/ngrok.service ]]; then
    echo "  ngrok service already installed"
else
    ngrok service install --config /root/.config/ngrok/ngrok.yml
    echo "  ngrok service installed"
fi

# Start or restart
if systemctl is-active ngrok &>/dev/null; then
    systemctl restart ngrok
    echo "  ngrok service restarted"
else
    ngrok service start
    echo "  ngrok service started"
fi
REMOTE_SCRIPT

    log "ngrok configured (domain: $ngrok_domain)"
}

# ---------------------------------------------------------------------------
# Phase 8: Configure SolarWinds syslog forwarding
# ---------------------------------------------------------------------------
phase_configure_syslog() {
    log "Phase 8: Configuring SolarWinds syslog forwarding"

    # Read PAPERTRAIL_INGESTION_TOKEN from the deployed .env
    local ingestion_token
    ingestion_token=$(run_remote grep -s '^PAPERTRAIL_INGESTION_TOKEN=' "$APP_DIR/.env" | cut -d= -f2- || true)

    if [[ -z "$ingestion_token" ]]; then
        log "WARNING: PAPERTRAIL_INGESTION_TOKEN not set in .env — skipping syslog setup"
        return 0
    fi

    run_remote bash -s -- "$ingestion_token" <<'REMOTE_SCRIPT'
set -euo pipefail
TOKEN="$1"
CONF="/etc/rsyslog.d/60-solarwinds.conf"

if [[ -f "$CONF" ]]; then
    echo "  SolarWinds rsyslog config already exists"
else
    cat > "$CONF" <<SYSLOG_EOF
# SolarWinds Observability — forward all logs via TLS syslog
\$DefaultNetstreamDriverCAFile /etc/ssl/certs/ca-certificates.crt
\$ActionSendStreamDriver gtls
\$ActionSendStreamDriverMode 1
\$ActionSendStreamDriverAuthMode x509/name
\$ActionSendStreamDriverPermittedPeer *.na-01.cloud.solarwinds.com

\$template SWOFormat,"<%pri%>1 %timestamp:::date-rfc3339% %HOSTNAME% %app-name% %procid% %msgid% [${TOKEN}@41058]%msg:::sp-if-no-1st-sp%%msg%"

*.* @@syslog.collector.na-01.cloud.solarwinds.com:6514;SWOFormat
SYSLOG_EOF

    # rsyslog needs the gtls driver for TLS
    if ! dpkg -l rsyslog-gnutls 2>/dev/null | grep -q "^ii"; then
        echo "  Installing rsyslog-gnutls..."
        apt-get -o DPkg::Lock::Timeout=60 update -qq
        apt-get -o DPkg::Lock::Timeout=60 install -y -qq rsyslog-gnutls
    fi

    systemctl restart rsyslog
    echo "  SolarWinds rsyslog config created and rsyslog restarted"
fi
REMOTE_SCRIPT

    log "SolarWinds syslog configured"
}

# ---------------------------------------------------------------------------
# Phase 9: Restart + Health Check
# ---------------------------------------------------------------------------
phase_restart_service() {
    log "Phase 9: Restarting service"
    run_remote systemctl restart nella

    # Poll until active (up to 15s)
    local attempts=0
    local max_attempts=8
    while [[ $attempts -lt $max_attempts ]]; do
        sleep 2
        if run_remote systemctl is-active nella &>/dev/null; then
            log "Service is active"

            # Optional webhook health check
            if run_remote grep -q "^WEBHOOK_SECRET=.\+" /home/nella/app/.env 2>/dev/null; then
                sleep 1
                if run_remote curl -sf http://localhost:8443/health &>/dev/null; then
                    log "Webhook health check passed"
                else
                    log "WARNING: Webhook health check failed (service is running though)"
                fi
            fi

            return 0
        fi
        attempts=$((attempts + 1))
    done

    echo "ERROR: Service failed to start. Last 30 lines of journal:" >&2
    run_remote journalctl -u nella -n 30 --no-pager >&2
    exit 1
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
main() {
    local start_time
    start_time=$(date +%s)

    parse_args "$@"
    validate_args

    if [[ "$QUICK" == true ]]; then
        log "Quick deploy (skipping system setup + deps)"
        phase_sync_code
        phase_sync_secrets
        phase_install_service
        phase_configure_ngrok
        phase_restart_service
    else
        log "Full deploy"
        phase_system_setup
        phase_sync_code
        phase_sync_secrets
        phase_install_deps
        phase_init_app
        phase_install_service
        phase_configure_ngrok
        phase_configure_syslog
        phase_restart_service
    fi

    local elapsed=$(( $(date +%s) - start_time ))
    log "Deploy complete in ${elapsed}s"

    # Post-deploy info
    local ngrok_domain
    ngrok_domain=$(grep -s '^NGROK_DOMAIN=' ".env" | cut -d= -f2- || true)
    local ngrok_authtoken
    ngrok_authtoken=$(grep -s '^NGROK_AUTHTOKEN=' ".env" | cut -d= -f2- || true)

    if [[ -n "$ngrok_domain" && -n "$ngrok_authtoken" ]]; then
        echo ""
        echo "--- Webhook URL ---"
        echo "  https://${ngrok_domain}/webhooks/<source>"
        echo ""
    else
        echo ""
        echo "--- Next steps ---"
        echo "  ngrok not configured (NGROK_AUTHTOKEN / NGROK_DOMAIN missing from .env)"
        echo "  To set up HTTPS webhooks manually:"
        echo "    1. SSH into the VPS: ssh $SSH_TARGET"
        echo "    2. Add NGROK_AUTHTOKEN and NGROK_DOMAIN to .env"
        echo "    3. Re-run this deploy script"
        echo ""
    fi
}

main "$@"
