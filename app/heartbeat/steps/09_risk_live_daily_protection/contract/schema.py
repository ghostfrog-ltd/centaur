"""Typed contract for `risk.live_daily_protection`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="risk.live_daily_protection",
    implementation_ref="app.heartbeat.steps.09_risk_live_daily_protection.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("risk_live_daily_protection",),
    safety_notes=(
        "This node preserves the existing `risk.live_daily_protection` order and graph halt audit trail."
    ),
)
