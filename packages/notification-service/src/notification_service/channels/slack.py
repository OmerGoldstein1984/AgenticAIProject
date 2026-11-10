"""
Slack webhook channel for the notification service.

FILE HEADER
-----------
Business problem this file solves:
    Critical alerts must reach chatops quickly. SlackChannel posts a JSON payload to a Slack
    incoming webhook URL (from settings) using httpx, so incidents surface in Slack channels in
    near real time.

Where it sits in the flow:
    One of four concrete channels. Instantiated by the router and called via send() when slack
    is a routed channel for a notification's severity/type.

What calls it / what it calls:
    Called by: router.py (via NotificationChannel.send).
    Calls: httpx (outbound HTTP POST), config.get_settings, base.Notification/SendResult.

What breaks if removed:
    Slack deliveries fail; notifications routed only to slack are dropped (other channels still
    work).

Language conventions:
    Python 3.11+. send(notification) -> SendResult. All HTTP/JSON errors are caught, logged, and
    returned as SendResult(success=False, error=...) so the pipeline never crashes.
"""
import logging

import httpx

from notification_service.channels.base import Notification, NotificationChannel, SendResult
from notification_service.config import get_settings

logger = logging.getLogger(__name__)


class SlackChannel(NotificationChannel):
    """Delivers notifications to Slack via an incoming webhook.

    WHAT: Posts a JSON payload (text + optional blocks) to the Slack webhook URL from Settings
        using httpx with a short timeout.
    WHY: Slack is the fastest way to page on-call engineers for critical incidents.
    EXAMPLE:
        SlackChannel().send(Notification(channel="slack", recipient="#alerts",
                                         subject="Down", body="...", severity="page"))
    INPUTS: notification (Notification).
    OUTPUTS: SendResult.
    SIDE EFFECTS: outbound HTTPS POST to slack.com (network I/O).
    FAILURE MODES: missing webhook URL, network error, non-2xx response -> caught, logged,
        returned as SendResult(success=False, error=...); never raises.
    ALTERNATIVE: the Slack SDK (bolt/webhook client). Chosen httpx for a light dependency
        footprint and consistency with the rest of the repo.
    """

    name = "slack"

    def send(self, notification: Notification) -> SendResult:
        """Deliver one notification to Slack.

        WHAT: See class docstring. Builds a Slack message payload and POSTs it to the webhook.
        WHY: Centralized Slack delivery with graceful degradation.
        INPUTS: notification (Notification).
        OUTPUTS: SendResult.
        SIDE EFFECTS: HTTPS network I/O.
        FAILURE MODES: any HTTP/communication error -> SendResult(success=False).
        """
        settings = get_settings()
        webhook_url = settings.slack_webhook_url
        if not webhook_url:
            return SendResult(
                success=False, channel=self.name, error="SLACK_WEBHOOK_URL not configured"
            )
        if not notification.recipient:
            return SendResult(success=False, channel=self.name, error="no recipient")

        payload = {
            "channel": notification.recipient,
            "text": f"*{notification.subject}*\n{notification.body}",
        }

        try:
            with httpx.Client(timeout=10.0) as client:
                response = client.post(webhook_url, json=payload)
                response.raise_for_status()

            logger.info(
                "Slack message sent to %s (%s)", notification.recipient, notification.subject
            )
            return SendResult(
                success=True,
                channel=self.name,
                message=f"sent to {notification.recipient}",
            )
        except Exception as exc:  # channel failures must not crash the pipeline
            logger.warning("Slack send failed to %s: %s", notification.recipient, exc)
            return SendResult(success=False, channel=self.name, error=str(exc))
