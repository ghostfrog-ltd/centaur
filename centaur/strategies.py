from __future__ import annotations

from dataclasses import dataclass, field
from math import log10
from typing import Any

from .config import RuntimeConfig


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
        )

    def as_dict(self, *, tick_id: str) -> dict[str, Any]:
        return {
            "tick_id": tick_id,
            "strategy_id": self.strategy_id,
            "strategy_family": self.strategy_family,
            "profile_id": self.profile_id,
            "source": self.source,
            "symbol": self.symbol,
            "asset_class": self.asset_class,
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


@dataclass(frozen=True, slots=True)
class StrategyEvaluationBatch:
    signals: list[StrategySignal]
    family_count: int
    profile_count: int


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


class MomentumStrategy(StrategyDefinition):
    family = "momentum"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        base_stop = max(config.shadow_stop_loss_pct, 0.01)
        return [
            StrategyProfile(
                strategy_id="momentum.balanced",
                family=self.family,
                profile_id="balanced",
                label="Momentum Balanced",
                asset_classes=("equity", "crypto"),
                holding_window_code="1h",
                holding_window_minutes=_window_code_to_minutes("1h"),
                stop_loss_pct=base_stop,
                target_multiple=max(config.shadow_target_multiple, 1.5),
                max_signals_per_tick=2,
                min_signal_score=max(55.0, config.shadow_min_opportunity_score),
                parameters={
                    "min_movement_pct": 0.08,
                    "min_discovery_score": 4.5,
                    "min_trade_count": 40,
                },
            ),
            StrategyProfile(
                strategy_id="momentum.strong",
                family=self.family,
                profile_id="strong",
                label="Momentum Strong",
                asset_classes=("equity",),
                holding_window_code="1d",
                holding_window_minutes=_window_code_to_minutes("1d"),
                stop_loss_pct=base_stop,
                target_multiple=max(config.shadow_target_multiple + 0.5, 2.0),
                max_signals_per_tick=1,
                min_signal_score=max(65.0, config.shadow_min_opportunity_score),
                parameters={
                    "min_movement_pct": 0.2,
                    "min_discovery_score": 5.2,
                    "min_trade_count": 75,
                },
            ),
        ]

    def evaluate_candidate(
        self,
        *,
        profile: StrategyProfile,
        candidate: dict[str, Any],
        market_context: dict[str, Any],
    ) -> StrategySignal | None:
        asset_class = str(candidate.get("asset_class", "equity"))
        if asset_class not in profile.asset_classes:
            return None

        movement_pct = _to_float(candidate.get("movement_pct"))
        discovery_score = _to_float(candidate.get("discovery_score")) or 0.0
        trade_count = _to_int(candidate.get("trade_count")) or 0
        if movement_pct is None or movement_pct < float(profile.parameters["min_movement_pct"]):
            return None
        if discovery_score < float(profile.parameters["min_discovery_score"]):
            return None
        if trade_count < int(profile.parameters["min_trade_count"]):
            return None

        entry_price = _to_float(candidate.get("close_price"))
        if entry_price is None or entry_price <= 0:
            return None

        entry_price_gbp = _to_float(candidate.get("close_price_gbp"))
        liquidity_component = _liquidity_component(
            volume=_to_int(candidate.get("volume")),
            trade_count=trade_count,
        )
        signal_score = round(
            min(
                100.0,
                (movement_pct * 120.0) + (discovery_score * 7.5) + (liquidity_component * 8.0),
            ),
            6,
        )
        if signal_score < profile.min_signal_score:
            return None

        confidence = round(
            min(0.95, 0.35 + (movement_pct * 0.35) + min(discovery_score / 20.0, 0.3)),
            6,
        )
        return _build_signal(
            profile=profile,
            candidate=candidate,
            entry_price=entry_price,
            entry_price_gbp=entry_price_gbp,
            signal_score=signal_score,
            confidence=confidence,
            movement_pct=movement_pct,
            discovery_score=discovery_score,
            rationale=(
                f"{profile.label} likes positive movement of {movement_pct:.3f}% "
                f"with discovery score {discovery_score:.3f} and trade count {trade_count}."
            ),
            note="rule_based_momentum",
        )


class MeanReversionStrategy(StrategyDefinition):
    family = "mean_reversion"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        return [
            StrategyProfile(
                strategy_id="mean_reversion.snapback",
                family=self.family,
                profile_id="snapback",
                label="Mean Reversion Snapback",
                asset_classes=("equity",),
                holding_window_code="1h",
                holding_window_minutes=_window_code_to_minutes("1h"),
                stop_loss_pct=max(config.shadow_stop_loss_pct * 0.9, 0.01),
                target_multiple=max(config.shadow_target_multiple - 0.25, 1.5),
                max_signals_per_tick=2,
                min_signal_score=max(52.0, config.shadow_min_opportunity_score - 3.0),
                parameters={
                    "max_movement_pct": -0.18,
                    "min_discovery_score": 4.0,
                    "min_trade_count": 40,
                },
            )
        ]

    def evaluate_candidate(
        self,
        *,
        profile: StrategyProfile,
        candidate: dict[str, Any],
        market_context: dict[str, Any],
    ) -> StrategySignal | None:
        asset_class = str(candidate.get("asset_class", "equity"))
        if asset_class not in profile.asset_classes:
            return None

        movement_pct = _to_float(candidate.get("movement_pct"))
        discovery_score = _to_float(candidate.get("discovery_score")) or 0.0
        trade_count = _to_int(candidate.get("trade_count")) or 0
        if movement_pct is None or movement_pct > float(profile.parameters["max_movement_pct"]):
            return None
        if discovery_score < float(profile.parameters["min_discovery_score"]):
            return None
        if trade_count < int(profile.parameters["min_trade_count"]):
            return None

        entry_price = _to_float(candidate.get("close_price"))
        if entry_price is None or entry_price <= 0:
            return None

        entry_price_gbp = _to_float(candidate.get("close_price_gbp"))
        liquidity_component = _liquidity_component(
            volume=_to_int(candidate.get("volume")),
            trade_count=trade_count,
        )
        drawdown_strength = abs(movement_pct)
        signal_score = round(
            min(
                100.0,
                (drawdown_strength * 100.0)
                + (discovery_score * 7.0)
                + (liquidity_component * 6.0),
            ),
            6,
        )
        if signal_score < profile.min_signal_score:
            return None

        confidence = round(
            min(0.9, 0.3 + (drawdown_strength * 0.35) + min(discovery_score / 22.0, 0.25)),
            6,
        )
        return _build_signal(
            profile=profile,
            candidate=candidate,
            entry_price=entry_price,
            entry_price_gbp=entry_price_gbp,
            signal_score=signal_score,
            confidence=confidence,
            movement_pct=movement_pct,
            discovery_score=discovery_score,
            rationale=(
                f"{profile.label} sees a pullback of {movement_pct:.3f}% "
                f"with enough liquidity to test a bounce."
            ),
            note="rule_based_mean_reversion",
        )


class MomentumVolatilityBreakoutStrategy(StrategyDefinition):
    family = "momentum"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        return [
            StrategyProfile(
                strategy_id="momentum.volatility_breakout",
                family=self.family,
                profile_id="volatility_breakout",
                label="Momentum Volatility Breakout",
                asset_classes=("equity",),
                holding_window_code="1h",
                holding_window_minutes=_window_code_to_minutes("1h"),
                stop_loss_pct=max(config.shadow_stop_loss_pct, 0.01),
                target_multiple=max(config.shadow_target_multiple, 2.0),
                max_signals_per_tick=2,
                min_signal_score=max(62.0, config.shadow_min_opportunity_score),
                parameters={
                    "lookback_periods": 20,
                    "volume_surge_multiple": 2.0,
                    "atr_floor_pct": 1.0,
                    "stop_atr_multiple": 2.0,
                    "target_atr_multiple": 4.0,
                    "break_even_atr_multiple": 2.0,
                },
            )
        ]

    def evaluate_candidate(
        self,
        *,
        profile: StrategyProfile,
        candidate: dict[str, Any],
        market_context: dict[str, Any],
    ) -> StrategySignal | None:
        asset_class = str(candidate.get("asset_class", "equity"))
        if asset_class not in profile.asset_classes:
            return None

        entry_price = _to_float(candidate.get("close_price"))
        entry_price_gbp = _to_float(candidate.get("close_price_gbp"))
        breakout_high = _to_float(candidate.get("breakout_high_20"))
        average_volume = _to_float(candidate.get("avg_volume_20"))
        atr_value = _to_float(candidate.get("atr_20"))
        atr_pct = _to_float(candidate.get("atr_pct_20"))
        volume_ratio = _to_float(candidate.get("volume_ratio_20"))
        breakout_margin_pct = _to_float(candidate.get("breakout_margin_pct_20")) or 0.0
        discovery_score = _to_float(candidate.get("discovery_score")) or 0.0
        movement_pct = _to_float(candidate.get("movement_pct"))
        technical_ready = bool(candidate.get("technical_context_ready"))
        if not technical_ready:
            return None
        if entry_price is None or entry_price <= 0:
            return None
        if breakout_high is None or average_volume is None or atr_value is None or atr_value <= 0:
            return None
        if atr_pct is None or volume_ratio is None:
            return None
        if not bool(candidate.get("price_trigger_20")):
            return None
        if volume_ratio <= float(profile.parameters["volume_surge_multiple"]):
            return None
        if atr_pct <= float(profile.parameters["atr_floor_pct"]):
            return None

        stop_loss_price = round(
            entry_price - (atr_value * float(profile.parameters["stop_atr_multiple"])),
            8,
        )
        target_price = round(
            entry_price + (atr_value * float(profile.parameters["target_atr_multiple"])),
            8,
        )
        break_even_trigger_price = round(
            entry_price + (atr_value * float(profile.parameters["break_even_atr_multiple"])),
            8,
        )
        if stop_loss_price <= 0 or target_price <= entry_price:
            return None

        price_ratio = (
            (entry_price_gbp / entry_price)
            if entry_price_gbp not in (None, 0) and entry_price > 0
            else None
        )
        stop_loss_price_gbp = _convert_with_ratio(stop_loss_price, price_ratio)
        target_price_gbp = _convert_with_ratio(target_price, price_ratio)
        break_even_trigger_price_gbp = _convert_with_ratio(
            break_even_trigger_price,
            price_ratio,
        )
        risk_pct = round(((entry_price - stop_loss_price) / entry_price) * 100.0, 6)
        target_return_pct = round(((target_price - entry_price) / entry_price) * 100.0, 6)
        signal_score = round(
            min(
                100.0,
                42.0
                + (max(0.0, breakout_margin_pct) * 18.0)
                + (min(volume_ratio, 5.0) * 8.0)
                + (min(atr_pct, 6.0) * 4.0)
                + (discovery_score * 2.0),
            ),
            6,
        )
        if signal_score < profile.min_signal_score:
            return None

        confidence = round(
            min(
                0.97,
                0.45
                + min(volume_ratio / 10.0, 0.22)
                + min(atr_pct / 12.0, 0.16)
                + min(max(0.0, breakout_margin_pct) / 5.0, 0.12),
            ),
            6,
        )
        return StrategySignal(
            strategy_id=profile.strategy_id,
            strategy_family=profile.family,
            profile_id=profile.profile_id,
            source=str(candidate.get("source", "")),
            symbol=str(candidate.get("symbol", "")).upper(),
            asset_class=asset_class,
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
            rationale=(
                f"{profile.label} confirmed a 20-bar breakout above {breakout_high:.4f} "
                f"with volume running at {volume_ratio:.2f}x the 20-bar average "
                f"and ATR at {atr_pct:.2f}% of price."
            ),
            note="rule_based_momentum_volatility_breakout",
            atr_value=round(atr_value, 8),
            atr_pct=round(atr_pct, 6),
            breakout_high_price=round(breakout_high, 8),
            avg_volume_lookback=round(average_volume, 8),
            volume_ratio=round(volume_ratio, 6),
            break_even_trigger_price=break_even_trigger_price,
            break_even_trigger_price_gbp=break_even_trigger_price_gbp,
            trailing_stop_mode="break_even_next_bar",
        )


class CryptoMomentumStrategy(StrategyDefinition):
    family = "crypto_momentum"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        return [
            StrategyProfile(
                strategy_id="crypto_momentum.trend",
                family=self.family,
                profile_id="trend",
                label="Crypto Momentum Trend",
                asset_classes=("crypto",),
                holding_window_code="1h",
                holding_window_minutes=_window_code_to_minutes("1h"),
                stop_loss_pct=max(float(config.crypto_momentum_stop_loss_pct), 0.02),
                target_multiple=max(float(config.crypto_momentum_target_multiple), 1.5),
                max_signals_per_tick=2,
                min_signal_score=max(
                    float(config.crypto_momentum_min_signal_score),
                    config.shadow_min_opportunity_score,
                ),
                parameters={
                    "min_movement_pct": float(config.crypto_momentum_min_movement_pct),
                    "min_discovery_score": float(config.crypto_momentum_min_discovery_score),
                    "min_trade_count": max(1, int(config.crypto_momentum_min_trade_count)),
                },
            )
        ]

    def evaluate_candidate(
        self,
        *,
        profile: StrategyProfile,
        candidate: dict[str, Any],
        market_context: dict[str, Any],
    ) -> StrategySignal | None:
        asset_class = str(candidate.get("asset_class", "equity"))
        if asset_class not in profile.asset_classes:
            return None

        movement_pct = _to_float(candidate.get("movement_pct"))
        discovery_score = _to_float(candidate.get("discovery_score")) or 0.0
        trade_count = _to_int(candidate.get("trade_count")) or 0
        if movement_pct is None or movement_pct < float(profile.parameters["min_movement_pct"]):
            return None
        if discovery_score < float(profile.parameters["min_discovery_score"]):
            return None
        if trade_count < int(profile.parameters["min_trade_count"]):
            return None

        entry_price = _to_float(candidate.get("close_price"))
        if entry_price is None or entry_price <= 0:
            return None

        entry_price_gbp = _to_float(candidate.get("close_price_gbp"))
        liquidity_component = _liquidity_component(
            volume=_to_int(candidate.get("volume")),
            trade_count=trade_count,
        )
        signal_score = round(
            min(
                100.0,
                (movement_pct * 135.0) + (discovery_score * 8.0) + (liquidity_component * 4.0),
            ),
            6,
        )
        if signal_score < profile.min_signal_score:
            return None

        confidence = round(
            min(0.92, 0.32 + (movement_pct * 0.4) + min(discovery_score / 18.0, 0.3)),
            6,
        )
        return _build_signal(
            profile=profile,
            candidate=candidate,
            entry_price=entry_price,
            entry_price_gbp=entry_price_gbp,
            signal_score=signal_score,
            confidence=confidence,
            movement_pct=movement_pct,
            discovery_score=discovery_score,
            rationale=(
                f"{profile.label} likes crypto strength of {movement_pct:.3f}% "
                f"with discovery score {discovery_score:.3f}."
            ),
            note="rule_based_crypto_momentum",
        )


class LiquidityProbeStrategy(StrategyDefinition):
    family = "liquidity_probe"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        return [
            StrategyProfile(
                strategy_id="liquidity_probe.steady_flow",
                family=self.family,
                profile_id="steady_flow",
                label="Liquidity Probe Steady Flow",
                asset_classes=("equity",),
                holding_window_code="15m",
                holding_window_minutes=_window_code_to_minutes("15m"),
                stop_loss_pct=max(config.shadow_stop_loss_pct * 0.75, 0.01),
                target_multiple=max(config.shadow_target_multiple - 0.5, 1.25),
                max_signals_per_tick=2,
                min_signal_score=max(50.0, config.shadow_min_opportunity_score - 5.0),
                parameters={
                    "min_discovery_score": 4.8,
                    "min_trade_count": 40,
                    "min_volume": 1500,
                },
            )
        ]

    def evaluate_candidate(
        self,
        *,
        profile: StrategyProfile,
        candidate: dict[str, Any],
        market_context: dict[str, Any],
    ) -> StrategySignal | None:
        asset_class = str(candidate.get("asset_class", "equity"))
        if asset_class not in profile.asset_classes:
            return None

        discovery_score = _to_float(candidate.get("discovery_score")) or 0.0
        trade_count = _to_int(candidate.get("trade_count")) or 0
        volume = _to_int(candidate.get("volume")) or 0
        if discovery_score < float(profile.parameters["min_discovery_score"]):
            return None
        if trade_count < int(profile.parameters["min_trade_count"]):
            return None
        if volume < int(profile.parameters["min_volume"]):
            return None

        entry_price = _to_float(candidate.get("close_price"))
        if entry_price is None or entry_price <= 0:
            return None

        entry_price_gbp = _to_float(candidate.get("close_price_gbp"))
        movement_pct = _to_float(candidate.get("movement_pct"))
        liquidity_component = _liquidity_component(volume=volume, trade_count=trade_count)
        signal_score = round(
            min(100.0, (discovery_score * 9.0) + (liquidity_component * 9.0)),
            6,
        )
        if signal_score < profile.min_signal_score:
            return None

        confidence = round(min(0.82, 0.28 + min(discovery_score / 18.0, 0.24)), 6)
        return _build_signal(
            profile=profile,
            candidate=candidate,
            entry_price=entry_price,
            entry_price_gbp=entry_price_gbp,
            signal_score=signal_score,
            confidence=confidence,
            movement_pct=movement_pct,
            discovery_score=discovery_score,
            rationale=(
                f"{profile.label} sees strong flow with discovery score {discovery_score:.3f}, "
                f"trade count {trade_count}, and volume {volume}."
            ),
            note="rule_based_liquidity_probe",
        )


def evaluate_strategies(
    *,
    tick_id: str,
    candidates: list[dict[str, Any]],
    config: RuntimeConfig,
    market_context: dict[str, Any],
) -> StrategyEvaluationBatch:
    registry = build_strategy_registry()
    signals: list[StrategySignal] = []
    profile_count = 0
    for strategy in registry:
        profiles = strategy.build_profiles(config)
        profile_count += len(profiles)
        for profile in profiles:
            signals.extend(
                strategy.evaluate_profile(
                    profile=profile,
                    candidates=candidates,
                    market_context=market_context,
                )
            )

    signals.sort(
        key=lambda item: (item.signal_score, item.confidence, item.strategy_id, item.symbol),
        reverse=True,
    )
    reranked = [item.with_rank(index) for index, item in enumerate(signals, start=1)]
    return StrategyEvaluationBatch(
        signals=reranked,
        family_count=len(registry),
        profile_count=profile_count,
    )


def build_strategy_registry() -> list[StrategyDefinition]:
    return [
        MomentumStrategy(),
        MomentumVolatilityBreakoutStrategy(),
        MeanReversionStrategy(),
        CryptoMomentumStrategy(),
        LiquidityProbeStrategy(),
    ]


def _build_signal(
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
        symbol=str(candidate.get("symbol", "")).upper(),
        asset_class=str(candidate.get("asset_class", "equity")),
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


def _window_code_to_minutes(code: str) -> int:
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


def _liquidity_component(*, volume: int | None, trade_count: int | None) -> float:
    return round(log10((volume or 0) + 1) + log10((trade_count or 0) + 1), 6)


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


def _convert_with_ratio(value: float | None, ratio: float | None) -> float | None:
    if value is None or ratio is None:
        return None
    return round(value * ratio, 8)
