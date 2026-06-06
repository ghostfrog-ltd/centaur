"""Typed contract for `analysis.gemini`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="analysis.gemini",
    implementation_ref="app.heartbeat.steps.27_analysis_gemini.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("analysis_gemini",),
    safety_notes=(
        "This node preserves the existing `analysis.gemini` order and graph halt audit trail."
    ),
)
