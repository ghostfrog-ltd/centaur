"""Shadow-only crypto research strategies.

Trading ideas:
    Observe two additional long-only crypto patterns without widening the
    execution envelope:

    * dip_rebound watches liquid crypto pullbacks that may mean-revert.
    * range_breakout watches liquid crypto pairs that clear recent range highs.

Execution boundary:
    These profiles are research/observe-only unless their strategy IDs are
    explicitly added to the paper/live allowlists after review. They still use
    crypto-specific identity, volume, spread, and spike gates so any future
    promotion has an auditable safety trail instead of a generic equity profile.
"""

from __future__ import annotations

from typing import Any

from app.framework.runtime.settings import RuntimeConfig

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


class CryptoResearchStrategy(StrategyDefinition):
    """Collect shadow evidence for additional crypto-only long setups."""

    family = "crypto_research"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        """Build research profiles from existing crypto risk knobs."""
        stop_loss_pct = max(float(config.crypto_momentum_stop_loss_pct), 0.01)
        target_multiple = max(float(config.crypto_momentum_target_multiple), 2.0)
        min_volume_gbp = float(
            getattr(config, "crypto_momentum_min_volume_gbp", 50_000.0)
        )
        max_spread_pct = float(getattr(config, "crypto_momentum_max_spread_pct", 0.25))
        max_movement_pct = float(getattr(config, "crypto_momentum_max_movement_pct", 2.5))
        return [
            StrategyProfile(
                strategy_id="crypto_research.dip_rebound",
                family=self.family,
                profile_id="dip_rebound",
                label="Crypto Research Dip Rebound",
                asset_classes=("crypto",),
                holding_window_code="1h",
                holding_window_minutes=window_code_to_minutes("1h"),
                stop_loss_pct=stop_loss_pct,
                target_multiple=target_multiple,
                max_signals_per_tick=2,
                min_signal_score=max(58.0, config.shadow_min_opportunity_score),
                parameters={
                    "min_pullback_pct": 0.25,
                    "max_pullback_pct": max_movement_pct,
                    "min_discovery_score": float(config.crypto_momentum_min_discovery_score),
                    "min_trade_count": max(1, int(config.crypto_momentum_min_trade_count)),
                    "min_volume_gbp": min_volume_gbp,
                    "max_spread_pct": max_spread_pct,
                },
            ),
            StrategyProfile(
                strategy_id="crypto_research.range_breakout",
                family=self.family,
                profile_id="range_breakout",
                label="Crypto Research Range Breakout",
                asset_classes=("crypto",),
                holding_window_code="1h",
                holding_window_minutes=window_code_to_minutes("1h"),
                stop_loss_pct=stop_loss_pct,
                target_multiple=target_multiple,
                max_signals_per_tick=2,
                min_signal_score=max(62.0, config.shadow_min_opportunity_score),
                parameters={
                    "min_movement_pct": 0.12,
                    "max_movement_pct": max_movement_pct,
                    "min_discovery_score": max(
                        float(config.crypto_momentum_min_discovery_score),
                        3.0,
                    ),
                    "min_trade_count": max(1, int(config.crypto_momentum_min_trade_count)),
                    "min_volume_gbp": min_volume_gbp,
                    "max_spread_pct": max_spread_pct,
                    "min_volume_ratio": 1.25,
                    "min_atr_pct": 0.25,
                    "max_atr_pct": 3.0,
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
        """Dispatch to the profile-specific crypto research gate."""
        if profile.profile_id == "dip_rebound":
            return self._evaluate_dip_rebound(
                profile=profile,
                candidate=candidate,
                market_context=market_context,
            )
        if profile.profile_id == "range_breakout":
            return self._evaluate_range_breakout(
                profile=profile,
                candidate=candidate,
                market_context=market_context,
            )
        return None

    def _evaluate_dip_rebound(
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

        common = self._crypto_common_inputs(
            profile=profile,
            candidate=candidate,
            reject=reject,
        )
        if common is None:
            return None
        movement_pct = common["movement_pct"]
        pullback_pct = abs(movement_pct)
        if movement_pct >= 0:
            reject("pullback_not_negative", movement_pct=movement_pct)
            return None
        if pullback_pct < float(profile.parameters["min_pullback_pct"]):
            reject(
                "pullback_below_min",
                pullback_pct=pullback_pct,
                min_pullback_pct=profile.parameters["min_pullback_pct"],
            )
            return None
        if pullback_pct > float(profile.parameters["max_pullback_pct"]):
            reject(
                "pullback_above_max",
                pullback_pct=pullback_pct,
                max_pullback_pct=profile.parameters["max_pullback_pct"],
            )
            return None

        score_liquidity = liquidity_component(
            volume=common["volume"],
            trade_count=common["trade_count"],
        )
        signal_score = round(
            min(
                100.0,
                (pullback_pct * 125.0)
                + (common["discovery_score"] * 7.5)
                + (score_liquidity * 4.0),
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

        confidence = round(
            min(
                0.9,
                0.28
                + (pullback_pct * 0.25)
                + min(common["discovery_score"] / 20.0, 0.3),
            ),
            6,
        )
        return build_signal(
            profile=profile,
            candidate=candidate,
            entry_price=common["entry_price"],
            entry_price_gbp=common["entry_price_gbp"],
            signal_score=signal_score,
            confidence=confidence,
            movement_pct=movement_pct,
            discovery_score=common["discovery_score"],
            rationale=(
                f"{profile.label} observes a {pullback_pct:.3f}% crypto pullback "
                f"with discovery score {common['discovery_score']:.3f}."
            ),
            note="shadow_only_crypto_dip_rebound",
        )

    def _evaluate_range_breakout(
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

        common = self._crypto_common_inputs(
            profile=profile,
            candidate=candidate,
            reject=reject,
        )
        if common is None:
            return None
        movement_pct = common["movement_pct"]
        if movement_pct < float(profile.parameters["min_movement_pct"]):
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

        if not bool(candidate.get("technical_context_ready")):
            reject("technical_context_not_ready")
            return None
        if not bool(candidate.get("price_trigger_20")):
            reject("price_trigger_missing")
            return None
        volume_ratio = to_float(candidate.get("volume_ratio_20"))
        atr_pct = to_float(candidate.get("atr_pct_20"))
        if volume_ratio is None or volume_ratio <= float(profile.parameters["min_volume_ratio"]):
            reject(
                "volume_ratio_below_min",
                volume_ratio=volume_ratio,
                min_volume_ratio=profile.parameters["min_volume_ratio"],
            )
            return None
        if atr_pct is None or atr_pct < float(profile.parameters["min_atr_pct"]):
            reject(
                "atr_below_min",
                atr_pct=atr_pct,
                min_atr_pct=profile.parameters["min_atr_pct"],
            )
            return None
        if atr_pct > float(profile.parameters["max_atr_pct"]):
            reject(
                "atr_above_max",
                atr_pct=atr_pct,
                max_atr_pct=profile.parameters["max_atr_pct"],
            )
            return None

        signal_score = round(
            min(
                100.0,
                (movement_pct * 115.0)
                + (common["discovery_score"] * 7.0)
                + (volume_ratio * 8.0)
                + (atr_pct * 4.0),
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

        confidence = round(
            min(
                0.9,
                0.3
                + (movement_pct * 0.25)
                + min(volume_ratio / 10.0, 0.2)
                + min(atr_pct / 12.0, 0.15),
            ),
            6,
        )
        return build_signal(
            profile=profile,
            candidate=candidate,
            entry_price=common["entry_price"],
            entry_price_gbp=common["entry_price_gbp"],
            signal_score=signal_score,
            confidence=confidence,
            movement_pct=movement_pct,
            discovery_score=common["discovery_score"],
            rationale=(
                f"{profile.label} observes crypto range expansion with "
                f"{movement_pct:.3f}% movement and {volume_ratio:.2f}x volume."
            ),
            note="shadow_only_crypto_range_breakout",
        )

    def _crypto_common_inputs(
        self,
        *,
        profile: StrategyProfile,
        candidate: dict[str, Any],
        reject: Any,
    ) -> dict[str, Any] | None:
        if not has_strategy_identity(candidate):
            reject("missing_instrument_identity")
            return None
        asset_class = normalized_asset_class(candidate)
        if asset_class not in profile.asset_classes:
            reject("asset_class_not_allowed", asset_class=asset_class)
            return None

        movement_pct = to_float(candidate.get("movement_pct"))
        discovery_score = to_float(candidate.get("discovery_score")) or 0.0
        trade_count = to_int(candidate.get("trade_count")) or 0
        if movement_pct is None:
            reject("missing_movement")
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

        entry_price = to_float(candidate.get("close_price"))
        if entry_price is None or entry_price <= 0:
            reject("missing_entry_price", entry_price=entry_price)
            return None

        entry_price_gbp = to_float(candidate.get("close_price_gbp"))
        volume = to_int(candidate.get("volume"))
        volume_gbp = to_float(candidate.get("volume_gbp"))
        if volume_gbp is None and entry_price_gbp is not None and volume is not None:
            volume_gbp = entry_price_gbp * volume
        if float(profile.parameters["min_volume_gbp"]) > 0 and (
            volume_gbp is None or volume_gbp < float(profile.parameters["min_volume_gbp"])
        ):
            reject(
                "volume_gbp_below_min",
                volume_gbp=volume_gbp,
                min_volume_gbp=profile.parameters["min_volume_gbp"],
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

        return {
            "movement_pct": movement_pct,
            "discovery_score": discovery_score,
            "trade_count": trade_count,
            "entry_price": entry_price,
            "entry_price_gbp": entry_price_gbp,
            "volume": volume,
            "volume_gbp": volume_gbp,
        }
