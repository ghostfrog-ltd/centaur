"""Heartbeat step implementation owned by `01_control_heartbeat`."""

from __future__ import annotations

from app.framework.runtime.autonomous_learning import run_autonomous_learning_cycle
from app.heartbeat.support import (
    PipelineResult,
    TickContext,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `control.heartbeat` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    heartbeat = {
        "status": "alive",
        "tick_id": context.tick_id,
        "timezone": context.started_at.astimezone().tzname(),
    }
    context.state["heartbeat"] = heartbeat
    run_autonomous_learning_cycle(context)
    return heartbeat
