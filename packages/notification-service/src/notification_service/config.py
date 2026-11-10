"""
Configuration management for the notification service.

FILE HEADER
-----------
Business problem this file solves:
    The notification service needs to know SMTP host/port/credentials, the Slack webhook URL,
    Twilio account SID/auth token/from number, and the Redis URL — and those values differ
    between a dev laptop (localhost), CI, and production. Settings centralizes all configuration
    as environment-variable-backed Pydantic settings so the same code runs in every environment
    without code changes.

Where it sits in the flow:
    Bootstrap layer for the notification service. The router and channels call get_settings() to
    read SMTP/Slack/Twilio/Redis configuration. Every runtime value the service needs flows
    through this module.

What calls it / what it calls:
    Called by: router.py, channels/email.py, channels/slack.py, channels/sms.py, channels/push.py.
    Calls: nothing from this repo (pydantic-settings, pydantic, stdlib).

What breaks if removed:
    The notification service cannot locate SMTP/Slack/Twilio/Redis; Settings() returns an
    incompletely-configured object and channel initialization fails.

Language conventions:
    Python 3.11+. Pydantic-settings BaseSettings with Field(alias=...) for env var names.
    Field defaults are dev-friendly localhost values; production overrides via .env / env vars.
    `extra = "ignore"` so unknown env vars don't crash startup.
"""
from typing import Optional

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """All runtime configuration for the notification service, sourced from env vars.

    WHAT: Pydantic-settings model mapping env vars (SMTP_HOST, SLACK_WEBHOOK_URL,
        TWILIO_ACCOUNT_SID, REDIS_URL, ...) to typed fields with dev-friendly defaults.
    WHY: One place to configure the service; environment-driven config means the same Docker
        image runs in dev/CI/prod with only env changes (12-factor app principle).
    EXAMPLE:
        Settings()  # reads .env and environment; smtp_host defaults to "localhost"
    INPUTS: none (reads os.environ + .env automatically).
    OUTPUTS: a Settings instance with typed fields.
    SIDE EFFECTS: reads .env file (env_file=".env") on first instantiation.
    FAILURE MODES: Pydantic validation error if an env var has the wrong type (e.g. SMTP_PORT=abc).
    ALTERNATIVE: read env vars manually with os.getenv. Chosen pydantic-settings for type
        coercion, validation, and a single source of truth.
    """

    # SMTP
    smtp_host: str = Field(default="localhost", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: Optional[str] = Field(default=None, alias="SMTP_USER")
    smtp_password: Optional[str] = Field(default=None, alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")
    smtp_from: str = Field(default="alerts@localhost", alias="SMTP_FROM")

    # Slack
    slack_webhook_url: Optional[str] = Field(default=None, alias="SLACK_WEBHOOK_URL")

    # Twilio
    twilio_account_sid: Optional[str] = Field(default=None, alias="TWILIO_ACCOUNT_SID")
    twilio_auth_token: Optional[str] = Field(default=None, alias="TWILIO_AUTH_TOKEN")
    twilio_from: Optional[str] = Field(default=None, alias="TWILIO_FROM")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # Push
    push_api_key: Optional[str] = Field(default=None, alias="PUSH_API_KEY")
    push_endpoint: Optional[str] = Field(default=None, alias="PUSH_ENDPOINT")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return a cached, singleton Settings instance.

    WHAT: Creates Settings() once and caches it in the module-level _settings; every subsequent
        call returns the same object.
    WHY: Avoids re-reading .env and re-validating on every call; process-wide config is
        consistent.
    INPUTS: none.
    OUTPUTS: the cached Settings instance.
    SIDE EFFECTS: mutates module-global _settings on first call.
    FAILURE MODES: propagates Settings validation error on first call if env is invalid.
    ALTERNATIVE: pass a Settings instance into each component (dependency injection). Chosen a
        module singleton for simplicity; DI would be more testable but adds plumbing.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
