from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from app.framework.adapters.trading212 import Trading212ApiError
from app.framework.engine.trading212_seed import Trading212PriceSeeder


class Trading212PriceSeederTests(unittest.TestCase):
    def _config(self) -> SimpleNamespace:
        return SimpleNamespace(
            trading212_paper_api_configured=True,
            trading212_paper_execution_enabled=True,
            trading212_live_execution_enabled=False,
            trading212_paper_price_seed_symbols=("VOD", "SHEL"),
            trading212_paper_equity_symbols=("VOD", "SHEL"),
            trading212_paper_ticker_overrides={},
        )

    def test_seed_prices_dry_run_does_not_submit_orders(self) -> None:
        submitted = []

        class FakeClient:
            def get_positions(self, _context):
                return []

            def get_orders(self, _context):
                return []

            def get_instruments(self, _context):
                return [
                    {"ticker": "VODl_EQ", "currencyCode": "GBX"},
                    {"ticker": "SHELl_EQ", "currencyCode": "GBX"},
                ]

            def submit_market_order(self, _context, *, order_request):
                submitted.append(order_request)
                return {"id": 1, **order_request}

        with TemporaryDirectory() as tmpdir:
            seeder = Trading212PriceSeeder(
                config=self._config(),
                ledger=SimpleNamespace(record_paper_trade_orders=lambda **_kwargs: 0),
                client_factory=lambda _config: FakeClient(),
                instrument_cache_path=Path(tmpdir) / "instruments.json",
            )

            result = seeder.run(confirm=False)

        self.assertEqual(result["mode"], "dry_run")
        self.assertEqual(result["orders_submitted"], 0)
        self.assertEqual(len(result["orders"]), 2)
        self.assertEqual(submitted, [])

    def test_confirmed_seed_submits_only_missing_symbols_and_records_orders(self) -> None:
        submitted = []
        saved_orders = []

        class FakeClient:
            def get_positions(self, _context):
                return [{"quantity": 0.01, "instrument": {"ticker": "VODl_EQ"}}]

            def get_orders(self, _context):
                return []

            def get_instruments(self, _context):
                return [
                    {"ticker": "VODl_EQ", "currencyCode": "GBX"},
                    {"ticker": "SHELl_EQ", "currencyCode": "GBX"},
                ]

            def submit_market_order(self, _context, *, order_request):
                submitted.append(order_request)
                return {
                    "id": 222,
                    "ticker": order_request["ticker"],
                    "quantity": order_request["quantity"],
                    "filledQuantity": order_request["quantity"],
                    "status": "FILLED",
                    "currency": "GBP",
                    "createdAt": "2026-06-02T15:00:00Z",
                }

        def record_paper_trade_orders(**kwargs):
            saved_orders.extend(kwargs["orders"])
            return len(kwargs["orders"])

        with TemporaryDirectory() as tmpdir:
            seeder = Trading212PriceSeeder(
                config=self._config(),
                ledger=SimpleNamespace(record_paper_trade_orders=record_paper_trade_orders),
                client_factory=lambda _config: FakeClient(),
                instrument_cache_path=Path(tmpdir) / "instruments.json",
            )

            result = seeder.run(confirm=True)

        self.assertEqual(result["mode"], "seed_orders")
        self.assertEqual(result["orders_submitted"], 1)
        self.assertEqual(result["orders_saved"], 1)
        self.assertEqual(submitted[0]["ticker"], "SHELl_EQ")
        self.assertEqual(submitted[0]["quantity"], "0.01")
        self.assertEqual(result["skipped"][0]["reason"], "already_held")
        self.assertTrue(saved_orders[0]["raw_json"]["price_seed_only"])

    def test_seed_retries_broker_reported_minimum_quantity(self) -> None:
        submitted = []

        class FakeClient:
            def get_positions(self, _context):
                return []

            def get_orders(self, _context):
                return []

            def get_instruments(self, _context):
                return [{"ticker": "VODl_EQ", "currencyCode": "GBX"}]

            def submit_market_order(self, _context, *, order_request):
                submitted.append(order_request)
                if len(submitted) == 1:
                    raise Trading212ApiError(
                        "Trading 212 API HTTP 400 on /equity/orders/market: Bad Request: "
                        '{"detail":"must trade at least 0.89101624"}'
                    )
                return {
                    "id": 333,
                    "ticker": order_request["ticker"],
                    "quantity": order_request["quantity"],
                    "filledQuantity": order_request["quantity"],
                    "status": "NEW",
                }

        config = self._config()
        config.trading212_paper_price_seed_symbols = ("VOD",)
        config.trading212_paper_equity_symbols = ("VOD",)
        with TemporaryDirectory() as tmpdir:
            seeder = Trading212PriceSeeder(
                config=config,
                ledger=SimpleNamespace(record_paper_trade_orders=lambda **kwargs: len(kwargs["orders"])),
                client_factory=lambda _config: FakeClient(),
                instrument_cache_path=Path(tmpdir) / "instruments.json",
            )

            result = seeder.run(confirm=True)

        self.assertEqual(result["orders_submitted"], 1)
        self.assertEqual(submitted[0]["quantity"], "0.01")
        self.assertEqual(submitted[1]["quantity"], "0.9")
        self.assertEqual(result["orders"][0]["qty"], 0.9)

    def test_seed_uses_mapped_symbol_when_venue_ticker_differs(self) -> None:
        class FakeClient:
            def get_positions(self, _context):
                return [{"quantity": 0.02, "instrument": {"ticker": "LSEl_EQ"}}]

            def get_orders(self, _context):
                return []

            def get_instruments(self, _context):
                return [{"ticker": "LSEl_EQ", "name": "London Stock Exchange Group"}]

            def submit_market_order(self, _context, *, order_request):
                raise AssertionError("LSEG seed should be recognized as already held")

        config = self._config()
        config.trading212_paper_price_seed_symbols = ("LSEG",)
        config.trading212_paper_equity_symbols = ("LSEG",)
        config.trading212_paper_ticker_overrides = {"LSEG": "LSEl_EQ"}
        with TemporaryDirectory() as tmpdir:
            seeder = Trading212PriceSeeder(
                config=config,
                ledger=SimpleNamespace(record_paper_trade_orders=lambda **kwargs: len(kwargs["orders"])),
                client_factory=lambda _config: FakeClient(),
                instrument_cache_path=Path(tmpdir) / "instruments.json",
            )

            result = seeder.run(confirm=False)

        self.assertEqual(result["orders"], [])
        self.assertEqual(result["skipped"][0]["symbol"], "LSEG")
        self.assertEqual(result["skipped"][0]["reason"], "already_held")

    def test_seed_uses_ticker_override_without_metadata_fetch(self) -> None:
        class FakeClient:
            def get_positions(self, _context):
                return []

            def get_orders(self, _context):
                return []

            def get_instruments(self, _context):
                raise AssertionError("override should avoid metadata fetch")

            def submit_market_order(self, _context, *, order_request):
                return {
                    "id": 444,
                    "ticker": order_request["ticker"],
                    "quantity": order_request["quantity"],
                    "filledQuantity": order_request["quantity"],
                    "status": "NEW",
                }

        config = self._config()
        config.trading212_paper_price_seed_symbols = ("SHEL",)
        config.trading212_paper_equity_symbols = ("SHEL",)
        config.trading212_paper_ticker_overrides = {"SHEL": "SHELl_EQ"}
        with TemporaryDirectory() as tmpdir:
            seeder = Trading212PriceSeeder(
                config=config,
                ledger=SimpleNamespace(record_paper_trade_orders=lambda **kwargs: len(kwargs["orders"])),
                client_factory=lambda _config: FakeClient(),
                instrument_cache_path=Path(tmpdir) / "missing.json",
            )

            result = seeder.run(confirm=True)

        self.assertEqual(result["orders_submitted"], 1)
        self.assertEqual(result["orders"][0]["venue_symbol"], "SHELl_EQ")

    def test_seed_quantity_is_capped(self) -> None:
        seeder = Trading212PriceSeeder(
            config=self._config(),
            ledger=SimpleNamespace(record_paper_trade_orders=lambda **_kwargs: 0),
            client_factory=lambda _config: None,
            instrument_cache_path=Path("/tmp/nonexistent-centaur-test-cache.json"),
        )

        with self.assertRaisesRegex(ValueError, "capped"):
            seeder.run(confirm=False, quantity="0.02")

    def test_seed_fails_closed_if_trading212_live_enabled(self) -> None:
        config = self._config()
        config.trading212_live_execution_enabled = True
        seeder = Trading212PriceSeeder(
            config=config,
            ledger=SimpleNamespace(record_paper_trade_orders=lambda **_kwargs: 0),
            client_factory=lambda _config: None,
            instrument_cache_path=Path("/tmp/nonexistent-centaur-test-cache.json"),
        )

        result = seeder.run(confirm=True)

        self.assertEqual(result["mode"], "skipped")
        self.assertEqual(result["reason"], "trading212_live_must_be_disabled_for_seed")


if __name__ == "__main__":
    unittest.main()
