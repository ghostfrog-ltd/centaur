"""Liquidity probe research strategy.

Trading idea:
    Surface equity candidates with unusually steady flow even when directional
    movement is not the main reason to watch them.

Execution boundary:
    This is a shadow/research profile, not a currently allowed paper strategy.
    It exists to collect evidence about flow quality without changing the paper
    execution envelope.
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


class LiquidityProbeStrategy(StrategyDefinition):
    """Detect equity candidates with enough flow to deserve observation."""

    family = "liquidity_probe"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        """Build the steady-flow profile with short observation windows."""
        return [
            StrategyProfile(
                strategy_id="liquidity_probe.steady_flow",
                family=self.family,
                profile_id="steady_flow",
                label="Liquidity Probe Steady Flow",
                asset_classes=("equity",),
                holding_window_code="15m",
                holding_window_minutes=window_code_to_minutes("15m"),
                stop_loss_pct=max(config.shadow_stop_loss_pct * 0.75, 0.01),
                target_multiple=max(config.shadow_target_multiple - 0.5, 1.25),
                max_signals_per_tick=2,
                min_signal_score=max(50.0, config.shadow_min_opportunity_score - 5.0),
                parameters={
                    # This strategy is about flow, so volume has its own hard
                    # floor rather than being only part of the score.
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
        """Return a flow-based signal after discovery, trades, and volume pass."""
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

        # Liquidity probe is equity-only. It should never promote crypto into
        # this flow profile.
        asset_class = normalized_asset_class(candidate)
        if asset_class not in profile.asset_classes:
            reject("asset_class_not_allowed", asset_class=asset_class)
            return None

        # Flow gates come before scoring. If the candidate does not meet the
        # minimum observed activity, we do not try to rescue it with score math.
        discovery_score = to_float(candidate.get("discovery_score")) or 0.0
        trade_count = to_int(candidate.get("trade_count")) or 0
        volume = to_int(candidate.get("volume")) or 0
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
        if volume < int(profile.parameters["min_volume"]):
            reject(
                "volume_below_min",
                volume=volume,
                min_volume=profile.parameters["min_volume"],
            )
            return None

        # A valid close is still required because the shared signal builder
        # derives stop and target prices from it.
        entry_price = to_float(candidate.get("close_price"))
        if entry_price is None or entry_price <= 0:
            reject("missing_entry_price", entry_price=entry_price)
            return None

        entry_price_gbp = to_float(candidate.get("close_price_gbp"))
        movement_pct = to_float(candidate.get("movement_pct"))
        score_liquidity = liquidity_component(volume=volume, trade_count=trade_count)
        # Unlike momentum strategies, this score intentionally ignores movement
        # as a primary driver. It is asking "is there enough flow to study?"
        signal_score = round(
            min(100.0, (discovery_score * 9.0) + (score_liquidity * 9.0)),
            6,
        )
        if signal_score < profile.min_signal_score:
            reject(
                "score_below_min",
                signal_score=signal_score,
                min_signal_score=profile.min_signal_score,
            )
            return None

        # Confidence is conservative because flow alone is weaker evidence than
        # price plus flow.
        confidence = round(min(0.82, 0.28 + min(discovery_score / 18.0, 0.24)), 6)
        # Shared builder gives the research proposal the same auditable shape as
        # every other deterministic signal.
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
                f"{profile.label} sees strong flow with discovery score {discovery_score:.3f}, "
                f"trade count {trade_count}, and volume {volume}."
            ),
            note="rule_based_liquidity_probe",
        )
