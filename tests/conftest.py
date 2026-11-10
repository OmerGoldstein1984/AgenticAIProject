"""
tests/conftest.py

FILE HEADER
-----------
Business problem this file solves:
    The ingestion-service package (src/ingestion) and the canonical-types Python package
    (sports_automation) live under sports-data-automation/packages/*/src and are not installed
    on the system Python path. pytest run from the repo root therefore cannot import them.
    conftest.py adds both src directories to sys.path once and provides shared fixtures used by
    test_ingestion.py, test_processing_engine.py, and test_contract.py.

Where it sits in the flow:
    tests/conftest.py — auto-loaded by pytest for every test under tests/.

What calls it / what it calls:
    Imported by pytest; no test calls it directly. Fixtures are requested by test modules.

What breaks if removed:
    ImportError for ingestion.schema_validator, ingestion.canonical_transformer,
    ingestion.main, and sports_automation.types.

Language conventions:
    Python 3.11+. Pytest fixtures. Paths resolved relative to this file so the suite runs
    from any working directory.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Make the two in-repo Python packages importable without installing them.
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[1]
_INGESTION_SRC = (
    _REPO_ROOT / "sports-data-automation" / "packages" / "ingestion-service" / "src"
)
_PROCESSING_ENGINE_SRC = (
    _REPO_ROOT / "sports-data-automation" / "packages" / "processing-engine" / "src"
)
_CANONICAL_PY = (
    _REPO_ROOT
    / "sports-data-automation"
    / "packages"
    / "canonical-types"
    / "python"
)

for _path in (_INGESTION_SRC, _PROCESSING_ENGINE_SRC, _CANONICAL_PY):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

import pytest  # noqa: E402  (import after sys.path is configured)


# ---------------------------------------------------------------------------
# Sample provider payloads (provider field names, lsports dialect)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_provider_odds():
    """Raw LSports odds payload using provider field names."""
    return {
        "provider_id": "lsports",
        "event_id": "evt_1001",
        "market_id": "match_winner",
        "selection_id": "home",
        "odds": 2.10,
        "odds_format": "decimal",
        "timestamp": "2026-11-09T14:30:00Z",
        "sequence": 7,
    }


@pytest.fixture
def sample_provider_event():
    """Raw LSports event payload using provider field names."""
    return {
        "id": "evt_1001",
        "sport": "football",
        "league": "Premier League",
        "home_team": {"id": "team_home", "name": "Red United", "short_name": "RED"},
        "away_team": {"id": "team_away", "name": "Blue City", "short_name": "BLU"},
        "start_time": "2026-11-10T15:00:00Z",
        "status": "scheduled",
        "score": {"home": 0, "away": 0},
    }


@pytest.fixture
def sample_provider_settlement():
    """Raw LSports settlement payload (mixed camelCase/snake_case accepted by transformer)."""
    return {
        "eventId": "evt_1001",
        "marketId": "match_winner",
        "selectionId": "home",
        "outcome": "won",
        "settledAt": "2026-11-10T17:05:00Z",
        "source": "official",
        "confidence": 1.0,
    }


# ---------------------------------------------------------------------------
# Canonical payloads (canonical field names, decimal odds, ISO 8601 timestamps)
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_canonical_odds():
    return {
        "providerId": "lsports",
        "eventId": "evt_1001",
        "marketId": "match_winner",
        "selectionId": "home",
        "odds": 2.10,
        "format": "decimal",
        "timestamp": "2026-11-09T14:30:00Z",
        "sequence": 7,
    }


@pytest.fixture
def sample_canonical_event():
    return {
        "id": "evt_1001",
        "sport": "football",
        "league": "Premier League",
        "homeTeam": {"id": "team_home", "name": "Red United", "shortName": "RED"},
        "awayTeam": {"id": "team_away", "name": "Blue City", "shortName": "BLU"},
        "startTime": "2026-11-10T15:00:00Z",
        "status": "scheduled",
        "score": {"home": 0, "away": 0},
    }


@pytest.fixture
def sample_canonical_settlement():
    return {
        "eventId": "evt_1001",
        "marketId": "match_winner",
        "selectionId": "home",
        "outcome": "won",
        "settledAt": "2026-11-10T17:05:00Z",
        "source": "official",
        "confidence": 1.0,
    }


# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class FakeDeduplicator:
    """In-memory stand-in for Deduplicator; no Redis required.

    check_and_store(key) returns True if the key was already seen (duplicate),
    False if it is newly stored. Mirrors the real Deduplicator contract.
    """

    def __init__(self, *args, **kwargs):
        self.seen = set()

    @property
    def is_connected(self):
        return True

    async def connect(self):
        return None

    async def disconnect(self):
        return None

    async def check_and_store(self, key: str) -> bool:
        already = key in self.seen
        self.seen.add(key)
        return already


@pytest.fixture
def fake_deduplicator():
    return FakeDeduplicator()


class ForwardSpy:
    """Records calls to forward_to_n8n so tests can assert forwarding behavior."""

    def __init__(self):
        self.calls = []

    async def __call__(self, data_type: str, data: dict, trace_id: Optional[str] = None):
        self.calls.append((data_type, data, trace_id))


@pytest.fixture
def forward_spy():
    return ForwardSpy()


@pytest.fixture
def settings(monkeypatch):
    """Monkeypatch ingestion.config.get_settings to return a test Settings.

    Avoids reading a real .env and avoids touching Redis/n8n.
    """
    from ingestion.config import Settings

    test_settings = Settings()
    monkeypatch.setattr("ingestion.config._settings", test_settings)
    monkeypatch.setattr("ingestion.config.get_settings", lambda: test_settings)
    return test_settings
