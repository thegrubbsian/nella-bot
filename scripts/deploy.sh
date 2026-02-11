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
    "token*.json" credentials.json data/ .DS_Store .ruff_cache/
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
SECRETS_DIR=""

usage() {
    cat <<EOF
Usage: $0 <ssh-target> <secrets-dir> [--quick]

  ssh-target   e.g. root@203.0.113.5
  secrets-dir  local directory containing .env (and optionally credentials.json, token_*.json)
  --quick      skip system setup and dependency install (code-only update)

Examples:
  $0 root@203.0.113.5 ~/nella-secrets
  $0 root@203.0.113.5 ~/nella-secrets --quick
EOF
    exit 1
}

parse_args() {
    [[ $# -lt 2 ]] && usage

    SSH_TARGET="$1"
    SECRETS_DIR="$2"
    shift 2

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

    # Secrets dir must exist with .env
    if [[ ! -d "$SECRETS_DIR" ]]; then
        echo "ERROR: Secrets directory does not exist: $SECRETS_DIR" >&2
        exit 1
    fi
    if [[ ! -f "$SECRETS_DIR/.env" ]]; then
        echo "ERROR: .env not found in secrets directory: $SECRETS_DIR" >&2
        exit 1
    fi

    # Warn about optional secret files
    if [[ ! -f "$SECRETS_DIR/credentials.json" ]]; then
        log "WARNING: credentials.json not found in $SECRETS_DIR (Google OAuth won't work for new accounts)"
    fi
    # shellcheck disable=SC2012
    if ! ls "$SECRETS_DIR"/token_*.json &>/dev/null; then
        log "WARNING: No token_*.json files found in $SECRETS_DIR (Google tools will be disabled)"
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
    scp -q "$SECRETS_DIR/.env" "$SSH_TARGET:$APP_DIR/.env"

    # credentials.json (optional)
    if [[ -f "$SECRETS_DIR/credentials.json" ]]; then
        scp -q "$SECRETS_DIR/credentials.json" "$SSH_TARGET:$APP_DIR/credentials.json"
    fi

    # token_*.json (optional, glob)
    for token_file in "$SECRETS_DIR"/token_*.json; do
        [[ -f "$token_file" ]] || continue
        scp -q "$token_file" "$SSH_TARGET:$APP_DIR/$(basename "$token_file")"
    done

    # Lock down permissions
    run_remote bash -s <<'REMOTE_SCRIPT'
set -euo pipefail
cd /home/nella/app
chmod 600 .env
chown nella:nella .env
for f in credentials.json token_*.json; do
    [[ -f "$f" ]] && chmod 600 "$f" && chown nella:nella "$f"
done
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
# Phase 7: Restart + Health Check
# ---------------------------------------------------------------------------
phase_restart_service() {
    log "Phase 7: Restarting service"
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
        phase_restart_service
    else
        log "Full deploy"
        phase_system_setup
        phase_sync_code
        phase_sync_secrets
        phase_install_deps
        phase_init_app
        phase_install_service
        phase_restart_service
    fi

    local elapsed=$(( $(date +%s) - start_time ))
    log "Deploy complete in ${elapsed}s"
}

main "$@"
