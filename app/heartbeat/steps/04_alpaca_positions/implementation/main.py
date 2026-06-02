"""Heartbeat step implementation owned by `04_alpaca_positions`."""

from __future__ import annotations

from app.heartbeat.support import (
    PipelineResult,
    TickContext,
    get_broker_adapter,
)


def run_implementation(context: TickContext) -> PipelineResult:
    """Run the `alpaca.positions` heartbeat step.

    This implementation is owned by this step folder. It mutates the shared
    `TickContext` only for this point in the ordered LangGraph heartbeat, and
    its state reads/writes are documented in `contract/schema.py` for audit.
    """
    adapter = get_broker_adapter(context, "alpaca_paper")
    raw_positions = [
        {
            **position,
            "broker_id": adapter.broker_id,
        }
        for position in adapter.get_positions(context)
    ]
    summary = adapter.summarize_positions(raw_positions)
    payload = {
        "broker_id": adapter.broker_id,
        "summary": summary,
        "raw": raw_positions,
    }
    context.state["alpaca_positions"] = payload
    context.state["execution_positions"] = payload
    snapshot_saved = 0
    account_payload = context.state.get("alpaca_account")
    if isinstance(account_payload, dict):
        account_summary = account_payload.get("summary")
        raw_account = account_payload.get("raw")
        if isinstance(account_summary, dict) and isinstance(raw_account, dict):
            context.usage_ledger.record_broker_account_snapshot(
                tick_id=context.tick_id,
                captured_at=context.started_at,
                broker_id=adapter.broker_id,
                summary=account_summary,
                raw_account=raw_account,
                positions=raw_positions,
            )
            snapshot_saved = 1
    return {
        "broker_id": adapter.broker_id,
        "account_snapshot_saved": snapshot_saved,
        **summary,
    }
