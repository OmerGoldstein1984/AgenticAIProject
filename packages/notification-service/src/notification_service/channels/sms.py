"""
Twilio SMS channel for the notification service.

FILE HEADER
-----------
Business problem this file solves:
    When email and Slack are not enough (e.g. off-hours pages), critical alerts must reach a
    phone by SMS. SmsChannel sends a text message via Twilio's REST API (account SID, auth
    token, from number from settings), degrading gracefully when Twilio isn't configured so the
    stack stays runnable in dev/CI without a live Twilio contract.

Where it sits in the flow:
    One of four concrete channels. Instantiated by the router and called via send() when sms
    is a routed channel for a notification's severity/type.

What calls it / what it calls:
    Called by: router.py (via NotificationChannel.send).
    Calls: twilio.rest.Client if installed (local import), else a failure result;
        config.get_settings; base.Notification/SendResult.

What breaks if removed:
    SMS deliveries fail; notifications routed only to sms are dropped (other channels still
    work).

Language conventions:
    Python 3.11+. send(notification) -> SendResult. Twilio errors and missing configuration
    are caught, logged, and returned as SendResult(success=False, error=...) so the pipeline
    never crashes.
"""
import logging

from notification_service.channels.base import Notification, NotificationChannel, SendResult
from notification_service.config import get_settings

logger = logging.getLogger(__name__)


class SmsChannel(NotificationChannel):
    """Delivers notifications by SMS via Twilio.

    WHAT: Sends a text message from twilio_from to notification.recipient using the Twilio REST
        API (account SID/auth token from Settings). If the twilio package isn't installed or no
        credentials are configured, it returns a failure SendResult (with a clear error) and
        logs it, keeping the stack runnable without a live Twilio contract.
    WHY: SMS is the fallback channel for pages when chat/email may be missed.
    EXAMPLE:
        SmsChannel().send(Notification(channel="sms", recipient="+15550001234",
                                       subject="Down", body="...", severity="page"))
    INPUTS: notification (Notification).
    OUTPUTS: SendResult.
    SIDE EFFECTS: outbound HTTPS to Twilio (network I/O), or a logged failure.
    FAILURE MODES: missing credentials, twilio import error, API error -> caught, logged,
        returned as SendResult(success=False, error=...); never raises.
    ALTERNATIVE: another SMS provider (SNS, Vonage). Chosen Twilio for its ubiquitous REST API.
    """

    name = "sms"

    def send(self, notification: Notification) -> SendResult:
        """Deliver one notification by SMS.

        WHAT: See class docstring. Attempts a real Twilio send when credentials/twilio are
            available; otherwise returns a failure SendResult with a clear error.
        WHY: Centralized SMS delivery with graceful degradation.
        INPUTS: notification (Notification).
        OUTPUTS: SendResult.
        SIDE EFFECTS: HTTPS network I/O or a logged failure.
        FAILURE MODES: any Twilio/communication error -> SendResult(success=False).
        """
        settings = get_settings()
        if not notification.recipient:
            return SendResult(success=False, channel=self.name, error="no recipient")

        body = f"{notification.subject}: {notification.body}"

        try:
            from twilio.rest import Client  # type: ignore

            if (
                not settings.twilio_account_sid
                or not settings.twilio_auth_token
                or not settings.twilio_from
            ):
                raise ValueError(
                    "TWILIO_ACCOUNT_SID/TWILIO_AUTH_TOKEN/TWILIO_FROM not configured"
                )
            client = Client(settings.twilio_account_sid, settings.twilio_auth_token)
            client.messages.create(
                body=body,
                from_=settings.twilio_from,
                to=notification.recipient,
            )
            logger.info("SMS sent to %s (%s)", notification.recipient, notification.subject)
            return SendResult(
                success=True,
                channel=self.name,
                message=f"sent to {notification.recipient}",
            )
        except Exception as exc:  # channel failures must not crash the pipeline
            logger.warning("SMS send failed to %s: %s", notification.recipient, exc)
            return SendResult(success=False, channel=self.name, error=str(exc))
