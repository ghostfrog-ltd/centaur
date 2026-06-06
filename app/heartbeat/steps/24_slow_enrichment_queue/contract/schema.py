"""Typed contract for `slow.enrichment_queue`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="slow.enrichment_queue",
    implementation_ref=(
        "app.heartbeat.steps.24_slow_enrichment_queue.implementation.main::"
        "run_implementation"
    ),
    reads_state=("market_scan",),
    writes_state=("slow_enrichment_queue",),
    safety_notes=(
        "Advisory-only queue step. It can enqueue non-selected ranked candidates "
        "for slow research enrichment, but slow queue output has no order authority."
    ),
)
