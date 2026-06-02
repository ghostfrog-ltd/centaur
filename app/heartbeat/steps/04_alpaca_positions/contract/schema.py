"""Typed contract for `alpaca.positions`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="alpaca.positions",
    implementation_ref="app.heartbeat.steps.04_alpaca_positions.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("alpaca_positions",),
    safety_notes=(
        "This node preserves the existing `alpaca.positions` order and graph halt audit trail."
    ),
)
