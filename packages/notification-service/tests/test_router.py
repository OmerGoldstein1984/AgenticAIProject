"""
Unit tests for the notification router.

FILE HEADER
-----------
Business problem this file solves:
    The router decides which channels receive a notification based on severity and type, and it
    must keep delivering when a channel fails. test_router.py verifies channel selection,
    template rendering, and failure isolation without real network calls.

Where it sits in the flow:
    Test layer for packages/notification-service/src/notification_service/router.py.

What calls it / what it calls:
    Called by: pytest.
    Calls: notification_service.router.NotificationRouter,
        notification_service.channels.base.Notification.

What breaks if removed:
    No coverage of routing logic or failure isolation; a misrouted or crashing channel would go
    undetected.

Language conventions:
    Python 3.11+. pytest. Channels are stubbed so the router is tested in isolation.
"""
from notification_service.channels.base import Notification, NotificationChannel, SendResult
from notification_service.router import (
    DEFAULT_SEVERITY_ROUTES,
    DEFAULT_TYPE_ROUTES,
    NotificationRouter,
)


class StubChannel(NotificationChannel):
    def __init__(self, name="stub", fail=False):
        self.name = name
        self.fail = fail
        self.sent = []

    def send(self, notification):
        self.sent.append(notification)
        if self.fail:
            raise RuntimeError("boom")
        return SendResult(success=True, channel=self.name, message="ok")


def _make_notification(**overrides):
    data = dict(
        channel="slack",
        recipient="#alerts",
        subject="Down",
        body="db down",
        severity="warning",
        type="alert",
    )
    data.update(overrides)
    return Notification(**data)


def test_route_selects_severity_channels():
    router = NotificationRouter(
        channels={
            "email": StubChannel("email"),
            "slack": StubChannel("slack"),
            "sms": StubChannel("sms"),
            "push": StubChannel("push"),
        }
    )
    results = router.route(_make_notification(severity="critical", type="alert"))
    channels_used = {r.channel for r in results}
    assert channels_used == {"email", "slack", "sms"}
    assert all(r.success for r in results)


def test_route_type_adds_channels():
    router = NotificationRouter(
        channels={
            "email": StubChannel("email"),
            "slack": StubChannel("slack"),
        }
    )
    results = router.route(_make_notification(severity="info", type="runbook"))
    channels_used = {r.channel for r in results}
    # info -> email; runbook -> email (dedup)
    assert channels_used == {"email"}


def test_route_channel_failure_is_isolated():
    router = NotificationRouter(
        channels={
            "email": StubChannel("email", fail=True),
            "slack": StubChannel("slack"),
        }
    )
    results = router.route(_make_notification(severity="warning"))
    outcomes = {r.channel: r.success for r in results}
    assert outcomes == {"email": False, "slack": True}
    assert any("boom" in (r.error or "") for r in results if r.channel == "email")


def test_route_unknown_channel_skipped():
    router = NotificationRouter(
        channels={"email": StubChannel("email")},
        severity_routes={"warning": ["email", "nonexistent"]},
    )
    results = router.route(_make_notification(severity="warning"))
    channels_used = {r.channel for r in results}
    assert "email" in channels_used
    assert any(
        r.channel == "nonexistent" and r.success is False for r in results
    )


def test_route_renders_template():
    from notification_service.templates import TemplateRegistry

    registry = TemplateRegistry()
    registry.register("notify", "Hello {{ name }}")
    router = NotificationRouter(
        channels={"email": StubChannel("email")},
        severity_routes={"info": ["email"]},
        template_registry=registry,
    )
    notif = _make_notification(
        severity="info", template_name="notify", context={"name": "world"}
    )
    router.route(notif)
    assert notif.body == "Hello world"


def test_default_routes_are_sane():
    assert DEFAULT_SEVERITY_ROUTES["page"] == ["slack", "sms", "push"]
    assert DEFAULT_SEVERITY_ROUTES["info"] == ["email"]
    assert DEFAULT_TYPE_ROUTES["alert"] == ["email", "slack"]
