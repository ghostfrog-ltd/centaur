"""Typed contract for `alpaca.clock`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="alpaca.clock",
    implementation_ref="app.heartbeat.steps.03_alpaca_clock.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("alpaca_clock",),
    safety_notes=(
        "This node preserves the existing `alpaca.clock` order and graph halt audit trail."
    ),
)
