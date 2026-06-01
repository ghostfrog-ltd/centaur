"""Crypto momentum trend strategy.

Trading idea:
    Watch crypto pairs that are already moving up with enough discovery and
    trade-count evidence to justify a small long-only momentum test.

Capital-preservation note:
    This strategy uses lane-specific crypto momentum settings. The current
    paper configuration keeps the stop at 1%, so a 10 USD paper entry risks
    roughly 0.10 USD before slippage/fill drift. This file only emits signals;
    the execution pipeline still enforces notional, broker, slot, and kill
    switch rules.
"""

from __future__ import annotations

from typing import Any

from app.runtime.settings import RuntimeConfig

from .base import StrategyDefinition, StrategyProfile, StrategySignal
from .common import (
    build_signal,
    has_strategy_identity,
    liquidity_component,
    normalized_asset_class,
    record_rejection,
    to_float,
    to_int,
    window_code_to_minutes,
)


class CryptoMomentumStrategy(StrategyDefinition):
    """Detect positive crypto continuation candidates for the crypto lane."""

    family = "crypto_momentum"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        """Build the crypto trend profile from paper/live lane-scoped settings."""
        return [
            StrategyProfile(
                strategy_id="crypto_momentum.trend",
                family=self.family,
                profile_id="trend",
                label="Crypto Momentum Trend",
                asset_classes=("crypto",),
                holding_window_code="1h",
                holding_window_minutes=window_code_to_minutes("1h"),
                # The explicit floor prevents an accidentally tiny stop from
                # being treated as a safe trading configuration.
                stop_loss_pct=max(float(config.crypto_momentum_stop_loss_pct), 0.01),
                target_multiple=max(float(config.crypto_momentum_target_multiple), 1.5),
                max_signals_per_tick=2,
                min_signal_score=max(
                    float(config.crypto_momentum_min_signal_score),
                    config.shadow_min_opportunity_score,
                ),
                parameters={
                    # movement_pct is a percent value. With the current default,
                    # 0.15 means the pair must be up at least 0.15%.
                    "min_movement_pct": float(config.crypto_momentum_min_movement_pct),
                    "max_movement_pct": float(
                        getattr(config, "crypto_momentum_max_movement_pct", 2.5)
                    ),
                    "min_discovery_score": float(config.crypto_momentum_min_discovery_score),
                    "min_trade_count": max(1, int(config.crypto_momentum_min_trade_count)),
                    "min_volume_gbp": float(
                        getattr(config, "crypto_momentum_min_volume_gbp", 50_000.0)
                    ),
                    "max_spread_pct": float(
                        getattr(config, "crypto_momentum_max_spread_pct", 0.25)
                    ),
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
        """Return a signal only when the crypto candidate passes trend gates."""
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

        # Crypto momentum is crypto-only. Equity candidates have separate
        # strategies and market-hours rules, so they fail closed here.
        asset_class = normalized_asset_class(candidate)
        if asset_class not in profile.asset_classes:
            reject("asset_class_not_allowed", asset_class=asset_class)
            return None

        # Momentum must be positive enough, with enough discovery/trade evidence
        # to avoid reacting to a thin or stale crypto quote.
        movement_pct = to_float(candidate.get("movement_pct"))
        discovery_score = to_float(candidate.get("discovery_score")) or 0.0
        trade_count = to_int(candidate.get("trade_count")) or 0
        if movement_pct is None or movement_pct < float(profile.parameters["min_movement_pct"]):
            reject(
                "movement_below_min",
                movement_pct=movement_pct,
                min_movement_pct=profile.parameters["min_movement_pct"],
            )
            return None
        if movement_pct > float(profile.parameters["max_movement_pct"]):
            reject(
                "movement_above_max",
                movement_pct=movement_pct,
                max_movement_pct=profile.parameters["max_movement_pct"],
            )
            return None
        if discovery_score < float(profile.parameters["min_discovery_score"]):
            reject(
                "discovery_below_min",
                discovery_score=discovery_score,
                min_discovery_score=profile.parameters["min_discovery_score"],
            )
            return None
        if trade_count < int(profile.parameters["min_trade_count"]):
            reject(
                "trade_count_below_min",
                trade_count=trade_count,
                min_trade_count=profile.parameters["min_trade_count"],
            )
            return None

        # Use the latest close as the entry anchor. Bad or missing prices are a
        # hard reject because risk prices would be meaningless.
        entry_price = to_float(candidate.get("close_price"))
        if entry_price is None or entry_price <= 0:
            reject("missing_entry_price", entry_price=entry_price)
            return None

        entry_price_gbp = to_float(candidate.get("close_price_gbp"))
        volume = to_int(candidate.get("volume"))
        volume_gbp = to_float(candidate.get("volume_gbp"))
        if volume_gbp is None and entry_price_gbp is not None and volume is not None:
            volume_gbp = entry_price_gbp * volume
        min_volume_gbp = float(profile.parameters["min_volume_gbp"])
        if min_volume_gbp > 0 and (volume_gbp is None or volume_gbp < min_volume_gbp):
            reject(
                "volume_gbp_below_min",
                volume_gbp=volume_gbp,
                min_volume_gbp=min_volume_gbp,
            )
            return None

        spread_pct = to_float(candidate.get("spread_pct"))
        if spread_pct is not None and spread_pct > float(profile.parameters["max_spread_pct"]):
            reject(
                "spread_above_max",
                spread_pct=spread_pct,
                max_spread_pct=profile.parameters["max_spread_pct"],
            )
            return None

        score_liquidity = liquidity_component(
            volume=volume,
            trade_count=trade_count,
        )
        # Score leans more heavily on movement than the generic momentum model
        # because this strategy is specifically looking for near-term crypto
        # continuation. Liquidity still contributes, but less aggressively.
        signal_score = round(
            min(
                100.0,
                (movement_pct * 135.0) + (discovery_score * 8.0) + (score_liquidity * 4.0),
            ),
            6,
        )
        if signal_score < profile.min_signal_score:
            reject(
                "score_below_min",
                signal_score=signal_score,
                min_signal_score=profile.min_signal_score,
            )
            return None

        # Confidence is capped and used only for ranking/allocation. It is not a
        # risk override.
        confidence = round(
            min(0.92, 0.32 + (movement_pct * 0.4) + min(discovery_score / 18.0, 0.3)),
            6,
        )
        # Shared signal construction applies the configured 1%+ stop, target
        # multiple, long-only direction, and instrument metadata.
        return build_signal(
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
