"""WebSocket client for live odds feed."""
import asyncio
import json
import logging
import websockets
from typing import Callable, Dict, Any, Optional
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

logger = logging.getLogger(__name__)


class WebSocketClient:
    """WebSocket client with automatic reconnection and message handling."""

    def __init__(
        self,
        url: str,
        on_message: Callable[[Dict[Any, Any]], None],
        reconnect_interval: int = 5,
        max_reconnect_attempts: int = 10,
        ping_interval: int = 30,
        ping_timeout: int = 10,
    ):
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
        return self._connected and self._websocket is not None

    async def connect(self):
        """Connect to WebSocket server."""
        self._running = True
        await self._connect_with_retry()

    async def _connect_with_retry(self):
        """Connect with exponential backoff retry."""
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

                # Start message handler
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
        """Handle incoming messages."""
        try:
            async for message in self._websocket:
                try:
                    data = json.loads(message)
                    # Call handler in background to not block
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
                # Trigger reconnection
                asyncio.create_task(self._connect_with_retry())

    async def _safe_on_message(self, data: Dict[Any, Any]):
        """Safely call on_message handler."""
        try:
            await self.on_message(data)
        except Exception as e:
            logger.exception(f"Error in on_message handler: {e}")

    async def disconnect(self):
        """Disconnect from WebSocket."""
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
        """Send message to WebSocket server."""
        if self._websocket and self._connected:
            await self._websocket.send(json.dumps(data))
        else:
            logger.warning("Cannot send: WebSocket not connected")