"""
Mock WebSocket odds feed server.

FILE HEADER
-----------
Business problem this file solves:
    Sportsbooks receive live odds from multiple providers (LSports, Betradar, Sportradar...) over
    WebSocket, in different formats (decimal/American/fractional), at high frequency
    (every 500ms-2s). The ingestion service needs a realistic, controllable source of odds to
    develop and test against without connecting to a real (expensive, rate-limited) provider feed.
    MockOddsFeed simulates exactly that: a WebSocket server that broadcasts randomized odds
    updates plus an initial snapshot on connect, mimicking a real provider's push behavior.

Where it sits in the flow:
    Upstream DATA SOURCE (leaf producer). The ingestion service's WebSocketClient
    (packages/ingestion-service/.../providers/websocket_client.py) connects here, receives the
    odds JSON, validates/transforms/deduplicates it, and forwards to n8n. This mock is what makes
    the stack runnable end-to-end in dev without a live LSports contract.

What calls it / what it calls:
    Called by: docker-compose (mock-odds-feed service, Dockerfile.odds) → python -m mock.odds_feed.
    Calls: nothing from this repo (only stdlib + websockets). It is a producer, not a consumer.

What breaks if removed:
    The ingestion service has no live-odds source to connect to; /ingest/odds and the WebSocket
    path go quiet. The rest of the pipeline (n8n nodes, settlement, alerts) has no data to act on.

Language conventions:
    Python 3.11+. asyncio, stdlib logging, websockets library. Runs as `python -m mock.odds_feed`
    (see Dockerfile.odds CMD). Config via env vars HOST/PORT/FEED_INTERVAL_MS.

GAP: The broadcast loop pushes random data; it does not read from or replay a real provider feed,
    and there is no way to inject a specific odds scenario on demand beyond randomness. Historical
    replay (mentioned in README/PROJECT_SPEC) is not implemented here. See 07_issues_found.md.
"""
import asyncio
import json
import logging
import random
import signal
import uuid
from datetime import datetime, timedelta
from typing import Dict, List, Set
import websockets
from websockets.server import WebSocketServerProtocol

logger = logging.getLogger(__name__)


