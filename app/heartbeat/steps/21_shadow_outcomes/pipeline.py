"""Heartbeat step pipeline: `shadow.outcomes`."""

from __future__ import annotations

from app.heartbeat.contracts import HeartbeatStepDefinition
from app.framework.runtime.models import TickContext

from .contract import CONTRACT
from .implementation import run_implementation


def run(context: TickContext) -> dict[str, object]:
    """Execute this heartbeat step pipeline."""

    return run_implementation(context)


STEP = HeartbeatStepDefinition(contract=CONTRACT, runner=run)

__all__ = ["STEP", "run"]
