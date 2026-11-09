"""
packages/processing-engine/src/processing_engine/alerts/human_review_queue.py

FILE HEADER
-----------
Business problem this file solves:
    Not all LLM alerts are trustworthy enough to auto-escalate. human_review_queue.py holds a
    review queue: alerts with confidence below a threshold are enqueued for human review,
    while high-confidence alerts auto-escalate. Reviewers can approve or reject queued alerts,
    producing an auditable human-in-the-loop trail required for regulatory compliance.

Where it sits in the flow:
    Support module under alerts/. Imported by processing_engine/__init__.py and the n8n
    alert-engine workflow (which routes low-confidence alerts here). Consumed by ops via the
    review API.

What calls it / what it calls:
    Called by: alert-engine workflow, demo scripts, tests.
    Calls: sports_automation.types (Alert, AlertSeverity), stdlib only.

What breaks if removed:
    No human-in-the-loop; low-confidence alerts either auto-escalate (risk of false pages) or
    are dropped (missed issues), breaking the alert quality story.

Language conventions:
    Python 3.11+. HumanReviewQueue holds an in-memory list of pending reviews.
    enqueue(alert, confidence) -> review_id; get_pending() -> list;
    approve(review_id, reviewer_id) / reject(...) -> bool. Threshold default 0.7.

GAP: the queue is in-memory only; persistence (Postgres/Redis) and a reviewer UI are not
    implemented here. n8n provides the workflow surface; this module is the logic layer.
    See 07_issues_found.md.
"""

import sys
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

# Ensure canonical types are importable (monorepo layout).
_HERE = os.path.dirname(os.path.abspath(__file__))
_CANONICAL_TYPES_PY = os.path.normpath(
    os.path.join(_HERE, "..", "..", "..", "..", "canonical-types", "python")
)
if os.path.isdir(_CANONICAL_TYPES_PY) and _CANONICAL_TYPES_PY not in sys.path:
    sys.path.insert(0, _CANONICAL_TYPES_PY)

from sports_automation.types import Alert, AlertSeverity  # noqa: E402

DEFAULT_REVIEW_THRESHOLD = 0.7


@dataclass
class ReviewItem:
    """One alert awaiting human review.

    WHAT: review_id, alert, confidence, decision, reviewer, timestamps.
    WHY: Auditable record of each human-reviewed alert.
    """
    review_id: str
    alert: Alert
    confidence: float
    decision: Optional[str] = None  # 'approved' | 'rejected' | None
    reviewer: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "review_id": self.review_id,
            "alert": self.alert.model_dump() if hasattr(self.alert, "model_dump")
            else self.alert.dict() if hasattr(self.alert, "dict")
            else dict(self.alert),
            "confidence": self.confidence,
            "decision": self.decision,
            "reviewer": self.reviewer,
            "decided_at": self.decided_at.isoformat() if self.decided_at else None,
            "created_at": self.created_at.isoformat(),
        }


class HumanReviewQueue:
    """In-memory human-review queue for low-confidence alerts.

    WHAT: Holds pending review items. enqueue() adds an alert routed for review;
        get_pending() lists unreviewed items; approve()/reject() record a reviewer's
        decision and remove the item from pending.
    WHY: Provides the human-in-the-loop gate for low-confidence LLM alerts, with an auditable
        approve/reject trail. High-confidence alerts bypass this queue and auto-escalate.
    INPUTS: confidence_threshold (float, default 0.7).
    OUTPUTS: review items and decisions.
    SIDE EFFECTS: mutates internal lists (in-memory).
    FAILURE MODES: approve/reject return False for unknown review_id; never raises.
    ALTERNATIVE: persistent queue (Postgres/Redis) + reviewer UI. Chosen in-memory for a
        dependency-free, testable implementation; n8n provides the workflow surface.
    """

    def __init__(self, confidence_threshold: float = DEFAULT_REVIEW_THRESHOLD):
        """Construct the queue with a confidence threshold.

        WHAT: Stores threshold and initializes empty pending/history lists.
        WHY: Threshold determines which alerts route here vs auto-escalate.
        INPUTS: confidence_threshold (0-1).
        OUTPUTS: None.
        SIDE EFFECTS: none.
        """
        self.confidence_threshold = max(0.0, min(1.0, confidence_threshold))
        self._pending: List[ReviewItem] = []
        self._history: List[ReviewItem] = []

    def should_route_to_review(self, confidence: float) -> bool:
        """Return True if an alert with this confidence should go to human review."""
        return confidence < self.confidence_threshold

    def enqueue(self, alert: Alert, confidence: float) -> str:
        """Enqueue an alert for human review. Returns the review_id.

        WHAT: Creates a ReviewItem and appends it to pending.
        WHY: Low-confidence alerts await a reviewer before escalation.
        INPUTS: alert (Alert), confidence (0-1).
        OUTPUTS: review_id (str).
        SIDE EFFECTS: appends to self._pending.
        """
        review_id = f"review_{uuid.uuid4().hex[:12]}"
        item = ReviewItem(review_id=review_id, alert=alert, confidence=confidence)
        self._pending.append(item)
        return review_id

    def get_pending(self) -> List[Dict[str, Any]]:
        """Return all unreviewed items as dicts."""
        return [item.to_dict() for item in self._pending]

    def get_history(self) -> List[Dict[str, Any]]:
        """Return all decided items as dicts."""
        return [item.to_dict() for item in self._history]

    def approve(self, review_id: str, reviewer: str) -> bool:
        """Approve a pending review. Returns True if the review existed and was approved."""
        for idx, item in enumerate(self._pending):
            if item.review_id == review_id:
                item.decision = "approved"
                item.reviewer = reviewer
                item.decided_at = datetime.utcnow()
                self._history.append(self._pending.pop(idx))
                return True
        return False

    def reject(self, review_id: str, reviewer: str) -> bool:
        """Reject a pending review. Returns True if the review existed and was rejected."""
        for idx, item in enumerate(self._pending):
            if item.review_id == review_id:
                item.decision = "rejected"
                item.reviewer = reviewer
                item.decided_at = datetime.utcnow()
                self._history.append(self._pending.pop(idx))
                return True
        return False

    def route_alert(self, alert: Alert, confidence: float) -> Dict[str, Any]:
        """Decide auto-escalate vs human-review and act accordingly.

        WHAT: If confidence < threshold, enqueue for review; otherwise mark auto-escalated.
            Returns a dict with action ('human_review' | 'auto_escalate'), review_id (if
            human_review), and confidence.
        WHY: Single entry point for the alert engine's human-in-the-loop decision.
        INPUTS: alert (Alert), confidence (0-1).
        OUTPUTS: dict {action, review_id?, confidence, threshold}.
        SIDE EFFECTS: may enqueue into self._pending.
        """
        if self.should_route_to_review(confidence):
            review_id = self.enqueue(alert, confidence)
            return {
                "action": "human_review",
                "review_id": review_id,
                "confidence": confidence,
                "threshold": self.confidence_threshold,
            }
        return {
            "action": "auto_escalate",
            "confidence": confidence,
            "threshold": self.confidence_threshold,
        }
