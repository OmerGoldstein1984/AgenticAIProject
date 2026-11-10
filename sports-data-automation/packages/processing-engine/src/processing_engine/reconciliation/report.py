"""
packages/processing-engine/src/processing_engine/reconciliation/report.py

FILE HEADER
-----------
Business problem this file solves:
    The daily reconciliation job must produce a single ReconciliationReport summarizing total
    events, matched count, discrepancies, auto-corrected count, and manual-review count.
    report.py assembles this report from a DriftDetector discrepancy list and an
    AutoCorrector correction result.

Where it sits in the flow:
    Core reconciliation module. Imported by processing_engine/__init__.py and the n8n
    reconciliation workflow. Consumed by dashboards/alerts (high discrepancy count triggers
    a critical alert per PROJECT_SPEC).

What calls it / what it calls:
    Called by: reconciliation workflow, demo scripts, tests.
    Calls: sports_automation.types (ReconciliationReport, Discrepancy), datetime.

What breaks if removed:
    No reconciliation report; the daily job cannot summarize drift or alert on high
    discrepancy counts, breaking the reconciliation-drift KPI.

Language conventions:
    Python 3.11+. build_report(date, total_events, matched, discrepancies, auto_corrected,
    manual_review_required) -> ReconciliationReport. Pure constructor with validation.
"""

import sys
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

# Ensure canonical types are importable (monorepo layout).
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANONICAL_TYPES_PY = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", "canonical-types", "python")
)
if os.path.isdir(_CANONICAL_TYPES_PY) and _CANONICAL_TYPES_PY not in sys.path:
    sys.path.insert(0, _CANONICAL_TYPES_PY)

from sports_automation.types import ReconciliationReport, Discrepancy  # noqa: E402


def build_report(
    date: str,
    total_events: int,
    matched: int,
    discrepancies: List[Discrepancy],
    auto_corrected: int,
    manual_review_required: int,
    trace_id: Optional[str] = None,
) -> ReconciliationReport:
    """Build a ReconciliationReport for one date.

    WHAT: Constructs a ReconciliationReport with the provided counts and discrepancy list,
        validating that counts are non-negative and that auto_corrected + manual_review
        <= len(discrepancies) + matched (sanity). trace_id is carried into the report for
        distributed tracing.
    WHY: A single, validated report is the reconciliation job's output; dashboards and alerts
        read it to surface drift to ops. trace_id correlates the reconciliation run with the
        ingestion->n8n->processing-engine trace.
    INPUTS: date (ISO date string), total_events, matched, discrepancies,
        auto_corrected, manual_review_required, trace_id (optional str).
    OUTPUTS: ReconciliationReport.
    SIDE EFFECTS: none.
    FAILURE MODES: raises ValueError on negative counts or inconsistent totals.
    """
    if total_events < 0:
        raise ValueError("total_events must be non-negative")
    if matched < 0:
        raise ValueError("matched must be non-negative")
    if matched > total_events:
        raise ValueError("matched cannot exceed total_events")
    if auto_corrected < 0:
        raise ValueError("auto_corrected must be non-negative")
    if manual_review_required < 0:
        raise ValueError("manual_review_required must be non-negative")

    return ReconciliationReport(
        date=date,
        total_events=total_events,
        matched=matched,
        discrepancies=list(discrepancies),
        auto_corrected=auto_corrected,
        manual_review_required=manual_review_required,
        trace_id=trace_id,
    )


def summarize(report: ReconciliationReport) -> Dict[str, Any]:
    """Produce a plain-text/dict summary of a ReconciliationReport for logging/dashboards.

    WHAT: Returns a dict with key metrics: match rate, discrepancy count, auto-corrected
        rate, manual-review count, and whether a critical alert is warranted
        (discrepancy count > 100 per PROJECT_SPEC).
    WHY: Dashboards and alert rules read this summary instead of the full Pydantic model.
    INPUTS: report (ReconciliationReport).
    OUTPUTS: dict summary.
    """
    total = report.total_events or 1
    discrepancy_count = len(report.discrepancies)
    high_count = sum(1 for d in report.discrepancies if d.severity == "high")
    return {
        "date": report.date,
        "total_events": report.total_events,
        "matched": report.matched,
        "match_rate": round(report.matched / total, 4),
        "discrepancy_count": discrepancy_count,
        "high_severity_count": high_count,
        "auto_corrected": report.auto_corrected,
        "manual_review_required": report.manual_review_required,
        "critical_alert": discrepancy_count > 100,
    }
