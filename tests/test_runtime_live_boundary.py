from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

import app.engine.pipelines as pipelines
from app.runtime.models import TickContext


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

    def test_trading212_paper_sync_skips_without_credentials(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(trading212_paper_api_configured=False),
            usage_ledger=SimpleNamespace(),
        )
        original = pipelines.get_broker_adapter

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("Trading 212 adapter should not be called")

        pipelines.get_broker_adapter = fail_if_called
        try:
            result = pipelines.trading212_paper_sync(context)
        finally:
            pipelines.get_broker_adapter = original

        self.assertEqual(result["mode"], "skipped")
        self.assertEqual(result["reason"], "trading212_paper_credentials_missing")
        self.assertEqual(context.state["trading212_paper_positions"]["raw"], [])

    def test_trading212_paper_sync_records_read_only_snapshot(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(trading212_paper_api_configured=True),
            usage_ledger=SimpleNamespace(),
        )
        snapshots = []
        context.usage_ledger.record_broker_account_snapshot = (
            lambda **kwargs: snapshots.append(kwargs)
        )
        context.usage_ledger.record_paper_trade_orders = lambda **_kwargs: 0

        class FakeTrading212Adapter:
            broker_id = "trading212_paper"

            def get_account(self, _context):
                return {"free": 5000.0, "total": 5000.0}

            def summarize_account(self, _raw_account):
                return {
                    "status": "DEMO",
                    "currency": "GBP",
                    "cash": 5000.0,
                    "equity": 5000.0,
                    "buying_power": 5000.0,
                    "portfolio_value": 5000.0,
                }

            def get_positions(self, _context):
                return []

            def summarize_positions(self, _raw_positions):
                return {"open_positions": 0, "symbols": []}

            def get_orders(self, _context, **_kwargs):
                return []

            def summarize_orders(self, _raw_orders):
                return {"open_orders": 0, "open_order_symbols": []}

        original = pipelines.get_broker_adapter
        pipelines.get_broker_adapter = lambda _context, broker_id: FakeTrading212Adapter()
        try:
            result = pipelines.trading212_paper_sync(context)
        finally:
            pipelines.get_broker_adapter = original

        self.assertEqual(result["mode"], "synced")
        self.assertEqual(result["broker_id"], "trading212_paper")
        self.assertEqual(result["equity"], 5000.0)
        self.assertEqual(snapshots[0]["broker_id"], "trading212_paper")
        self.assertIn("trading212_paper", context.state["broker_accounts"])

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

    def test_live_equity_entry_blocks_when_alpaca_pdt_equity_is_too_small(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(
                live_execution_equity_only=False,
                live_execution_require_market_open=True,
                live_execution_equity_broker_id="alpaca_live",
                live_execution_crypto_broker_id="alpaca_live",
                live_execution_default_notional_usd=10.0,
            ),
            usage_ledger=SimpleNamespace(),
            state={
                "alpaca_live_account": {
                    "summary": {"equity": 133.39},
                    "raw": {"last_equity": "133.12", "equity": "133.39"},
                }
            },
        )
        proposal = {
            "proposal_id": "proposal-1",
            "symbol": "QCOM",
            "asset_class": "equity",
            "direction": "long",
            "strategy_id": "mean_reversion.snapback",
            "entry_price": 100.0,
            "stop_loss_price": 98.0,
            "target_price": 104.0,
        }
        original = pipelines.get_execution_adapter

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("PDT guard should block before adapter lookup")

        pipelines.get_execution_adapter = fail_if_called
        try:
            approval, rejection = pipelines._build_live_trade_approval(
                context=context,
                proposal=proposal,
                tick_id="test",
                config=context.config,
                market_gate={"market_open": True, "crypto_scan_ready": True},
                position_symbols=set(),
                open_order_symbols=set(),
            )
        finally:
            pipelines.get_execution_adapter = original

        self.assertIsNone(approval)
        self.assertIsNotNone(rejection)
        self.assertEqual(rejection["reason"], "pdt_equity_entry_blocked_live")
        self.assertEqual(rejection["broker_id"], "alpaca_live")

    def test_live_pdt_guard_does_not_block_crypto(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(),
            usage_ledger=SimpleNamespace(),
            state={
                "alpaca_live_account": {
                    "summary": {"equity": 133.39},
                    "raw": {"last_equity": "133.12"},
                }
            },
        )

        self.assertIsNone(
            pipelines._live_equity_pdt_entry_rejection(
                context=context,
                broker_id="alpaca_live",
                asset_class="crypto",
            )
        )

    def test_live_pdt_guard_allows_equity_when_basis_is_above_threshold(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(),
            usage_ledger=SimpleNamespace(),
            state={
                "alpaca_live_account": {
                    "summary": {"equity": 25010.0},
                    "raw": {"last_equity": "25010.00"},
                }
            },
        )

        self.assertIsNone(
            pipelines._live_equity_pdt_entry_rejection(
                context=context,
                broker_id="alpaca_live",
                asset_class="equity",
            )
        )


if __name__ == "__main__":
    unittest.main()
