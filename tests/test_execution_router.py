from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
import unittest

from centaur.execution_router import ExecutionRouter
from centaur.models import TickContext


class ExecutionRouterTests(unittest.TestCase):
    def _context(self, *, mode: str = "paper", environment: str = "paper") -> TickContext:
        return TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(
                centaur_mode=mode,
                centaur_environment=environment,
                live_execution_enabled=True,
                live_execution_kill_switch=False,
                live_execution_activation_ack="LIVE_TRADING_APPROVED",
                live_execution_equity_broker_id="alpaca_live",
                live_execution_crypto_broker_id="alpaca_live",
                live_execution_allowed_strategies=("mean_reversion.snapback",),
                live_execution_default_notional_usd=10.0,
                live_execution_max_open_positions=10,
            ),
            usage_ledger=SimpleNamespace(),
            state={
                "alpaca_live_account": {
                    "broker_id": "alpaca_live",
                    "summary": {
                        "status": "ACTIVE",
                        "trading_blocked": False,
                        "account_blocked": False,
                        "trade_suspended_by_user": False,
                    },
                    "raw": {},
                },
                "alpaca_live_positions": {
                    "broker_id": "alpaca_live",
                    "summary": {"open_positions": 0, "symbols": []},
                    "raw": [],
                },
                "alpaca_live_orders": {
                    "broker_id": "alpaca_live",
                    "summary": {"open_orders": 0, "open_order_symbols": []},
                    "raw": [],
                },
                "market_data_latest_bars": {
                    "raw": {
                        "AAPL": {
                            "t": datetime.now().astimezone().isoformat(),
                            "c": 100.0,
                        }
                    }
                },
                "crypto_data_latest_bars": {"raw": {}},
            },
        )

    def test_paper_lane_submits_through_adapter(self) -> None:
        calls = []

        class FakeAdapter:
            def submit_order(self, context, *, order_request):
                calls.append((context.tick_id, order_request))
                return {"id": "order-1", "symbol": order_request["symbol"]}

        router = ExecutionRouter(adapter_factory=lambda _context, _broker_id: FakeAdapter())
        result = router.route_entry_approval(
            context=self._context(),
            approval={
                "broker_id": "alpaca_paper",
                "order_request": {"symbol": "AAPL"},
            },
            lane="paper",
        )

        self.assertTrue(result.submitted)
        self.assertEqual(result.order["id"], "order-1")
        self.assertEqual(len(calls), 1)

    def test_live_dry_records_intent_without_adapter_call(self) -> None:
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("adapter should not be called in live_dry")

        context = self._context(mode="live_dry", environment="live")
        persisted = []
        context.usage_ledger.record_execution_router_intent = lambda **kwargs: persisted.append(kwargs)
        router = ExecutionRouter(adapter_factory=fail_if_called)
        result = router.route_entry_approval(
            context=context,
            approval={
                "broker_id": "alpaca_live",
                "order_request": {"symbol": "AAPL"},
            },
            lane="live",
        )

        self.assertFalse(result.submitted)
        self.assertEqual(result.status, "live_dry_intent")
        self.assertEqual(result.intended_order["symbol"], "AAPL")
        self.assertEqual(context.state["execution_router_intents"][0]["action"], "entry")
        self.assertEqual(persisted[0]["mode"], "live_dry")
        self.assertEqual(persisted[0]["lane"], "live")
        self.assertEqual(persisted[0]["intended_order"]["symbol"], "AAPL")

    def test_live_guard_blocks_live_submission_before_adapter(self) -> None:
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("adapter should not be called when guard blocks")

        context = self._context(mode="live", environment="live")
        context.config.live_execution_kill_switch = True
        router = ExecutionRouter(adapter_factory=fail_if_called)
        result = router.route_entry_approval(
            context=context,
            approval={
                "broker_id": "alpaca_live",
                "strategy_id": "mean_reversion.snapback",
                "notional_usd": 10.0,
                "order_request": {"symbol": "AAPL"},
            },
            lane="live",
        )

        self.assertFalse(result.submitted)
        self.assertEqual(result.error, "live_kill_switch_on")

    def test_live_guard_allows_valid_live_submission(self) -> None:
        class FakeAdapter:
            def submit_order(self, context, *, order_request):
                return {"id": "live-order-1", "symbol": order_request["symbol"]}

        router = ExecutionRouter(adapter_factory=lambda _context, _broker_id: FakeAdapter())
        result = router.route_entry_approval(
            context=self._context(mode="live", environment="live"),
            approval={
                "broker_id": "alpaca_live",
                "strategy_id": "mean_reversion.snapback",
                "notional_usd": 10.0,
                "order_request": {"symbol": "AAPL"},
            },
            lane="live",
        )

        self.assertTrue(result.submitted)
        self.assertEqual(result.order["id"], "live-order-1")

    def test_live_guard_rejects_explicit_non_broker_venue_symbol(self) -> None:
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("adapter should not be called when instrument guard blocks")

        router = ExecutionRouter(adapter_factory=fail_if_called)
        result = router.route_entry_approval(
            context=self._context(mode="live", environment="live"),
            approval={
                "broker_id": "alpaca_live",
                "strategy_id": "mean_reversion.snapback",
                "notional_usd": 10.0,
                "order_request": {"symbol": "BTCUSDT", "venue": "binance"},
            },
            lane="live",
        )

        self.assertFalse(result.submitted)
        self.assertEqual(result.error, "instrument_venue_mismatch_live")

    def test_live_guard_rejects_missing_live_sync(self) -> None:
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("adapter should not be called when sync guard blocks")

        context = self._context(mode="live", environment="live")
        context.state.pop("alpaca_live_account")
        router = ExecutionRouter(adapter_factory=fail_if_called)
        result = router.route_entry_approval(
            context=context,
            approval={
                "broker_id": "alpaca_live",
                "strategy_id": "mean_reversion.snapback",
                "notional_usd": 10.0,
                "order_request": {"symbol": "AAPL"},
            },
            lane="live",
        )

        self.assertFalse(result.submitted)
        self.assertEqual(result.error, "live_sync_missing")

    def test_live_guard_rejects_missing_latest_bar(self) -> None:
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("adapter should not be called when bar guard blocks")

        context = self._context(mode="live", environment="live")
        context.state["market_data_latest_bars"] = {"raw": {}}
        router = ExecutionRouter(adapter_factory=fail_if_called)
        result = router.route_entry_approval(
            context=context,
            approval={
                "broker_id": "alpaca_live",
                "strategy_id": "mean_reversion.snapback",
                "notional_usd": 10.0,
                "order_request": {"symbol": "AAPL"},
            },
            lane="live",
        )

        self.assertFalse(result.submitted)
        self.assertEqual(result.error, "latest_bar_unavailable")

    def test_live_guard_rejects_full_live_capacity(self) -> None:
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("adapter should not be called when capacity guard blocks")

        context = self._context(mode="live", environment="live")
        context.state["alpaca_live_positions"]["summary"]["open_positions"] = 10
        router = ExecutionRouter(adapter_factory=fail_if_called)
        result = router.route_entry_approval(
            context=context,
            approval={
                "broker_id": "alpaca_live",
                "strategy_id": "mean_reversion.snapback",
                "notional_usd": 10.0,
                "order_request": {"symbol": "AAPL"},
            },
            lane="live",
        )

        self.assertFalse(result.submitted)
        self.assertEqual(result.error, "max_live_positions_reached")

    def test_live_exit_order_uses_guard_before_adapter(self) -> None:
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("adapter should not be called when guard blocks")

        context = self._context(mode="live", environment="live")
        context.config.live_execution_allowed_strategies = ("other.strategy",)
        router = ExecutionRouter(adapter_factory=fail_if_called)
        result = router.route_order_request(
            context=context,
            broker_id="alpaca_live",
            order_request={"symbol": "AAPL", "side": "sell"},
            lane="live",
            action="exit",
            strategy_id="mean_reversion.snapback",
        )

        self.assertFalse(result.submitted)
        self.assertEqual(result.error, "strategy_not_allowed_live")

    def test_live_cancel_uses_guard_before_adapter(self) -> None:
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("adapter should not be called when guard blocks")

        context = self._context(mode="live", environment="live")
        context.config.live_execution_activation_ack = ""
        router = ExecutionRouter(adapter_factory=fail_if_called)
        result = router.route_cancel_order(
            context=context,
            broker_id="alpaca_live",
            order_id="order-1",
            lane="live",
        )

        self.assertFalse(result.canceled)
        self.assertEqual(result.error, "activation_ack_missing")

    def test_live_dry_cancel_records_intent_without_adapter_call(self) -> None:
        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("adapter should not be called in live_dry")

        context = self._context(mode="live_dry", environment="live")
        router = ExecutionRouter(adapter_factory=fail_if_called)
        result = router.route_cancel_order(
            context=context,
            broker_id="alpaca_live",
            order_id="order-1",
            lane="live",
        )

        self.assertFalse(result.canceled)
        self.assertEqual(result.status, "live_dry_intent")
        self.assertEqual(context.state["execution_router_intents"][0]["action"], "cancel")

    def test_paper_cancel_routes_to_adapter(self) -> None:
        calls = []

        class FakeAdapter:
            def cancel_order(self, context, *, order_id):
                calls.append((context.tick_id, order_id))

        router = ExecutionRouter(adapter_factory=lambda _context, _broker_id: FakeAdapter())
        result = router.route_cancel_order(
            context=self._context(),
            broker_id="alpaca_paper",
            order_id="order-1",
            lane="paper",
        )

        self.assertTrue(result.canceled)
        self.assertEqual(calls, [("test", "order-1")])


if __name__ == "__main__":
    unittest.main()
