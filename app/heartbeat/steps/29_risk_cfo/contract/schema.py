"""Typed contract for `risk.cfo`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="risk.cfo",
    implementation_ref="app.heartbeat.steps.29_risk_cfo.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("risk_cfo",),
    safety_notes=(
        "This node preserves the existing `risk.cfo` order and graph halt audit trail."
    ),
)
