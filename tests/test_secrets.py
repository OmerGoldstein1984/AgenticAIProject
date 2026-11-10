"""
Unit tests for ingestion.security.secrets: redaction and dev-default detection.
"""

from __future__ import annotations

from ingestion.security.secrets import redact, contains_dev_default, mask_headers


def test_redact_hides_middle_of_secret():
    assert redact("sk-ant-abcdef1234567890") == "sk...90"
    assert redact("sk-ant-abcdef1234567890", show=4) == "sk-a...7890"


def test_redact_short_secret_fully_masked():
    assert redact("abc") == "***"
    assert redact("ab") == "***"


def test_redact_none_and_empty():
    assert redact(None) == "[redacted]"
    assert redact("") == "[redacted]"


def test_contains_dev_default_catches_placeholders():
    assert contains_dev_default("changeme") is True
    assert contains_dev_default("changeme123") is True
    assert contains_dev_default("your-secret-here") is True
    assert contains_dev_default("admin") is True
    assert contains_dev_default("password") is True
    assert contains_dev_default("POSTGRES_PASSWORD=changeme") is True  # substring


def test_contains_dev_default_rejects_real_values():
    assert contains_dev_default("sk-ant-v1real-long-key-value-abcdef") is False
    assert contains_dev_default("postgresql://user:R4nd0mP@ss@db:5432/db") is False


def test_contains_dev_default_none_empty():
    assert contains_dev_default(None) is False
    assert contains_dev_default("") is False


def test_mask_headers_hides_credentials():
    headers = {
        "authorization": "Bearer sk-ant-secret",
        "x-api-key": "sk-ant-key",
        "content-type": "application/json",
        "x-custom": "visible",
    }
    masked = mask_headers(headers)
    # Full secrets must never appear; redact() partially masks long values.
    assert "sk-ant-secret" not in masked["authorization"]
    assert "sk-ant-key" not in masked["x-api-key"]
    assert "..." in masked["authorization"] and "..." in masked["x-api-key"]
    assert masked["content-type"] == "application/json"
    assert masked["x-custom"] == "visible"
    # original untouched
    assert headers["authorization"] == "Bearer sk-ant-secret"
