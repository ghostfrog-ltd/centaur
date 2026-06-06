"""Paper-research crypto pullback watch strategy.

Trading idea:
    Observe fresh crypto downside moves that are large enough to deserve
    follow-up research without pretending Centaur can safely short them today.

Execution boundary:
    This strategy emits watch-only proposals with a non-executable direction so
    the current long-only paper/live routers fail closed. Diagnostics still show
    whether a candidate was research-eligible and why it passed or failed.
"""

from __future__ import annotations

from typing import Any

from app.framework.runtime.settings import RuntimeConfig

from .base import StrategyDefinition, StrategyProfile, StrategySignal
from .common import (
    has_strategy_identity,
    liquidity_component,
    normalized_asset_class,
    normalized_symbol,
    record_rejection,
    to_float,
    to_int,
    window_code_to_minutes,
)


class CryptoPullbackStrategy(StrategyDefinition):
    """Observe fresh downside crypto pullbacks for paper-only research."""

    family = "crypto_pullback"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        stop_loss_pct = max(float(config.crypto_momentum_stop_loss_pct), 0.01)
        target_multiple = max(float(config.crypto_momentum_target_multiple), 2.0)
        return [
            StrategyProfile(
                strategy_id="crypto_pullback.downside_reversal_watch",
                family=self.family,
                profile_id="downside_reversal_watch",
                label="Crypto Pullback Downside Reversal Watch",
                asset_classes=("crypto",),
                holding_window_code="1h",
                holding_window_minutes=window_code_to_minutes("1h"),
                stop_loss_pct=stop_loss_pct,
                target_multiple=target_multiple,
                max_signals_per_tick=2,
                min_signal_score=max(58.0, config.shadow_min_opportunity_score),
                parameters={
                    "min_pullback_pct": 0.150,
                    "max_pullback_pct": 2.500,
                    "min_discovery_score": 2.500,
                    "preferred_min_trade_count": 2,
                    "preferred_min_volume_gbp": 50_000.0,
                    "max_spread_pct": float(
                        getattr(config, "crypto_momentum_max_spread_pct", 0.25)
                    ),
                    "paper_allowed": True,
                    "live_allowed": False,
                    "research_only": True,
                    "diagnostics_always_include": True,
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
        def reject(reason: str, **metrics: Any) -> None:
            record_rejection(
                market_context=market_context,
                profile=profile,
                candidate=candidate,
                reason=reason,
                metrics=metrics,
            )

        if not has_strategy_identity(candidate):
            reject("missing_instrument_identity")
            return None
        asset_class = normalized_asset_class(candidate)
        if asset_class not in profile.asset_classes:
            reject("asset_class_not_allowed", asset_class=asset_class)
            return None

        movement_pct = to_float(candidate.get("movement_pct"))
        if movement_pct is None:
            reject("missing_movement")
            return None
        if movement_pct >= 0:
            reject("movement_not_negative", movement_pct=movement_pct)
            return None

        pullback_pct = abs(movement_pct)
        if pullback_pct < float(profile.parameters["min_pullback_pct"]):
            reject(
                "pullback_below_min",
                movement_pct=movement_pct,
                min_pullback_pct=profile.parameters["min_pullback_pct"],
            )
            return None
        if pullback_pct > float(profile.parameters["max_pullback_pct"]):
            reject(
                "pullback_above_max",
                movement_pct=movement_pct,
                max_pullback_pct=profile.parameters["max_pullback_pct"],
            )
            return None

        discovery_score = to_float(candidate.get("discovery_score")) or 0.0
        if discovery_score < float(profile.parameters["min_discovery_score"]):
            reject(
                "discovery_below_min",
                discovery_score=discovery_score,
                min_discovery_score=profile.parameters["min_discovery_score"],
            )
            return None

        entry_price = to_float(candidate.get("close_price"))
        if entry_price is None or entry_price <= 0:
            reject("missing_entry_price", entry_price=entry_price)
            return None

        entry_price_gbp = to_float(candidate.get("close_price_gbp"))
        trade_count = to_int(candidate.get("trade_count"))
        volume = to_int(candidate.get("volume"))
        volume_gbp = to_float(candidate.get("volume_gbp"))
        if volume_gbp is None and entry_price_gbp is not None and volume is not None:
            volume_gbp = entry_price_gbp * volume
        spread_pct = to_float(candidate.get("spread_pct"))

        liquidity_score = liquidity_component(volume=volume, trade_count=trade_count)
        trade_bonus = 4.0 if (trade_count or 0) >= int(profile.parameters["preferred_min_trade_count"]) else 0.0
        volume_bonus = 4.0 if (
            volume_gbp is not None
            and volume_gbp >= float(profile.parameters["preferred_min_volume_gbp"])
        ) else 0.0
        spread_bonus = 2.0 if (
            spread_pct is not None
            and spread_pct <= float(profile.parameters["max_spread_pct"])
        ) else 0.0
        signal_score = round(
            min(
                100.0,
                (pullback_pct * 130.0)
                + (discovery_score * 8.0)
                + (liquidity_score * 3.5)
                + trade_bonus
                + volume_bonus
                + spread_bonus,
            ),
            6,
        )
        if signal_score < float(profile.min_signal_score):
            reject(
                "score_below_min",
                signal_score=signal_score,
                min_signal_score=profile.min_signal_score,
            )
            return None

        confidence = round(
            min(0.9, 0.28 + (pullback_pct * 0.22) + min(discovery_score / 18.0, 0.3)),
            6,
        )
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
        return StrategySignal(
            strategy_id=profile.strategy_id,
            strategy_family=profile.family,
            profile_id=profile.profile_id,
            source=str(candidate.get("source", "")),
            symbol=normalized_symbol(candidate),
            asset_class=asset_class,
            direction="pullback_watch",
            signal_rank=0,
            signal_score=signal_score,
            confidence=confidence,
            entry_price=round(entry_price, 8),
            entry_price_gbp=round(entry_price_gbp, 8) if entry_price_gbp is not None else None,
            stop_loss_price=stop_loss_price,
            stop_loss_price_gbp=stop_loss_price_gbp,
            target_price=target_price,
            target_price_gbp=target_price_gbp,
            risk_pct=round(profile.stop_loss_pct * 100.0, 4),
            target_return_pct=round(profile.stop_loss_pct * profile.target_multiple * 100.0, 4),
            holding_window_code=profile.holding_window_code,
            holding_window_minutes=profile.holding_window_minutes,
            movement_pct=movement_pct,
            discovery_score=round(discovery_score, 6),
            rationale=(
                f"{profile.label} observes a {pullback_pct:.3f}% downside move in "
                f"{normalized_symbol(candidate)} for paper-only research follow-up."
            ),
            note="paper_research_only_crypto_pullback_watch",
            canonical_instrument_id=str(candidate.get("canonical_instrument_id", "")),
            venue=str(candidate.get("venue", "")),
            venue_symbol=str(candidate.get("venue_symbol", "")),
        )
