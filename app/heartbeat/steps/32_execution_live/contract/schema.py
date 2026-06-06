"""Typed contract for `execution.live`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="execution.live",
    implementation_ref="app.heartbeat.steps.32_execution_live.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("execution_live",),
    safety_notes=(
        "This node preserves the existing `execution.live` order and graph halt audit trail."
    ),
)
