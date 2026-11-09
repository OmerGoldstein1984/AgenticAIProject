"""
packages/processing-engine/src/processing_engine/__init__.py

FILE HEADER
-----------
Business problem this file solves:
    Marks the processing_engine directory as a Python package and exposes the public API
    (settlement rule engine, LLM alert client, reconciliation job) so consumers (n8n nodes,
    demo scripts, tests) can `from processing_engine import ...` without reaching into
    submodules.

Where it sits in the flow:
    Top-level package init for packages/processing-engine/. Imported by anything that uses
    the processing engine as a library.

What calls it / what it calls:
    Called by: n8n custom nodes, scripts/seed_demo_data.py, tests.
    Calls: submodule __init__ files (settlement, alerts, reconciliation).

What breaks if removed:
    `import processing_engine` fails; the package is not importable as a namespace.

Language conventions:
    Python 3.11+. Keep this file minimal — only re-export public symbols.
"""

from processing_engine.settlement.models import SettlementResult, SettlementOutcome
from processing_engine.settlement.rule_engine import SettlementRuleEngine
from processing_engine.settlement.dsl_parser import parse_rule_set
from processing_engine.alerts.llm_client import LLMClient, generate_alert
from processing_engine.alerts.confidence_scorer import ConfidenceScorer
from processing_engine.alerts.human_review_queue import HumanReviewQueue
from processing_engine.reconciliation.checksum import compute_checksum
from processing_engine.reconciliation.drift_detector import DriftDetector
from processing_engine.reconciliation.auto_corrector import AutoCorrector
from processing_engine.reconciliation.report import build_report

__all__ = [
    # settlement
    "SettlementResult",
    "SettlementOutcome",
    "SettlementRuleEngine",
    "parse_rule_set",
    # alerts
    "LLMClient",
    "generate_alert",
    "ConfidenceScorer",
    "HumanReviewQueue",
    # reconciliation
    "compute_checksum",
    "DriftDetector",
    "AutoCorrector",
    "build_report",
]
