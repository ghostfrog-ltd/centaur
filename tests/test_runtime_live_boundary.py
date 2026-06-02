from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import app.framework.engine.pipelines as pipelines
from app.framework.runtime.models import TickContext


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

    def test_market_gate_tracks_trading212_london_session_separately(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 2, 12, 0, tzinfo=ZoneInfo("Europe/London")),
            config=SimpleNamespace(
                discovery_crypto_symbols=(),
                market_timezone="America/New_York",
                trading212_paper_api_configured=True,
                trading212_paper_execution_enabled=True,
                trading212_paper_market_timezone="Europe/London",
                trading212_paper_market_open_time="08:00",
                trading212_paper_market_close_time="16:30",
            ),
            usage_ledger=SimpleNamespace(),
            state={
                "alpaca_account": {
                    "summary": {
                        "status": "ACTIVE",
                        "trading_blocked": False,
                        "account_blocked": False,
                    }
                },
                "alpaca_clock": {
                    "summary": {
                        "is_open": False,
                        "next_open": "2026-06-02T09:30:00-04:00",
                        "next_close": "2026-06-02T16:00:00-04:00",
                    }
                },
                "trading212_paper_account": {
                    "summary": {
                        "status": "DEMO",
                        "trading_blocked": False,
                        "account_blocked": False,
                    }
                },
            },
        )

        result = pipelines.market_gate(context)

        self.assertFalse(result["market_open"])
        self.assertFalse(result["equity_scan_ready"])
        self.assertTrue(
            result["broker_equity_markets"]["trading212_paper"]["market_open"]
        )
        self.assertTrue(
            result["broker_equity_markets"]["trading212_paper"]["equity_scan_ready"]
        )

    def test_trading212_approval_uses_own_market_window(self) -> None:
        class FakeExecutionAdapter:
            def validate_entry_constraints(self, **_kwargs):
                return None

            def build_entry_order_request(self, **kwargs):
                return {
                    "ticker": "VODl_EQ",
                    "client_order_id": kwargs["client_order_id"],
                }

        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 2, 12, 0, tzinfo=ZoneInfo("Europe/London")),
            config=SimpleNamespace(
                paper_execution_equity_only=False,
                paper_execution_require_market_open=True,
                paper_execution_min_projected_gain_pct=0.01,
                paper_execution_limit_buffer_bps=5.0,
                paper_execution_default_notional_usd=10.0,
                trading212_paper_default_notional_native=10.0,
                paper_execution_equity_broker_id="alpaca_paper",
            ),
            usage_ledger=SimpleNamespace(),
            state={"fx_gbp_reference": {"usd_to_gbp": 0.8}},
        )
        proposal = {
            "proposal_id": "proposal-1",
            "symbol": "VOD",
            "asset_class": "equity",
            "strategy_id": "mean_reversion.snapback",
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss_price": 95.0,
            "target_price": 103.0,
        }
        market_gate = {
            "market_open": False,
            "equity_reason": "market_closed",
            "next_close": "2026-06-02T16:00:00-04:00",
            "broker_equity_markets": {
                "trading212_paper": {
                    "market_open": True,
                    "reason": "market_open",
                    "next_close": "2026-06-02T16:30:00+01:00",
                }
            },
        }
        original = pipelines.get_execution_adapter
        pipelines.get_execution_adapter = lambda _context, _broker_id: FakeExecutionAdapter()
        try:
            approval, rejection = pipelines._build_paper_trade_approval(
                context=context,
                proposal=proposal,
                tick_id="test",
                config=context.config,
                market_gate=market_gate,
                position_symbols=set(),
                open_order_symbols=set(),
                broker_id="trading212_paper",
            )
        finally:
            pipelines.get_execution_adapter = original

        self.assertIsNone(rejection)
        self.assertIsNotNone(approval)
        self.assertEqual(approval["broker_id"], "trading212_paper")

    def test_trading212_latest_bars_can_use_positions_api_current_price(self) -> None:
        captured: dict[str, object] = {}

        def record_latest_bars(**kwargs):
            captured.update(kwargs)
            return len(kwargs["bars_by_symbol"])

        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 2, 12, 0, tzinfo=ZoneInfo("Europe/London")),
            config=SimpleNamespace(
                trading212_paper_market_data_provider="positions_api",
                trading212_paper_equity_symbols=("VOD",),
            ),
            usage_ledger=SimpleNamespace(record_latest_bars=record_latest_bars),
            state={
                "market_gate": {
                    "broker_equity_markets": {
                        "trading212_paper": {
                            "equity_scan_ready": True,
                            "reason": "market_open",
                        }
                    }
                },
                "fx_gbp_reference": {"usd_to_gbp": 0.8},
                "trading212_paper_positions": {
                    "raw": [
                        {
                            "quantity": 0.01,
                            "currentPrice": 72.5,
                            "instrument": {
                                "ticker": "VODl_EQ",
                                "currencyCode": "GBX",
                            },
                        }
                    ]
                },
            },
        )

        result = pipelines.trading212_latest_bars(context)

        self.assertEqual(result["mode"], "latest_bars")
        self.assertEqual(result["bars_saved"], 1)
        self.assertEqual(captured["source"], "trading212_market_data")
        self.assertEqual(captured["bars_by_symbol"]["VOD"]["c"], 72.5)
        self.assertEqual(captured["bars_by_symbol"]["VOD"]["venue_symbol"], "VODl_EQ")
        self.assertEqual(captured["bars_by_symbol"]["VOD"]["quote_currency"], "GBX")

    def test_trading212_positions_api_skips_without_seed_positions(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 2, 12, 0, tzinfo=ZoneInfo("Europe/London")),
            config=SimpleNamespace(
                trading212_paper_market_data_provider="positions_api",
                trading212_paper_equity_symbols=("VOD",),
            ),
            usage_ledger=SimpleNamespace(record_latest_bars=lambda **_kwargs: 0),
            state={
                "market_gate": {
                    "broker_equity_markets": {
                        "trading212_paper": {"equity_scan_ready": True}
                    }
                },
                "fx_gbp_reference": {"usd_to_gbp": 0.8},
                "trading212_paper_positions": {"raw": []},
            },
        )

        result = pipelines.trading212_latest_bars(context)

        self.assertEqual(result["mode"], "skipped")
        self.assertEqual(
            result["reason"],
            "trading212_no_held_positions_with_current_price",
        )

    def test_trading212_price_seed_positions_do_not_consume_strategy_slots(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 2, 12, 0, tzinfo=ZoneInfo("Europe/London")),
            config=SimpleNamespace(
                trading212_paper_price_seed_symbols=("VOD", "SHEL"),
                trading212_paper_equity_symbols=("VOD", "SHEL"),
            ),
            usage_ledger=SimpleNamespace(),
            state={
                "trading212_paper_positions": {
                    "summary": {"open_positions": 1, "symbols": ["VOD"]},
                    "raw": [
                        {
                            "quantity": 0.01,
                            "currentPrice": 72.5,
                            "instrument": {"ticker": "VODl_EQ"},
                        }
                    ],
                },
            },
        )

        position_state = pipelines._paper_lane_position_state(
            context,
            "trading212_paper",
            recent_orders=[],
        )

        self.assertEqual(position_state["open_positions"], 0)
        self.assertEqual(position_state["price_seed_positions"], 1)
        self.assertEqual(position_state["symbols"], set())
        self.assertEqual(position_state["price_seed_symbols"], {"VOD"})

    def test_trading212_managed_buy_revokes_price_seed_exemption(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 2, 12, 0, tzinfo=ZoneInfo("Europe/London")),
            config=SimpleNamespace(
                trading212_paper_price_seed_symbols=("VOD",),
                trading212_paper_equity_symbols=("VOD",),
            ),
            usage_ledger=SimpleNamespace(),
            state={
                "trading212_paper_positions": {
                    "summary": {"open_positions": 1, "symbols": ["VOD"]},
                    "raw": [
                        {
                            "quantity": 13.9,
                            "currentPrice": 72.5,
                            "instrument": {"ticker": "VODl_EQ"},
                        }
                    ],
                },
            },
        )
        managed_orders = [
            {
                "broker_id": "trading212_paper",
                "symbol": "VOD",
                "side": "buy",
                "filled_qty": "13.888888",
                "raw_json": {"planned_stop_loss_price": 70.0},
            }
        ]

        position_state = pipelines._paper_lane_position_state(
            context,
            "trading212_paper",
            recent_orders=managed_orders,
        )

        self.assertEqual(position_state["open_positions"], 1)
        self.assertEqual(position_state["price_seed_positions"], 0)
        self.assertEqual(position_state["symbols"], {"VOD"})

    def test_paper_exit_management_skips_trading212_price_seed_positions(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 2, 12, 0, tzinfo=ZoneInfo("Europe/London")),
            config=SimpleNamespace(
                paper_execution_equity_broker_id="alpaca_paper",
                paper_execution_crypto_broker_id="alpaca_paper",
                trading212_paper_api_configured=True,
                trading212_paper_execution_enabled=True,
                trading212_paper_price_seed_symbols=("VOD",),
                trading212_paper_equity_symbols=("VOD",),
            ),
            usage_ledger=SimpleNamespace(
                list_recent_execution_lane_trade_orders=lambda **_kwargs: [],
            ),
            state={
                "alpaca_positions": {"raw": []},
                "trading212_paper_positions": {
                    "raw": [
                        {
                            "broker_id": "trading212_paper",
                            "quantity": 0.01,
                            "instrument": {"ticker": "VODl_EQ"},
                        }
                    ]
                },
                "alpaca_orders": {"raw": []},
                "trading212_paper_orders": {"raw": []},
            },
        )
        original = pipelines.ExecutionRouter

        class FailRouter:
            def route_order_request(self, **_kwargs):
                raise AssertionError("seed positions should not route exits")

            def route_cancel_order(self, **_kwargs):
                raise AssertionError("seed positions should not cancel exits")

        pipelines.ExecutionRouter = lambda: FailRouter()
        try:
            result = pipelines.paper_exit_management(context)
        finally:
            pipelines.ExecutionRouter = original

        self.assertEqual(result["mode"], "monitoring")
        self.assertEqual(result["exit_orders_submitted"], 0)
        self.assertEqual(result["skip_reason"], "price_seed_position")
        self.assertEqual(
            context.state["paper_exit_management"]["skipped"][0]["broker_id"],
            "trading212_paper",
        )

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
