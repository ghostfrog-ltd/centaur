from __future__ import annotations

import unittest

from app.framework.core.instruments import default_instrument_registry
from app.framework.core.instruments import instrument_ref_from_metadata


class InstrumentRegistryTests(unittest.TestCase):
    def test_vendor_symbols_resolve_to_same_canonical_instrument(self) -> None:
        registry = default_instrument_registry()

        alpaca = registry.resolve_venue_symbol(
            venue="alpaca",
            venue_symbol="BTC/USD",
        )
        binance = registry.resolve_venue_symbol(
            venue="binance",
            venue_symbol="BTCUSDT",
        )

        self.assertIsNotNone(alpaca)
        self.assertIsNotNone(binance)
        assert alpaca is not None
        assert binance is not None
        alpaca_instrument, alpaca_mapping = alpaca
        binance_instrument, binance_mapping = binance

        self.assertEqual(
            alpaca_instrument.canonical_instrument_id,
            "BTC-USD-SPOT",
        )
        self.assertEqual(
            binance_instrument.canonical_instrument_id,
            "BTC-USD-SPOT",
        )
        self.assertEqual(alpaca_mapping.venue, "alpaca")
        self.assertEqual(binance_mapping.venue, "binance")
        self.assertNotEqual(alpaca_mapping.venue_symbol, binance_mapping.venue_symbol)

    def test_execution_mapping_is_venue_specific(self) -> None:
        registry = default_instrument_registry()

        alpaca = registry.execution_symbol_for(
            canonical_instrument_id="BTC-USD-SPOT",
            venue="alpaca",
        )
        binance = registry.execution_symbol_for(
            canonical_instrument_id="BTC-USD-SPOT",
            venue="binance",
        )

        self.assertIsNotNone(alpaca)
        assert alpaca is not None
        self.assertEqual(alpaca.venue_symbol, "BTC/USD")
        self.assertIsNone(binance)

    def test_reference_for_returns_first_class_instrument_ref(self) -> None:
        registry = default_instrument_registry()

        ref = registry.reference_for(
            venue="alpaca",
            venue_symbol="BTC/USD",
            asset_class="crypto",
        )

        self.assertEqual(ref.canonical_instrument_id, "BTC-USD-SPOT")
        self.assertEqual(ref.venue, "alpaca")
        self.assertEqual(ref.venue_symbol, "BTC/USD")
        self.assertEqual(ref.asset_class, "crypto")
        self.assertEqual(
            ref.as_metadata(),
            {
                "canonical_instrument_id": "BTC-USD-SPOT",
                "venue": "alpaca",
                "venue_symbol": "BTC/USD",
            },
        )
        self.assertEqual(ref.as_dict()["asset_class"], "crypto")

    def test_instrument_ref_from_metadata_preserves_first_class_identity(self) -> None:
        ref = instrument_ref_from_metadata(
            {
                "canonical_instrument_id": "BTC-USD-SPOT",
                "venue": "alpaca",
                "venue_symbol": "BTC/USD",
                "asset_class": "crypto",
            }
        )

        self.assertIsNotNone(ref)
        assert ref is not None
        self.assertEqual(ref.canonical_instrument_id, "BTC-USD-SPOT")
        self.assertEqual(ref.as_dict()["asset_class"], "crypto")

    def test_reference_for_preserves_unknown_vendor_mapping(self) -> None:
        registry = default_instrument_registry()

        ref = registry.reference_for(
            venue="polygon",
            venue_symbol="MSFT",
            asset_class="equity",
            canonical_instrument_id="MSFT-US-EQUITY",
        )

        self.assertEqual(ref.canonical_instrument_id, "MSFT-US-EQUITY")
        self.assertEqual(ref.venue, "polygon")
        self.assertEqual(ref.venue_symbol, "MSFT")
        self.assertEqual(ref.asset_class, "equity")


if __name__ == "__main__":
    unittest.main()
