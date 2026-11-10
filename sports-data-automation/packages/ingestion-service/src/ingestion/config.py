"""
Configuration management for ingestion service.

FILE HEADER
-----------
Business problem this file solves:
    The ingestion service needs to know where Redis, Postgres, n8n, and the provider feeds live,
    how often to poll, how long to keep dedup keys, and where the schema registry is — and those
    values differ between a dev laptop (localhost), CI, and production. Settings centralizes all
    configuration as environment-variable-backed Pydantic settings so the same code runs in every
    environment without code changes.

Where it sits in the flow:
    Bootstrap layer for the ingestion service. main.py calls get_settings() in lifespan() to
    construct SchemaValidator, CanonicalTransformer, Deduplicator, WebSocketClient, and RESTPoller.
    Every runtime value the service needs flows through this module.

What calls it / what it calls:
    Called by: packages/ingestion-service/src/ingestion/main.py (get_settings in lifespan and
    each process_* function).
    Calls: nothing from this repo (pydantic-settings, pydantic, stdlib os).
What breaks if removed:
    The ingestion service cannot locate Redis/Postgres/n8n/providers; get_settings() returns an
    incompletely-configured object and lifespan() fails to initialize subcomponents.
Language conventions:
    Python 3.11+. Pydantic-settings BaseSettings with Field(alias=...) for env var names.
    Field defaults are dev-friendly localhost values; production overrides via .env / env vars.
    `extra = "ignore"` so unknown env vars don't crash startup.
GAP: No validation that required secrets (e.g. POSTGRES_PASSWORD) are actually set; dev defaults
    like "changeme" would silently reach production if .env is missing. See 07_issues_found.md.
"""
from pydantic_settings import BaseSettings
from pydantic import Field, model_validator
from typing import List, Dict, Optional
import os


class Settings(BaseSettings):
    """All runtime configuration for the ingestion service, sourced from env vars.

    WHAT: Pydantic-settings model mapping env vars (PORT, REDIS_URL, POSTGRES_DSN, ...)
        to typed fields with dev-friendly defaults.
    WHY: One place to configure the service; environment-driven config means the same Docker
        image runs in dev/CI/prod with only env changes (12-factor app principle).
    EXAMPLE:
        Settings()  # reads .env and environment; redis_url defaults to redis://localhost:6379/0
    INPUTS: none (reads os.environ + .env automatically).
    OUTPUTS: a Settings instance with typed fields.
    SIDE EFFECTS: reads .env file (env_file=".env") on first instantiation.
    FAILURE MODES: Pydantic validation error if an env var has the wrong type (e.g. PORT=abc).
    ALTERNATIVE: read env vars manually with os.getenv. Chosen pydantic-settings for type
        coercion, validation, and a single source of truth.
    # INTERVIEW: env_file + extra="ignore" means this never crashes on unknown CI env vars,
    #    but also never warns you about a typo'd variable (e.g. REDIES_URL). Trade-off: silent
    #    misconfiguration is possible.
    """
    # Service
    port: int = Field(default=8000, alias="PORT")
    debug: bool = Field(default=True, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # Redis
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # PostgreSQL
    postgres_dsn: str = Field(
        default="postgresql://sports_user:changeme@localhost:5432/sports_automation",
        alias="POSTGRES_DSN"
    )

    # n8n
    n8n_webhook_url: str = Field(
        default="http://localhost:5678/webhook",
        alias="N8N_WEBHOOK_URL"
    )

    # Providers
    odds_feed_ws_url: str = Field(
        default="ws://localhost:8080/ws",
        alias="ODDS_FEED_WS_URL"
    )

    rest_endpoints: List[Dict] = Field(
        default=[
            {
                "name": "event_feed",
                "url": "http://localhost:8081/events",
                "type": "event",
                "interval": 30,
            },
            {
                "name": "settlement_feed",
                "url": "http://localhost:8081/settlements",
                "type": "settlement",
                "interval": 60,
            },
        ],
        alias="REST_ENDPOINTS"
    )

    rest_poll_interval: int = Field(default=30, alias="REST_POLL_INTERVAL")
    ws_reconnect_interval: int = Field(default=5, alias="WS_RECONNECT_INTERVAL")

    # Provider registry
    providers_config_path: str = Field(
        default="./providers.json", alias="PROVIDERS_CONFIG_PATH"
    )
    provider_registry_enabled: bool = Field(
        default=False, alias="PROVIDER_REGISTRY_ENABLED"
    )

    # Schema registry
    schema_registry_path: str = Field(
        default="./schemas",
        alias="SCHEMA_REGISTRY_PATH"
    )

    # Deduplication
    deduplication_ttl_seconds: int = Field(
        default=86400,  # 24 hours
        alias="DEDUPLICATION_TTL_SECONDS"
    )

    # n8n retry / dead letter queue
    n8n_max_retries: int = Field(default=3, alias="N8N_MAX_RETRIES")
    n8n_retry_backoff: float = Field(default=1.0, alias="N8N_RETRY_BACKOFF")
    dlq_redis_key_prefix: str = Field(default="dlq:n8n:", alias="DLQ_REDIS_KEY_PREFIX")

    # Ingestion API key auth (X-API-Key on /ingest/* endpoints)
    ingestion_api_key: str = Field(default="", alias="INGESTION_API_KEY")

    # CORS
    cors_allow_origins: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:5678"],
        alias="CORS_ALLOW_ORIGINS",
    )

    # Metrics
    metrics_port: int = Field(default=9090, alias="METRICS_PORT")

    @model_validator(mode="after")
    def _validate_no_dev_defaults_in_production(self) -> "Settings":
        """Fail fast at startup when dev-default secrets leak into non-dev environments.

        WHAT: When DEBUG is falsy (production/staging), rejects Settings whose postgres_dsn
            still contains the dev placeholder "changeme". Prevents dev credentials from
            silently reaching production, where they would either fail to connect or expose
            a well-known default password.
        WHY: The documented GAP in config.py (header lines 29–30) is that required secrets
            have dev-friendly defaults that can silently reach production if .env is missing.
            This validator makes misconfiguration fail fast at startup instead of silently
            at runtime.
        INPUTS: none (reads self fields).
        OUTPUTS: the validated Settings instance.
        SIDE EFFECTS: raises ValueError on a dev-default value in a non-dev environment.
        """
        if self.debug:
            return self
        dev_defaults = {
            "postgres_dsn": "changeme",
        }
        for field, placeholder in dev_defaults.items():
            value = getattr(self, field, None)
            if isinstance(value, str) and placeholder in value:
                raise ValueError(
                    f"{field} contains dev default '{placeholder}'; "
                    f"set a production value via {field.upper()} env var before deploying "
                    f"to non-dev (DEBUG=0)"
                )
        return self

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return a cached, singleton Settings instance.

    WHAT: Creates Settings() once and caches it in the module-level _settings; every subsequent
        call returns the same object.
    WHY: Avoids re-reading .env and re-validating on every call; process-wide config is consistent.
        Each process_* function in main.py calls get_settings() to read current values at request
        time (so env changes within a process would be reflected — though with the singleton they
        won't change after first call).
    INPUTS: none.
    OUTPUTS: the cached Settings instance.
    SIDE EFFECTS: mutates module-global _settings on first call.
    FAILURE MODES: propagates Settings validation error on first call if env is invalid.
    ALTERNATIVE: pass a Settings instance into each component (dependency injection). Chosen a
        module singleton for simplicity; DI would be more testable but adds plumbing.
    # GAP: because it's a singleton cached at import time, tests cannot easily override settings
    #    per-test without monkeypatching _settings. See 07_issues_found.md.
    """
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
