from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class CanonicalInstrument:
    canonical_instrument_id: str
    base_asset: str
    quote_asset: str
    asset_class: str
    instrument_type: str

    @property
    def asset_market(self) -> str:
        return self.asset_class


@dataclass(frozen=True, slots=True)
class VenueSymbolMapping:
    venue: str
    venue_symbol: str
    canonical_instrument_id: str
    can_use_for_signals: bool
    can_use_for_execution: bool
    priority: int = 100


@dataclass(frozen=True, slots=True)
class InstrumentRef:
    """Resolved instrument identity at a specific venue."""

    canonical_instrument_id: str
    venue: str
    venue_symbol: str
    asset_class: str = ""

    def as_metadata(self) -> dict[str, str]:
        return {
            "canonical_instrument_id": self.canonical_instrument_id,
            "venue": self.venue,
            "venue_symbol": self.venue_symbol,
        }

    def as_dict(self) -> dict[str, str]:
        return {
            **self.as_metadata(),
            "asset_class": self.asset_class,
        }


class InstrumentRegistry:
    def __init__(
        self,
        *,
        instruments: list[CanonicalInstrument],
        mappings: list[VenueSymbolMapping],
    ) -> None:
        self._instruments = {
            _normalize_identifier(item.canonical_instrument_id): item
            for item in instruments
        }
        self._mappings = {
            (_normalize_venue(item.venue), _normalize_symbol(item.venue_symbol)): item
            for item in mappings
        }
        self._mappings_by_canonical: dict[str, list[VenueSymbolMapping]] = {}
        for item in sorted(mappings, key=lambda value: value.priority):
            self._mappings_by_canonical.setdefault(
                _normalize_identifier(item.canonical_instrument_id),
                [],
            ).append(item)

    def get(self, canonical_instrument_id: str) -> CanonicalInstrument | None:
        return self._instruments.get(_normalize_identifier(canonical_instrument_id))

    def resolve_venue_symbol(
        self,
        *,
        venue: str,
        venue_symbol: str,
    ) -> tuple[CanonicalInstrument, VenueSymbolMapping] | None:
        mapping = self._mappings.get(
            (_normalize_venue(venue), _normalize_symbol(venue_symbol))
        )
        if mapping is None:
            return None
        instrument = self._instruments.get(mapping.canonical_instrument_id)
        if instrument is None:
            return None
        return instrument, mapping

    def execution_symbol_for(
        self,
        *,
        canonical_instrument_id: str,
        venue: str,
    ) -> VenueSymbolMapping | None:
        target_venue = _normalize_venue(venue)
        candidates = self._mappings_by_canonical.get(
            _normalize_identifier(canonical_instrument_id),
            [],
        )
        for item in candidates:
            if (
                _normalize_venue(item.venue) == target_venue
                and item.can_use_for_execution
            ):
                return item
        return None

    def reference_for(
        self,
        *,
        venue: str,
        venue_symbol: str,
        asset_class: str = "",
        canonical_instrument_id: str = "",
    ) -> InstrumentRef:
        normalized_venue = _normalize_venue(venue)
        normalized_symbol = _normalize_symbol(venue_symbol)
        normalized_canonical = _normalize_identifier(canonical_instrument_id)
        resolved = (
            self.resolve_venue_symbol(
                venue=normalized_venue,
                venue_symbol=normalized_symbol,
            )
            if normalized_venue and normalized_symbol
            else None
        )
        if resolved is not None:
            instrument, mapping = resolved
            return InstrumentRef(
                canonical_instrument_id=instrument.canonical_instrument_id,
                venue=mapping.venue,
                venue_symbol=mapping.venue_symbol,
                asset_class=instrument.asset_class,
            )
        return InstrumentRef(
            canonical_instrument_id=normalized_canonical,
            venue=normalized_venue,
            venue_symbol=normalized_symbol,
            asset_class=str(asset_class or "").strip().lower(),
        )


def default_instrument_registry() -> InstrumentRegistry:
    return InstrumentRegistry(
        instruments=[
            CanonicalInstrument(
                canonical_instrument_id="BTC-USD-SPOT",
                base_asset="BTC",
                quote_asset="USD",
                asset_class="crypto",
                instrument_type="spot",
            ),
            CanonicalInstrument(
                canonical_instrument_id="ETH-USD-SPOT",
                base_asset="ETH",
                quote_asset="USD",
                asset_class="crypto",
                instrument_type="spot",
            ),
            CanonicalInstrument(
                canonical_instrument_id="AAPL-US-EQUITY",
                base_asset="AAPL",
                quote_asset="USD",
                asset_class="equity",
                instrument_type="stock",
            ),
        ],
        mappings=[
            VenueSymbolMapping(
                venue="alpaca",
                venue_symbol="BTC/USD",
                canonical_instrument_id="BTC-USD-SPOT",
                can_use_for_signals=True,
                can_use_for_execution=True,
                priority=10,
            ),
            VenueSymbolMapping(
                venue="binance",
                venue_symbol="BTCUSDT",
                canonical_instrument_id="BTC-USD-SPOT",
                can_use_for_signals=True,
                can_use_for_execution=False,
                priority=20,
            ),
            VenueSymbolMapping(
                venue="coinbase",
                venue_symbol="BTC-USD",
                canonical_instrument_id="BTC-USD-SPOT",
                can_use_for_signals=True,
                can_use_for_execution=False,
                priority=30,
            ),
            VenueSymbolMapping(
                venue="alpaca",
                venue_symbol="ETH/USD",
                canonical_instrument_id="ETH-USD-SPOT",
                can_use_for_signals=True,
                can_use_for_execution=True,
                priority=10,
            ),
            VenueSymbolMapping(
                venue="alpaca",
                venue_symbol="AAPL",
                canonical_instrument_id="AAPL-US-EQUITY",
                can_use_for_signals=True,
                can_use_for_execution=True,
                priority=10,
            ),
        ],
    )


def instrument_ref_from_metadata(values: dict[str, Any]) -> InstrumentRef | None:
    canonical_id = str(values.get("canonical_instrument_id") or "").strip()
    venue = str(values.get("venue") or "").strip()
    venue_symbol = str(values.get("venue_symbol") or "").strip()
    if not (canonical_id or venue or venue_symbol):
        return None
    return InstrumentRef(
        canonical_instrument_id=canonical_id,
        venue=venue,
        venue_symbol=venue_symbol,
        asset_class=str(values.get("asset_class") or "").strip().lower(),
    )


def _normalize_venue(value: str) -> str:
    return str(value or "").strip().lower()


def _normalize_symbol(value: str) -> str:
    return str(value or "").strip().upper()


def _normalize_identifier(value: str) -> str:
    return str(value or "").strip().upper()
