"""Typed contract for `execution.live_exits`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="execution.live_exits",
    implementation_ref="app.heartbeat.steps.20_execution_live_exits.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("execution_live_exits",),
    safety_notes=(
        "This node preserves the existing `execution.live_exits` order and graph halt audit trail."
    ),
)
