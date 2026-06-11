"""Mean reversion snapback strategy.

Trading idea:
    Look for an equity that has pulled back sharply on the latest scan, but
    still has enough discovery/liquidity evidence to make a bounce worth
    watching. This strategy is long-only; it never suggests shorting a falling
    name.

Execution boundary:
    This file only creates an auditable StrategySignal. Paper/live eligibility,
    notional, market-hours checks, kill switches, duplicate-position checks,
    and broker routing are enforced later by the pipeline risk/execution gates.
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


class MeanReversionStrategy(StrategyDefinition):
    """Detect equity pullbacks that may snap back over a short holding window."""

    family = "mean_reversion"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        """Build the single approved snapback profile from runtime risk settings."""
        return [
            StrategyProfile(
                strategy_id="mean_reversion.snapback",
                family=self.family,
                profile_id="snapback",
                label="Mean Reversion Snapback",
                asset_classes=("equity",),
                holding_window_code="1h",
                holding_window_minutes=window_code_to_minutes("1h"),
                # Snapback uses a slightly tighter stop/target profile than the
                # shared shadow default, but never below a 1% stop or 1.5R target.
                stop_loss_pct=max(config.shadow_stop_loss_pct * 0.9, 0.01),
                target_multiple=max(config.shadow_target_multiple - 0.25, 1.5),
                max_signals_per_tick=2,
                min_signal_score=max(52.0, config.shadow_min_opportunity_score - 3.0),
                parameters={
                    # movement_pct is a percent value, not a decimal ratio:
                    # -0.18 means down 0.18% from the previous comparable bar.
                    "max_movement_pct": -0.18,
                    "min_discovery_score": 4.0,
                    "min_trade_count": 40,
                    # Percentage-point units, matching target_return_pct and
                    # realized_return_pct elsewhere in the replay/reporting code.
                    "min_expected_net_move_pct": 0.0,
                    "estimated_round_trip_cost_pct": self._estimated_round_trip_cost_pct(config),
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
        """Return a signal only when the candidate passes every snapback gate."""
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

        # Snapback is equity-only. Crypto has its own momentum profile and risk
        # tuning, so a crypto candidate must fail closed here.
        asset_class = normalized_asset_class(candidate)
        if asset_class not in profile.asset_classes:
            reject("asset_class_not_allowed", asset_class=asset_class)
            return None

        # The first gate is the actual pullback: the move must be negative and
        # at least as deep as max_movement_pct. Shallow dips are ignored.
        movement_pct = to_float(candidate.get("movement_pct"))
        discovery_score = to_float(candidate.get("discovery_score")) or 0.0
        trade_count = to_int(candidate.get("trade_count")) or 0
        if movement_pct is None or movement_pct > float(profile.parameters["max_movement_pct"]):
            reject(
                "movement_above_snapback_max",
                movement_pct=movement_pct,
                max_movement_pct=profile.parameters["max_movement_pct"],
            )
            return None

        # Discovery score and trade count are lightweight quality/liquidity
        # checks. They reduce the chance of buying a move that is just a stale
        # or thinly traded print.
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

        # The close is used as the planned entry anchor. Invalid prices cannot
        # produce stops/targets, so they fail before scoring.
        entry_price = to_float(candidate.get("close_price"))
        if entry_price is None or entry_price <= 0:
            reject("missing_entry_price", entry_price=entry_price)
            return None

        min_expected_net_move_pct = float(
            profile.parameters.get("min_expected_net_move_pct", 0.0) or 0.0
        )
        estimated_round_trip_cost_pct = float(
            profile.parameters.get("estimated_round_trip_cost_pct", 0.0) or 0.0
        )
        expected_target_return_pct = profile.stop_loss_pct * profile.target_multiple * 100.0
        required_expected_move_pct = estimated_round_trip_cost_pct + min_expected_net_move_pct
        if expected_target_return_pct < required_expected_move_pct:
            reject(
                "expected_move_below_cost_adjusted_min",
                expected_target_return_pct=round(expected_target_return_pct, 6),
                estimated_round_trip_cost_pct=round(estimated_round_trip_cost_pct, 6),
                min_expected_net_move_pct=round(min_expected_net_move_pct, 6),
                required_expected_move_pct=round(required_expected_move_pct, 6),
            )
            return None

        entry_price_gbp = to_float(candidate.get("close_price_gbp"))
        score_liquidity = liquidity_component(
            volume=to_int(candidate.get("volume")),
            trade_count=trade_count,
        )
        drawdown_strength = abs(movement_pct)
        # Score rewards a deeper pullback, stronger discovery, and healthier
        # liquidity. The 100 cap keeps this comparable with other strategies.
        signal_score = round(
            min(
                100.0,
                (drawdown_strength * 100.0)
                + (discovery_score * 7.0)
                + (score_liquidity * 6.0),
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

        # Confidence is intentionally capped below 1.0. It is a ranking hint for
        # the allocator, not permission to bypass downstream capital gates.
        confidence = round(
            min(0.9, 0.3 + (drawdown_strength * 0.35) + min(discovery_score / 22.0, 0.25)),
            6,
        )
        # build_signal applies the profile stop and target multiple, preserves
        # instrument metadata, and creates the final long-only signal object.
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
                f"{profile.label} sees a pullback of {movement_pct:.3f}% "
                f"with enough liquidity to test a bounce."
            ),
            note="rule_based_mean_reversion",
        )

    def _estimated_round_trip_cost_pct(self, config: RuntimeConfig) -> float:
        spread_pct = max(
            0.0,
            float(getattr(config, "shadow_execution_spread_bps", 0.0) or 0.0),
        ) / 100.0
        slippage_pct = (
            max(0.0, float(getattr(config, "shadow_entry_slippage_bps", 0.0) or 0.0))
            + max(0.0, float(getattr(config, "shadow_exit_slippage_bps", 0.0) or 0.0))
        ) / 100.0
        fixed_cost_pct = 0.0
        notional = float(getattr(config, "paper_execution_default_notional_usd", 0.0) or 0.0)
        fixed_cost = max(
            0.0,
            float(getattr(config, "shadow_fixed_round_trip_cost_usd", 0.0) or 0.0),
        )
        if notional > 0.0 and fixed_cost > 0.0:
            fixed_cost_pct = (fixed_cost / notional) * 100.0
        return round(spread_pct + slippage_pct + fixed_cost_pct, 6)
