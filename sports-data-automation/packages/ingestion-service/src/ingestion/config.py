"""Configuration management for ingestion service."""
from pydantic_settings import BaseSettings
from pydantic import Field
from typing import List, Dict, Optional
import os


class Settings(BaseSettings):
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

    # Metrics
    metrics_port: int = Field(default=9090, alias="METRICS_PORT")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "ignore"


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Get cached settings instance."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings