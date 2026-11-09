"""
WebSocket client for live odds feed.

FILE HEADER
-----------
Business problem this file solves:
    Live odds arrive via WebSocket push (every 500ms-2s) and the connection can drop at any
    time. The ingestion service needs a resilient WebSocket client that connects, stays alive
    with pings, reconnects with exponential backoff on failure, fans incoming messages to a
    handler, and never blocks the receive loop on slow message processing.

Where it sits in the flow:
    Provider adapter in the ingestion pipeline. Started in lifespan(); connects to the mock
    odds feed (ws://localhost:8080/ws) and calls handle_odds_message for each message, which
    routes to process_odds.

What calls it / what it calls:
    Called by: main.py lifespan (WebSocketClient(...).connect()).
    Calls: websockets library for the connection; the on_message callback passed at
        construction.
What breaks if removed:
    No live-odds data flows; only REST polls and manual /ingest/* endpoints keep the pipeline
    busy. The most time-critical path (odds) goes quiet.
Language conventions:
    Python 3.11+. asyncio, websockets library. Automatic reconnection with exponential backoff
    (capped at 60s), ping/pong keepalive, background message handling.
GAP: max_reconnect_attempts defaults to 10, after which the client stops (_running=False) and
    odds ingestion silently halts until restart. A production client would reconnect forever.
    See 07_issues_found.md.
"""
import asyncio
import json
import logging
import websockets
from typing import Callable, Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client with automatic reconnection and message handling.

    WHAT: Connects to a WebSocket URL, runs a message loop that parses each JSON message and
        schedules on_message as a background task (so a slow handler never blocks receiving),
        and reconnects with exponential backoff when the connection drops or fails to connect.
    WHY: Live odds are the most time-critical feed; the client must survive transient network
        blips and provider restarts without operator intervention.
    INPUTS (constructor): url, on_message callback, reconnect_interval (5s),
        max_reconnect_attempts (10), ping_interval (30s), ping_timeout (10s).
    OUTPUTS: None; side effect is opening the socket and invoking on_message per message.
    SIDE EFFECTS: opens a WebSocket connection, spawns a message-handling task, reconnects on
        failure.
    FAILURE MODES: connection refused/dropped → retry with backoff up to max_reconnect_attempts,
        then stop; invalid JSON in a message → logged and skipped (one bad message doesn't
        kill the feed); on_message handler error → caught by _safe_on_message, logged.
    ALTERNATIVE: a managed client (e.g. websockets.client.connect with higher-level wrapper, or
        a message queue). Chosen raw websockets with explicit reconnect logic for full control
        over backoff and keepalive — transparent and easy to debug in an interview.
    # INTERVIEW: note the receive loop (`async for message in self._websocket`) and the finally
    #    clause that sets _connected=False and schedules reconnect — this is what makes the
    #    client self-healing.
    # GAP: stops retrying after max_reconnect_attempts (10) rather than reconnecting forever;
    #    odds ingestion halts until the service restarts. See 07_issues_found.md.
    """

    def __init__(
        self,
        url: str,
        on_message: Callable[[Dict[Any, Any]], None],
        reconnect_interval: int = 5,
        max_reconnect_attempts: int = 10,
        ping_interval: int = 30,
        ping_timeout: int = 10,
    ):
        """Store connection config; the connection is established on connect()."""
        self.url = url
        self.on_message = on_message
        self.reconnect_interval = reconnect_interval
        self.max_reconnect_attempts = max_reconnect_attempts
        self.ping_interval = ping_interval
        self.ping_timeout = ping_timeout

        self._websocket: Optional[websockets.WebSocketClientProtocol] = None
        self._running = False
        self._reconnect_task: Optional[asyncio.Task] = None
        self._message_task: Optional[asyncio.Task] = None
        self._connected = False

    @property
    def is_connected(self) -> bool:
        """True while a socket is open and the client is meant to be running."""
        return self._connected and self._websocket is not None

    async def connect(self):
        """Initiate connection with retry (runs _connect_with_retry)."""
        self._running = True
        await self._connect_with_retry()

    async def _connect_with_retry(self):
        """Attempt to connect, retrying with exponential backoff until success or attempts exhausted."""
        attempt = 0
        while self._running and attempt < self.max_reconnect_attempts:
            try:
                logger.info(f"Connecting to WebSocket: {self.url} (attempt {attempt + 1})")
                self._websocket = await websockets.connect(
                    self.url,
                    ping_interval=self.ping_interval,
                    ping_timeout=self.ping_timeout,
                    close_timeout=10,
                )
                self._connected = True
                logger.info("WebSocket connected successfully")

                # Start the background message handler
                self._message_task = asyncio.create_task(self._handle_messages())
                return

            except Exception as e:
                attempt += 1
                self._connected = False
                logger.warning(f"WebSocket connection failed (attempt {attempt}): {e}")

                if attempt < self.max_reconnect_attempts and self._running:
                    wait_time = min(self.reconnect_interval * (2 ** (attempt - 1)), 60)
                    logger.info(f"Reconnecting in {wait_time}s...")
                    await asyncio.sleep(wait_time)

        if attempt >= self.max_reconnect_attempts:
            logger.error("Max reconnection attempts reached")
            self._running = False

    async def _handle_messages(self):
        """Read messages from the socket and fan each to the handler in the background."""
        try:
            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    # Call handler in background to not block the receive loop
                    asyncio.create_task(self._safe_on_message(data))
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse WebSocket message: {e}")
                except Exception as e:
                    logger.exception(f"Error handling message: {e}")
        except websockets.ConnectionClosed:
            logger.info("WebSocket connection closed")
        except Exception as e:
            logger.exception(f"Message handler error: {e}")
        finally:
            self._connected = False
            if self._running:
                # Trigger reconnection (fire-and-forget task)
                asyncio.create_task(self._connect_with_retry())

    async def _safe_on_message(self, data: Dict[Any, Any]):
        """Call the user-supplied on_message handler without crashing the receive loop."""
        try:
            await self.on_message(data)
        except Exception as e:
            logger.exception(f"Error in on_message handler: {e}")

    async def disconnect(self):
        """Close the client cleanly: stop the loop, cancel the message task, close the socket."""
        self._running = False
        self._connected = False

        if self._message_task:
            self._message_task.cancel()
            try:
                await self._message_task
            except asyncio.CancelledError:
                pass

        if self._websocket:
            await self._websocket.close()
            self._websocket = None

        logger.info("WebSocket disconnected")

    async def send(self, data: Dict[Any, Any]):
        """Send a JSON message to the server (if connected)."""
        if self._websocket and self._connected:
            await self._websocket.send(json.dumps(data))
        else:
            logger.warning("Cannot send: WebSocket not connected")
