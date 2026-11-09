"""
scripts/seed_demo_data.py
=========================
FILE HEADER
-----------
Business problem this file solves:
    The stack needs realistic demo data (events, odds, settlements) so the interview demo can
    show end-to-end settlement, odds normalization, alerts, and reconciliation without waiting
    on the mock feeds' random output. seed_demo_data.py seeds deterministic demo events/odds/
    settlements via the ingestion service API (or directly) so the platform is demoable on
    demand.

Where it sits in the flow:
    Developer-experience / operations layer. Run from the host:
        python3 scripts/seed_demo_data.py --url http://localhost:8000
    It POSTs to /ingest/event, /ingest/odds, and /ingest/settlement. It can also be run as
    `python -m scripts.seed_demo_data` when the scripts/ directory is on the Python path
    (e.g. inside a container that mounts scripts/).

What calls it / what it calls:
    Called by: scripts/dev-setup.sh, `make demo-data` (adapted), developers.
    Calls: httpx/urllib (HTTP client), stdlib argparse/json/datetime/uuid.

What breaks if removed:
    `make demo-data` has nothing to seed; the demo starts with empty or random data and the
    settlement/alert/reconciliation paths have no deterministic scenario to show.

Language conventions:
    Python 3.11+. Standard library only (urllib) so it runs without installing extra deps.
    Deterministic data (fixed event IDs, scores, odds) for reproducible demos.
    Validate input at system boundaries: --url must be a valid HTTP URL; counts must be
    non-negative integers.
"""

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List


def _build_events() -> List[Dict[str, Any]]:
    """Build a deterministic set of demo events across sports/statuses."""
    now = datetime.now(timezone.utc)
    events = [
        {
            "id": "evt_demo_football_01",
            "sport": "football",
            "league": "Premier League",
            "home_team": {"id": "team_demo_home_01", "name": "Red United", "short_name": "RED"},
            "away_team": {"id": "team_demo_away_01", "name": "Blue City", "short_name": "BLU"},
            "start_time": (now + timedelta(hours=2)).isoformat(),
            "status": "scheduled",
            "score": {"home": 0, "away": 0},
        },
        {
            "id": "evt_demo_football_02",
            "sport": "football",
            "league": "Premier League",
            "home_team": {"id": "team_demo_home_02", "name": "Green Athletic", "short_name": "GRN"},
            "away_team": {"id": "team_demo_away_02", "name": "Yellow Rovers", "short_name": "YEL"},
            "start_time": (now - timedelta(hours=2)).isoformat(),
            "status": "ended",
            "score": {"home": 2, "away": 1},
        },
        {
            "id": "evt_demo_tennis_01",
            "sport": "tennis",
            "league": "ATP 1000",
            "home_team": {"id": "team_demo_home_03", "name": "Player A", "short_name": "PA"},
            "away_team": {"id": "team_demo_away_03", "name": "Player B", "short_name": "PB"},
            "start_time": (now + timedelta(hours=1)).isoformat(),
            "status": "live",
            "score": {"home": 1, "away": 1},
        },
        {
            "id": "evt_demo_basketball_01",
            "sport": "basketball",
            "league": "NBA",
            "home_team": {"id": "team_demo_home_04", "name": "West Lions", "short_name": "WL"},
            "away_team": {"id": "team_demo_away_04", "name": "East Tigers", "short_name": "ET"},
            "start_time": (now - timedelta(hours=5)).isoformat(),
            "status": "ended",
            "score": {"home": 102, "away": 98},
        },
    ]
    return events


def _build_odds() -> List[Dict[str, Any]]:
    """Build deterministic demo odds quotes (decimal format, internal canonical)."""
    odds = [
        # match_winner for football_01 (scheduled)
        {"provider_id": "provider_0", "event_id": "evt_demo_football_01", "market_id": "match_winner", "selection_id": "home", "odds": 2.10, "format": "decimal", "sequence": 1},
        {"provider_id": "provider_0", "event_id": "evt_demo_football_01", "market_id": "match_winner", "selection_id": "draw", "odds": 3.30, "format": "decimal", "sequence": 2},
        {"provider_id": "provider_0", "event_id": "evt_demo_football_01", "market_id": "match_winner", "selection_id": "away", "odds": 3.50, "format": "decimal", "sequence": 3},
        # second provider for football_01 (arbitrage-ish comparison)
        {"provider_id": "provider_1", "event_id": "evt_demo_football_01", "market_id": "match_winner", "selection_id": "home", "odds": 2.25, "format": "decimal", "sequence": 1},
        {"provider_id": "provider_1", "event_id": "evt_demo_football_01", "market_id": "match_winner", "selection_id": "draw", "odds": 3.10, "format": "decimal", "sequence": 2},
        {"provider_id": "provider_1", "event_id": "evt_demo_football_01", "market_id": "match_winner", "selection_id": "away", "odds": 3.40, "format": "decimal", "sequence": 3},
        # total_goals
        {"provider_id": "provider_0", "event_id": "evt_demo_football_01", "market_id": "total_goals", "selection_id": "over_2.5", "odds": 1.90, "format": "decimal", "sequence": 10},
        {"provider_id": "provider_0", "event_id": "evt_demo_football_01", "market_id": "total_goals", "selection_id": "under_2.5", "odds": 1.90, "format": "decimal", "sequence": 11},
    ]
    return odds


