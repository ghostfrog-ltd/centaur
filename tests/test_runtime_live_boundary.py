from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

import centaur.pipelines as pipelines
from centaur.models import TickContext


class RuntimeLiveBoundaryTests(unittest.TestCase):
    def test_paper_mode_does_not_touch_live_broker_sync(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(
                centaur_mode="paper",
                alpaca_live_api_configured=True,
            ),
            usage_ledger=SimpleNamespace(),
        )
        original = pipelines.get_broker_adapter

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("live broker adapter should not be called")

        pipelines.get_broker_adapter = fail_if_called
        try:
            result = pipelines.alpaca_live_sync(context)
        finally:
            pipelines.get_broker_adapter = original

        self.assertEqual(result["reason"], "runtime_mode_not_live")
        self.assertEqual(context.state["alpaca_live_positions"]["raw"], [])
        self.assertEqual(context.state["alpaca_live_orders"]["raw"], [])

    def test_live_dry_does_not_submit_live_orders(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(centaur_mode="live_dry"),
            usage_ledger=SimpleNamespace(),
            state={
                "live_risk_cfo": {
                    "approved_order_requests": [
                        {
                            "broker_id": "alpaca_live",
                            "order_request": {"symbol": "AAPL"},
                        }
                    ]
                }
            },
        )
        original = pipelines.get_broker_adapter

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("live order adapter should not be called")

        pipelines.get_broker_adapter = fail_if_called
        try:
            result = pipelines.execution_live(context)
        finally:
            pipelines.get_broker_adapter = original

        self.assertEqual(result["mode"], "live_dry")
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual(result["intended_orders"], 1)

    def test_live_dry_stale_reaper_records_cancel_intent(self) -> None:
        started_at = datetime.now().astimezone()
        context = TickContext(
            tick_id="test",
            started_at=started_at,
            config=SimpleNamespace(
                centaur_mode="live_dry",
                centaur_environment="live",
                live_execution_enabled=True,
                live_execution_kill_switch=False,
                live_execution_activation_ack="LIVE_TRADING_APPROVED",
                live_execution_equity_broker_id="alpaca_live",
                live_execution_crypto_broker_id="alpaca_live",
                live_execution_allowed_strategies=("mean_reversion.snapback",),
                live_execution_default_notional_usd=10.0,
                paper_execution_stale_order_minutes=5,
            ),
            usage_ledger=SimpleNamespace(),
            state={
                "alpaca_live_orders": {
                    "summary": {"open_orders": 1, "open_order_symbols": ["AAPL"]},
                    "raw": [
                        {
                            "id": "live-order-1",
                            "symbol": "AAPL",
                            "asset_class": "equity",
                            "side": "buy",
                            "type": "limit",
                            "status": "new",
                            "filled_qty": "0",
                            "submitted_at": (
                                started_at - timedelta(minutes=10)
                            ).isoformat(),
                        }
                    ],
                }
            },
        )
        original = pipelines.get_broker_adapter

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("live adapter should not be called in live_dry")

        pipelines.get_broker_adapter = fail_if_called
        try:
            result = pipelines.live_stale_order_reaper(context)
        finally:
            pipelines.get_broker_adapter = original

        self.assertEqual(result["mode"], "live_dry")
        self.assertEqual(result["orders_canceled"], 0)
        self.assertEqual(result["orders_intended"], 1)
        self.assertEqual(
            context.state["execution_router_intents"][0]["action"],
            "cancel",
        )


if __name__ == "__main__":
    unittest.main()
