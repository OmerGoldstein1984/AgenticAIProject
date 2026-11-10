"""
Alert/runbook notification router.

FILE HEADER
-----------
Business problem this file solves:
    Notifications must reach the right channels based on their severity and type (e.g. page
    -> Slack + SMS + Push, info -> Email only). The router centralizes that mapping so channels
    are selected consistently and no single channel failure can take down the whole pipeline.

Where it sits in the flow:
    Orchestration layer. Receives a Notification, looks up the channels for its severity/type,
    calls send() on each, and aggregates the SendResult objects. Called by n8n nodes, demo
    scripts, and tests.

What calls it / what it calls:
    Called by: n8n nodes, demo scripts, tests.
    Calls: config.get_settings, channels/* (each channel's send), templates.TemplateRegistry.

What breaks if removed:
    No channel selection/dispatch; notifications cannot be delivered through the service.

Language conventions:
    Python 3.11+. route(notification) -> List[SendResult]. Each channel send is wrapped in
    try/except so channel failures are logged and the pipeline continues.
"""
import logging
from typing import Any, Dict, List, Optional

from notification_service.channels import (
    EmailChannel,
    PushChannel,
    SlackChannel,
    SmsChannel,
)
from notification_service.channels.base import Notification, NotificationChannel, SendResult
from notification_service.config import get_settings
from notification_service.templates import TemplateRegistry

logger = logging.getLogger(__name__)

# Default severity -> channel routing. Production overrides via settings/subclassing.
DEFAULT_SEVERITY_ROUTES: Dict[str, List[str]] = {
    "info": ["email"],
    "warning": ["email", "slack"],
    "critical": ["email", "slack", "sms"],
    "page": ["slack", "sms", "push"],
}

# Default type -> channel routing (merged with severity routes).
DEFAULT_TYPE_ROUTES: Dict[str, List[str]] = {
    "alert": ["email", "slack"],
    "runbook": ["email"],
}


class NotificationRouter:
    """Routes notifications to channels and aggregates delivery results.

    WHAT: Holds a channel registry (name -> NotificationChannel) and severity/type route maps.
        route() selects channels for a notification, renders any named template, calls send() on
        each channel (catching exceptions), and returns the list of SendResult objects.
    WHY: Central, testable routing; channel failures are isolated so one bad channel never
        crashes the pipeline.
    EXAMPLE:
        router = NotificationRouter()
        results = router.route(Notification(channel="slack", recipient="#alerts",
                                            subject="Down", body="...", severity="page"))
    INPUTS: route receives a Notification.
    OUTPUTS: List[SendResult] - one per attempted channel.
    SIDE EFFECTS: outbound I/O via each channel (SMTP/HTTP/SMS/push).
    FAILURE MODES: channel send exceptions are caught, logged, and recorded as
        SendResult(success=False, error=...); the router continues to the next channel.
    ALTERNATIVE: pub/sub (n8n, Kafka). Chosen a direct in-process router for simplicity and
        easy unit testing.
    """

    def __init__(
        self,
        channels: Optional[Dict[str, NotificationChannel]] = None,
        severity_routes: Optional[Dict[str, List[str]]] = None,
        type_routes: Optional[Dict[str, List[str]]] = None,
        template_registry: Optional[TemplateRegistry] = None,
    ) -> None:
        self._channels: Dict[str, NotificationChannel] = channels or {
            "email": EmailChannel(),
            "slack": SlackChannel(),
            "sms": SmsChannel(),
            "push": PushChannel(),
        }
        self._severity_routes: Dict[str, List[str]] = (
            dict(DEFAULT_SEVERITY_ROUTES)
            if severity_routes is None
            else dict(severity_routes)
        )
        self._type_routes: Dict[str, List[str]] = (
            dict(DEFAULT_TYPE_ROUTES) if type_routes is None else dict(type_routes)
        )
        self._templates = template_registry or TemplateRegistry()

    @property
    def channels(self) -> Dict[str, NotificationChannel]:
        """Return the channel registry (read-only view of channel name -> channel)."""
        return dict(self._channels)

    def _select_channels(self, notification: Notification) -> List[str]:
        """Select channel names for a notification based on severity and type.

        WHAT: Combines severity routes and type routes (type adds channels), de-duplicating
            while preserving order.
        WHY: Severity drives urgency; type adds channel preferences; both are honored.
        INPUTS: notification (Notification).
        OUTPUTS: ordered list of unique channel names.
        SIDE EFFECTS: none.
        FAILURE MODES: unknown severity/type -> falls back to severity route or ["email"].
        """
        channels: List[str] = []
        for source in (
            self._severity_routes.get(notification.severity, []),
            self._type_routes.get(notification.type, []),
        ):
            for channel in source:
                if channel not in channels:
                    channels.append(channel)
        if not channels:
            channels = ["email"]
        return channels

    def route(self, notification: Notification) -> List[SendResult]:
        """Route and deliver one notification to all selected channels.

        WHAT: Selects channels, renders a named template into notification.body when
            template_name is set, calls send() on each channel, catching exceptions, and
            aggregates results.
        WHY: One entry point for delivery; failures in one channel never block the others.
        INPUTS: notification (Notification).
        OUTPUTS: List[SendResult] - one per attempted channel.
        SIDE EFFECTS: outbound I/O via channels; may mutate notification.body when a template
            is rendered.
        FAILURE MODES: unknown channel -> logged and skipped; channel send exception -> caught,
            logged, recorded as SendResult(success=False).
        ALTERNATIVE: fire-and-forget without results. Chosen to return results so callers can
            retry or alert on failed channels.
        """
        # Render named template into the body before dispatch.
        if notification.template_name:
            try:
                rendered = self._templates.render(
                    notification.template_name, notification.context
                )
                if rendered != notification.template_name:
                    notification.body = rendered
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning("Template render failed in router: %s", exc)

        results: List[SendResult] = []
        for channel_name in self._select_channels(notification):
            channel = self._channels.get(channel_name)
            if channel is None:
                logger.warning("Unknown channel %r; skipping", channel_name)
                results.append(
                    SendResult(
                        success=False,
                        channel=channel_name,
                        error=f"unknown channel {channel_name}",
                    )
                )
                continue

            try:
                result = channel.send(notification)
            except Exception as exc:  # channel failures must not crash the pipeline
                logger.warning("Channel %s raised while sending: %s", channel_name, exc)
                result = SendResult(success=False, channel=channel_name, error=str(exc))
            results.append(result)

        return results
