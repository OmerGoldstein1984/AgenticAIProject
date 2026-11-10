"""
Provider registry with hot-reload.

FILE HEADER
-----------
Business problem this file solves:
    ProviderConfig is defined in types.py but no provider-registry loader exists. Providers are
    hard-coded in Settings.rest_endpoints (config.py), so adding a provider requires a code
    change and redeploy. ProviderRegistry loads ProviderConfig instances from a config file,
    watches it for changes (hot-reload), and returns configured adapter instances.

Where it sits in the flow:
    Bootstrap layer in main.py lifespan(). Replaces direct construction of RESTPoller and
    WebSocketClient from Settings.rest_endpoints / odds_feed_ws_url. Falls back to the old
    settings if the registry fails to load.

What calls it / what it calls:
    Called by: main.py lifespan
    Calls: ProviderAdapterFactory (provider_registry.py), ProviderConfig (sports_automation.types),
        RESTPoller, WebSocketClient

Language conventions:
    Python 3.11+. asyncio. JSON config file. Periodic mtime-based file watcher.
"""

import asyncio
import json
import logging
import os
from typing import Any, Callable, Dict, List, Optional

from ingestion.providers.provider_registry import ProviderAdapterFactory
from ingestion.providers.rest_poller import RESTPoller
from ingestion.providers.websocket_client import WebSocketClient
from sports_automation.types import ProviderConfig

logger = logging.getLogger(__name__)

MessageHandler = Callable[[dict], None]


