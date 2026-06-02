"""Typed contract for `fx.gbp_reference`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="fx.gbp_reference",
    implementation_ref="app.heartbeat.steps.14_fx_gbp_reference.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("fx_gbp_reference",),
    safety_notes=(
        "This node preserves the existing `fx.gbp_reference` order and graph halt audit trail."
    ),
)
