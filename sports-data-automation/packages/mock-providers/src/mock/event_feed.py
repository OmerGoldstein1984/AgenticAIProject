"""
Mock REST event and settlement feed server.

FILE HEADER
-----------
Business problem this file solves:
    The ingestion service polls REST endpoints for match events and settlements, but a real
    provider's event/settlement API is expensive, rate-limited, and not always available during
    development. MockEventFeed is a self-contained FastAPI server that exposes /events and
    /settlements endpoints (with filtering, pagination, and a /simulate endpoint to mutate state
    on demand), giving the ingestion service a realistic REST source to develop against.

Where it sits in the flow:
    Upstream DATA SOURCE (leaf producer), sibling to MockOddsFeed (WebSocket). The ingestion
    service's RESTPoller (packages/ingestion-service/.../providers/rest_poller.py) polls
    http://localhost:8081/events and /settlements on intervals, then validates/transforms/
    deduplicates/forwards to n8n.

What calls it / what it calls:
    Called by: docker-compose (mock-event-feed service, Dockerfile.events) → python -m mock.event_feed;
    also polled by ingestion-service RESTPoller at runtime.
    Calls: nothing from this repo (FastAPI, uvicorn, stdlib only).
What breaks if removed:
    The ingestion service has no REST event/settlement source; event routing and settlement in
    n8n have no data to act on.
Language conventions:
    Python 3.11+. FastAPI with Query params, uvicorn server. Runs as `python -m mock.event_feed`
    (see Dockerfile.events CMD). Port 8081.
GAP: Data is generated once at startup and kept in memory; /simulate mutates it but there is no
    persistence, so restarting the server loses all simulated state. No deterministic seed mode.
    See 07_issues_found.md.
"""
import asyncio
import json
import logging
import random
import signal
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import JSONResponse
import uvicorn

logger = logging.getLogger(__name__)


