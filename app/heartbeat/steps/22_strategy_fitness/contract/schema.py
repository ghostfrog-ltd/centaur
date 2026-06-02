"""Typed contract for `strategy.fitness`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="strategy.fitness",
    implementation_ref="app.heartbeat.steps.22_strategy_fitness.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("strategy_fitness",),
    safety_notes=(
        "This node preserves the existing `strategy.fitness` order and graph halt audit trail."
    ),
)
