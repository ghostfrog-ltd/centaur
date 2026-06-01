"""Generic momentum research strategy.

Trading idea:
    Find assets with positive movement and enough discovery/liquidity evidence
    to warrant shadow/research observation.

Execution boundary:
    These profiles are not part of the current paper allowlist. Keeping the
    logic in its own file makes that distinction visible: this module can
    produce research signals, but later risk gates decide whether a signal is
    eligible for paper/live execution.
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


class MomentumStrategy(StrategyDefinition):
    """General positive-momentum profiles used for shadow evidence."""

    family = "momentum"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        """Build balanced and strong momentum profiles from shared shadow settings."""
        base_stop = max(config.shadow_stop_loss_pct, 0.01)
        return [
            StrategyProfile(
                strategy_id="momentum.balanced",
                family=self.family,
                profile_id="balanced",
                label="Momentum Balanced",
                asset_classes=("equity", "crypto"),
                holding_window_code="1h",
                holding_window_minutes=window_code_to_minutes("1h"),
                stop_loss_pct=base_stop,
                target_multiple=max(config.shadow_target_multiple, 1.5),
                max_signals_per_tick=2,
                min_signal_score=max(55.0, config.shadow_min_opportunity_score),
                parameters={
                    # movement_pct is a percent value, so 0.08 means up 0.08%.
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
                holding_window_minutes=window_code_to_minutes("1d"),
                stop_loss_pct=base_stop,
                target_multiple=max(config.shadow_target_multiple + 0.5, 2.0),
                max_signals_per_tick=1,
                min_signal_score=max(65.0, config.shadow_min_opportunity_score),
                parameters={
                    # Strong momentum is more selective and equity-only.
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
        """Return a generic momentum signal when the profile-specific gates pass."""
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

        # The profile controls asset-class scope. Balanced can observe equity
        # and crypto; strong is equity-only.
        asset_class = normalized_asset_class(candidate)
        if asset_class not in profile.asset_classes:
            reject("asset_class_not_allowed", asset_class=asset_class)
            return None

        # Require positive movement plus basic discovery/liquidity support.
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

        # Invalid prices fail before scoring because stops and targets derive
        # from the latest close.
        entry_price = to_float(candidate.get("close_price"))
        if entry_price is None or entry_price <= 0:
            reject("missing_entry_price", entry_price=entry_price)
            return None

        entry_price_gbp = to_float(candidate.get("close_price_gbp"))
        score_liquidity = liquidity_component(
            volume=to_int(candidate.get("volume")),
            trade_count=trade_count,
        )
        # Score combines trend strength, discovery quality, and liquidity. The
        # cap keeps ranking comparable with every other deterministic strategy.
        signal_score = round(
            min(
                100.0,
                (movement_pct * 120.0) + (discovery_score * 7.5) + (score_liquidity * 8.0),
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

        # Confidence is a bounded ranking hint, not execution permission.
        confidence = round(
            min(0.95, 0.35 + (movement_pct * 0.35) + min(discovery_score / 20.0, 0.3)),
            6,
        )
        # Shared builder keeps stop/target math consistent with the other
        # profile-based strategies.
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
                f"{profile.label} likes positive movement of {movement_pct:.3f}% "
                f"with discovery score {discovery_score:.3f} and trade count {trade_count}."
            ),
            note="rule_based_momentum",
        )
