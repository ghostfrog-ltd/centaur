"""Typed contract for `market.scan`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="market.scan",
    implementation_ref="app.heartbeat.steps.23_market_scan.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("market_scan",),
    safety_notes=(
        "This node preserves the existing `market.scan` order and graph halt audit trail."
    ),
)