def _build_settlements() -> List[Dict[str, Any]]:
    """Build deterministic demo settlements for ended events (official results)."""
    now = datetime.now(timezone.utc)
    settlements = [
        # football_01 is scheduled -> no settlement yet
        # football_02 ended 2-1 home win -> home won
        {
            "event_id": "evt_demo_football_02",
            "market_id": "match_winner",
            "selection_id": "home",
            "outcome": "won",
            "settled_at": now.isoformat(),
            "source": "official",
            "confidence": 1.0,
        },
        {
            "event_id": "evt_demo_football_02",
            "market_id": "match_winner",
            "selection_id": "away",
            "outcome": "lost",
            "settled_at": now.isoformat(),
            "source": "official",
            "confidence": 1.0,
        },
        {
            "event_id": "evt_demo_football_02",
            "market_id": "match_winner",
            "selection_id": "draw",
            "outcome": "lost",
            "settled_at": now.isoformat(),
            "source": "official",
            "confidence": 1.0,
        },
        # basketball_01 ended 102-98 home win -> home won
        {
            "event_id": "evt_demo_basketball_01",
            "market_id": "match_winner",
            "selection_id": "home",
            "outcome": "won",
            "settled_at": now.isoformat(),
            "source": "official",
            "confidence": 1.0,
        },
        {
            "event_id": "evt_demo_basketball_01",
            "market_id": "match_winner",
            "selection_id": "away",
            "outcome": "lost",
            "settled_at": now.isoformat(),
            "source": "official",
            "confidence": 1.0,
        },
    ]
    return settlements


def _post(url: str, path: str, payload: Any, timeout: float = 10.0) -> Dict[str, Any]:
    """POST JSON payload to url/path. Returns the parsed JSON response or an error dict."""
    full_url = url.rstrip("/") + path
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        full_url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw.strip() else {"status": "ok"}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        return {"status": "error", "code": exc.code, "body": raw}
    except Exception as exc:  # pragma: no cover - network failure
        return {"status": "error", "error": str(exc)}


def seed(base_url: str) -> Dict[str, int]:
    """Seed events, odds, and settlements into the ingestion service.

    WHAT: Posts every demo event to /ingest/event, every odds quote to /ingest/odds, and
        every settlement to /ingest/settlement. Returns a summary counts dict.
    WHY: Deterministic demo data makes the settlement/alert/reconciliation demo scenario
        reproducible on every run.
    INPUTS: base_url (ingestion service base URL).
    OUTPUTS: dict with events/odds/settlements counts and per-item statuses.
    SIDE EFFECTS: makes outbound HTTP POST requests to the ingestion service.
    FAILURE MODES: individual POST failures are recorded but do not abort the whole seed;
        connection refused returns an error count.
    """
    events = _build_events()
    odds = _build_odds()
    settlements = _build_settlements()

    event_statuses: List[Dict[str, Any]] = []
    for ev in events:
        event_statuses.append({"id": ev["id"], "result": _post(base_url, "/ingest/event", ev)})

    odds_statuses: List[Dict[str, Any]] = []
    for od in odds:
        odds_statuses.append({"selection_id": od["selection_id"], "result": _post(base_url, "/ingest/odds", od)})

    settlement_statuses: List[Dict[str, Any]] = []
    for st in settlements:
        settlement_statuses.append({"selection_id": st["selection_id"], "result": _post(base_url, "/ingest/settlement", st)})

    return {
        "events": len(events),
        "odds": len(odds),
        "settlements": len(settlements),
        "event_statuses": event_statuses,
        "odds_statuses": odds_statuses,
        "settlement_statuses": settlement_statuses,
    }


def _parse_args(argv: List[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Seed demo events, odds, and settlements into the ingestion service."
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000",
        help="Ingestion service base URL (default: http://localhost:8000)",
    )
    return parser.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    """CLI entry point: seed demo data and print a summary."""
    args = _parse_args(sys.argv[1:] if argv is None else argv)

    # Validate the URL boundary: must be http/https.
    if not (args.url.startswith("http://") or args.url.startswith("https://")):
        print(f"Error: --url must start with http:// or https://, got: {args.url}", file=sys.stderr)
        return 2

    print(f"Seeding demo data into {args.url} ...")
    try:
        summary = seed(args.url)
    except Exception as exc:  # pragma: no cover - network failure
        print(f"Error seeding demo data: {exc}", file=sys.stderr)
        return 1

    print(f"  events seeded:     {summary['events']}")
    print(f"  odds seeded:       {summary['odds']}")
    print(f"  settlements seeded:{summary['settlements']}")
    failures = 0
    for key in ("event_statuses", "odds_statuses", "settlement_statuses"):
        for item in summary[key]:
            result = item["result"]
            if result.get("status") not in ("processed", "accepted", "duplicate", "ok"):
                failures += 1
                print(f"  FAILED {item}: {result}")
    if failures:
        print(f"Completed with {failure}s failure(s).")
        return 1
    print("Demo data seeded successfully.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