class ProviderRegistry:
    """Loads ProviderConfig instances, supports hot-reload, returns adapter instances.

    WHAT: Reads a JSON file of ProviderConfig objects, builds adapter instances via
        ProviderAdapterFactory, starts them, and watches the file for changes to hot-reload
        without restarting the service.
    WHY: Adding a new provider becomes a config-file change, not a code change. Hot-reload
        means config updates take effect without a redeploy.
    INPUTS: config_path (path to JSON providers file), enabled flag.
    OUTPUTS: adapter instances via get_rest_pollers() / get_websocket_clients() / get_adapter().
    SIDE EFFECTS: reads the config file on start and on change; starts/stops adapters.
    FAILURE MODES: if the config file is missing or invalid, logs an error and leaves the
        registry empty (caller is responsible for fallback). Invalid provider types are
        skipped with a log warning.
    ALTERNATIVE: hard-code providers in Settings (current approach). Chosen registry for
        config-driven provider onboarding.
    """

    def __init__(self, config_path: str, enabled: bool = True) -> None:
        self.config_path = config_path
        self.enabled = enabled
        self._configs: Dict[str, ProviderConfig] = {}
        self._adapters: Dict[str, Any] = {}
        self._factory = ProviderAdapterFactory()
        self._watch_task: Optional[asyncio.Task] = None
        self._last_mtime: Optional[float] = None
        # Callback/timing state captured at start() for reuse on hot-reload
        self._on_event: Optional[MessageHandler] = None
        self._on_settlement: Optional[MessageHandler] = None
        self._on_message: Optional[MessageHandler] = None
        self._poll_interval: int = 30
        self._reconnect_interval: int = 5

    async def start(
        self,
        on_event: Optional[MessageHandler] = None,
        on_settlement: Optional[MessageHandler] = None,
        on_message: Optional[MessageHandler] = None,
        poll_interval: int = 30,
        reconnect_interval: int = 5,
    ) -> None:
        """Load configs, build and start adapters, and start the hot-reload watcher."""
        if not self.enabled:
            logger.info("Provider registry is disabled; skipping")
            return

        self._on_event = on_event
        self._on_settlement = on_settlement
        self._on_message = on_message
        self._poll_interval = poll_interval
        self._reconnect_interval = reconnect_interval

        self._load_configs()
        await self._build_and_start_adapters()
        self._watch_task = asyncio.create_task(self._watch())
        logger.info(
            f"Provider registry started with {len(self._adapters)} adapters "
            f"from {len(self._configs)} configs"
        )

    async def stop(self) -> None:
        """Stop the watcher and stop/disconnect all adapters."""
        if self._watch_task:
            self._watch_task.cancel()
            try:
                await self._watch_task
            except asyncio.CancelledError:
                pass
            self._watch_task = None

        for adapter in list(self._adapters.values()):
            try:
                if isinstance(adapter, RESTPoller):
                    await adapter.stop()
                elif isinstance(adapter, WebSocketClient):
                    await adapter.disconnect()
            except Exception as e:
                logger.warning(f"Error stopping adapter: {e}")

        self._adapters.clear()
        self._configs.clear()
        logger.info("Provider registry stopped")

    def get_rest_pollers(self) -> List[RESTPoller]:
        """Return all REST poller adapters."""
        return [a for a in self._adapters.values() if isinstance(a, RESTPoller)]

    def get_websocket_clients(self) -> List[WebSocketClient]:
        """Return all WebSocket client adapters."""
        return [a for a in self._adapters.values() if isinstance(a, WebSocketClient)]

    def get_adapter(self, provider_id: str) -> Optional[Any]:
        """Return the adapter for a specific provider id, or None."""
        return self._adapters.get(provider_id)

    def is_enabled(self) -> bool:
        """True if the registry is enabled."""
        return self.enabled

    # ------------------------------------------------------------------
    # Internal: config loading, adapter building/start, hot-reload watcher
    # ------------------------------------------------------------------

    def _load_configs(self) -> None:
        """Load ProviderConfig instances from the JSON config file."""
        if not os.path.exists(self.config_path):
            logger.warning(f"Providers config file not found: {self.config_path}")
            self._configs = {}
            return

        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to read providers config {self.config_path}: {e}")
            self._configs = {}
            return

        configs: Dict[str, ProviderConfig] = {}
        if isinstance(raw, list):
            for item in raw:
                try:
                    config = ProviderConfig(**item)
                    configs[config.id] = config
                except Exception as e:
                    logger.warning(f"Skipping invalid provider config entry: {e}")
        else:
            logger.error(f"Providers config {self.config_path} must be a JSON list")

        self._configs = configs
        try:
            self._last_mtime = os.path.getmtime(self.config_path)
        except OSError:
            self._last_mtime = None
        logger.info(f"Loaded {len(configs)} provider configs from {self.config_path}")

    async def _build_and_start_adapters(self) -> None:
        """Stop old adapters, build new ones from loaded configs, and start them."""
        # Stop old adapters first
        for adapter in list(self._adapters.values()):
            try:
                if isinstance(adapter, RESTPoller):
                    await adapter.stop()
                elif isinstance(adapter, WebSocketClient):
                    await adapter.disconnect()
            except Exception as e:
                logger.warning(f"Error stopping old adapter: {e}")

        adapters: Dict[str, Any] = {}
        for config in self._configs.values():
            if not config.enabled:
                logger.debug(f"Skipping disabled provider: {config.id}")
                continue
            try:
                adapter = self._factory.create(
                    config,
                    on_event=self._on_event,
                    on_settlement=self._on_settlement,
                    on_message=self._on_message,
                    poll_interval=self._poll_interval,
                    reconnect_interval=self._reconnect_interval,
                )
                # Start the adapter
                if isinstance(adapter, RESTPoller):
                    await adapter.start()
                elif isinstance(adapter, WebSocketClient):
                    await adapter.connect()
                adapters[config.id] = adapter
                logger.debug(f"Started adapter for provider: {config.id} ({config.type})")
            except Exception as e:
                logger.error(f"Failed to build/start adapter for provider {config.id}: {e}")

        self._adapters = adapters

    async def _watch(self) -> None:
        """Periodically check the config file mtime and hot-reload on change."""
        while True:
            try:
                await asyncio.sleep(10)
                if not os.path.exists(self.config_path):
                    continue
                mtime = os.path.getmtime(self.config_path)
                if self._last_mtime is not None and mtime != self._last_mtime:
                    logger.info("Providers config file changed; hot-reloading")
                    self._load_configs()
                    await self._build_and_start_adapters()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.exception(f"Error in config watcher: {e}")
