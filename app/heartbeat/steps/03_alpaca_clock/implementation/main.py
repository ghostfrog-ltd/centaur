"""Heartbeat step implementation owned by `03_alpaca_clock`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    get_broker_adapter,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `alpaca.clock` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    adapter = get_broker_adapter(context, "alpaca_paper")
    raw_clock = {
        **adapter.get_clock(context),
        "broker_id": adapter.broker_id,
    }
    summary = adapter.summarize_clock(raw_clock)
    payload = {
        "broker_id": adapter.broker_id,
        "summary": summary,
        "raw": raw_clock,
    }
    context.state["alpaca_clock"] = payload
    context.state["execution_clock"] = payload
    return {
        "broker_id": adapter.broker_id,
        **summary,
    }
