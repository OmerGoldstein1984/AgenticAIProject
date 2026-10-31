"""Mock WebSocket odds feed server."""
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
    """Simulates a live odds feed via WebSocket."""

    def __init__(
        self,
        host: str = "0.0.0.0",
        port: int = 8080,
        interval_ms: int = 500,
        num_events: int = 50,
        num_providers: int = 3,
    ):
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
        """Generate a single odds update."""
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
        """Broadcast odds updates to all connected clients."""
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
        """Handle new WebSocket connection."""
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
        """Start the WebSocket server."""
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
        """Stop the WebSocket server."""
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
    """Main entry point."""
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