"""Typed contract for `market.latest_bars`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="market.latest_bars",
    implementation_ref="app.heartbeat.steps.16_market_latest_bars.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("market_latest_bars",),
    safety_notes=(
        "This node preserves the existing `market.latest_bars` order and graph halt audit trail."
    ),
)
