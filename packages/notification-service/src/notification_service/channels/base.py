"""
Core channel abstractions for the notification service.

FILE HEADER
-----------
Business problem this file solves:
    The notification service supports multiple channels (email, Slack, SMS, push) with different
    protocols. A common abstraction lets the router treat every channel uniformly and lets new
    channels be added without changing routing logic. base.py defines the Notification model,
    the SendResult outcome, and the abstract NotificationChannel interface.

Where it sits in the flow:
    Core abstraction layer. Every channel (email, slack, sms, push) subclasses
    NotificationChannel and implements send(). The router holds a list of NotificationChannel
    instances and calls send() on each routed channel.

What calls it / what it calls:
    Called by: channels/*.py (subclass NotificationChannel), router.py (calls send).
    Calls: nothing from this repo (pydantic, typing, abc).

What breaks if removed:
    No channel interface or notification model; channels and router cannot be constructed.

Language conventions:
    Python 3.11+. Pydantic v2 models for Notification and SendResult; abc.ABC for the channel.
    send(notification: Notification) -> SendResult.
"""
import logging
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class Notification(BaseModel):
    """A single outbound notification.

    WHAT: Holds everything a channel needs to deliver one message: channel, recipient, subject,
        body, severity, type, optional template name, and render context.
    WHY: A single schema shared by router, channels, and templates keeps the pipeline
        deterministic and easy to test/mock.
    EXAMPLE:
        Notification(channel="slack", recipient="#alerts", subject="Down", body="...",
                     severity="critical", type="alert")
    INPUTS: none (constructed by router/templates).
    OUTPUTS: a Notification instance.
    SIDE EFFECTS: none.
    FAILURE MODES: Pydantic validation error if a field has the wrong type.
    ALTERNATIVE: a plain dataclass. Chosen Pydantic for validation and coercion.
    """

    channel: str
    recipient: str
    subject: str
    body: str
    severity: str = Field(default="info")
    type: str = Field(default="alert")
    template_name: Optional[str] = Field(default=None)
    context: Dict[str, Any] = Field(default_factory=dict)


class SendResult(BaseModel):
    """Outcome of delivering one notification through one channel.

    WHAT: Records whether delivery succeeded, the channel used, a human message, and any error.
    WHY: The router aggregates SendResult objects per channel so callers can see which channels
        succeeded/failed without the pipeline crashing.
    INPUTS: none (constructed by channels/router).
    OUTPUTS: a SendResult instance.
    SIDE EFFECTS: none.
    """

    success: bool
    channel: str
    message: str = Field(default="")
    error: Optional[str] = Field(default=None)


class NotificationChannel(ABC):
    """Abstract base for every notification channel.

    WHAT: Defines the send(notification) -> SendResult contract every channel implements, plus
        a human-readable name.
    WHY: The router can iterate over heterogeneous channels (email, slack, sms, push) through a
        single interface, and new channels can be added without touching the router.
    EXAMPLE:
        class EmailChannel(NotificationChannel):
            name = "email"
            def send(self, notification): ...
    INPUTS: send receives a Notification.
    OUTPUTS: send returns a SendResult.
    SIDE EFFECTS: send performs outbound I/O (SMTP, HTTP, SMS API, Redis).
    FAILURE MODES: channels must catch their own exceptions and return SendResult(success=False,
        error=...) rather than raising, so one channel failure never crashes the pipeline.
    ALTERNATIVE: a Protocol/structural interface. Chosen ABC for an explicit, documented contract.
    """

    name: str = "channel"

    @abstractmethod
    def send(self, notification: Notification) -> SendResult:
        """Deliver one notification through this channel.

        WHAT: Subclasses perform channel-specific delivery and return a SendResult.
        WHY: Uniform entry point for the router.
        INPUTS: notification (Notification).
        OUTPUTS: SendResult.
        SIDE EFFECTS: outbound I/O specific to the channel.
        FAILURE MODES: must not raise; return SendResult(success=False, error=...) on failure.
        """
        ...  # pragma: no cover - abstract
