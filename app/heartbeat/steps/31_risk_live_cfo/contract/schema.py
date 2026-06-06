"""Typed contract for `risk.live_cfo`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="risk.live_cfo",
    implementation_ref="app.heartbeat.steps.31_risk_live_cfo.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("live_risk_cfo",),
    safety_notes=(
        "This node preserves the existing `risk.live_cfo` order and graph halt audit trail."
    ),
)
