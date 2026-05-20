from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from math import log10
from typing import Any


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    symbol: str
    source: str
    asset_class: str
    rank: int
    selected: bool
    discovery_score: float
    close_price: float | None
    close_price_gbp: float | None
    previous_close_price: float | None
    movement_pct: float | None
    volume: int | None
    trade_count: int | None
    bar_timestamp: str | None
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "symbol": self.symbol,
            "source": self.source,
            "asset_class": self.asset_class,
            "rank": self.rank,
            "selected": self.selected,
            "discovery_score": self.discovery_score,
            "close_price": self.close_price,
            "close_price_gbp": self.close_price_gbp,
            "previous_close_price": self.previous_close_price,
            "movement_pct": self.movement_pct,
            "volume": self.volume,
            "trade_count": self.trade_count,
            "bar_timestamp": _normalize_timestamp(self.bar_timestamp),
            "note": self.note,
        }


def rank_candidates(
    *,
    current_rows: list[dict[str, Any]],
    previous_by_symbol: dict[tuple[str, str], dict[str, Any]],
    target_count: int,
) -> list[RankedCandidate]:
    scored_rows: list[RankedCandidate] = []

    for row in current_rows:
        symbol = str(row["symbol"])
        source = str(row["source"])
        asset_class = _asset_class_for_source(source)
        close_price = _to_float(row.get("close_price"))
        close_price_gbp = _to_float(row.get("close_price_gbp"))
        previous_row = previous_by_symbol.get((source, symbol))
        previous_close = _to_float(previous_row.get("close_price")) if previous_row else None
        movement_pct = _movement_pct(close_price, previous_close)
        volume = _to_int(row.get("volume"))
        trade_count = _to_int(row.get("trade_count"))
        liquidity_score = _liquidity_score(volume=volume, trade_count=trade_count)
        movement_score = abs(movement_pct) if movement_pct is not None else 0.0
        discovery_score = round((movement_score * 10.0) + liquidity_score, 6)
        note = "movement_and_liquidity"
        if previous_close is None:
            note = "liquidity_only_no_history"

        scored_rows.append(
            RankedCandidate(
                symbol=symbol,
                source=source,
                asset_class=asset_class,
                rank=0,
                selected=False,
                discovery_score=discovery_score,
                close_price=close_price,
                close_price_gbp=close_price_gbp,
                previous_close_price=previous_close,
                movement_pct=movement_pct,
                volume=volume,
                trade_count=trade_count,
                bar_timestamp=row.get("bar_timestamp"),
                note=note,
            )
        )

    scored_rows.sort(
        key=lambda item: (
            item.discovery_score,
            abs(item.movement_pct or 0.0),
            item.trade_count or 0,
            item.volume or 0,
            item.symbol,
        ),
        reverse=True,
    )

    ranked_rows: list[RankedCandidate] = []
    for index, item in enumerate(scored_rows, start=1):
        ranked_rows.append(
            RankedCandidate(
                symbol=item.symbol,
                source=item.source,
                asset_class=item.asset_class,
                rank=index,
                selected=index <= target_count,
                discovery_score=item.discovery_score,
                close_price=item.close_price,
                close_price_gbp=item.close_price_gbp,
                previous_close_price=item.previous_close_price,
                movement_pct=item.movement_pct,
                volume=item.volume,
                trade_count=item.trade_count,
                bar_timestamp=item.bar_timestamp,
                note=item.note,
            )
        )
    return ranked_rows


def _asset_class_for_source(source: str) -> str:
    if source == "alpaca_crypto_data":
        return "crypto"
    return "equity"


def _movement_pct(current: float | None, previous: float | None) -> float | None:
    if current is None or previous is None or previous == 0:
        return None
    return round(((current - previous) / previous) * 100.0, 6)


def _liquidity_score(*, volume: int | None, trade_count: int | None) -> float:
    volume_component = log10((volume or 0) + 1)
    trades_component = log10((trade_count or 0) + 1)
    return round(volume_component + trades_component, 6)


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _normalize_timestamp(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return str(value)
