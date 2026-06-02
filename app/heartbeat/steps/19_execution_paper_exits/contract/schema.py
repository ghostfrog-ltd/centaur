"""Typed contract for `execution.paper_exits`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="execution.paper_exits",
    implementation_ref="app.heartbeat.steps.19_execution_paper_exits.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("execution_paper_exits",),
    safety_notes=(
        "This node preserves the existing `execution.paper_exits` order and graph halt audit trail."
    ),
)
