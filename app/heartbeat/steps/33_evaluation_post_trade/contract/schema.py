"""Typed contract for `evaluation.post_trade`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="evaluation.post_trade",
    implementation_ref="app.heartbeat.steps.33_evaluation_post_trade.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("evaluation_post_trade",),
    safety_notes=(
        "This node preserves the existing `evaluation.post_trade` order and graph halt audit trail."
    ),
)
