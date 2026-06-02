"""Heartbeat step implementation owned by `02_alpaca_account`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    get_broker_adapter,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `alpaca.account` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    adapter = get_broker_adapter(context, "alpaca_paper")
    raw_account = {
        **adapter.get_account(context),
        "broker_id": adapter.broker_id,
    }
    summary = adapter.summarize_account(raw_account)
    payload = {
        "broker_id": adapter.broker_id,
        "summary": summary,
        "raw": raw_account,
    }
    context.state["alpaca_account"] = payload
    context.state["execution_account"] = payload
    broker_accounts = context.state.setdefault("broker_accounts", {})
    if isinstance(broker_accounts, dict):
        broker_accounts[adapter.broker_id] = payload
    return {
        "broker_id": adapter.broker_id,
        **summary,
    }