class MockEventFeed:
    """Simulates REST API for events and settlements.

    WHAT: A FastAPI app exposing /events (filtered, paginated), /settlements, single-item
        lookups, and /simulate endpoints to mutate event status or create settlements on demand.
    WHY: Lets the ingestion service's REST poller be developed and tested against a realistic
        REST source without a live provider contract. The /simulate endpoints let a demo
        inject events/settlements to drive the settlement and alert pipeline.
    INPUTS (constructor): host, port (default 8081), num_events (100).
    OUTPUTS: none returned; side effect is building self.app (FastAPI) with routes and starting
        an HTTP server on run().
    SIDE EFFECTS: generates self.events and self.settlements in memory at construction;
        binds an HTTP port on run().
    FAILURE MODES: port already in use → uvicorn fails to bind and the process exits.
    ALTERNATIVE: read canned fixtures from JSON. Chosen in-code generation for a self-contained
        mock that can be mutated via /simulate during a live demo.
    # GAP: no persistence or deterministic seed; state is lost on restart. See 07_issues_found.md.
    """

    def __init__(self, host: str = "0.0.0.0", port: int = 8081, num_events: int = 100):
        """Build the event/settlement catalog and wire up FastAPI routes.

        WHAT: Sets host/port/num_events, generates self.events (num_events matches) and
            self.settlements (for ended events), then calls _setup_routes() to register
            all FastAPI endpoints.
        WHY: Settlements are derived from ended events at construction so the settlement
            pipeline has realistic data to consume without waiting for matches to end.
        INPUTS: host, port, num_events (all optional with defaults).
        OUTPUTS: None; sets self.events, self.settlements, self.app.
        SIDE EFFECTS: calls _generate_events and _generate_settlements (uses module-level
            random, so results vary per process); builds self.app with routes.
        FAILURE MODES: none (constructor cannot fail meaningfully).
        """
        self.host = host
        self.port = port
        self.num_events = num_events

        self.events = self._generate_events(num_events)
        self.settlements = self._generate_settlements()
        self.event_index = 0
        self.settlement_index = 0

        self.app = FastAPI(title="Mock Sports Data Feed", version="1.0.0")
        self._setup_routes()

    def _generate_events(self, count: int) -> List[Dict]:
        """Generate the mock match catalog.

        WHAT: Builds `count` matches with random sport/league/teams/start time/status/score,
            deriving status from the match's start time relative to now (future → scheduled,
            recent → live/half_time/ended, old → ended/cancelled/postponed/abandoned).
        WHY: A realistic mix of statuses lets the ingestion service and settlement pipeline
            exercise every code path (live routing, ended settlement, void on cancelled, etc.)
            without waiting for real matches to finish.
        INPUTS: count (number of matches).
        OUTPUTS: list of event dicts (id, sport, league, homeTeam, awayTeam, startTime, status,
            score, metadata).
        SIDE EFFECTS: none (pure function of count + random).
        FAILURE MODES: none.
        ALTERNATIVE: load from fixture. Chosen generation for a self-contained, varied catalog.
        # BUSINESS: the mix of statuses directly determines how much settlement work the
        #    pipeline has; a demo needs a healthy share of "ended" matches so settlement runs.
        """
        sports = ["football", "basketball", "tennis", "baseball", "hockey"]
        leagues = {
            "football": ["Premier League", "La Liga", "Bundesliga", "Serie A", "Ligue 1", "Champions League"],
            "basketball": ["NBA", "EuroLeague", "NCAA"],
            "tennis": ["ATP 250", "ATP 500", "ATP 1000", "Grand Slam", "WTA 250", "WTA 1000"],
            "baseball": ["MLB", "NPB", "KBO"],
            "hockey": ["NHL", "KHL", "SHL"],
        }

        events = []
        for i in range(count):
            sport = random.choice(sports)
            league = random.choice(leagues[sport])

            if sport == "tennis":
                home = f"Player {chr(65 + random.randint(0, 25))}"
                away = f"Player {chr(65 + random.randint(0, 25))}"
                while away == home:
                    away = f"Player {chr(65 + random.randint(0, 25))}"
            else:
                team_prefixes = ["FC", "United", "City", "Athletic", "Rovers", "Town", "Albion"]
                home = f"{random.choice(['Red', 'Blue', 'Green', 'White', 'Black'])} {random.choice(team_prefixes)}"
                away = f"{random.choice(['Yellow', 'Orange', 'Purple', 'Pink', 'Brown'])} {random.choice(team_prefixes)}"

            start_time = datetime.utcnow() + timedelta(
                minutes=random.randint(-120, 240)
            )

            # Determine status based on time
            if start_time > datetime.utcnow() + timedelta(minutes=5):
                status = "scheduled"
            elif start_time > datetime.utcnow() - timedelta(minutes=90):
                if random.random() < 0.7:
                    status = "live"
                elif random.random() < 0.1:
                    status = "half_time"
                else:
                    status = "ended"
            else:
                status = random.choice(["ended", "cancelled", "postponed", "abandoned"])

            score = None
            if status in ("live", "half_time", "ended"):
                if sport == "tennis":
                    score = {"home": random.randint(0, 3), "away": random.randint(0, 3)}
                elif sport in ("football", "hockey"):
                    score = {"home": random.randint(0, 4), "away": random.randint(0, 4)}
                elif sport == "basketball":
                    score = {"home": random.randint(80, 120), "away": random.randint(80, 120)}
                elif sport == "baseball":
                    score = {"home": random.randint(0, 10), "away": random.randint(0, 10)}

            events.append({
                "id": f"evt_{i:06d}",
                "sport": sport,
                "league": league,
                "homeTeam": {"id": f"team_{i}_home", "name": home, "shortName": home[:3].upper()},
                "awayTeam": {"id": f"team_{i}_away", "name": away, "shortName": away[:3].upper()},
                "startTime": start_time.isoformat() + "Z",
                "status": status,
                "score": score,
                "metadata": {
                    "venue": f"Stadium {i}",
                    "referee": f"Ref {random.randint(1, 100)}",
                },
            })

        return events

    def _generate_settlements(self) -> List[Dict]:
        """Generate mock settlements for ended events.

        WHAT: For each ended event (up to 50), compute a settlement outcome from the score
            (home/away win, draw, or void 5% of the time) with a settledAt two hours after
            start and confidence 0.95-1.0.
        WHY: The settlement pipeline needs official-looking results to consume; pre-generating
            them means the /settlements endpoint returns data immediately on startup.
        INPUTS: none (uses self.events).
        OUTPUTS: list of settlement dicts (eventId, marketId, selectionId, outcome, settledAt,
            source, confidence).
        SIDE EFFECTS: none (reads self.events only).
        FAILURE MODES: none.
        ALTERNATIVE: fetch settlements from a real odds provider's results API. Chosen
            in-code derivation because no provider credentials exist here.
        # BUSINESS: settlement outcome drives payouts; getting it wrong (e.g. mis-handling a
        #    tennis retirement) is a regulatory and financial issue. The mock models a clean
        #    "official" source so the settlement engine can be validated against it.
        """
        settlements = []
        ended_events = [e for e in self.events if e["status"] == "ended"]

        for event in ended_events[:50]:  # Settle first 50 ended events
            sport = event["sport"]

            if sport == "tennis":
                # Tennis: winner based on sets
                home_sets = event["score"]["home"]
                away_sets = event["score"]["away"]
                if home_sets > away_sets:
                    outcome = "won"
                    selection = "home_win"
                else:
                    outcome = "lost"
                    selection = "away_win"
            elif sport in ("football", "hockey"):
                home_goals = event["score"]["home"]
                away_goals = event["score"]["away"]
                if home_goals > away_goals:
                    outcome = "won"
                    selection = "home_win"
                elif away_goals > home_goals:
                    outcome = "lost"
                    selection = "away_win"
                else:
                    outcome = "won"
                    selection = "draw"
            else:
                outcome = random.choice(["won", "lost"])
                selection = random.choice(["home_win", "away_win", "draw"])

            # Add some void settlements
            if random.random() < 0.05:
                outcome = "void"
                selection = "void"

            settled_at = datetime.fromisoformat(event["startTime"].replace("Z", "")) + timedelta(hours=2)

            settlements.append({
                "eventId": event["id"],
                "marketId": "match_winner",
                "selectionId": selection,
                "outcome": outcome,
                "settledAt": settled_at.isoformat() + "Z",
                "source": "official",
                "confidence": round(random.uniform(0.95, 1.0), 2),
            })

        return settlements

    def _setup_routes(self):
        """Register all FastAPI routes on self.app.

        WHAT: Defines /health, /events (list with filtering/pagination), /events/{event_id},
            /settlements (list with filtering/pagination),
            /settlements/{event_id}/{market_id}/{selection_id}, and two /simulate endpoints
            (mutate event status / create a settlement).
        WHY: These endpoints mirror the shape of a real sports-data provider's REST API so the
            ingestion service's RESTPoller can be tested against a realistic contract.
        INPUTS: none (uses self.events, self.settlements).
        OUTPUTS: None; side effect is decorating self.app with route handlers.
        SIDE EFFECTS: none beyond route registration.
        FAILURE MODES: route handlers raise HTTPException(404) for missing items and
            HTTPException(400)/409 for bad input — these are FastAPI's normal error responses.
        ALTERNATIVE: None needed; this is the mock's entire surface area.
        """

        @self.app.get("/health")
        async def health():
            """Health endpoint: report how many events/settlements are loaded."""
            return {"status": "healthy", "events": len(self.events), "settlements": len(self.settlements)}

        @self.app.get("/events")
        async def get_events(
            limit: int = Query(default=50, le=500),
            offset: int = Query(default=0, ge=0),
            sport: Optional[str] = Query(default=None),
            status: Optional[str] = Query(default=None),
            league: Optional[str] = Query(default=None),
            since: Optional[str] = Query(default=None),
        ):
            """Get events with filtering and pagination.

            WHAT: Filters self.events by sport/status/league/since, paginates [offset:offset+limit],
                and returns {data, pagination: {total, limit, offset, has_more}}.
            WHY: Real providers paginate; the ingestion poller must handle pagination and
                incremental fetching (since) rather than re-fetching everything.
            INPUTS: query params limit/offset/sport/status/league/since.
            OUTPUTS: dict with data (list) and pagination metadata.
            SIDE EFFECTS: none (reads self.events only).
            FAILURE MODES: invalid `since` format → HTTPException(400).
            ALTERNATIVE: return all events unpaginated. Chosen pagination because real feeds are
                large and the poller must handle cursors/pages.
            # INTERVIEW: pagination + `since` is how the poller avoids re-processing the same
            #    events on every poll — key to efficient, idempotent ingestion.
            """
            filtered = self.events

            if sport:
                filtered = [e for e in filtered if e["sport"] == sport]
            if status:
                filtered = [e for e in filtered if e["status"] == status]
            if league:
                filtered = [e for e in filtered if e["league"] == league]
            if since:
                try:
                    since_dt = datetime.fromisoformat(since.replace("Z", ""))
                    filtered = [
                        e for e in filtered
                        if datetime.fromisoformat(e["startTime"].replace("Z", "")) >= since_dt
                    ]
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid since format")

            total = len(filtered)
            paginated = filtered[offset:offset + limit]

            return {
                "data": paginated,
                "pagination": {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "has_more": offset + limit < total,
                },
            }

        @self.app.get("/events/{event_id}")
        async def get_event(event_id: str):
            """Get single event by ID."""
            event = next((e for e in self.events if e["id"] == event_id), None)
            if not event:
                raise HTTPException(status_code=404, detail="Event not found")
            return event

        @self.app.get("/settlements")
        async def get_settlements(
            limit: int = Query(default=50, le=500),
            offset: int = Query(default=0, ge=0),
            event_id: Optional[str] = Query(default=None),
            since: Optional[str] = Query(default=None),
        ):
            """Get settlements with filtering and pagination."""
            filtered = self.settlements

            if event_id:
                filtered = [s for s in filtered if s["eventId"] == event_id]
            if since:
                try:
                    since_dt = datetime.fromisoformat(since.replace("Z", ""))
                    filtered = [
                        s for s in filtered
                        if datetime.fromisoformat(s["settledAt"].replace("Z", "")) >= since_dt
                    ]
                except ValueError:
                    raise HTTPException(status_code=400, detail="Invalid since format")

            total = len(filtered)
            paginated = filtered[offset:offset + limit]

            return {
                "data": paginated,
                "pagination": {
                    "total": total,
                    "limit": limit,
                    "offset": offset,
                    "has_more": offset + limit < total,
                },
            }

        @self.app.get("/settlements/{event_id}/{market_id}/{selection_id}")
        async def get_settlement(event_id: str, market_id: str, selection_id: str):
            """Get single settlement."""
            settlement = next(
                (s for s in self.settlements
                 if s["eventId"] == event_id and s["marketId"] == market_id and s["selectionId"] == selection_id),
                None
            )
            if not settlement:
                raise HTTPException(status_code=404, detail="Settlement not found")
            return settlement

        @self.app.post("/events/simulate")
        async def simulate_event_update():
            """Simulate a random event update (for testing/demo)."""
            if not self.events:
                raise HTTPException(status_code=404, detail="No events available")

            event = random.choice(self.events)

            # Update status
            if event["status"] == "scheduled":
                event["status"] = "live"
            elif event["status"] == "live":
                if random.random() < 0.3:
                    event["status"] = "half_time"
            elif event["status"] == "half_time":
                event["status"] = "live"
            elif event["status"] == "live" and random.random() < 0.1:
                event["status"] = "ended"
                # Generate score
                if event["sport"] == "tennis":
                    event["score"] = {"home": random.randint(2, 3), "away": random.randint(0, 2)}
                elif event["sport"] in ("football", "hockey"):
                    event["score"] = {"home": random.randint(0, 4), "away": random.randint(0, 4)}
                elif event["sport"] == "basketball":
                    event["score"] = {"home": random.randint(80, 120), "away": random.randint(80, 120)}

            return {"status": "updated", "event": event}

        @self.app.post("/settlements/simulate")
        async def simulate_settlement():
            """Simulate a new settlement (for testing/demo)."""
            live_events = [e for e in self.events if e["status"] == "ended"]
            if not live_events:
                raise HTTPException(status_code=404, detail="No ended events available")

            event = random.choice(live_events)

            # Check if already settled
            existing = next(
                (s for s in self.settlements if s["eventId"] == event["id"]),
                None
            )
            if existing:
                raise HTTPException(status_code=409, detail="Event already settled")

            sport = event["sport"]
            if sport == "tennis":
                home_sets = event["score"]["home"]
                away_sets = event["score"]["away"]
                if home_sets > away_sets:
                    outcome = "won"
                    selection = "home_win"
                else:
                    outcome = "lost"
                    selection = "away_win"
            else:
                home_goals = event["score"]["home"]
                away_goals = event["score"]["away"]
                if home_goals > away_goals:
                    outcome = "won"
                    selection = "home_win"
                elif away_goals > home_goals:
                    outcome = "lost"
                    selection = "away_win"
                else:
                    outcome = "won"
                    selection = "draw"

            settlement = {
                "eventId": event["id"],
                "marketId": "match_winner",
                "selectionId": selection,
                "outcome": outcome,
                "settledAt": datetime.utcnow().isoformat() + "Z",
                "source": "official",
                "confidence": 1.0,
            }

            self.settlements.append(settlement)
            return {"status": "created", "settlement": settlement}

    async def run(self):
        """Run the FastAPI server with uvicorn.

        WHAT: Builds a uvicorn.Config around self.app and serves forever.
        WHY: Entry point called by main(); makes the mock actually listen on HTTP.
        INPUTS: none (uses self.host, self.port, self.app).
        OUTPUTS: None; runs until cancelled.
        SIDE EFFECTS: binds an HTTP port and blocks the event loop.
        FAILURE MODES: port in use → uvicorn fails to bind, process exits.
        ALTERNATIVE: run with `uvicorn mock.event_feed:app` from CLI. Chosen programmatic run
            so main() can install signal handlers for clean shutdown.
        """
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()


async def main():
    """Main entry point: build the feed, handle signals, run the server.

    WHAT: Reads HOST/PORT from env, builds MockEventFeed, installs SIGTERM/SIGINT handlers that
        stop the loop, then runs feed.run() until cancelled.
    WHY: Standard async service entry point with clean shutdown for `docker compose stop`/Ctrl+C.
    INPUTS: none (env vars HOST, PORT).
    OUTPUTS: None; runs until cancelled.
    SIDE EFFECTS: binds HTTP port 8081, installs signal handlers, blocks the event loop.
    FAILURE MODES: if run() fails (port in use), the exception propagates and the process exits.
    ALTERNATIVE: `uvicorn mock.event_feed:app --reload` for dev. Chosen programmatic run for
        deterministic signal handling in docker/tests.
    """
    import os

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8081"))

    feed = MockEventFeed(host=host, port=port)

    # Handle shutdown
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: loop.stop())

    await feed.run()


if __name__ == "__main__":
    asyncio.run(main())
