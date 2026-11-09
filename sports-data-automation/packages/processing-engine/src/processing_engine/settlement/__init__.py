"""
packages/processing-engine/src/processing_engine/settlement/__init__.py

FILE HEADER
-----------
Business problem this file solves:
    Exposes the settlement subpackage public API (SettlementResult, SettlementOutcome,
    SettlementRuleEngine, parse_rule_set) so consumers can import settlement logic without
    reaching into individual modules.

Where it sits in the flow:
    Leaf package under processing_engine/. Imported by processing_engine/__init__.py and by
    anything evaluating settlement rules (n8n settlement-worker, demo scripts, tests).

What calls it / what it calls:
    Called by: processing_engine.__init__, settlement rule consumers.
    Calls: models, rule_engine, dsl_parser.

What breaks if removed:
    `from processing_engine.settlement import ...` fails.

Language conventions:
    Python 3.11+. Minimal re-export init.
"""

from processing_engine.settlement.models import SettlementResult, SettlementOutcome
from processing_engine.settlement.rule_engine import SettlementRuleEngine
from processing_engine.settlement.dsl_parser import parse_rule_set

__all__ = ["SettlementResult", "SettlementOutcome", "SettlementRuleEngine", "parse_rule_set"]
