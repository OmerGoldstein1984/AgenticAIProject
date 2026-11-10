"""
Push notification channel for the notification service.

FILE HEADER
-----------
Business problem this file solves:
    Mobile/desktop push notifications reach engineers on their devices. PushChannel renders a
    notification through a template registry and delivers it to a push endpoint (or simulates
    when no endpoint/key is configured), so urgent alerts surface outside of email/Slack/SMS.

Where it sits in the flow:
    One of four concrete channels. Instantiated by the router and called via send() when push
    is a routed channel for a notification's severity/type.

What calls it / what it calls:
    Called by: router.py (via NotificationChannel.send).
    Calls: templates.TemplateRegistry (render), httpx (optional outbound POST),
        config.get_settings, base.Notification/SendResult.

What breaks if removed:
    Push deliveries fail; notifications routed only to push are dropped (other channels still
    work).

Language conventions:
    Python 3.11+. send(notification) -> SendResult. Template-render and delivery errors are
    caught, logged, and returned as SendResult(success=False, error=...) so the pipeline never
    crashes.
"""
import logging

import httpx

from notification_service.channels.base import Notification, NotificationChannel, SendResult
from notification_service.config import get_settings
from notification_service.templates import TemplateRegistry

logger = logging.getLogger(__name__)


class PushChannel(NotificationChannel):
    """Template-based push notification channel.

    WHAT: Renders the notification title/body through TemplateRegistry (using template_name and
        context) and POSTs the result to a push endpoint (PUSH_ENDPOINT + PUSH_API_KEY from
        settings). If no endpoint is configured, it simulates a delivery and logs it, keeping
        the stack runnable without a live push contract.
    WHY: Push reaches engineers on mobile devices for urgent, high-severity alerts.
    EXAMPLE:
        PushChannel().send(Notification(channel="push", recipient="device_123",
                                        subject="Down", body="...", severity="page",
                                        template_name="alert_page", context={"event": "..."}))
    INPUTS: notification (Notification).
    OUTPUTS: SendResult.
    SIDE EFFECTS: optional outbound HTTPS POST to a push provider (network I/O), or a simulated
        log line.
    FAILURE MODES: template render error, missing endpoint, HTTP error -> caught, logged,
        returned as SendResult(success=False, error=...); never raises.
    ALTERNATIVE: FCM/APNs SDKs. Chosen a generic HTTP endpoint + template registry for
        provider-agnostic delivery.
    """

    name = "push"

    def __init__(self, template_registry: TemplateRegistry | None = None) -> None:
        self._templates = template_registry or TemplateRegistry()

    def send(self, notification: Notification) -> SendResult:
        """Deliver one notification as a push message.

        WHAT: Renders title/body via the template registry, then POSTs to the push endpoint (or
            simulates when no endpoint is configured).
        WHY: Centralized template-based push delivery with graceful degradation.
        INPUTS: notification (Notification).
        OUTPUTS: SendResult.
        SIDE EFFECTS: optional HTTPS network I/O or a simulated log line.
        FAILURE MODES: any template/delivery error -> SendResult(success=False).
        """
        settings = get_settings()
        if not notification.recipient:
            return SendResult(success=False, channel=self.name, error="no recipient")

        # Render title/body through the template registry when a template is named.
        title = notification.subject
        body = notification.body
        if notification.template_name:
            try:
                rendered_title = self._templates.render(
                    notification.template_name + ".title", notification.context
                )
                rendered_body = self._templates.render(
                    notification.template_name, notification.context
                )
                if rendered_title != notification.template_name + ".title":
                    title = rendered_title
                if rendered_body != notification.template_name:
                    body = rendered_body
            except Exception as exc:  # template errors must not crash the pipeline
                logger.warning("Push template render failed: %s", exc)

        payload = {
            "recipient": notification.recipient,
            "title": title,
            "body": body,
            "severity": notification.severity,
        }

        endpoint = settings.push_endpoint
        api_key = settings.push_api_key
        if not endpoint:
            logger.info(
                "Push simulated to %s (%s): %s", notification.recipient, title, body
            )
            return SendResult(
                success=True,
                channel=self.name,
                message=f"simulated to {notification.recipient}",
            )

        try:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            with httpx.Client(timeout=10.0) as client:
                response = client.post(endpoint, json=payload, headers=headers)
                response.raise_for_status()

            logger.info("Push sent to %s (%s)", notification.recipient, title)
            return SendResult(
                success=True,
                channel=self.name,
                message=f"sent to {notification.recipient}",
            )
        except Exception as exc:  # channel failures must not crash the pipeline
            logger.warning("Push send failed to %s: %s", notification.recipient, exc)
            return SendResult(success=False, channel=self.name, error=str(exc))
