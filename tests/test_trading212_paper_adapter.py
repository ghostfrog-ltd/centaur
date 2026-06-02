from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

from app.framework.adapters.brokers import get_broker_adapter
from app.framework.adapters.brokers.base import BrokerAdapterError
from app.framework.adapters.brokers.trading212 import (
    Trading212LiveBrokerAdapter,
    Trading212PaperBrokerAdapter,
)
from app.framework.runtime.models import TickContext


class Trading212PaperAdapterTests(unittest.TestCase):
    def _adapter(self, *, configured: bool = True) -> Trading212PaperBrokerAdapter:
        return Trading212PaperBrokerAdapter(
            api_key="paper-key" if configured else "",
            api_secret="paper-secret" if configured else "",
            base_url="https://demo.trading212.com/api/v0",
            timeout_seconds=10,
            primary_currency="GBP",
            ticker_overrides={"AAPL": "AAPL_US_EQ"},
            equity_symbols=("VOD", "SHEL", "BARC"),
            api_configured=configured,
        )

    def _context(self, *, configured: bool = True) -> TickContext:
        return TickContext(
            tick_id="test",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(
                trading212_paper_api_key="paper-key" if configured else "",
                trading212_paper_api_secret="paper-secret" if configured else "",
                trading212_paper_base_url="https://demo.trading212.com/api/v0",
                trading212_paper_request_timeout_seconds=10,
                trading212_paper_primary_currency="GBP",
                trading212_paper_ticker_overrides={"AAPL": "AAPL_US_EQ"},
                trading212_paper_equity_symbols=("VOD", "SHEL", "BARC"),
                trading212_paper_api_configured=configured,
                trading212_paper_default_notional_native=10.0,
            ),
            usage_ledger=SimpleNamespace(),
        )

    def test_broker_registry_resolves_trading212_paper_scaffold(self) -> None:
        adapter = get_broker_adapter(self._context(), "trading212_paper")

        self.assertIsInstance(adapter, Trading212PaperBrokerAdapter)
        self.assertEqual(adapter.broker_id, "trading212_paper")

    def test_broker_registry_resolves_disabled_trading212_live(self) -> None:
        context = self._context()
        context.config.trading212_live_api_key = ""
        context.config.trading212_live_api_secret = ""
        context.config.trading212_live_base_url = "https://live.trading212.com/api/v0"
        context.config.trading212_live_request_timeout_seconds = 10
        context.config.trading212_live_primary_currency = "GBP"
        context.config.trading212_live_ticker_overrides = {}
        context.config.trading212_live_equity_symbols = ("VOD",)
        context.config.trading212_live_api_configured = False
        context.config.trading212_live_execution_enabled = False

        adapter = get_broker_adapter(context, "trading212_live")

        self.assertIsInstance(adapter, Trading212LiveBrokerAdapter)
        self.assertEqual(adapter.broker_id, "trading212_live")

    def test_validate_entry_requires_configuration(self) -> None:
        rejection = self._adapter(configured=False).validate_entry_constraints(
            context=self._context(configured=False),
            proposal={"symbol": "AAPL", "asset_class": "equity"},
            notional_usd=10.0,
            usd_to_gbp=0.79,
        )

        self.assertEqual(rejection, "trading212_paper_not_configured")

    def test_validate_entry_rejects_crypto(self) -> None:
        rejection = self._adapter().validate_entry_constraints(
            context=self._context(),
            proposal={"symbol": "BTC/USD", "asset_class": "crypto"},
            notional_usd=10.0,
            usd_to_gbp=0.79,
        )

        self.assertEqual(rejection, "unsupported_asset_class")

    def test_validate_entry_requires_trading212_market_data(self) -> None:
        rejection = self._adapter().validate_entry_constraints(
            context=self._context(),
            proposal={
                "symbol": "AAPL",
                "asset_class": "equity",
                "source": "alpaca_market_data",
            },
            notional_usd=10.0,
            usd_to_gbp=0.79,
        )

        self.assertEqual(rejection, "trading212_market_data_required")

    def test_validate_entry_allows_trading212_sourced_equity(self) -> None:
        rejection = self._adapter().validate_entry_constraints(
            context=self._context(),
            proposal={
                "symbol": "VOD",
                "asset_class": "equity",
                "source": "trading212_market_data",
                "venue_symbol": "VODl_EQ",
            },
            notional_usd=10.0,
            usd_to_gbp=0.79,
        )

        self.assertIsNone(rejection)

    def test_validate_entry_rejects_unapproved_uk_alias(self) -> None:
        rejection = self._adapter().validate_entry_constraints(
            context=self._context(),
            proposal={
                "symbol": "UK_GOLD",
                "asset_class": "equity",
                "source": "trading212_market_data",
                "venue_symbol": "SGLNl_EQ",
            },
            notional_usd=10.0,
            usd_to_gbp=0.79,
        )

        self.assertEqual(rejection, "trading212_symbol_not_allowed")

    def test_validate_entry_requires_trading212_ticker(self) -> None:
        rejection = self._adapter().validate_entry_constraints(
            context=self._context(),
            proposal={
                "symbol": "VOD",
                "asset_class": "equity",
                "source": "trading212_market_data",
            },
            notional_usd=10.0,
            usd_to_gbp=0.79,
        )

        self.assertEqual(rejection, "trading212_ticker_unmapped")

    def test_build_entry_order_request_is_fx_bounded(self) -> None:
        request = self._adapter().build_entry_order_request(
            proposal={"symbol": "AAPL", "asset_class": "equity", "entry_price": 100.0},
            client_order_id="centaur-test",
            notional_usd=12.5,
            limit_buffer_bps=5.0,
            usd_to_gbp=0.8,
        )

        self.assertEqual(request["ticker"], "AAPL_US_EQ")
        self.assertEqual(request["quantity"], "0.125")
        self.assertEqual(request["limitPrice"], 80.04)
        self.assertEqual(request["centaur_notional_usd"], 12.5)
        self.assertEqual(request["centaur_notional_native"], 10.0)
        self.assertEqual(request["centaur_notional_currency"], "GBP")
        self.assertEqual(request["centaur_execution_status"], "approved_for_paper")

    def test_build_entry_order_request_uses_gbp_price_when_present(self) -> None:
        request = self._adapter().build_entry_order_request(
            proposal={
                "symbol": "VOD",
                "asset_class": "equity",
                "entry_price": 72.0,
                "entry_price_gbp": 0.72,
                "venue_symbol": "VODl_EQ",
            },
            client_order_id="centaur-test",
            notional_usd=12.5,
            limit_buffer_bps=5.0,
            usd_to_gbp=0.8,
        )

        self.assertEqual(request["ticker"], "VODl_EQ")
        self.assertEqual(request["quantity"], "13.888888")
        self.assertEqual(request["limitPrice"], 0.7204)

    def test_submit_order_normalizes_demo_response_and_records_client_id(self) -> None:
        adapter = self._adapter()

        class FakeClient:
            def submit_limit_order(self, _context, *, order_request):
                return {
                    "id": 123,
                    "ticker": order_request["ticker"],
                    "quantity": order_request["quantity"],
                    "limitPrice": order_request["limitPrice"],
                    "status": "NEW",
                    "createdAt": "2026-06-01T18:00:00Z",
                }

        adapter._client = lambda: FakeClient()
        context = self._context()
        context.usage_ledger.paper_order_client_id_exists = lambda **_kwargs: False

        order = adapter.submit_order(
            context,
            order_request={
                "ticker": "AAPL_US_EQ",
                "quantity": "0.1",
                "limitPrice": 80.04,
                "timeValidity": "DAY",
                "client_order_id": "centaur-test",
                "centaur_symbol": "AAPL",
                "centaur_notional_usd": 12.5,
                "centaur_notional_native": 10.0,
                "centaur_notional_currency": "GBP",
            },
        )

        self.assertEqual(order["id"], "123")
        self.assertEqual(order["symbol"], "AAPL")
        self.assertEqual(order["side"], "buy")
        self.assertEqual(order["notional"], 12.5)
        self.assertEqual(order["notional_native"], 10.0)
        self.assertEqual(order["notional_currency"], "GBP")
        self.assertEqual(order["client_order_id"], "centaur-test")
        self.assertIn("centaur-test", context.state["submitted_client_order_ids"])

    def test_submit_order_rejects_duplicate_client_order_id(self) -> None:
        context = self._context()
        context.usage_ledger.paper_order_client_id_exists = lambda **_kwargs: True

        with self.assertRaisesRegex(BrokerAdapterError, "duplicate_client_order_id"):
            self._adapter().submit_order(
                context,
                order_request={
                    "ticker": "AAPL_US_EQ",
                    "quantity": "0.1",
                    "limitPrice": 80.04,
                    "client_order_id": "centaur-test",
                },
            )

    def test_trading212_live_adapter_fails_closed_for_entries_and_submit(self) -> None:
        adapter = Trading212LiveBrokerAdapter(
            api_key="",
            api_secret="",
            base_url="https://live.trading212.com/api/v0",
            timeout_seconds=10,
            primary_currency="GBP",
            ticker_overrides={},
            equity_symbols=("VOD",),
            api_configured=False,
        )
        context = self._context()

        rejection = adapter.validate_entry_constraints(
            context=context,
            proposal={
                "symbol": "VOD",
                "asset_class": "equity",
                "source": "trading212_market_data",
                "venue_symbol": "VODl_EQ",
            },
            notional_usd=10.0,
            usd_to_gbp=0.79,
        )

        self.assertEqual(rejection, "trading212_live_disabled")
        with self.assertRaisesRegex(BrokerAdapterError, "trading212_live_disabled"):
            adapter.build_entry_order_request(
                proposal={
                    "symbol": "VOD",
                    "asset_class": "equity",
                    "entry_price": 100.0,
                },
                client_order_id="live-test",
                notional_usd=10.0,
                limit_buffer_bps=5.0,
                usd_to_gbp=0.79,
            )
        with self.assertRaisesRegex(BrokerAdapterError, "trading212_live_disabled"):
            adapter.submit_order(
                context,
                order_request={
                    "ticker": "VODl_EQ",
                    "quantity": "1",
                    "limitPrice": 80.04,
                    "client_order_id": "live-test",
                },
            )


if __name__ == "__main__":
    unittest.main()
