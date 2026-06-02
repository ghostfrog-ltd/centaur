"""Typed contract for `alpaca.orders`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="alpaca.orders",
    implementation_ref="app.heartbeat.steps.05_alpaca_orders.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("alpaca_orders",),
    safety_notes=(
        "This node preserves the existing `alpaca.orders` order and graph halt audit trail."
    ),
)
