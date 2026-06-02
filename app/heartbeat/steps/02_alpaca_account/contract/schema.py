"""Typed contract for `alpaca.account`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="alpaca.account",
    implementation_ref="app.heartbeat.steps.02_alpaca_account.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("alpaca_account",),
    safety_notes=(
        "This node preserves the existing `alpaca.account` order and graph halt audit trail."
    ),
)
