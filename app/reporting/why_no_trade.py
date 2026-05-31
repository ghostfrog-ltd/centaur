"""Why-no-trade evidence facade.

The current broad evidence report includes the trade-funnel surfaces while the
dedicated dashboard model continues to live in `app.reporting.status`.
"""

from app.reporting.evidence_report import EvidenceReport

__all__ = ["EvidenceReport"]
