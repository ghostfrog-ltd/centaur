"""Typed contract for `trading212_paper.sync`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="trading212_paper.sync",
    implementation_ref="app.heartbeat.steps.07_trading212_paper_sync.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("trading212_paper_sync",),
    safety_notes=(
        "This node preserves the existing `trading212_paper.sync` order and graph halt audit trail."
    ),
)
