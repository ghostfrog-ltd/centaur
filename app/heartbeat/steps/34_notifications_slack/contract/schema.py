"""Typed contract for `notifications.slack`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepContract


CONTRACT = HeartbeatStepContract(
    name="notifications.slack",
    implementation_ref="app.heartbeat.steps.34_notifications_slack.implementation.main::run_implementation",
    reads_state=(),
    writes_state=("notifications_slack",),
    safety_notes=(
        "This node preserves the existing `notifications.slack` order and graph halt audit trail."
    ),
)
