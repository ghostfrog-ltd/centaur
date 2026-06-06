"""Typed contract for `execution.paper`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="execution.paper",
    implementation_ref="app.heartbeat.steps.30_execution_paper.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("execution_paper",),
    safety_notes=(
        "This node preserves the existing `execution.paper` order and graph halt audit trail."
    ),
)
