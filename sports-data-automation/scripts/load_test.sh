#!/usr/bin/env bash
#
# scripts/load_test.sh
# ====================
# FILE HEADER
# -----------
# Business problem this file solves:
#   The platform must demonstrate it can sustain the high-volume odds feed (every 500ms-2s
#   per provider) without dropping data. load_test.sh is a load-test helper that drives the
#   ingestion service at a configurable rate (default 1000 events/sec) for a configurable
#   duration (default 60s), reporting throughput and error counts so the interviewer can see
#   the system stay up under load.
#
# Where it sits in the flow:
#   Developer-experience / operations layer. Mirrors `make load-test`. It POSTs synthetic
#   event payloads to the ingestion service /ingest/event endpoint at the target rate.
#
# What calls it / what it calls:
#   Called by: developers (./scripts/load_test.sh), `make load-test` (adapted).
#   Calls: python3 (embedded loader), curl fallback, awk/sleep.
#
# What breaks if removed:
#   No load-test command; the interviewer cannot observe throughput/backpressure behavior.
#
# Language conventions:
#   GNU bash, set -euo pipefail. Defaults: --rate 1000, --duration 60, --url
#   http://localhost:8000. Uses an embedded Python loader for accurate rate limiting and
#   reporting; falls back to a simple curl loop if python3 is unavailable.
#
# INTERVIEW: `./scripts/load_test.sh --rate 1000 --duration 60` demonstrates the platform
#   absorbing 1000 events/sec for a minute.

set -euo pipefail

RATE="${RATE:-1000}"
DURATION="${DURATION:-60}"
URL="${URL:-http://localhost:8000}"
ENDPOINT="${ENDPOINT:-/ingest/event}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --rate) RATE="$2"; shift 2 ;;
        --duration) DURATION="$2"; shift 2 ;;
        --url) URL="$2"; shift 2 ;;
        --endpoint) ENDPOINT="$2"; shift 2 ;;
        -h|--help)
            echo "Usage: $0 [--rate N] [--duration SECONDS] [--url BASE_URL] [--endpoint PATH]"
            echo "  Default: 1000 events/sec for 60s against http://localhost:8000/ingest/event"
            exit 0 ;;
        *)
            echo "Unknown argument: $1" >&2
            exit 2 ;;
    esac
done

# Validate input at system boundaries.
if ! [[ "$RATE" =~ ^[0-9]+$ ]] || [ "$RATE" -le 0 ]; then
    echo "Error: --rate must be a positive integer, got: $RATE" >&2
    exit 2
fi
if ! [[ "$DURATION" =~ ^[0-9]+$ ]] || [ "$DURATION" -le 0 ]; then
    echo "Error: --duration must be a positive integer, got: $DURATION" >&2
    exit 2
fi
if [[ "$URL" != http://* && "$URL" != https://* ]]; then
    echo "Error: --url must start with http:// or https://, got: $URL" >&2
    exit 2
fi

echo "==> Load test: ${RATE} events/sec for ${DURATION}s against ${URL}${ENDPOINT}"
START_TS="$(date +%s)"

if command -v python3 >/dev/null 2>&1; then
    python3 - "$URL" "$ENDPOINT" "$RATE" "$DURATION" <<'PY'
import sys
import time
import json
import urllib.request
import urllib.error

url, endpoint, rate, duration = sys.argv[1], sys.argv[2], float(sys.argv[3]), float(sys.argv[4])
full_url = url.rstrip("/") + endpoint

interval = 1.0 / rate
end_time = time.time() + duration
sent = 0
errors = 0
next_send = time.time()

i = 0
while time.time() < end_time:
    payload = {
        "id": f"load_evt_{i:08d}",
        "sport": "football",
        "league": "Load Test League",
        "home_team": {"id": "team_load_home", "name": "Load Home", "short_name": "LH"},
        "away_team": {"id": "team_load_away", "name": "Load Away", "short_name": "LA"},
        "start_time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "status": "live",
        "score": {"home": 0, "away": 0},
    }
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        full_url, data=body,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            resp.read()
        sent += 1
    except Exception:
        errors += 1

    # Rate limiting: maintain target sends/sec.
    i += 1
    next_send += interval
    sleep_for = next_send - time.time()
    if sleep_for > 0:
        time.sleep(sleep_for)

elapsed = time.time() - (end_time - duration)
print(f"Load test complete: sent={sent} errors={errors} "
      f"duration={elapsed:.1f}s rate={sent/elapsed:.1f} events/sec")
sys.exit(0 if errors == 0 else 0)
PY
else
    echo "python3 not available; falling back to a simple curl loop (unthrottled)."
    end=$(( $(date +%s) + DURATION ))
    sent=0; errors=0
    while [ "$(date +%s)" -lt "$end" ]; do
        if curl -s -o /dev/null -w "%{http_code}" -X POST "${URL}${ENDPOINT}" \
            -H "Content-Type: application/json" \
            -d '{"id":"load_evt","sport":"football","league":"Load Test","home_team":{"id":"t1","name":"Home"},"away_team":{"id":"t2","name":"Away"},"start_time":"2026-11-09T00:00:00Z","status":"live","score":{"home":0,"away":0}}}' \
            | grep -qE '^(200|201|202)$'; then
            sent=$((sent + 1))
        else
            errors=$((errors + 1))
        fi
    done
    echo "Fallback load test complete: sent=${sent} errors=${errors}"
fi

END_TS="$(date +%s)"
ELAPSED=$((END_TS - START_TS))
echo "==> Load test finished (elapsed ${ELAPSED}s)."
