"""
packages/notification-service/src/notification_service/__init__.py

FILE HEADER
-----------
Business problem this file solves:
    Marks the notification_service directory as a Python package and exposes the public API
    (Settings, Notification, NotificationChannel, SendResult, TemplateRegistry,
    NotificationRouter, and the channel implementations) so consumers can
    `from notification_service import ...` without reaching into submodules.

Where it sits in the flow:
    Top-level package init for packages/notification-service/. Imported by anything that uses
    the notification service as a library (n8n nodes, demo scripts, tests, router).

What calls it / what it calls:
    Called by: n8n custom nodes, scripts, tests.
    Calls: submodule __init__ files (channels), config, templates, router.

What breaks if removed:
    `import notification_service` fails; the package is not importable as a namespace.

Language conventions:
    Python 3.11+. Keep this file minimal — only re-export public symbols.
"""

from notification_service.channels import (  # noqa: F401
    EmailChannel,
    NotificationChannel,
    PushChannel,
    SendResult,
    SlackChannel,
    SmsChannel,
)
from notification_service.config import Settings  # noqa: F401
from notification_service.router import NotificationRouter  # noqa: F401
from notification_service.templates import TemplateRegistry  # noqa: F401
from notification_service.channels.base import Notification  # noqa: F401

__all__ = [
    # config
    "Settings",
    # core models
    "Notification",
    "SendResult",
    # channels
    "NotificationChannel",
    "EmailChannel",
    "SlackChannel",
    "SmsChannel",
    "PushChannel",
    # templates
    "TemplateRegistry",
    # router
    "NotificationRouter",
]