class MockOddsFeed:
    """Simulates a live odds feed via WebSocket.

    WHAT: A WebSocket server that broadcasts randomized odds updates to every connected client
        on a fixed interval, and sends an initial snapshot (first 10 events x providers x 2
        markets) on each new connection.
    WHY: Provides a deterministic, always-available feed so the ingestion service can be built,
        tested, and demoed without a paid real provider. Mirrors the push model of real sports
        data feeds (LSports-style).
    INPUTS (constructor): host, port, interval_ms (default 500ms), num_events (50),
        num_providers (3).
    OUTPUTS: nothing returned; side effect is opening a listening socket and pushing JSON
        messages to connected WebSocket clients.
    SIDE EFFECTS: binds to host:port, spawns a broadcast task, maintains an in-memory set of
        connected clients and per-producer sequence counters.
    FAILURE MODES: port already in use → websockets.serve raises OSError and the process exits;
        client send failures are caught per-client so one dead client doesn't kill the feed.
    ALTERNATIVE: read canned fixtures from a file. Chosen random generation because it produces
        endless, varied data for load testing and demos without shipping fixture files.
    # GAP: no seed/deterministic mode — each run generates different data, which makes
    #    reproducible demo scenarios and deterministic tests harder. See 07_issues_found.md.
    """

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        interval_ms: int = 500,
        num_events: int = 50,
        num_providers: int = 3,
    ):
        """Configure the feed and generate the in-memory mock catalog.

        WHAT: Sets network params, builds self.events (num_events matches), creates
            self.providers (provider_0..N), and zeroes self.sequences per provider.
        WHY: The catalog is the source of truth that _generate_odds_update and the snapshot draw
            from; sequences must start at zero so dedup keys are stable within a run.
        INPUTS: host/port/interval_ms/num_events/num_producers (all optional with defaults).
        OUTPUTS: None; sets instance attributes.
        SIDE EFFECTS: calls _generate_events(num_events) which uses module-level random, so
            results vary per process (see GAP above).
        FAILURE MODES: none (constructor cannot fail meaningfully).
        """
        self.host = host
        self.port = port
        self.interval_ms = interval_ms
        self.num_events = num_events
        self.num_providers = num_providers

        self._server = None
        self._clients: Set[WebSocketServerProtocol] = set()
        self._running = False
        self._broadcast_task: asyncio.Task | None = None

        # Generate mock data
        self.providers = [f"provider_{i}" for i in range(num_providers)]
        self.events = self._generate_events(num_events)
        self.sequences = {provider: 0 for provider in self.providers}

    def _generate_events(self, count: int) -> List[Dict]:
        """Build the static mock match catalog used by the feed.

        WHAT: Generates `count` matches with random sport/league/teams/start time/status/score.
        WHY: The feed needs a fixed set of events to reference in odds updates; generating them
            once in the constructor keeps every odds update pointing at real-looking event IDs.
        INPUTS: count (number of matches).
        OUTPUTS: list of event dicts with id, sport, league, homeTeam, awayTeam, startTime,
            status, score.
        SIDE EFFECTS: none (pure function of count + module-level random).
        FAILURE MODES: none.
        ALTERNATIVE: load events from a JSON fixture. Chosen in-code generation for a
            self-contained, dependency-free mock.
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

            # Generate team names
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
                minutes=random.randint(-60, 120)
            )

            status = "scheduled"
            if start_time < datetime.utcnow():
                if random.random() < 0.3:
                    status = "live"
                elif random.random() < 0.1:
                    status = "half_time"
                else:
                    status = "ended"

            events.append({
                "id": f"evt_{i:06d}",
                "sport": sport,
                "league": league,
                "homeTeam": {"id": f"team_{i}_home", "name": home},
                "awayTeam": {"id": f"team_{i}_away", "name": away},
                "startTime": start_time.isoformat() + "Z",
                "status": status,
            })

        return events

    def _generate_odds_update(self) -> Dict:
        """Produce one randomized odds update message.

        WHAT: Picks a random event/provider/market/selection, computes odds in a random format
            (decimal/American/fractional), and returns a CanonicalOdds-shaped dict with a fresh
            per-provider sequence number.
        WHY: Simulates the continuous stream of price changes a real provider pushes. The format
            randomization exercises the ingestion service's normalization (American/fractional
            → decimal) on every update.
        INPUTS: none (uses self.events, self.providers, self.sequences).
        OUTPUTS: a dict with providerId, eventId, marketId, selectionId, odds, format,
            timestamp, sequence.
        SIDE EFFECTS: increments self.sequences[provider] (monotonic per-producer counter).
        FAILURE MODES: none (dict construction cannot fail meaningfully).
        ALTERNATIVE: stream real provider prices. Chosen random because no live provider
            credentials exist in this interview project.
        # BUSINESS: odds are the highest-volume feed; if normalization mis-handles a format,
        #    traders see wrong prices and the book loses money. This mock lets us test that path.
        """
        event = random.choice(self.events)
        provider = random.choice(self.providers)

        # Market types
        markets = [
            {"id": "match_winner", "selections": ["home", "draw", "away"]},
            {"id": "total_goals", "selections": ["over_2.5", "under_2.5"]},
            {"id": "both_teams_score", "selections": ["yes", "no"]},
            {"id": "correct_score", "selections": ["1-0", "2-0", "2-1", "1-1", "0-1", "0-2"]},
        ]

        market = random.choice(markets)
        selection = random.choice(market["selections"])

        # Base odds with some variation
        base_odds = {
            "match_winner": {"home": 2.1, "draw": 3.3, "away": 3.5},
            "total_goals": {"over_2.5": 1.9, "under_2.5": 1.9},
            "both_teams_score": {"yes": 1.8, "no": 2.0},
            "correct_score": {"1-0": 6.5, "2-0": 7.0, "2-1": 8.5, "1-1": 6.0, "0-1": 7.5, "0-2": 8.0},
        }

        base = base_odds[market["id"]].get(selection, 2.0)
        # Add noise
        odds = round(base * random.uniform(0.95, 1.05), 2)

        # Cycle through formats
        formats = ["decimal", "american", "fractional"]
        fmt = random.choice(formats)

        # Convert to requested format
        if fmt == "american":
            if odds >= 2.0:
                odds = round((odds - 1) * 100)
            else:
                odds = round(-100 / (odds - 1))
        elif fmt == "fractional":
            # Simplified fractional
            odds = round(odds - 1, 1)

        self.sequences[provider] += 1

        return {
            "providerId": provider,
            "eventId": event["id"],
            "marketId": market["id"],
            "selectionId": selection,
            "odds": odds,
            "format": fmt,
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "sequence": self.sequences[provider],
        }

    async def _broadcast_loop(self):
        """Broadcast odds updates to all connected clients.

        WHAT: While running, generates 1-3 updates per interval and fans each JSON message out
            to every connected WebSocket client, dropping clients that have disconnected.
        WHY: This is the core "push" behavior — one producer, many consumers, just like a real
            feed fan-out. Clients that drop are cleaned up so the loop doesn't keep retrying dead
            sockets.
        INPUTS: none (reads self._running, self._clients, self.interval_ms).
        OUTPUTS: None; side effect is writing to client sockets.
        SIDE EFFECTS: mutates self._clients (removes disconnected); sleeps between intervals.
        FAILURE MODES: broadcast exception is logged but the loop continues (resilient to a
            single bad send).
        ALTERNATIVE: push to a message queue (Redis/Kafka) instead of direct sockets. Chosen
            direct WebSocket because the ingestion client speaks WebSocket, keeping the mock
            simple and protocol-faithful.
        # GAP: no backpressure — if a client is slow, sends block the broadcast loop for all
        #    clients. A production feed would use a per-client queue or a broker. See
        #    07_issues_found.md.
        """
        while self._running:
            try:
                # Generate 1-3 updates per interval
                num_updates = random.randint(1, 3)
                for _ in range(num_updates):
                    update = self._generate_odds_update()
                    message = json.dumps(update)

                    # Send to all connected clients
                    if self._clients:
                        disconnected = set()
                        for client in self._clients:
                            try:
                                await client.send(message)
                            except websockets.ConnectionClosed:
                                disconnected.add(client)
                            except Exception as e:
                                logger.warning(f"Error sending to client: {e}")
                                disconnected.add(client)

                        # Clean up disconnected clients
                        self._clients -= disconnected

            except Exception as e:
                logger.exception(f"Broadcast error: {e}")

            await asyncio.sleep(self.interval_ms / 1000.0)

    async def _handler(self, websocket: WebSocketServerProtocol):
        """Handle a new WebSocket connection from one ingestion client.

        WHAT: Registers the client, sends an initial snapshot (first 10 events x providers x
            2 markets) so the client has current prices immediately, then keeps the connection
            alive until it closes.
        WHY: A real feed sends a snapshot on subscribe so the client isn't starting from empty;
            this mirrors that behavior so the ingestion service sees data right after connect.
        INPUTS: websocket (the new client connection).
        OUTPUTS: None; side effect is adding/removing the client from self._clients and sending
            the snapshot.
        SIDE EFFECTS: mutates self._clients; sends many messages on connect.
        FAILURE MODES: ConnectionClosed is handled cleanly; other exceptions logged; client
            always removed from self._clients in finally.
        ALTERNATIVE: send snapshot lazily on first request. Chosen eager snapshot so the client
            has a usable state immediately, matching real feed subscribe semantics.
        """
        client_id = id(websocket)
        self._clients.add(websocket)
        logger.info(f"Client connected: {client_id} (total: {len(self._clients)})")

        try:
            # Send initial snapshot
            for event in self.events[:10]:  # Send first 10 events as snapshot
                for provider in self.providers:
                    for market in ["match_winner", "total_goals"]:
                        self.sequences[provider] += 1
                        snapshot = {
                            "providerId": provider,
                            "eventId": event["id"],
                            "marketId": market,
                            "selectionId": "home" if market == "match_winner" else "over_2.5",
                            "odds": round(random.uniform(1.5, 4.0), 2),
                            "format": "decimal",
                            "timestamp": datetime.utcnow().isoformat() + "Z",
                            "sequence": self.sequences[provider],
                        }
                        await websocket.send(json.dumps(snapshot))

            # Keep connection alive
            await websocket.wait_closed()
        except websockets.ConnectionClosed:
            pass
        except Exception as e:
            logger.exception(f"Handler error: {e}")
        finally:
            self._clients.discard(websocket)
            logger.info(f"Client disconnected: {client_id} (total: {len(self._clients)})")

    async def start(self):
        """Start the WebSocket server and the broadcast loop.

        WHAT: Binds to host:port via websockets.serve and launches _broadcast_loop as a task.
        WHY: Entry point called by main(); makes the feed actually listen and push data.
        INPUTS: none (uses self.host, self.port).
        OUTPUTS: None; side effect is opening the listening port and starting the broadcast task.
        SIDE EFFECTS: sets self._server and self._broadcast_task; binds a TCP port.
        FAILURE MODES: port already bound → OSError propagates to main() and exits the process.
        ALTERNATIVE: None — this is the only way to start serving.
        # INTERVIEW: know that websockets.serve is async and must be awaited; the server keeps
        #    running until stop() is called or the process exits.
        """
        self._running = True

        self._server = await websockets.serve(
            self._handler,
            self.host,
            self.port,
            ping_interval=20,
            ping_timeout=10,
        )

        self._broadcast_task = asyncio.create_task(self._broadcast_loop())

        logger.info(f"Mock odds feed started on ws://{self.host}:{self.port}")

    async def stop(self):
        """Stop the WebSocket server and close all client connections.

        WHAT: Sets _running False, cancels the broadcast task, closes the server, and closes
            every client WebSocket.
        WHY: Clean shutdown (signal handlers call this) so ports are released and clients aren't
            left hanging; important for `docker compose down` and test teardown.
        INPUTS: none.
        OUTPUTS: None; side effect is closing sockets and clearing self._clients.
        SIDE EFFECTS: cancels self._broadcast_task; closes self._server and all clients.
        FAILURE MODES: CancelledError swallowed during task await; close errors not raised.
        ALTERNATIVE: let the process exit and rely on the OS to close ports. Chosen explicit
            stop for deterministic test/teardown behavior.
        """
        self._running = False

        if self._broadcast_task:
            self._broadcast_task.cancel()
            try:
                await self._broadcast_task
            except asyncio.CancelledError:
                pass

        if self._server:
            self._server.close()
            await self._server.wait_closed()

        # Close all client connections
        for client in self._clients:
            await client.close()
        self._clients.clear()

        logger.info("Mock odds feed stopped")


async def main():
    """Main entry point: configure logging, build the feed, handle signals, run forever.

    WHAT: Reads HOST/PORT/FEED_INTERVAL_MS from env, builds MockOddsFeed, installs SIGTERM/
        SIGINT handlers that call feed.stop(), then awaits feed.start() and blocks on an
        asyncio.Future until cancelled.
    WHY: Standard async service entry point; signal handling makes `docker compose stop` and
        Ctrl+C shut the feed down cleanly instead of killing it mid-broadcast.
    INPUTS: none (env vars).
    OUTPUTS: None; runs until cancelled.
    SIDE EFFECTS: binds a port, installs signal handlers, blocks the event loop forever.
    FAILURE MODES: if start() fails (port in use), the exception propagates and the process
        exits with a traceback.
    ALTERNATIVE: use a framework like uvicorn/fastapi for the mock too. Chosen raw websockets
        because the mock only needs a WebSocket server, keeping dependencies minimal.
    """
    import os

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    host = os.getenv("HOST", "0.0.0.0")
    port = int(os.getenv("PORT", "8080"))
    interval_ms = int(os.getenv("FEED_INTERVAL_MS", "500"))

    feed = MockOddsFeed(host=host, port=port, interval_ms=interval_ms)

    # Handle shutdown signals
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, lambda: asyncio.create_task(feed.stop()))

    await feed.start()

    # Keep running
    try:
        await asyncio.Future()  # Run forever
    except asyncio.CancelledError:
        pass
    finally:
        await feed.stop()


if __name__ == "__main__":
    asyncio.run(main())
