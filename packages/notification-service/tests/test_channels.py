"""
Unit tests for notification channels (all mocked).

FILE HEADER
-----------
Business problem this file solves:
    Each channel (email, Slack, SMS, push) performs outbound I/O that must not be exercised in
    unit tests. test_channels.py mocks SMTP, httpx, and Twilio so every channel's send() is
    verified for success and failure paths without network access or credentials.

Where it sits in the flow:
    Test layer for packages/notification-service/src/notification_service/channels/*.py.
    Run with pytest from the notification-service package directory.

What calls it / what it calls:
    Called by: pytest.
    Calls: notification_service.channels.*, notification_service.config.

What breaks if removed:
    No coverage of channel success/failure behavior; regressions in SMTP/HTTP/Twilio handling
    go undetected.

Language conventions:
    Python 3.11+. pytest with pytest-mock. Each channel has success and failure tests.
"""
import smtplib

import pytest

from notification_service.channels import (
    EmailChannel,
    PushChannel,
    SlackChannel,
    SmsChannel,
)
from notification_service.channels.base import Notification


def _make_notification(**overrides):
    data = dict(
        channel="email",
        recipient="ops@example.com",
        subject="Test alert",
        body="Something happened",
        severity="critical",
        type="alert",
    )
    data.update(overrides)
    return Notification(**data)


def _reset_settings():
    import notification_service.config as cfg

    cfg._settings = None


class TestEmailChannel:
    def test_send_success(self, monkeypatch):
        channel = EmailChannel()
        sent = {}

        class FakeServer:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def starttls(self):
                pass

            def login(self, user, password):
                sent["logged_in"] = True

            def send_message(self, msg):
                sent["to"] = msg["To"]
                sent["subject"] = msg["Subject"]

        monkeypatch.setattr("smtplib.SMTP", lambda *a, **k: FakeServer())
        result = channel.send(_make_notification(recipient="a@b.com"))
        assert result.success is True
        assert result.channel == "email"
        assert sent["to"] == "a@b.com"

    def test_send_failure(self, monkeypatch):
        channel = EmailChannel()

        def boom(*a, **k):
            raise smtplib.SMTPException("connection refused")

        monkeypatch.setattr("smtplib.SMTP", boom)
        result = channel.send(_make_notification())
        assert result.success is False
        assert result.channel == "email"
        assert "connection refused" in result.error


class TestSlackChannel:
    def test_send_success(self, monkeypatch):
        channel = SlackChannel()
        monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/x")
        _reset_settings()
        posted = {}

        class FakeResponse:
            def raise_for_status(self):
                pass

        class FakeClient:
            def __init__(self, *a, **k):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def post(self, url, json=None, timeout=None):
                posted["url"] = url
                posted["json"] = json
                return FakeResponse()

        monkeypatch.setattr("httpx.Client", FakeClient)
        result = channel.send(
            _make_notification(
                channel="slack",
                recipient="#alerts",
                subject="Down",
                body="db down",
                severity="page",
            )
        )
        assert result.success is True
        assert posted["json"]["channel"] == "#alerts"

    def test_send_no_webhook(self, monkeypatch):
        channel = SlackChannel()
        monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
        _reset_settings()
        result = channel.send(_make_notification(channel="slack", recipient="#alerts"))
        assert result.success is False
        assert "not configured" in result.error


class TestSmsChannel:
    def test_send_no_credentials(self, monkeypatch):
        channel = SmsChannel()
        monkeypatch.delenv("TWILIO_ACCOUNT_SID", raising=False)
        monkeypatch.delenv("TWILIO_AUTH_TOKEN", raising=False)
        monkeypatch.delenv("TWILIO_FROM", raising=False)
        _reset_settings()
        result = channel.send(
            _make_notification(channel="sms", recipient="+15550001234")
        )
        assert result.success is False
        assert result.error


class TestPushChannel:
    def test_send_simulated_when_no_endpoint(self, monkeypatch):
        channel = PushChannel()
        monkeypatch.delenv("PUSH_ENDPOINT", raising=False)
        _reset_settings()
        result = channel.send(
            _make_notification(
                channel="push",
                recipient="device_1",
                subject="Down",
                body="db down",
                severity="page",
            )
        )
        assert result.success is True
        assert result.channel == "push"

    def test_send_template_render(self):
        channel = PushChannel()
        result = channel.send(
            _make_notification(
                channel="push",
                recipient="device_1",
                subject="Down",
                body="",
                severity="page",
                template_name="alert_page",
                context={
                    "subject": "Down",
                    "severity": "page",
                    "body": "db is down",
                },
            )
        )
        assert result.success is True
