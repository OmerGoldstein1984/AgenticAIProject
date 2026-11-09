"""
packages/processing-engine/src/processing_engine/reconciliation/__init__.py

FILE HEADER
-----------
Business problem this file solves:
    Exposes the reconciliation subpackage public API (compute_checksum, DriftDetector,
    AutoCorrector, build_report) so consumers can run drift detection and build reports
    without reaching into individual modules.

Where it sits in the flow:
    Leaf package under processing_engine/. Imported by processing_engine/__init__.py and by
    the n8n reconciliation workflow / demo scripts.

What calls it / what it calls:
    Called by: processing_engine.__init__, reconciliation consumers.
    Calls: checksum, drift_detector, auto_corrector, report.

What breaks if removed:
    `from processing_engine.reconciliation import ...` fails.

Language conventions:
    Python 3.11+. Minimal re-export init.
"""

from processing_engine.reconciliation.checksum import compute_checksum
from processing_engine.reconciliation.drift_detector import DriftDetector
from processing_engine.reconciliation.auto_corrector import AutoCorrector
from processing_engine.reconciliation.report import build_report

__all__ = ["compute_checksum", "DriftDetector", "AutoCorrector", "build_report"]
