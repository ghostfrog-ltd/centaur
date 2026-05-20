from __future__ import annotations

from datetime import datetime
from typing import Any


def build_live_bar_row(
    *,
    source: str,
    symbol: str,
    raw_bar: dict[str, Any],
    close_price_gbp: float | None = None,
) -> dict[str, Any]:
    close_price = _to_float(raw_bar.get("c"))
    open_price = _to_float(raw_bar.get("o"))
    high_price = _to_float(raw_bar.get("h"))
    low_price = _to_float(raw_bar.get("l"))
    quote_ratio = (
        (close_price_gbp / close_price)
        if close_price_gbp is not None and close_price not in (None, 0)
        else None
    )
    bar_timestamp = _to_datetime(raw_bar.get("t"))
    return {
        "source": source,
        "symbol": symbol,
        "captured_at": bar_timestamp,
        "bar_timestamp": bar_timestamp,
        "open_price": open_price,
        "high_price": high_price,
        "low_price": low_price,
        "close_price": close_price,
        "open_price_gbp": _convert_with_ratio(open_price, quote_ratio),
        "high_price_gbp": _convert_with_ratio(high_price, quote_ratio),
        "low_price_gbp": _convert_with_ratio(low_price, quote_ratio),
        "close_price_gbp": close_price_gbp,
        "volume": _to_float(raw_bar.get("v")),
        "trade_count": _to_int(raw_bar.get("n")),
    }


def merge_bar_rows(
    *,
    historical_rows: list[dict[str, Any]],
    live_row: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for row in historical_rows:
        timestamp = _bar_sort_key(row)
        if timestamp is None:
            continue
        merged[timestamp.isoformat()] = dict(row)
    if live_row:
        timestamp = _bar_sort_key(live_row)
        if timestamp is not None:
            merged[timestamp.isoformat()] = dict(live_row)
    rows = list(merged.values())
    rows.sort(key=_bar_sort_key_or_min)
    return rows


def compute_volatility_breakout_context(
    *,
    bars: list[dict[str, Any]],
    lookback_periods: int = 20,
) -> dict[str, Any]:
    result = {
        "technical_context_ready": False,
        "technical_lookback_periods": lookback_periods,
        "technical_bars_available": len(bars),
        "breakout_high_20": None,
        "avg_volume_20": None,
        "atr_20": None,
        "atr_pct_20": None,
        "current_price": None,
        "current_volume": None,
        "volume_ratio_20": None,
        "breakout_margin_pct_20": None,
        "price_trigger_20": False,
        "volume_surge_20": False,
        "volatility_floor_pass_20": False,
    }
    if lookback_periods <= 0:
        return result

    ordered = list(bars)
    ordered.sort(key=_bar_sort_key_or_min)
    if len(ordered) < lookback_periods + 1:
        return result

    current_bar = ordered[-1]
    lookback_rows = ordered[-(lookback_periods + 1) : -1]
    current_price = _to_float(current_bar.get("close_price"))
    current_volume = _to_float(current_bar.get("volume"))
    breakout_high = _max_value(lookback_rows, "high_price")
    avg_volume = _average_value(lookback_rows, "volume")
    atr_value = _average_true_range(lookback_rows)
    volume_ratio = (
        round(current_volume / avg_volume, 6)
        if current_volume is not None and avg_volume not in (None, 0)
        else None
    )
    breakout_margin_pct = (
        round(((current_price - breakout_high) / breakout_high) * 100.0, 6)
        if current_price is not None and breakout_high not in (None, 0)
        else None
    )
    atr_pct = (
        round((atr_value / current_price) * 100.0, 6)
        if atr_value is not None and current_price not in (None, 0)
        else None
    )

    result.update(
        {
            "technical_context_ready": True,
            "technical_bars_available": len(ordered),
            "breakout_high_20": breakout_high,
            "avg_volume_20": avg_volume,
            "atr_20": atr_value,
            "atr_pct_20": atr_pct,
            "current_price": current_price,
            "current_volume": current_volume,
            "volume_ratio_20": volume_ratio,
            "breakout_margin_pct_20": breakout_margin_pct,
            "price_trigger_20": bool(
                current_price is not None
                and breakout_high is not None
                and current_price > breakout_high
            ),
            "volume_surge_20": bool(volume_ratio is not None and volume_ratio > 2.0),
            "volatility_floor_pass_20": bool(atr_pct is not None and atr_pct > 1.0),
        }
    )
    return result


def _average_true_range(rows: list[dict[str, Any]]) -> float | None:
    ranges: list[float] = []
    previous_close: float | None = None
    for row in rows:
        high = _to_float(row.get("high_price"))
        low = _to_float(row.get("low_price"))
        close = _to_float(row.get("close_price"))
        open_price = _to_float(row.get("open_price"))
        if high is None or low is None:
            continue
        reference_close = previous_close
        if reference_close is None:
            reference_close = close if close is not None else open_price
        if reference_close is None:
            true_range = high - low
        else:
            true_range = max(
                high - low,
                abs(high - reference_close),
                abs(low - reference_close),
            )
        ranges.append(true_range)
        previous_close = close if close is not None else previous_close
    if not ranges:
        return None
    return round(sum(ranges) / len(ranges), 8)


def _average_value(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [value for value in (_to_float(row.get(key)) for row in rows) if value is not None]
    if not values:
        return None
    return round(sum(values) / len(values), 8)


def _max_value(rows: list[dict[str, Any]], key: str) -> float | None:
    values = [value for value in (_to_float(row.get(key)) for row in rows) if value is not None]
    if not values:
        return None
    return round(max(values), 8)


def _convert_with_ratio(value: float | None, ratio: float | None) -> float | None:
    if value is None or ratio is None:
        return None
    return round(value * ratio, 8)


def _bar_sort_key(row: dict[str, Any]) -> datetime | None:
    return _to_datetime(row.get("bar_timestamp")) or _to_datetime(row.get("captured_at"))


def _bar_sort_key_or_min(row: dict[str, Any]) -> datetime:
    return _bar_sort_key(row) or datetime.min


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    normalized = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except ValueError:
        return None


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
        return int(float(value))
    except (TypeError, ValueError):
        return None
