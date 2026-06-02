"""Typed contract for `context.enrichment`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="context.enrichment",
    implementation_ref="app.heartbeat.steps.24_context_enrichment.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("context_enrichment",),
    safety_notes=(
        "This node preserves the existing `context.enrichment` order and graph halt audit trail."
    ),
)
