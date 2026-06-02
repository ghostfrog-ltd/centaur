from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from app.framework.core.instruments import InstrumentRef
from app.framework.runtime.settings import RuntimeConfig


@dataclass(frozen=True, slots=True)
class StrategyProfile:
    strategy_id: str
    family: str
    profile_id: str
    label: str
    asset_classes: tuple[str, ...]
    holding_window_code: str
    holding_window_minutes: int
    stop_loss_pct: float
    target_multiple: float
    max_signals_per_tick: int
    min_signal_score: float
    parameters: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class StrategySignal:
    strategy_id: str
    strategy_family: str
    profile_id: str
    source: str
    symbol: str
    asset_class: str
    direction: str
    signal_rank: int
    signal_score: float
    confidence: float
    entry_price: float
    entry_price_gbp: float | None
    stop_loss_price: float
    stop_loss_price_gbp: float | None
    target_price: float
    target_price_gbp: float | None
    risk_pct: float
    target_return_pct: float
    holding_window_code: str
    holding_window_minutes: int
    movement_pct: float | None
    discovery_score: float
    rationale: str
    note: str
    atr_value: float | None = None
    atr_pct: float | None = None
    breakout_high_price: float | None = None
    avg_volume_lookback: float | None = None
    volume_ratio: float | None = None
    break_even_trigger_price: float | None = None
    break_even_trigger_price_gbp: float | None = None
    trailing_stop_mode: str = ""
    canonical_instrument_id: str = ""
    venue: str = ""
    venue_symbol: str = ""
    instrument_ref: InstrumentRef | None = None

    def with_rank(self, rank: int) -> "StrategySignal":
        return StrategySignal(
            strategy_id=self.strategy_id,
            strategy_family=self.strategy_family,
            profile_id=self.profile_id,
            source=self.source,
            symbol=self.symbol,
            asset_class=self.asset_class,
            direction=self.direction,
            signal_rank=rank,
            signal_score=self.signal_score,
            confidence=self.confidence,
            entry_price=self.entry_price,
            entry_price_gbp=self.entry_price_gbp,
            stop_loss_price=self.stop_loss_price,
            stop_loss_price_gbp=self.stop_loss_price_gbp,
            target_price=self.target_price,
            target_price_gbp=self.target_price_gbp,
            risk_pct=self.risk_pct,
            target_return_pct=self.target_return_pct,
            holding_window_code=self.holding_window_code,
            holding_window_minutes=self.holding_window_minutes,
            movement_pct=self.movement_pct,
            discovery_score=self.discovery_score,
            rationale=self.rationale,
            note=self.note,
            atr_value=self.atr_value,
            atr_pct=self.atr_pct,
            breakout_high_price=self.breakout_high_price,
            avg_volume_lookback=self.avg_volume_lookback,
            volume_ratio=self.volume_ratio,
            break_even_trigger_price=self.break_even_trigger_price,
            break_even_trigger_price_gbp=self.break_even_trigger_price_gbp,
            trailing_stop_mode=self.trailing_stop_mode,
            canonical_instrument_id=self.canonical_instrument_id,
            venue=self.venue,
            venue_symbol=self.venue_symbol,
            instrument_ref=self.instrument_ref,
        )

    def as_dict(self, *, tick_id: str) -> dict[str, Any]:
        payload = {
            "tick_id": tick_id,
            "strategy_id": self.strategy_id,
            "strategy_family": self.strategy_family,
            "profile_id": self.profile_id,
            "source": self.source,
            "symbol": self.symbol,
            "asset_class": self.asset_class,
            "canonical_instrument_id": self.canonical_instrument_id,
            "venue": self.venue,
            "venue_symbol": self.venue_symbol,
            "direction": self.direction,
            "signal_rank": self.signal_rank,
            "signal_score": self.signal_score,
            "confidence": self.confidence,
            "entry_price": self.entry_price,
            "entry_price_gbp": self.entry_price_gbp,
            "stop_loss_price": self.stop_loss_price,
            "stop_loss_price_gbp": self.stop_loss_price_gbp,
            "target_price": self.target_price,
            "target_price_gbp": self.target_price_gbp,
            "risk_pct": self.risk_pct,
            "target_return_pct": self.target_return_pct,
            "holding_window_code": self.holding_window_code,
            "holding_window_minutes": self.holding_window_minutes,
            "movement_pct": self.movement_pct,
            "discovery_score": self.discovery_score,
            "rationale": self.rationale,
            "note": self.note,
            "atr_value": self.atr_value,
            "atr_pct": self.atr_pct,
            "breakout_high_price": self.breakout_high_price,
            "avg_volume_lookback": self.avg_volume_lookback,
            "volume_ratio": self.volume_ratio,
            "break_even_trigger_price": self.break_even_trigger_price,
            "break_even_trigger_price_gbp": self.break_even_trigger_price_gbp,
            "trailing_stop_mode": self.trailing_stop_mode,
        }
        if self.instrument_ref is not None:
            payload["instrument_ref"] = self.instrument_ref.as_dict()
        return payload


@dataclass(frozen=True, slots=True)
class StrategyEvaluationBatch:
    signals: list[StrategySignal]
    family_count: int
    profile_count: int
    rejection_summary: dict[str, Any] = field(default_factory=dict)


class StrategyDefinition:
    family = "base"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        raise NotImplementedError

    def evaluate_candidate(
        self,
        *,
        profile: StrategyProfile,
        candidate: dict[str, Any],
        market_context: dict[str, Any],
    ) -> StrategySignal | None:
        raise NotImplementedError

    def evaluate_profile(
        self,
        *,
        profile: StrategyProfile,
        candidates: list[dict[str, Any]],
        market_context: dict[str, Any],
    ) -> list[StrategySignal]:
        matched: list[StrategySignal] = []
        for candidate in candidates:
            signal = self.evaluate_candidate(
                profile=profile,
                candidate=candidate,
                market_context=market_context,
            )
            if signal is not None:
                matched.append(signal)

        matched.sort(
            key=lambda item: (item.signal_score, item.confidence, item.symbol),
            reverse=True,
        )
        limited = matched[: max(1, profile.max_signals_per_tick)]
        return [item.with_rank(index) for index, item in enumerate(limited, start=1)]
