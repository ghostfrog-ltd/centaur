"""Typed contract for `maintenance.live_stale_orders`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="maintenance.live_stale_orders",
    implementation_ref="app.heartbeat.steps.12_maintenance_live_stale_orders.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("maintenance_live_stale_orders",),
    safety_notes=(
        "This node preserves the existing `maintenance.live_stale_orders` order and graph halt audit trail."
    ),
)
