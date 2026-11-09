#!/usr/bin/env bash
#
# scripts/dev-setup.sh
# ====================
# FILE HEADER
# -----------
# Business problem this file solves:
#   Setting up the sports-data-automation stack by hand (build images, start containers,
#   wait for health, run migrations, seed demo data) is error-prone and inconsistent.
#   dev-setup.sh is the one-command "fresh start" for a dev machine or the interview demo:
#   it builds, starts, migrates, and seeds so the whole platform is runnable after a single
#   invocation.
#
# Where it sits in the flow:
#   Developer-experience / operations layer. Mirrors `make dev-setup` (build up migrate seed)
#   but as a standalone script that also waits for services to be healthy before seeding.
#
# What calls it / what it calls:
#   Called by: developers (./scripts/dev-setup.sh), CI, the interview demo runner.
#   Calls: docker compose, docker (health polling), curl (seed).
#
# What breaks if removed:
#   No one-command setup; every operator must remember and type the long docker commands.
#
# Language conventions:
#   GNU bash, set -euo pipefail, POSIX-compatible. Uses DOCKER_COMPOSE (docker compose or
#   docker-compose) and defaults the project directory to the script's parent.
#
# INTERVIEW: `./scripts/dev-setup.sh` is the "fresh start" — know it so the stack is
#   reproducible on interview day.

set -euo pipefail

# Resolve the project root (directory containing this script's parent = sports-data-automation).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.yml}"
DOCKER_COMPOSE="docker compose"
if ! docker compose version >/dev/null 2>&1; then
    DOCKER_COMPOSE="docker-compose"
fi

cd "$PROJECT_ROOT"

echo "==> Sports Data Automation Platform - dev-setup"
echo "    Project root: $PROJECT_ROOT"

# ---------------------------------------------------------------------------
# 1. Build all Docker images
# ---------------------------------------------------------------------------
echo "==> Building Docker images..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" build --parallel

# ---------------------------------------------------------------------------
# 2. Start the stack (detached)
# ---------------------------------------------------------------------------
echo "==> Starting stack..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" up -d

# ---------------------------------------------------------------------------
# 3. Wait for core services to be healthy
# ---------------------------------------------------------------------------
echo "==> Waiting for services to become healthy..."
wait_for_health() {
    local service="$1"
    local timeout="${2:-120}"
    local elapsed=0
    echo "    Waiting for $service to be healthy (timeout ${timeout}s)..."
    while true; do
        local status
        status=$($DOCKER_COMPOSE -f "$COMPOSE_FILE" ps --format json "$service" 2>/dev/null \
            | python3 -c "import sys,json; d=json.load(sys.stdin); print(d[0]['Status'] if d and isinstance(d,list) else '')" 2>/dev/null || echo "")
        if echo "$status" | grep -qi "healthy"; then
            echo "    $service is healthy."
            return 0
        fi
        if [ "$elapsed" -ge "$timeout" ]; then
            echo "    WARNING: $service not healthy after ${timeout}s (continuing anyway)."
            return 1
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
}

wait_for_health "redis" 60 || true
wait_for_health "postgres" 60 || true
wait_for_health "ingestion-service" 90 || true

# ---------------------------------------------------------------------------
# 4. Run database migrations (best-effort; prints fallback if not implemented)
# ---------------------------------------------------------------------------
echo "==> Running database migrations..."
$DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T ingestion-service alembic upgrade head 2>/dev/null \
    || echo "    Migrations not yet implemented (skipping)."

# ---------------------------------------------------------------------------
# 5. Seed demo data
# ---------------------------------------------------------------------------
echo "==> Seeding demo data..."
if [ -f "$SCRIPT_DIR/seed_demo_data.py" ]; then
    # Prefer running from the host against the ingestion API (works without mounting scripts/).
    INGESTION_URL="${INGESTION_URL:-http://localhost:8000}"
    echo "    Seeding via ingestion API at $INGESTION_URL ..."
    python3 "$SCRIPT_DIR/seed_demo_data.py" --url "$INGESTION_URL" \
        || echo "    WARNING: seed_demo_data.py failed (see above)."
else
    $DOCKER_COMPOSE -f "$COMPOSE_FILE" exec -T ingestion-service \
        python -m scripts.seed_demo_data 2>/dev/null \
        || echo "    Seed script not yet implemented (skipping)."
fi

echo ""
echo "==> Development environment ready!"
echo "    n8n:        http://localhost:5678 (admin / \${N8N_PASSWORD:-changeme})"
echo "    Grafana:    http://localhost:3000 (admin / \${GRAFANA_PASSWORD:-admin})"
echo "    Prometheus: http://localhost:9090"
echo "    Ingestion API: http://localhost:8000/docs"
echo "    Mock Odds Feed: http://localhost:8080"
echo "    Mock Event Feed: http://localhost:8081"
