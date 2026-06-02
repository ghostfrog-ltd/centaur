"""Typed contract for `risk.trailing_drawdown_observer`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="risk.trailing_drawdown_observer",
    implementation_ref="app.heartbeat.steps.10_risk_trailing_drawdown_observer.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("risk_trailing_drawdown_observer",),
    safety_notes=(
        "This node preserves the existing `risk.trailing_drawdown_observer` order and graph halt audit trail."
    ),
)
