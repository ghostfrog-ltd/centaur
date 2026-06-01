"""Momentum volatility breakout strategy.

Trading idea:
    Watch equities that break above the prior 20-bar high while volume and ATR
    confirm the move is not just a tiny, illiquid price tick.

Why this strategy is more explicit than the simple momentum strategies:
    The stop, target, and break-even trigger are ATR-based instead of using the
    shared percent stop. That keeps the plan scaled to recent volatility and
    makes the planned risk/reward visible in the persisted signal.

Execution boundary:
    This file only emits long-only StrategySignal objects. Paper/live execution
    still depends on the configured strategy allowlist, projected-gain floors,
    market-hours rules, position/order duplication checks, notional limits, and
    broker adapters later in the pipeline.
"""

from __future__ import annotations

from typing import Any

from app.core.instruments import instrument_ref_from_metadata
from app.runtime.settings import RuntimeConfig

from .base import StrategyDefinition, StrategyProfile, StrategySignal
from .common import (
    convert_with_ratio,
    has_strategy_identity,
    normalized_asset_class,
    normalized_symbol,
    record_rejection,
    to_float,
    window_code_to_minutes,
)


class MomentumVolatilityBreakoutStrategy(StrategyDefinition):
    """Detect 20-bar equity breakouts with volume and volatility confirmation."""

    family = "momentum"

    def build_profiles(self, config: RuntimeConfig) -> list[StrategyProfile]:
        """Build the single volatility-breakout profile."""
        return [
            StrategyProfile(
                strategy_id="momentum.volatility_breakout",
                family=self.family,
                profile_id="volatility_breakout",
                label="Momentum Volatility Breakout",
                asset_classes=("equity",),
                holding_window_code="1h",
                holding_window_minutes=window_code_to_minutes("1h"),
                stop_loss_pct=max(config.shadow_stop_loss_pct, 0.01),
                target_multiple=max(config.shadow_target_multiple, 2.0),
                max_signals_per_tick=2,
                min_signal_score=max(62.0, config.shadow_min_opportunity_score),
                parameters={
                    # Technical context is computed upstream from recent bars.
                    # This strategy consumes those fields but does not fetch
                    # market data itself.
                    "lookback_periods": 20,
                    # Strictly greater-than gates are used below. A volume ratio
                    # of exactly 2.0x or ATR of exactly 1.0% is not enough.
                    "volume_surge_multiple": 2.0,
                    "atr_floor_pct": 1.0,
                    # Risk plan: stop 2 ATR below entry, target 4 ATR above
                    # entry, and observe break-even activation at +2 ATR.
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
        """Return a breakout signal only after all technical gates pass."""
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

        # Breakout is equity-only. Crypto has a separate momentum strategy with
        # separate lane-scoped risk settings.
        asset_class = normalized_asset_class(candidate)
        if asset_class not in profile.asset_classes:
            reject("asset_class_not_allowed", asset_class=asset_class)
            return None

        # These fields come from compute_volatility_breakout_context upstream.
        # A missing field means the candidate is not technically reviewable yet.
        entry_price = to_float(candidate.get("close_price"))
        entry_price_gbp = to_float(candidate.get("close_price_gbp"))
        breakout_high = to_float(candidate.get("breakout_high_20"))
        average_volume = to_float(candidate.get("avg_volume_20"))
        atr_value = to_float(candidate.get("atr_20"))
        atr_pct = to_float(candidate.get("atr_pct_20"))
        volume_ratio = to_float(candidate.get("volume_ratio_20"))
        breakout_margin_pct = to_float(candidate.get("breakout_margin_pct_20")) or 0.0
        discovery_score = to_float(candidate.get("discovery_score")) or 0.0
        movement_pct = to_float(candidate.get("movement_pct"))
        technical_ready = bool(candidate.get("technical_context_ready"))

        # Fail closed unless the upstream technical calculator had enough bars.
        if not technical_ready:
            reject("technical_context_not_ready")
            return None
        if entry_price is None or entry_price <= 0:
            reject("missing_entry_price", entry_price=entry_price)
            return None
        if breakout_high is None or average_volume is None or atr_value is None or atr_value <= 0:
            reject(
                "missing_breakout_context",
                breakout_high=breakout_high,
                average_volume=average_volume,
                atr_value=atr_value,
            )
            return None
        if atr_pct is None or volume_ratio is None:
            reject("missing_confirmation_context", atr_pct=atr_pct, volume_ratio=volume_ratio)
            return None

        # The core breakout rule: price must be above the 20-bar high.
        if not bool(candidate.get("price_trigger_20")):
            reject(
                "price_trigger_missing",
                entry_price=entry_price,
                breakout_high=breakout_high,
            )
            return None

        # Confirmation gates reduce false breakouts from low-volume prints or
        # tiny price movement. Equality does not pass; the evidence must clear
        # the configured threshold.
        if volume_ratio <= float(profile.parameters["volume_surge_multiple"]):
            reject(
                "volume_ratio_below_min",
                volume_ratio=volume_ratio,
                volume_surge_multiple=profile.parameters["volume_surge_multiple"],
            )
            return None
        if atr_pct <= float(profile.parameters["atr_floor_pct"]):
            reject(
                "atr_below_floor",
                atr_pct=atr_pct,
                atr_floor_pct=profile.parameters["atr_floor_pct"],
            )
            return None

        # ATR-based risk plan. This differs from build_signal because the stop
        # and target are volatility-scaled, not fixed percent distances.
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

        # A malformed ATR/price combination must never create a nonsensical
        # negative stop or a target below entry.
        if stop_loss_price <= 0 or target_price <= entry_price:
            reject(
                "invalid_risk_plan",
                stop_loss_price=stop_loss_price,
                target_price=target_price,
            )
            return None

        # GBP fields are for reporting/accounting surfaces. The trade decision
        # remains anchored to the native instrument price.
        price_ratio = (
            (entry_price_gbp / entry_price)
            if entry_price_gbp not in (None, 0) and entry_price > 0
            else None
        )
        stop_loss_price_gbp = convert_with_ratio(stop_loss_price, price_ratio)
        target_price_gbp = convert_with_ratio(target_price, price_ratio)
        break_even_trigger_price_gbp = convert_with_ratio(
            break_even_trigger_price,
            price_ratio,
        )
        risk_pct = round(((entry_price - stop_loss_price) / entry_price) * 100.0, 6)
        target_return_pct = round(((target_price - entry_price) / entry_price) * 100.0, 6)

        # Score rewards breakout margin, volume surge, ATR strength, and
        # discovery quality. Volume and ATR are capped in the score so one
        # extreme input cannot dominate the whole ranking.
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
            reject(
                "score_below_min",
                signal_score=signal_score,
                min_signal_score=profile.min_signal_score,
            )
            return None

        # Confidence follows the same evidence stack as score, but remains a
        # bounded ranking hint. It cannot override risk gates downstream.
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
        # This strategy builds the signal inline because it carries extra
        # breakout-specific audit fields: ATR, breakout high, volume ratio, and
        # the next-bar break-even trigger.
        return StrategySignal(
            strategy_id=profile.strategy_id,
            strategy_family=profile.family,
            profile_id=profile.profile_id,
            source=str(candidate.get("source", "")),
            symbol=normalized_symbol(candidate),
            asset_class=asset_class,
            canonical_instrument_id=str(candidate.get("canonical_instrument_id", "")).strip(),
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
