"""Typed contract for `risk.trading212_paper_daily_protection`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="risk.trading212_paper_daily_protection",
    implementation_ref="app.heartbeat.steps.15_risk_trading212_paper_daily_protection.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("risk_trading212_paper_daily_protection",),
    safety_notes=(
        "This node preserves the existing `risk.trading212_paper_daily_protection` order and graph halt audit trail."
    ),
)
