"""Typed contract for `alpaca_live.sync`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="alpaca_live.sync",
    implementation_ref="app.heartbeat.steps.06_alpaca_live_sync.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("alpaca_live_sync",),
    safety_notes=(
        "This node preserves the existing `alpaca_live.sync` order and graph halt audit trail."
    ),
)
