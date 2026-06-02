"""Typed contract for `shadow.outcomes`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="shadow.outcomes",
    implementation_ref="app.heartbeat.steps.21_shadow_outcomes.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("shadow_outcomes",),
    safety_notes=(
        "This node preserves the existing `shadow.outcomes` order and graph halt audit trail."
    ),
)
