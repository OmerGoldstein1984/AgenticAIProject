"""
packages/processing-engine/src/processing_engine/reconciliation/auto_corrector.py

FILE HEADER
-----------
Business problem this file solves:
    Not every discrepancy can be auto-corrected safely. auto_corrector.py applies safe,
    deterministic corrections (e.g. settle to official outcome, update a score) and flags
    ambiguous or high-severity discrepancies for manual review, producing an auditable
    split between auto-corrected and manual-review items.

Where it sits in the flow:
    Core reconciliation module. Imported by processing_engine/__init__.py and the n8n
    reconciliation workflow. Consumed after drift_detector finds discrepancies; its output
    feeds report.py.

What calls it / what it calls:
    Called by: reconciliation workflow, report, tests.
    Calls: sports_automation.types (Discrepancy), stdlib only.

What breaks if removed:
    No auto-correction path; every discrepancy goes to manual review (ops overload) or none
    are corrected (drift persists).

Language conventions:
    Python 3.11+. AutoCorrector.correct(discrepancies) -> (corrected, flagged). Safe
    corrections: low/medium severity on non-financial fields; high-severity or
    financial-field discrepancies (outcome/odds) are flagged for manual review.
"""

import sys
import os
from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

# Ensure canonical types are importable (monorepo layout).
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANONICAL_TYPES_PY = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", "canonical-types", "python")
)
if os.path.isdir(_CANONICAL_TYPES_PY) and _CANONICAL_TYPES_PY not in sys.path:
    sys.path.insert(0, _CANONICAL_TYPES_PY)

from sports_automation.types import Discrepancy  # noqa: E402

# Fields that auto_corrector is allowed to fix without human review.
_SAFE_CORRECTABLE_FIELDS = {"score", "status", "metadata"}


@dataclass
class CorrectionResult:
    """Outcome of attempting to correct one discrepancy.

    WHAT: discrepancy, corrected (bool), reason, corrected_value.
    WHY: Auditable record of what was auto-corrected and why.
    """
    discrepancy: Discrepancy
    corrected: bool
    reason: str
    corrected_value: Any = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entity_type": self.discrepancy.entity_type,
            "entity_id": self.discrepancy.entity_id,
            "field": self.discrepancy.field,
            "expected": self.discrepancy.expected,
            "actual": self.discrepancy.actual,
            "severity": self.discrepancy.severity,
            "corrected": self.corrected,
            "reason": self.reason,
            "corrected_value": self.corrected_value,
        }


class AutoCorrector:
    """Auto-corrects safe discrepancies and flags the rest for manual review.

    WHAT: Evaluates each Discrepancy. Low/medium severity on safe-correctable fields
        (score, status, metadata) are auto-corrected to the expected value. High-severity
        discrepancies or discrepancies on financial fields (outcome, odds) are flagged for
        manual review (not corrected) because they affect payouts.
    WHY: Automation handles routine drift (a score typo) while protecting financial
        correctness (never auto-change an outcome). Every decision is recorded for audit.
    INPUTS: discrepancies (List[Discrepancy]).
    OUTPUTS: (corrected: List[CorrectionResult], flagged: List[CorrectionResult]).
    SIDE EFFECTS: none (pure; the caller applies corrections to source systems).
    FAILURE MODES: never raises; unclear discrepancies are flagged.
    ALTERNATIVE: full ML-driven correction. Chosen deterministic rules for auditability —
        ops can explain exactly why each discrepancy was auto-corrected or flagged.
    """

    def __init__(self, safe_fields: set | None = None):
        """Construct with a set of fields considered safe to auto-correct.

        WHAT: Stores the safe-correctable field set (defaults to score/status/metadata).
        WHY: Operators can tighten or relax which fields auto-correct touches.
        INPUTS: safe_fields (optional set of field names).
        """
        self.safe_fields = set(safe_fields) if safe_fields else set(_SAFE_CORRECTABLE_FIELDS)

    def correct(self, discrepancies: List[Discrepancy]) -> Tuple[List[CorrectionResult], List[CorrectionResult]]:
        """Split discrepancies into auto-corrected and flagged-for-manual-review.

        WHAT: For each discrepancy, decides safe auto-correct vs flag. Returns two lists of
            CorrectionResult.
        WHY: report.py consumes these to build the ReconciliationReport counts.
        INPUTS: discrepancies.
        OUTPUTS: (corrected_results, flagged_results).
        SIDE EFFECTS: none.
        """
        corrected: List[CorrectionResult] = []
        flagged: List[CorrectionResult] = []

        for disc in discrepancies:
            is_financial = disc.field in {"outcome", "odds", "selection_id", "market_id"}
            is_safe_field = disc.field in self.safe_fields
            is_low_severity = disc.severity in ("low", "medium")
            is_entity_missing = disc.field == "__entity__"

            # Never auto-correct financial fields or missing entities.
            if is_financial or is_entity_missing or disc.severity == "high":
                flagged.append(
                    CorrectionResult(
                        discrepancy=disc,
                        corrected=False,
                        reason="high severity or financial field; requires manual review",
                        corrected_value=disc.expected,
                    )
                )
                continue

            # Safe-correctable field with low/medium severity -> auto-correct
            if is_safe_field and is_low_severity:
                corrected.append(
                    CorrectionResult(
                        discrepancy=disc,
                        corrected=True,
                        reason="auto-corrected to expected value",
                        corrected_value=disc.expected,
                    )
                )
                continue

            # Anything else -> flag for manual review
            flagged.append(
                CorrectionResult(
                    discrepancy=disc,
                    corrected=False,
                    reason="not auto-correctable; manual review required",
                    corrected_value=disc.expected,
                )
            )

        return corrected, flagged
