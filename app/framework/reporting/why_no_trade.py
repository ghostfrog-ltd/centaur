"""Why-no-trade evidence facade.

The current broad evidence report includes the trade-funnel surfaces while the
dedicated dashboard model continues to live in `app.framework.reporting.status`.
"""

from app.framework.reporting.evidence_report import EvidenceReport

__all__ = ["EvidenceReport"]
