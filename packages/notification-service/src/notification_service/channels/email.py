"""
SMTP email channel for the notification service.

FILE HEADER
-----------
Business problem this file solves:
    Alerts and runbook notifications must be deliverable by email. EmailChannel sends MIME
    messages over SMTP (with optional TLS/auth) using settings from config.py, so operators
    receive alerts in their inbox without depending on Slack/Twilio/push.

Where it sits in the flow:
    One of four concrete channels. Instantiated by the router and called via send() when email
    is a routed channel for a notification's severity/type.

What calls it / what it calls:
    Called by: router.py (via NotificationChannel.send).
    Calls: smtplib/email.mime (stdlib), config.get_settings, base.Notification/SendResult.

What breaks if removed:
    Email deliveries fail; notifications routed only to email are dropped (other channels still
    work).

Language conventions:
    Python 3.11+. send(notification) -> SendResult. All SMTP errors are caught, logged, and
    returned as SendResult(success=False, error=...) so the pipeline never crashes.
"""
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from notification_service.channels.base import Notification, NotificationChannel, SendResult
from notification_service.config import get_settings

logger = logging.getLogger(__name__)


class EmailChannel(NotificationChannel):
    """Delivers notifications by email over SMTP.

    WHAT: Builds a MIME multipart message from the notification's subject/body and sends it via
        smtplib using SMTP host/port/user/pass from Settings (with optional STARTTLS).
    WHY: Email is the primary low-latency, no-external-account channel for alerts.
    EXAMPLE:
        EmailChannel().send(Notification(channel="email", recipient="ops@example.com",
                                         subject="Down", body="...", severity="critical"))
    INPUTS: notification (Notification).
    OUTPUTS: SendResult.
    SIDE EFFECTS: opens an SMTP connection and sends email (outbound network I/O).
    FAILURE MODES: connection refused, auth failure, send failure -> caught, logged, returned
        as SendResult(success=False, error=...); never raises.
    ALTERNATIVE: a third-party email API (Sendgrid/SES). Chosen SMTP for zero extra accounts.
    """

    name = "email"

    def send(self, notification: Notification) -> SendResult:
        """Deliver one notification by email.

        WHAT: See class docstring. Connects to SMTP, optionally starts TLS, logs in if
            credentials are configured, and sends the message.
        WHY: Centralized email delivery with graceful degradation.
        INPUTS: notification (Notification).
        OUTPUTS: SendResult.
        SIDE EFFECTS: SMTP network I/O.
        FAILURE MODES: any SMTP/communication error -> SendResult(success=False).
        """
        settings = get_settings()
        if not notification.recipient:
            return SendResult(success=False, channel=self.name, error="no recipient")

        try:
            msg = MIMEMultipart()
            msg["From"] = settings.smtp_from
            msg["To"] = notification.recipient
            msg["Subject"] = notification.subject
            msg.attach(MIMEText(notification.body, "plain"))

            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10) as server:
                if settings.smtp_use_tls:
                    server.starttls()
                if settings.smtp_user and settings.smtp_password:
                    server.login(settings.smtp_user, settings.smtp_password)
                server.send_message(msg)

            logger.info("Email sent to %s (%s)", notification.recipient, notification.subject)
            return SendResult(
                success=True,
                channel=self.name,
                message=f"sent to {notification.recipient}",
            )
        except Exception as exc:  # channel failures must not crash the pipeline
            logger.warning("Email send failed to %s: %s", notification.recipient, exc)
            return SendResult(success=False, channel=self.name, error=str(exc))
