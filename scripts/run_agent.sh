#!/bin/bash
# Run AI Agent Runner locally on Mac
# Connects to Railway Redis + MT5 Bridge, uses Claude Code SDK (Max subscription)
#
# Prerequisites:
#   1. Enable public networking for Redis + Postgres in Railway dashboard
#   2. Update backend/.env.local with public URLs
#   3. Claude CLI installed and authenticated (claude login)
#
# Usage: ./scripts/run_agent.sh

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_DIR/backend"

echo "=== AI Trading Agent — Agent Runner ==="
echo "Starting agent runner on local Mac..."
echo ""

# Check claude CLI
if ! command -v claude &> /dev/null; then
    echo "ERROR: 'claude' CLI not found. Install it first: npm install -g @anthropic-ai/claude-code"
    exit 1
fi

# Check .env.local
if [ ! -f "$BACKEND_DIR/.env.local" ]; then
    echo "ERROR: backend/.env.local not found. Create it first (see template)."
    exit 1
fi

# Check for REPLACE placeholders
if grep -q "REPLACE_WITH" "$BACKEND_DIR/.env.local"; then
    echo "ERROR: backend/.env.local still has REPLACE_WITH placeholders."
    echo "Enable public networking in Railway dashboard and update the URLs."
    exit 1
fi

# Load env
set -a
source "$BACKEND_DIR/.env.local"
set +a

# Set Python path
export PYTHONPATH="$BACKEND_DIR:$PROJECT_DIR:$PYTHONPATH"

echo "Runner ID:     $RUNNER_ID"
echo "Agent Mode:    $AGENT_MODE"
echo "Rollout Mode:  $ROLLOUT_MODE"
echo "Redis:         ${REDIS_URL:0:30}..."
echo "MT5 Bridge:    $MT5_BRIDGE_URL"
echo ""

# Run
cd "$BACKEND_DIR"
VENV_PYTHON="$BACKEND_DIR/venv/bin/python"
if [ -f "$VENV_PYTHON" ]; then
    exec "$VENV_PYTHON" -m app.runner.agent_entrypoint
else
    exec python3 -m app.runner.agent_entrypoint
fi
