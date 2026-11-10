"""
Adapter factory for the provider registry.

FILE HEADER
-----------
Business problem this file solves:
    ProviderConfig (types.py) defines how to reach a provider, but nothing maps a provider
    type (websocket/rest/graphql/batch) to the concrete client class. Without this factory,
    adding a new provider type requires editing main.py instead of just registering a builder.

Where it sits in the flow:
    Used by ProviderRegistry (registry.py) to construct adapter instances from ProviderConfig
    objects. Sits between config loading and the provider adapters (RESTPoller,
    WebSocketClient).

What calls it / what it calls:
    Called by: ProviderRegistry._build_and_start_adapters
    Calls: ingestion.providers.rest_poller.RESTPoller, ingestion.providers.websocket_client.WebSocketClient

Language conventions:
    Python 3.11+. Pydantic v2 models from sports_automation.types.
"""

from typing import Any, Callable, Optional

from ingestion.providers.rest_poller import RESTPoller
from ingestion.providers.websocket_client import WebSocketClient
from sports_automation.types import ProviderConfig

MessageHandler = Callable[[dict], None]


class ProviderAdapterFactory:
    """Maps provider type to the appropriate client class and builds instances.

    WHAT: Registry of provider-type -> builder callable. Given a ProviderConfig plus optional
        callbacks and timing values, returns a configured adapter instance.
    WHY: Adding a new provider type means registering one builder here, not editing main.py.
        Keeps the ingestion service open for extension, closed for modification.
    INPUTS: ProviderConfig, optional callbacks (on_event, on_settlement, on_message),
        poll_interval, reconnect_interval.
    OUTPUTS: RESTPoller, WebSocketClient, or raises ValueError for unsupported types.
    FAILURE MODES: ValueError for unknown provider types (graphql/batch not yet wired).
    ALTERNATIVE: a big if/else block in main.py. Chosen a registry so new types are additive.
    """

    TYPE_WEBSOCKET = "websocket"
    TYPE_REST = "rest"
    TYPE_GRAPHQL = "graphql"
    TYPE_BATCH = "batch"

    def __init__(self) -> None:
        self._builders: dict[str, Callable[..., Any]] = {
            self.TYPE_WEBSOCKET: self._build_websocket,
            self.TYPE_REST: self._build_rest,
        }

    def create(
        self,
        provider_config: ProviderConfig,
        on_event: Optional[MessageHandler] = None,
        on_settlement: Optional[MessageHandler] = None,
        on_message: Optional[MessageHandler] = None,
        poll_interval: int = 30,
        reconnect_interval: int = 5,
        **kwargs: Any,
    ) -> Any:
        """Build an adapter instance for the given provider config.

        Routes by provider_config.type to the matching builder. Unknown types raise ValueError.
        """
        builder = self._builders.get(provider_config.type)
        if builder is None:
            raise ValueError(
                f"Unsupported provider type '{provider_config.type}' "
                f"for provider '{provider_config.id}'"
            )
        return builder(
            provider_config,
            on_event=on_event,
            on_settlement=on_settlement,
            on_message=on_message,
            poll_interval=poll_interval,
            reconnect_interval=reconnect_interval,
            **kwargs,
        )

    def _build_websocket(
        self,
        config: ProviderConfig,
        on_message: Optional[MessageHandler] = None,
        reconnect_interval: int = 5,
        **kwargs: Any,
    ) -> WebSocketClient:
        """Build a WebSocketClient from a websocket ProviderConfig."""
        return WebSocketClient(
            url=config.endpoint,
            on_message=on_message,
            reconnect_interval=reconnect_interval,
        )

    def _build_rest(
        self,
        config: ProviderConfig,
        on_event: Optional[MessageHandler] = None,
        on_settlement: Optional[MessageHandler] = None,
        poll_interval: int = 30,
        **kwargs: Any,
    ) -> RESTPoller:
        """Build a RESTPoller from a rest ProviderConfig.

        ProviderConfig.type is the transport ('rest'), but RESTPoller needs a feed type
        ('event' | 'settlement') to route items to the right callback. We infer it from the
        provider name/id.
        """
        feed_type = self._infer_feed_type(config)
        endpoint = {
            "name": config.name,
            "url": config.endpoint,
            "type": feed_type,
            "interval": poll_interval,
        }
        return RESTPoller(
            endpoints=[endpoint],
            poll_interval=poll_interval,
            on_event=on_event,
            on_settlement=on_settlement,
        )

    @staticmethod
    def _infer_feed_type(config: ProviderConfig) -> str:
        """Infer the REST feed type ('event' | 'settlement') from provider name/id."""
        name = (config.name or config.id or "").lower()
        if "settlement" in name:
            return "settlement"
        return "event"
