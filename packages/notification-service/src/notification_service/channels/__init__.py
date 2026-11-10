"""
Channel package for the notification service.

FILE HEADER
-----------
Business problem this file solves:
    Exposes the channel implementations (email, Slack, SMS, push) and the shared abstractions
    (NotificationChannel, Notification, SendResult) so the router and tests can import
    `from notification_service.channels import EmailChannel, ...` without reaching into
    submodules.

Where it sits in the flow:
    Channel layer of packages/notification-service/. Imported by router.py and tests.

What calls it / what it calls:
    Called by: router.py, tests.
    Calls: base.py, email.py, slack.py, sms.py, push.py.

What breaks if removed:
    `from notification_service.channels import ...` fails; the router cannot assemble channels.

Language conventions:
    Python 3.11+. Only re-export public symbols.
"""

from notification_service.channels.base import Notification, NotificationChannel, SendResult
from notification_service.channels.email import EmailChannel
from notification_service.channels.push import PushChannel
from notification_service.channels.slack import SlackChannel
from notification_service.channels.sms import SmsChannel

__all__ = [
    "Notification",
    "NotificationChannel",
    "SendResult",
    "EmailChannel",
    "SlackChannel",
    "SmsChannel",
    "PushChannel",
]
