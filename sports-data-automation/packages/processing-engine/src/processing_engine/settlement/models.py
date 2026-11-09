"""
packages/processing-engine/src/processing_engine/settlement/models.py

FILE HEADER
-----------
Business problem this file solves:
    The settlement rule engine needs canonical settlement types (SettlementResult,
    SettlementOutcome) to return structured, auditable settlement decisions. Rather than
    redefining them, this module re-exports the canonical types from
    sports_automation.types so the processing engine and the ingestion service share one
    source of truth for settlement outcomes.

Where it sits in the flow:
    Leaf module under settlement/. Imported by rule_engine.py, dsl_parser.py, and
    processing_engine/__init__.py. Consumers (n8n settlement-worker, demo scripts) import
    SettlementResult/SettlementOutcome from here.

What calls it / what it calls:
    Called by: rule_engine, dsl_parser, processing_engine.__init__, external consumers.
    Calls: sports_automation.types (canonical types) via sys.path-resolved import.

What breaks if removed:
    SettlementResult/SettlementOutcome are unavailable; rule_engine cannot build results,
    and the settlement contract with the ingestion service / n8n nodes breaks.

Language conventions:
    Python 3.11+. Re-export/alias of canonical SettlementResult/SettlementOutcome. Falls back
    to local aliases only if the canonical types package is not importable (defensive).

GAP: imports sports_automation.types via a sys.path insert resolved relative to this file
    (monorepo layout). In Docker, ensure the canonical-types Python dir is on PYTHONPATH or
    mounted into the container; otherwise the defensive local aliases are used.
"""

import os
import sys

# Make the monorepo's canonical-types Python package importable.
# File: packages/processing-engine/src/processing_engine/settlement/models.py
# Canonical types live at: packages/canonical-types/python/sports_automation/types.py
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANONICAL_TYPES_PY = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", "canonical-types", "python")
)
if os.path.isdir(_CANONICAL_TYPES_PY) and _CANONICAL_TYPES_PY not in sys.path:
    sys.path.insert(0, _CANONICAL_TYPES_PY)

try:
    from sports_automation.types import SettlementResult, SettlementOutcome  # noqa: E402
except ImportError:  # pragma: no cover - defensive fallback when canonical-types is absent
    """Defensive local aliases so the package imports even if canonical-types is not on the
    path. These mirror sports_automation.types exactly; prefer the canonical import."""
    from enum import Enum
    from typing import Optional, Dict, Any
    from pydantic import BaseModel, Field
    from datetime import datetime

    class SettlementOutcome(str, Enum):
        """Financial outcome of settling one bet selection (canonical mirror)."""
        WON = "won"
        LOST = "lost"
        VOID = "void"
        HALF_WON = "half_won"
        HALF_LOST = "half_lost"

    class SettlementResult(BaseModel):
        """Result of settling one bet selection (canonical mirror)."""
        event_id: str
        market_id: str
        selection_id: str
        outcome: SettlementOutcome
        settled_at: datetime
        source: str  # 'official' | 'manual' | 'auto_reconciled'
        confidence: float = Field(ge=0, le=1)

__all__ = ["SettlementResult", "SettlementOutcome"]
