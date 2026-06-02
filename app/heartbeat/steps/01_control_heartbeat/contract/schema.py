"""Typed contract for `control.heartbeat`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="control.heartbeat",
    implementation_ref="app.heartbeat.steps.01_control_heartbeat.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("control_heartbeat",),
    safety_notes=(
        "This node preserves the existing `control.heartbeat` order and graph halt audit trail."
    ),
)
