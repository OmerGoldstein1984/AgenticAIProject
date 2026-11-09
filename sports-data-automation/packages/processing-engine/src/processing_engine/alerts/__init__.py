"""
packages/processing-engine/src/processing_engine/alerts/__init__.py

FILE HEADER
-----------
Business problem this file solves:
    Exposes the alerts subpackage public API (LLMClient, generate_alert, ConfidenceScorer,
    HumanReviewQueue) so consumers can generate and route alerts without reaching into
    individual modules.

Where it sits in the flow:
    Leaf package under processing_engine/. Imported by processing_engine/__init__.py and by
    the n8n alert-engine workflow / demo scripts.

What calls it / what it calls:
    Called by: processing_engine.__init__, alert consumers.
    Calls: llm_client, prompt_templates, confidence_scorer, human_review_queue.

What breaks if removed:
    `from processing_engine.alerts import ...` fails.

Language conventions:
    Python 3.11+. Minimal re-export init.
"""

from processing_engine.alerts.llm_client import LLMClient, generate_alert
from processing_engine.alerts.prompt_templates import build_system_prompt, build_user_prompt
from processing_engine.alerts.confidence_scorer import ConfidenceScorer
from processing_engine.alerts.human_review_queue import HumanReviewQueue

__all__ = [
    "LLMClient",
    "generate_alert",
    "build_system_prompt",
    "build_user_prompt",
    "ConfidenceScorer",
    "HumanReviewQueue",
]
