"""Mock REST event and settlement feed server."""
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
    """Simulates REST API for events and settlements."""

    def __init__(self, host: str = "0.0.0.0", port: int = 8081, num_events: int = 100):
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
        """Generate mock events."""
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
        """Generate mock settlements for ended events."""
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
        """Setup FastAPI routes."""

        @self.app.get("/health")
        async def health():
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
            """Get events with filtering and pagination."""
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
            """Simulate a random event update (for testing)."""
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
            """Simulate a new settlement (for testing)."""
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
        """Run the server."""
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="info",
        )
        server = uvicorn.Server(config)
        await server.serve()


async def main():
    """Main entry point."""
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