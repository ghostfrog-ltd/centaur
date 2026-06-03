from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import app.heartbeat.support as heartbeat_support
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

    def test_live_entry_follow_blocks_when_existing_live_position_lacks_plan(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(
                centaur_mode="live",
                centaur_environment="live",
                paper_execution_equity_broker_id="alpaca_paper",
                paper_execution_crypto_broker_id="alpaca_paper",
                live_execution_enabled=True,
                live_execution_kill_switch=False,
                alpaca_live_api_configured=True,
                live_execution_activation_ack="LIVE_TRADING_APPROVED",
                live_execution_allowed_strategies=("mean_reversion.snapback",),
                live_execution_max_open_positions=10,
                live_execution_default_notional_usd=10.0,
                live_execution_max_orders_per_tick=1,
            ),
            usage_ledger=SimpleNamespace(
                get_first_paper_trade_order=lambda **_kwargs: None,
                list_recent_execution_lane_trade_orders=lambda **_kwargs: [],
            ),
            state={
                "market_gate": {
                    "account_trade_ready": True,
                    "reason": "market_open",
                },
                "live_daily_protection": {"system_status": "active"},
                "risk_cfo": {
                    "approved_order_requests": [
                        {
                            "proposal_id": "proposal-1",
                            "broker_id": "alpaca_paper",
                        }
                    ]
                },
                "execution": {
                    "orders": [
                        {
                            "proposal_id": "proposal-1",
                            "broker_id": "alpaca_paper",
                        }
                    ]
                },
                "shadow_trade_proposals": {
                    "proposals": [
                        {
                            "proposal_id": "proposal-1",
                            "symbol": "MSFT",
                            "strategy_id": "mean_reversion.snapback",
                        }
                    ]
                },
                "alpaca_live_account": {
                    "summary": {
                        "status": "ACTIVE",
                        "equity": 131.0,
                        "trading_blocked": False,
                        "account_blocked": False,
                        "trade_suspended_by_user": False,
                    },
                    "raw": {},
                },
                "alpaca_live_positions": {
                    "summary": {"open_positions": 1, "symbols": ["AMZN"]},
                    "raw": [
                        {
                            "symbol": "AMZN",
                            "broker_id": "alpaca_live",
                            "qty": "0.036",
                        }
                    ],
                },
                "alpaca_live_orders": {
                    "summary": {"open_orders": 0, "open_order_symbols": []},
                    "raw": [],
                },
            },
        )

        result = pipelines.live_risk_cfo_gate(context)

        self.assertEqual(result["decision"], "hold")
        self.assertEqual(result["reason"], "unmanaged_live_positions_present")
        self.assertEqual(result["approved_trades"], 0)
        self.assertEqual(result["unmanaged_live_positions"], ["AMZN"])

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

    def test_daily_protection_uses_broker_last_equity_baseline(self) -> None:
        class FakeUsageLedger:
            def get_daily_protection_state(self, *, session_date):
                return {
                    "session_date": session_date,
                    "baseline_equity": 100009.91,
                    "system_status": "active",
                }

            def upsert_daily_protection_state(self, **kwargs):
                baseline = max(
                    float(kwargs["baseline_equity"]),
                    float(kwargs["current_equity"]),
                )
                drawdown = max(0.0, baseline - float(kwargs["current_equity"]))
                return {
                    "session_date": kwargs["session_date"],
                    "market_open_at": kwargs["market_open_at"],
                    "baseline_equity": baseline,
                    "latest_equity": kwargs["current_equity"],
                    "equity_drawdown_usd": drawdown,
                    "max_daily_drawdown_usd": kwargs["max_daily_drawdown_usd"],
                    "system_status": kwargs["system_status"],
                    "stale_orders_reaped_count": 0,
                }

        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 3, 15, 57, tzinfo=ZoneInfo("America/New_York")),
            config=SimpleNamespace(
                market_timezone="America/New_York",
                paper_execution_max_daily_drawdown_usd=2.0,
            ),
            usage_ledger=FakeUsageLedger(),
            state={
                "alpaca_account": {
                    "summary": {
                        "equity": "100008.50",
                    },
                    "raw": {
                        "last_equity": "100011.80",
                    }
                }
            },
        )

        result = pipelines.daily_protection(context)

        self.assertEqual(result["system_status"], "protected")
        self.assertTrue(result["entries_blocked"])
        self.assertEqual(result["baseline_equity"], 100011.80)
        self.assertAlmostEqual(result["equity_drawdown_usd"], 3.30)

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

    def test_equity_entry_cutoff_applies_every_market_day(self) -> None:
        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 2, 15, 15, tzinfo=ZoneInfo("America/New_York")),
            config=SimpleNamespace(
                market_timezone="America/New_York",
                paper_execution_equity_only=False,
                paper_execution_require_market_open=True,
                paper_execution_equity_no_weekend_carry_enabled=True,
                paper_execution_equity_friday_entry_cutoff_minutes_before_close=60,
                paper_execution_min_projected_gain_pct=0.01,
                paper_execution_default_notional_usd=10.0,
                paper_execution_equity_broker_id="alpaca_paper",
                paper_execution_crypto_broker_id="alpaca_paper",
            ),
            usage_ledger=SimpleNamespace(),
            state={},
        )
        proposal = {
            "proposal_id": "proposal-1",
            "symbol": "MSFT",
            "asset_class": "equity",
            "strategy_id": "mean_reversion.snapback",
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss_price": 95.0,
            "target_price": 103.0,
        }
        original = pipelines.get_execution_adapter

        def fail_if_called(*_args, **_kwargs):
            raise AssertionError("near-close entry cutoff should block before broker lookup")

        pipelines.get_execution_adapter = fail_if_called
        try:
            approval, rejection = pipelines._build_paper_trade_approval(
                context=context,
                proposal=proposal,
                tick_id="test",
                config=context.config,
                market_gate={
                    "market_open": True,
                    "next_close": "2026-06-02T16:00:00-04:00",
                },
                position_symbols=set(),
                open_order_symbols=set(),
            )
        finally:
            pipelines.get_execution_adapter = original

        self.assertIsNone(approval)
        self.assertIsNotNone(rejection)
        self.assertEqual(
            rejection["reason"],
            "equity_entry_cutoff_no_overnight_carry",
        )

    def test_equity_flatten_applies_every_market_day(self) -> None:
        class FakeExecutionAdapter:
            def build_exit_order_request(self, **kwargs):
                return {
                    "symbol": kwargs["symbol"],
                    "side": "sell",
                    "qty": kwargs["qty"],
                    "client_order_id": kwargs["client_order_id"],
                }

        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 2, 15, 50, tzinfo=ZoneInfo("America/New_York")),
            config=SimpleNamespace(
                market_timezone="America/New_York",
                paper_execution_equity_no_weekend_carry_enabled=True,
                paper_execution_equity_friday_flatten_minutes_before_close=15,
                paper_execution_profit_capture_pct=0.0125,
            ),
            usage_ledger=SimpleNamespace(),
            state={
                "market_gate": {"next_close": "2026-06-02T16:00:00-04:00"},
                "fx_gbp_reference": {},
            },
        )
        original = heartbeat_support.get_execution_adapter
        heartbeat_support.get_execution_adapter = lambda _context, _broker_id: FakeExecutionAdapter()
        try:
            exit_request, skip_reason = heartbeat_support._build_exit_order_request(
                context=context,
                tick_id="test",
                position={"symbol": "MSFT", "qty": "0.1", "current_price": "99"},
                entry_order={
                    "order_id": "entry-1",
                    "broker_id": "alpaca_paper",
                    "symbol": "MSFT",
                    "asset_class": "equity",
                    "strategy_id": "mean_reversion.snapback",
                    "submitted_at": datetime(
                        2026,
                        6,
                        2,
                        15,
                        0,
                        tzinfo=ZoneInfo("America/New_York"),
                    ),
                    "filled_avg_price": 100.0,
                    "raw_json": {
                        "planned_stop_loss_price": 95.0,
                        "planned_take_profit_price": 110.0,
                        "planned_managed_exit_policy": "profit_after_1h_else_1d",
                        "planned_profit_exit_window_minutes": 60,
                        "planned_max_hold_window_minutes": 1440,
                    },
                },
                latest_bar={
                    "t": "2026-06-02T15:50:00-04:00",
                    "l": 98.0,
                    "h": 100.0,
                    "c": 99.0,
                },
                bar_history=[],
                as_of=context.started_at,
                limit_buffer_bps=5.0,
            )
        finally:
            heartbeat_support.get_execution_adapter = original

        self.assertIsNone(skip_reason)
        self.assertIsNotNone(exit_request)
        self.assertEqual(exit_request["exit_reason"], "equity_no_overnight_carry")

    def test_paper_exit_management_flattens_unmanaged_equity_near_close(self) -> None:
        captured: dict[str, object] = {}

        class FakeRouter:
            def route_order_request(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    submitted=True,
                    order={
                        "id": "exit-1",
                        "symbol": kwargs["order_request"]["symbol"],
                        "side": "sell",
                        "status": "new",
                    },
                    error=None,
                )

            def route_cancel_order(self, **_kwargs):
                raise AssertionError("unmanaged flatten should not refresh exits")

        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 2, 15, 50, tzinfo=ZoneInfo("America/New_York")),
            config=SimpleNamespace(
                market_timezone="America/New_York",
                paper_execution_equity_broker_id="alpaca_paper",
                paper_execution_crypto_broker_id="alpaca_paper",
                trading212_paper_api_configured=False,
                trading212_paper_execution_enabled=False,
                paper_execution_equity_no_weekend_carry_enabled=True,
                paper_execution_equity_friday_flatten_minutes_before_close=15,
                paper_execution_profit_capture_pct=0.0125,
                paper_execution_limit_buffer_bps=5.0,
            ),
            usage_ledger=SimpleNamespace(
                list_recent_execution_lane_trade_orders=lambda **_kwargs: [],
                record_paper_trade_orders=lambda **kwargs: len(kwargs["orders"]),
            ),
            state={
                "market_gate": {"next_close": "2026-06-02T16:00:00-04:00"},
                "fx_gbp_reference": {},
                "alpaca_positions": {
                    "raw": [
                        {
                            "broker_id": "alpaca_paper",
                            "symbol": "AMZN",
                            "qty": "0.04",
                            "current_price": "99.0",
                            "avg_entry_price": "100.0",
                        }
                    ]
                },
                "alpaca_orders": {"raw": []},
                "market_data_latest_bars": {
                    "raw": {
                        "AMZN": {
                            "t": "2026-06-02T15:50:00-04:00",
                            "l": 98.0,
                            "h": 100.0,
                            "c": 99.0,
                        }
                    }
                },
                "crypto_data_latest_bars": {"raw": {}},
            },
        )
        original = pipelines.ExecutionRouter
        pipelines.ExecutionRouter = lambda: FakeRouter()
        try:
            result = pipelines.paper_exit_management(context)
        finally:
            pipelines.ExecutionRouter = original

        self.assertEqual(result["mode"], "managed_exits")
        self.assertEqual(result["exit_orders_submitted"], 1)
        self.assertEqual(captured["action"], "flatten")
        self.assertEqual(
            context.state["paper_exit_management"]["orders"][0]["exit_reason"],
            "equity_no_overnight_carry",
        )
        self.assertTrue(
            context.state["paper_exit_management"]["orders"][0]["unmanaged_flatten"]
        )

    def test_paper_exit_management_flattens_managed_equity_without_latest_bar_near_close(self) -> None:
        captured: dict[str, object] = {}

        class FakeRouter:
            def route_order_request(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    submitted=True,
                    order={
                        "id": "exit-1",
                        "symbol": kwargs["order_request"]["symbol"],
                        "side": "sell",
                        "status": "new",
                    },
                    error=None,
                )

            def route_cancel_order(self, **_kwargs):
                raise AssertionError("no open exit should be refreshed")

        started_at = datetime(2026, 6, 2, 15, 50, tzinfo=ZoneInfo("America/New_York"))
        entry_order = {
            "order_id": "entry-1",
            "broker_id": "alpaca_paper",
            "symbol": "AMZN",
            "side": "buy",
            "status": "filled",
            "qty": "0.04",
            "filled_qty": "0.04",
            "asset_class": "equity",
            "strategy_id": "mean_reversion.snapback",
            "submitted_at": started_at - timedelta(hours=1),
            "filled_avg_price": 100.0,
            "raw_json": {
                "planned_stop_loss_price": 95.0,
                "planned_take_profit_price": 110.0,
                "planned_managed_exit_policy": "profit_after_1h_else_1d",
                "planned_profit_exit_window_minutes": 60,
                "planned_max_hold_window_minutes": 1440,
            },
        }
        context = TickContext(
            tick_id="test",
            started_at=started_at,
            config=SimpleNamespace(
                market_timezone="America/New_York",
                paper_execution_equity_broker_id="alpaca_paper",
                paper_execution_crypto_broker_id="alpaca_paper",
                trading212_paper_api_configured=False,
                trading212_paper_execution_enabled=False,
                paper_execution_equity_no_weekend_carry_enabled=True,
                paper_execution_equity_friday_flatten_minutes_before_close=15,
                paper_execution_profit_capture_pct=0.0125,
                paper_execution_limit_buffer_bps=5.0,
            ),
            usage_ledger=SimpleNamespace(
                list_recent_execution_lane_trade_orders=lambda **_kwargs: [entry_order],
                get_market_bars_for_window=lambda **_kwargs: [],
                record_paper_trade_orders=lambda **kwargs: len(kwargs["orders"]),
            ),
            state={
                "market_gate": {"next_close": "2026-06-02T16:00:00-04:00"},
                "fx_gbp_reference": {},
                "alpaca_positions": {
                    "raw": [
                        {
                            "broker_id": "alpaca_paper",
                            "symbol": "AMZN",
                            "qty": "0.04",
                            "current_price": "99.0",
                            "avg_entry_price": "100.0",
                        }
                    ]
                },
                "alpaca_orders": {"raw": []},
                "market_data_latest_bars": {"raw": {}},
                "crypto_data_latest_bars": {"raw": {}},
            },
        )
        original = pipelines.ExecutionRouter
        pipelines.ExecutionRouter = lambda: FakeRouter()
        try:
            result = pipelines.paper_exit_management(context)
        finally:
            pipelines.ExecutionRouter = original

        self.assertEqual(result["mode"], "managed_exits")
        self.assertEqual(result["exit_orders_submitted"], 1)
        self.assertEqual(captured["action"], "exit")
        self.assertEqual(
            context.state["paper_exit_management"]["orders"][0]["exit_reason"],
            "equity_no_overnight_carry",
        )

    def test_paper_exit_management_keeps_flattening_after_close_when_window_was_missed(self) -> None:
        captured: dict[str, object] = {}

        class FakeRouter:
            def route_order_request(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    submitted=True,
                    order={
                        "id": "exit-1",
                        "symbol": kwargs["order_request"]["symbol"],
                        "side": "sell",
                        "status": "new",
                    },
                    error=None,
                )

            def route_cancel_order(self, **_kwargs):
                raise AssertionError("no open exit should be refreshed")

        started_at = datetime(2026, 6, 2, 16, 34, tzinfo=ZoneInfo("America/New_York"))
        entry_order = {
            "order_id": "entry-1",
            "broker_id": "alpaca_paper",
            "symbol": "AMZN",
            "side": "buy",
            "status": "filled",
            "qty": "0.04",
            "filled_qty": "0.04",
            "asset_class": "equity",
            "strategy_id": "mean_reversion.snapback",
            "submitted_at": started_at - timedelta(hours=2),
            "filled_avg_price": 100.0,
            "raw_json": {
                "planned_stop_loss_price": 95.0,
                "planned_take_profit_price": 110.0,
                "planned_managed_exit_policy": "profit_after_1h_else_1d",
                "planned_profit_exit_window_minutes": 60,
                "planned_max_hold_window_minutes": 1440,
            },
        }
        context = TickContext(
            tick_id="test",
            started_at=started_at,
            config=SimpleNamespace(
                market_timezone="America/New_York",
                paper_execution_equity_broker_id="alpaca_paper",
                paper_execution_crypto_broker_id="alpaca_paper",
                trading212_paper_api_configured=False,
                trading212_paper_execution_enabled=False,
                paper_execution_equity_no_weekend_carry_enabled=True,
                paper_execution_equity_friday_flatten_minutes_before_close=15,
                paper_execution_profit_capture_pct=0.0125,
                paper_execution_limit_buffer_bps=5.0,
            ),
            usage_ledger=SimpleNamespace(
                list_recent_execution_lane_trade_orders=lambda **_kwargs: [entry_order],
                get_market_bars_for_window=lambda **_kwargs: [],
                record_paper_trade_orders=lambda **kwargs: len(kwargs["orders"]),
            ),
            state={
                "market_gate": {"next_close": "2026-06-03T16:00:00-04:00"},
                "fx_gbp_reference": {},
                "alpaca_positions": {
                    "raw": [
                        {
                            "broker_id": "alpaca_paper",
                            "symbol": "AMZN",
                            "qty": "0.04",
                            "current_price": "99.0",
                            "avg_entry_price": "100.0",
                        }
                    ]
                },
                "alpaca_orders": {"raw": []},
                "market_data_latest_bars": {"raw": {}},
                "crypto_data_latest_bars": {"raw": {}},
            },
        )
        original = pipelines.ExecutionRouter
        pipelines.ExecutionRouter = lambda: FakeRouter()
        try:
            result = pipelines.paper_exit_management(context)
        finally:
            pipelines.ExecutionRouter = original

        self.assertEqual(result["mode"], "managed_exits")
        self.assertEqual(result["exit_orders_submitted"], 1)
        self.assertEqual(captured["action"], "exit")
        self.assertEqual(
            context.state["paper_exit_management"]["orders"][0]["exit_reason"],
            "equity_no_overnight_carry",
        )

    def test_missing_plan_paper_position_uses_current_profit_capture(self) -> None:
        captured: dict[str, object] = {}

        class FakeExecutionAdapter:
            def build_exit_order_request(self, **kwargs):
                return {
                    "symbol": kwargs["symbol"],
                    "side": "sell",
                    "qty": kwargs["qty"],
                    "client_order_id": kwargs["client_order_id"],
                }

        class FakeRouter:
            def route_order_request(self, **kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    submitted=True,
                    order={
                        "id": "exit-1",
                        "symbol": kwargs["order_request"]["symbol"],
                        "side": "sell",
                        "status": "new",
                    },
                    error=None,
                )

            def route_cancel_order(self, **_kwargs):
                raise AssertionError("no open exit should be refreshed")

        context = TickContext(
            tick_id="test",
            started_at=datetime(2026, 6, 2, 12, 10, tzinfo=ZoneInfo("America/New_York")),
            config=SimpleNamespace(
                market_timezone="America/New_York",
                paper_execution_equity_broker_id="alpaca_paper",
                paper_execution_crypto_broker_id="alpaca_paper",
                trading212_paper_api_configured=False,
                trading212_paper_execution_enabled=False,
                paper_execution_equity_no_weekend_carry_enabled=True,
                paper_execution_equity_friday_flatten_minutes_before_close=15,
                paper_execution_profit_capture_pct=0.005,
                paper_execution_limit_buffer_bps=5.0,
            ),
            usage_ledger=SimpleNamespace(
                list_recent_execution_lane_trade_orders=lambda **_kwargs: [],
                record_paper_trade_orders=lambda **kwargs: len(kwargs["orders"]),
            ),
            state={
                "market_gate": {"next_close": "2026-06-02T16:00:00-04:00"},
                "fx_gbp_reference": {},
                "alpaca_positions": {
                    "raw": [
                        {
                            "broker_id": "alpaca_paper",
                            "symbol": "MRVL",
                            "qty": "0.1",
                            "current_price": "100.6",
                            "avg_entry_price": "100.0",
                        }
                    ]
                },
                "alpaca_orders": {"raw": []},
                "market_data_latest_bars": {
                    "raw": {
                        "MRVL": {
                            "t": "2026-06-02T12:10:00-04:00",
                            "l": 100.1,
                            "h": 100.6,
                            "c": 100.55,
                        }
                    }
                },
                "crypto_data_latest_bars": {"raw": {}},
            },
        )
        original_router = pipelines.ExecutionRouter
        original_adapter = heartbeat_support.get_execution_adapter
        pipelines.ExecutionRouter = lambda: FakeRouter()
        heartbeat_support.get_execution_adapter = lambda _context, _broker_id: FakeExecutionAdapter()
        try:
            result = pipelines.paper_exit_management(context)
        finally:
            pipelines.ExecutionRouter = original_router
            heartbeat_support.get_execution_adapter = original_adapter

        self.assertEqual(result["mode"], "managed_exits")
        self.assertEqual(result["exit_orders_submitted"], 1)
        self.assertEqual(captured["action"], "flatten")
        self.assertEqual(
            context.state["paper_exit_management"]["orders"][0]["exit_reason"],
            "settings_profit_capture",
        )
        self.assertTrue(
            context.state["paper_exit_management"]["orders"][0]["unmanaged_flatten"]
        )

    def test_red_max_hold_is_hard_backstop(self) -> None:
        class FakeExecutionAdapter:
            def build_exit_order_request(self, **kwargs):
                return {
                    "symbol": kwargs["symbol"],
                    "side": "sell",
                    "qty": kwargs["qty"],
                    "client_order_id": kwargs["client_order_id"],
                }

        started_at = datetime(2026, 6, 2, 12, 0, tzinfo=ZoneInfo("Europe/London"))
        context = TickContext(
            tick_id="test",
            started_at=started_at,
            config=SimpleNamespace(
                market_timezone="America/New_York",
                paper_execution_equity_no_weekend_carry_enabled=True,
                paper_execution_profit_capture_pct=0.0125,
            ),
            usage_ledger=SimpleNamespace(),
            state={"market_gate": {}, "fx_gbp_reference": {}},
        )
        original = heartbeat_support.get_execution_adapter
        heartbeat_support.get_execution_adapter = lambda _context, _broker_id: FakeExecutionAdapter()
        try:
            exit_request, skip_reason = heartbeat_support._build_exit_order_request(
                context=context,
                tick_id="test",
                position={"symbol": "LINK/USD", "qty": "1.0", "current_price": "9.0"},
                entry_order={
                    "order_id": "entry-1",
                    "broker_id": "alpaca_paper",
                    "symbol": "LINK/USD",
                    "asset_class": "crypto",
                    "strategy_id": "crypto_momentum.trend",
                    "submitted_at": started_at - timedelta(hours=25),
                    "filled_avg_price": 10.0,
                    "raw_json": {
                        "planned_stop_loss_price": 8.0,
                        "planned_take_profit_price": 12.0,
                        "planned_holding_window_minutes": 1440,
                        "planned_managed_exit_policy": "profit_capture_else_1d",
                    },
                },
                latest_bar={
                    "t": started_at.isoformat(),
                    "l": 8.5,
                    "h": 9.2,
                    "c": 9.0,
                },
                bar_history=[],
                as_of=started_at,
                limit_buffer_bps=25.0,
            )
        finally:
            heartbeat_support.get_execution_adapter = original

        self.assertIsNone(skip_reason)
        self.assertIsNotNone(exit_request)
        self.assertEqual(exit_request["exit_reason"], "max_holding_window_elapsed")

    def test_profit_capture_uses_current_config_not_stored_entry_value(self) -> None:
        class FakeExecutionAdapter:
            def build_exit_order_request(self, **kwargs):
                return {
                    "symbol": kwargs["symbol"],
                    "side": "sell",
                    "qty": kwargs["qty"],
                    "client_order_id": kwargs["client_order_id"],
                }

        started_at = datetime(2026, 6, 2, 12, 10, tzinfo=ZoneInfo("America/New_York"))
        context = TickContext(
            tick_id="test",
            started_at=started_at,
            config=SimpleNamespace(
                market_timezone="America/New_York",
                paper_execution_equity_no_weekend_carry_enabled=True,
                paper_execution_profit_capture_pct=0.005,
            ),
            usage_ledger=SimpleNamespace(),
            state={
                "market_gate": {"next_close": "2026-06-02T16:00:00-04:00"},
                "fx_gbp_reference": {},
            },
        )
        original = heartbeat_support.get_execution_adapter
        heartbeat_support.get_execution_adapter = lambda _context, _broker_id: FakeExecutionAdapter()
        try:
            exit_request, skip_reason = heartbeat_support._build_exit_order_request(
                context=context,
                tick_id="test",
                position={"symbol": "MRVL", "qty": "0.1", "current_price": "100.5"},
                entry_order={
                    "order_id": "entry-1",
                    "broker_id": "alpaca_paper",
                    "symbol": "MRVL",
                    "asset_class": "equity",
                    "strategy_id": "mean_reversion.snapback",
                    "submitted_at": started_at - timedelta(minutes=10),
                    "filled_avg_price": 100.0,
                    "raw_json": {
                        "planned_stop_loss_price": 95.0,
                        "planned_take_profit_price": 110.0,
                        "planned_managed_exit_policy": "profit_after_1h_else_1d",
                        "planned_profit_exit_window_minutes": 60,
                        "planned_max_hold_window_minutes": 1440,
                        "planned_profit_capture_pct": 0.0125,
                    },
                },
                latest_bar={
                    "t": started_at.isoformat(),
                    "l": 100.0,
                    "h": 100.6,
                    "c": 100.5,
                },
                bar_history=[],
                as_of=started_at,
                limit_buffer_bps=5.0,
            )
        finally:
            heartbeat_support.get_execution_adapter = original

        self.assertIsNone(skip_reason)
        self.assertIsNotNone(exit_request)
        self.assertEqual(exit_request["exit_reason"], "profit_capture_hit")
        self.assertEqual(exit_request["planned_profit_capture_pct"], 0.005)
        self.assertEqual(exit_request["planned_profit_capture_price"], 100.5)

    def test_current_profit_capture_overrides_stale_entry_target(self) -> None:
        class FakeExecutionAdapter:
            def build_exit_order_request(self, **_kwargs):
                raise AssertionError("stale take-profit metadata should not build a sell")

        started_at = datetime(2026, 6, 2, 12, 10, tzinfo=ZoneInfo("America/New_York"))
        context = TickContext(
            tick_id="test",
            started_at=started_at,
            config=SimpleNamespace(
                market_timezone="America/New_York",
                paper_execution_equity_no_weekend_carry_enabled=True,
                paper_execution_profit_capture_pct=0.016,
            ),
            usage_ledger=SimpleNamespace(),
            state={
                "market_gate": {"next_close": "2026-06-02T16:00:00-04:00"},
                "fx_gbp_reference": {},
            },
        )
        original = heartbeat_support.get_execution_adapter
        heartbeat_support.get_execution_adapter = lambda _context, _broker_id: FakeExecutionAdapter()
        try:
            exit_request, skip_reason = heartbeat_support._build_exit_order_request(
                context=context,
                tick_id="test",
                position={"symbol": "MRVL", "qty": "0.1", "current_price": "101.3"},
                entry_order={
                    "order_id": "entry-1",
                    "broker_id": "alpaca_paper",
                    "symbol": "MRVL",
                    "asset_class": "equity",
                    "strategy_id": "mean_reversion.snapback",
                    "submitted_at": started_at - timedelta(minutes=10),
                    "filled_avg_price": 100.0,
                    "raw_json": {
                        "planned_stop_loss_price": 95.0,
                        "planned_take_profit_price": 101.25,
                        "planned_managed_exit_policy": "profit_after_1h_else_1d",
                        "planned_profit_exit_window_minutes": 60,
                        "planned_max_hold_window_minutes": 1440,
                    },
                },
                latest_bar={
                    "t": started_at.isoformat(),
                    "l": 100.8,
                    "h": 101.3,
                    "c": 101.2,
                },
                bar_history=[],
                as_of=started_at,
                limit_buffer_bps=5.0,
            )
        finally:
            heartbeat_support.get_execution_adapter = original

        self.assertIsNone(exit_request)
        self.assertEqual(skip_reason, "exit_not_due")

    def test_entry_target_is_legacy_fallback_when_profit_capture_disabled(self) -> None:
        class FakeExecutionAdapter:
            def build_exit_order_request(self, **kwargs):
                return {
                    "symbol": kwargs["symbol"],
                    "side": "sell",
                    "qty": kwargs["qty"],
                    "client_order_id": kwargs["client_order_id"],
                }

        started_at = datetime(2026, 6, 2, 12, 10, tzinfo=ZoneInfo("America/New_York"))
        context = TickContext(
            tick_id="test",
            started_at=started_at,
            config=SimpleNamespace(
                market_timezone="America/New_York",
                paper_execution_equity_no_weekend_carry_enabled=True,
                paper_execution_profit_capture_pct=0.0,
            ),
            usage_ledger=SimpleNamespace(),
            state={
                "market_gate": {"next_close": "2026-06-02T16:00:00-04:00"},
                "fx_gbp_reference": {},
            },
        )
        original = heartbeat_support.get_execution_adapter
        heartbeat_support.get_execution_adapter = lambda _context, _broker_id: FakeExecutionAdapter()
        try:
            exit_request, skip_reason = heartbeat_support._build_exit_order_request(
                context=context,
                tick_id="test",
                position={"symbol": "MRVL", "qty": "0.1", "current_price": "101.3"},
                entry_order={
                    "order_id": "entry-1",
                    "broker_id": "alpaca_paper",
                    "symbol": "MRVL",
                    "asset_class": "equity",
                    "strategy_id": "mean_reversion.snapback",
                    "submitted_at": started_at - timedelta(minutes=10),
                    "filled_avg_price": 100.0,
                    "raw_json": {
                        "planned_stop_loss_price": 95.0,
                        "planned_take_profit_price": 101.25,
                        "planned_managed_exit_policy": "profit_after_1h_else_1d",
                        "planned_profit_exit_window_minutes": 60,
                        "planned_max_hold_window_minutes": 1440,
                    },
                },
                latest_bar={
                    "t": started_at.isoformat(),
                    "l": 100.8,
                    "h": 101.3,
                    "c": 101.2,
                },
                bar_history=[],
                as_of=started_at,
                limit_buffer_bps=5.0,
            )
        finally:
            heartbeat_support.get_execution_adapter = original

        self.assertIsNone(skip_reason)
        self.assertIsNotNone(exit_request)
        self.assertEqual(exit_request["exit_reason"], "take_profit_hit")

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
