from __future__ import annotations

import unittest
from datetime import datetime
from types import SimpleNamespace

from app.adapters.brokers import get_broker_adapter
from app.adapters.brokers.base import BrokerAdapterError
from app.adapters.brokers.trading212 import Trading212PaperBrokerAdapter
from app.runtime.models import TickContext


class Trading212PaperAdapterTests(unittest.TestCase):
    def _adapter(self, *, configured: bool = True) -> Trading212PaperBrokerAdapter:
        return Trading212PaperBrokerAdapter(
            api_key="paper-key" if configured else "",
            api_secret="paper-secret" if configured else "",
            base_url="https://demo.trading212.com/api/v0",
            timeout_seconds=10,
            primary_currency="GBP",
            ticker_overrides={"AAPL": "AAPL_US_EQ"},
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
                trading212_paper_api_configured=configured,
                trading212_paper_default_notional_native=10.0,
            ),
            usage_ledger=SimpleNamespace(),
        )

    def test_broker_registry_resolves_trading212_paper_scaffold(self) -> None:
        adapter = get_broker_adapter(self._context(), "trading212_paper")

        self.assertIsInstance(adapter, Trading212PaperBrokerAdapter)
        self.assertEqual(adapter.broker_id, "trading212_paper")

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


if __name__ == "__main__":
    unittest.main()
