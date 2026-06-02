"""Typed contract for `risk.daily_protection`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="risk.daily_protection",
    implementation_ref="app.heartbeat.steps.08_risk_daily_protection.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("risk_daily_protection",),
    safety_notes=(
        "This node preserves the existing `risk.daily_protection` order and graph halt audit trail."
    ),
)
