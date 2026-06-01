from __future__ import annotations

from math import log10
from typing import Any

from app.core.instruments import instrument_ref_from_metadata

from .base import StrategyProfile, StrategySignal


def build_signal(
    *,
    profile: StrategyProfile,
    candidate: dict[str, Any],
    entry_price: float,
    entry_price_gbp: float | None,
    signal_score: float,
    confidence: float,
    movement_pct: float | None,
    discovery_score: float,
    rationale: str,
    note: str,
) -> StrategySignal:
    stop_loss_price = round(entry_price * (1.0 - profile.stop_loss_pct), 8)
    target_price = round(entry_price * (1.0 + (profile.stop_loss_pct * profile.target_multiple)), 8)
    stop_loss_price_gbp = (
        round(entry_price_gbp * (1.0 - profile.stop_loss_pct), 8)
        if entry_price_gbp is not None
        else None
    )
    target_price_gbp = (
        round(entry_price_gbp * (1.0 + (profile.stop_loss_pct * profile.target_multiple)), 8)
        if entry_price_gbp is not None
        else None
    )
    risk_pct = round(profile.stop_loss_pct * 100.0, 4)
    target_return_pct = round(profile.stop_loss_pct * profile.target_multiple * 100.0, 4)

    return StrategySignal(
        strategy_id=profile.strategy_id,
        strategy_family=profile.family,
        profile_id=profile.profile_id,
        source=str(candidate.get("source", "")),
        symbol=normalized_symbol(candidate),
        asset_class=normalized_asset_class(candidate) or "",
        canonical_instrument_id=str(candidate.get("canonical_instrument_id", "")),
        venue=str(candidate.get("venue", "")),
        venue_symbol=str(candidate.get("venue_symbol", "")),
        instrument_ref=instrument_ref_from_metadata(candidate),
        direction="long",
        signal_rank=0,
        signal_score=signal_score,
        confidence=confidence,
        entry_price=round(entry_price, 8),
        entry_price_gbp=round(entry_price_gbp, 8) if entry_price_gbp is not None else None,
        stop_loss_price=stop_loss_price,
        stop_loss_price_gbp=stop_loss_price_gbp,
        target_price=target_price,
        target_price_gbp=target_price_gbp,
        risk_pct=risk_pct,
        target_return_pct=target_return_pct,
        holding_window_code=profile.holding_window_code,
        holding_window_minutes=profile.holding_window_minutes,
        movement_pct=movement_pct,
        discovery_score=round(discovery_score, 6),
        rationale=rationale,
        note=note,
    )


def window_code_to_minutes(code: str) -> int:
    normalized = code.strip().lower()
    if len(normalized) < 2:
        raise ValueError(f"Unsupported strategy window: {code}")

    suffix = normalized[-1]
    value = int(normalized[:-1])
    if value <= 0:
        raise ValueError(f"Strategy window must be positive: {code}")
    if suffix == "m":
        return value
    if suffix == "h":
        return value * 60
    if suffix == "d":
        return value * 60 * 24
    raise ValueError(f"Unsupported strategy window: {code}")


def liquidity_component(*, volume: int | None, trade_count: int | None) -> float:
    return round(log10((volume or 0) + 1) + log10((trade_count or 0) + 1), 6)


def normalized_asset_class(candidate: dict[str, Any]) -> str:
    return str(candidate.get("asset_class") or "").strip().lower()


def normalized_symbol(candidate: dict[str, Any]) -> str:
    return str(candidate.get("symbol") or "").strip().upper()


def has_strategy_identity(candidate: dict[str, Any]) -> bool:
    return bool(normalized_symbol(candidate)) and bool(
        str(candidate.get("canonical_instrument_id") or "").strip()
    )


def record_rejection(
    *,
    market_context: dict[str, Any],
    profile: StrategyProfile,
    candidate: dict[str, Any],
    reason: str,
    metrics: dict[str, Any] | None = None,
) -> None:
    """Append a bounded, later-summarised reject event for audit/reporting."""
    sink = market_context.get("strategy_rejections")
    if not isinstance(sink, list):
        return
    sink.append(
        {
            "strategy_id": profile.strategy_id,
            "strategy_family": profile.family,
            "profile_id": profile.profile_id,
            "reason": reason,
            "symbol": normalized_symbol(candidate),
            "asset_class": normalized_asset_class(candidate),
            "canonical_instrument_id": str(
                candidate.get("canonical_instrument_id") or ""
            ).strip(),
            "metrics": metrics or {},
        }
    )


def to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def convert_with_ratio(value: float | None, ratio: float | None) -> float | None:
    if value is None or ratio is None:
        return None
    return round(value * ratio, 8)
