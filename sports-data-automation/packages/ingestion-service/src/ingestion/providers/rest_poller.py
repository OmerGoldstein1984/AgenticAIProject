"""
REST poller for event and settlement feeds.

FILE HEADER
-----------
Business problem this file solves:
    Providers publish match events and settlements over REST, but they don't push every change.
    The ingestion service needs to poll provider endpoints on an interval, handle pagination
    wrappers, conditional requests (ETag/Last-Modified), rate limits (429), and transient
    failures — without missing updates or hammering the provider. RESTPoller does exactly that,
    calling back into the ingestion service for each event/settlement it fetches.

Where it sits in the flow:
    Provider adapter in the ingestion pipeline. Started in lifespan(); runs one background task
    per configured endpoint, fetching on a timer and handing items to on_event/on_settlement
    callbacks (main.py's process_event/process_settlement).

What calls it / what it calls:
    Called by: main.py lifespan (RESTPoller(...).start()).
    Calls: httpx for HTTP; the on_event/on_settlement callbacks passed at construction.
What breaks if removed:
    No event/settlement data flows from REST providers; only WebSocket odds (and manual
    /ingest/* endpoints) keep the pipeline busy.
Language conventions:
    Python 3.11+. asyncio, httpx.AsyncClient, tenacity (imported but see GAP below).
    Conditional requests via If-None-Match/If-Modified-Since headers.
GAP: tenacity is imported but not actually used — retry/backoff is hand-rolled in
    _fetch_and_process (429 → sleep 60s) rather than declarative tenacity decorators.
    See 07_issues_found.md.
"""
import asyncio
import logging
from typing import Callable, Dict, Any, List, Optional
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

logger = logging.getLogger(__name__)


class RESTPoller:
    """Polls REST endpoints for events and settlements with configurable intervals.

    WHAT: For each configured endpoint, spawns an async task that GETs the URL on a timer,
        extracts items from the response, and hands each item to the matching callback.
        Supports ETag/Last-Modified conditional requests and 429 rate-limit backoff.
    WHY: Providers don't push everything; polling guarantees the ingestion service eventually
        sees every event and settlement even if a WebSocket reconnect misses some.
    INPUTS (constructor): endpoints (list of {name, url, type, interval}), poll_interval,
        on_event/on_settlement callbacks, timeout.
    OUTPUTS: None; side effect is invoking callbacks with fetched items.
    SIDE EFFECTS: opens an httpx.AsyncClient, spawns asyncio.Tasks per endpoint, makes HTTP
        requests, invokes callbacks.
    FAILURE MODES: per-endpoint exceptions are caught and logged (one bad endpoint doesn't stop
        the others); 429 triggers a 60s backoff for that endpoint; task cancellation on stop().
    ALTERNATIVE: WebSocket-only ingestion. Chosen polling because the mock event/settlement
        feeds are REST and many real providers publish results over REST.
    # GAP: tenacity imported but unused; retry policy is hand-rolled and not configurable.
    #    See 07_issues_found.md.
    """

    def __init__(
        self,
        endpoints: List[Dict[str, Any]],
        poll_interval: int = 30,
        on_event: Optional[Callable[[Dict[Any, Any]], None]] = None,
        on_settlement: Optional[Callable[[Dict[Any, Any]], None]] = None,
        timeout: int = 30,
    ):
        """Store config; the httpx client and task list are created on start()."""
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
        """True between start() and stop()."""
        return self._running

    async def start(self):
        """Create the HTTP client and launch one polling task per endpoint."""
        self._running = True
        self._client = httpx.AsyncClient(timeout=self.timeout)

        for endpoint in self.endpoints:
            task = asyncio.create_task(self._poll_endpoint(endpoint))
            self._tasks.append(task)

        logger.info(f"Started REST poller for {len(self.endpoints)} endpoints")

    async def stop(self):
        """Cancel all polling tasks and close the HTTP client."""
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
        """Loop: fetch the endpoint, then sleep until the next interval."""
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
                # One poll failure must not kill the whole endpoint loop
                logger.exception(f"Error polling {name}: {e}")

            # Wait for the next poll interval
            try:
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                break

    async def _fetch_and_process(self, endpoint: Dict[str, Any]):
        """Fetch one page from the endpoint and process every item returned."""
        name = endpoint.get("name", "unknown")
        url = endpoint.get("url")
        feed_type = endpoint.get("type", "event")

        if not self._client:
            return

        # Prepare headers for conditional requests (avoid re-fetching unchanged data)
        headers = {}
        if name in self._last_etag:
            headers["If-None-Match"] = self._last_etag[name]
        if name in self._last_modified:
            headers["If-Modified-Since"] = self._last_modified[name]

        try:
            response = await self._client.get(url, headers=headers)

            # 304 Not Modified: nothing new since last poll
            if response.status_code == 304:
                logger.debug(f"{name}: Not modified")
                return

            response.raise_for_status()

            # Remember cache validators for the next poll
            if "ETag" in response.headers:
                self._last_etag[name] = response.headers["ETag"]
            if "Last-Modified" in response.headers:
                self._last_modified[name] = response.headers["Last-Modified"]

            # Parse the JSON response
            data = response.json()

            # Providers wrap lists differently; normalize to a flat list of items
            items = self._extract_items(data, feed_type)

            logger.debug(f"{name}: Fetched {len(items)} items")

            # Hand each item to the ingestion pipeline
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
        """Normalize provider response shapes (list, wrapped dict, single object) to a list."""
        if isinstance(data, list):
            return data
        elif isinstance(data, dict):
            for key in ["data", "items", "results", "events", "settlements", "odds"]:
                if key in data and isinstance(data[key], list):
                    return data[key]
            return [data]
        return []

    async def _process_item(self, item: Dict[Any, Any], feed_type: str):
        """Route one item to the ingestion callback based on feed type."""
        try:
            if feed_type == "event" and self.on_event:
                await self.on_event(item)
            elif feed_type == "settlement" and self.on_settlement:
                await self.on_settlement(item)
            else:
                logger.warning(f"No handler for feed type: {feed_type}")
        except Exception as e:
            # One bad item must not abort the whole batch
            logger.exception(f"Error processing {feed_type} item: {e}")
