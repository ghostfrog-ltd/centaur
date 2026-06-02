"""Typed contract for `trading212.latest_bars`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="trading212.latest_bars",
    implementation_ref="app.heartbeat.steps.17_trading212_latest_bars.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("trading212_latest_bars",),
    safety_notes=(
        "This node preserves the existing `trading212.latest_bars` order and graph halt audit trail."
    ),
)
