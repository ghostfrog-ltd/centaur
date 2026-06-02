"""Typed contract for `strategy.signals`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="strategy.signals",
    implementation_ref="app.heartbeat.steps.25_strategy_signals.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("strategy_signals",),
    safety_notes=(
        "This node preserves the existing `strategy.signals` order and graph halt audit trail."
    ),
)
