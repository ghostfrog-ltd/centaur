"""Typed contract for `shadow.proposals`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="shadow.proposals",
    implementation_ref="app.heartbeat.steps.27_shadow_proposals.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("shadow_proposals",),
    safety_notes=(
        "This node preserves the existing `shadow.proposals` order and graph halt audit trail."
    ),
)
