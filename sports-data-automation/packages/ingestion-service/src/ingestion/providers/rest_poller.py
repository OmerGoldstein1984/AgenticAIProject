"""REST poller for event and settlement feeds."""
import asyncio
import logging
from typing import Callable, Dict, Any, List, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class RESTPoller:
    """Polls REST endpoints for events and settlements with configurable intervals."""

    def __init__(
        self,
        endpoints: List[Dict[str, Any]],
        poll_interval: int = 30,
        on_event: Optional[Callable[[Dict[Any, Any]], None]] = None,
        on_settlement: Optional[Callable[[Dict[Any, Any]], None]] = None,
        timeout: int = 30,
    ):
        self.endpoints = endpoints
        self.poll_interval = poll_interval
        self.on_event = on_event
        self.on_settlement = on_settlement
        self.timeout = timeout

        self._client: Optional[httpx.AsyncClient] = None
        self._running = False
        self._tasks: List[asyncio.Task] = []
        self._last_etag: Dict[str, str] = {}
        self._last_modified: Dict[str, str] = {}

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self):
        """Start polling all endpoints."""
        self._running = True
        self._client = httpx.AsyncClient(timeout=self.timeout)

        for endpoint in self.endpoints:
            task = asyncio.create_task(self._poll_endpoint(endpoint))
            self._tasks.append(task)

        logger.info(f"Started REST poller for {len(self.endpoints)} endpoints")

    async def stop(self):
        """Stop all polling tasks."""
        self._running = False

        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        if self._client:
            await self._client.aclose()
            self._client = None

        self._tasks.clear()
        logger.info("REST poller stopped")

    async def _poll_endpoint(self, endpoint: Dict[str, Any]):
        """Poll a single endpoint repeatedly."""
        name = endpoint.get("name", "unknown")
        url = endpoint.get("url")
        feed_type = endpoint.get("type", "event")
        interval = endpoint.get("interval", self.poll_interval)

        if not url:
            logger.error(f"Endpoint {name} missing URL")
            return

        logger.info(f"Starting poll for {name} ({feed_type}) every {interval}s")

        while self._running:
            try:
                await self._fetch_and_process(endpoint)
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error polling {name}: {e}")

            # Wait for next poll interval
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def _fetch_and_process(self, endpoint: Dict[str, Any]):
        """Fetch data from endpoint and process."""
        name = endpoint.get("name", "unknown")
        url = endpoint.get("url")
        feed_type = endpoint.get("type", "event")

        if not self._client:
            return

        # Prepare headers for conditional requests
        headers = {}
        if name in self._last_etag:
            headers["If-None-Match"] = self._last_etag[name]
        if name in self._last_modified:
            headers["If-Modified-Since"] = self._last_modified[name]

        try:
            response = await self._client.get(url, headers=headers)

            # Handle 304 Not Modified
            if response.status_code == 304:
                logger.debug(f"{name}: Not modified")
                return

            response.raise_for_status()

            # Store cache validators
            if "ETag" in response.headers:
                self._last_etag[name] = response.headers["ETag"]
            if "Last-Modified" in response.headers:
                self._last_modified[name] = response.headers["Last-Modified"]

            # Parse response
            data = response.json()

            # Handle different response formats
            items = self._extract_items(data, feed_type)

            logger.debug(f"{name}: Fetched {len(items)} items")

            # Process each item
            for item in items:
                await self._process_item(item, feed_type)

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                logger.warning(f"{name}: Rate limited, backing off")
                await asyncio.sleep(60)
            else:
                logger.error(f"{name}: HTTP error {e.response.status_code}")
        except Exception as e:
            logger.exception(f"{name}: Fetch error: {e}")

    def _extract_items(self, data: Any, feed_type: str) -> List[Dict[Any, Any]]:
        """Extract items from various response formats."""
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            # Common wrapper formats
            for key in ["data", "items", "results", "events", "settlements", "odds"]:
                if key in data and isinstance(data[key], list):
                    return data[key]
            # Single item
            return [data]
        return []

    async def _process_item(self, item: Dict[Any, Any], feed_type: str):
        """Process a single item based on feed type."""
        try:
            if feed_type == "event" and self.on_event:
                await self.on_event(item)
            elif feed_type == "settlement" and self.on_settlement:
                await self.on_settlement(item)
            else:
                logger.warning(f"No handler for feed type: {feed_type}")
        except Exception as e:
            logger.exception(f"Error processing {feed_type} item: {e}")