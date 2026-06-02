"""Typed contract for `market.gate`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="market.gate",
    implementation_ref="app.heartbeat.steps.13_market_gate.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("market_gate",),
    safety_notes=(
        "This node preserves the existing `market.gate` order and graph halt audit trail."
    ),
)
