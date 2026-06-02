"""Typed contract for `crypto.latest_bars`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="crypto.latest_bars",
    implementation_ref="app.heartbeat.steps.18_crypto_latest_bars.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("crypto_latest_bars",),
    safety_notes=(
        "This node preserves the existing `crypto.latest_bars` order and graph halt audit trail."
    ),
)
