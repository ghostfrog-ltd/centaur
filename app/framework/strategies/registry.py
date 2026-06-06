from __future__ import annotations

from typing import Any

from app.framework.runtime.settings import RuntimeConfig

from .base import (
    StrategyDefinition,
    StrategyEvaluationBatch,
    StrategyProfile,
    StrategySignal,
)
from .crypto_momentum import CryptoMomentumStrategy
from .crypto_pullback import CryptoPullbackStrategy
from .crypto_research import CryptoResearchStrategy
from .liquidity_probe import LiquidityProbeStrategy
from .mean_reversion import MeanReversionStrategy
from .momentum import MomentumStrategy
from .momentum_breakout import MomentumVolatilityBreakoutStrategy


def evaluate_strategies(
    *,
    tick_id: str,
    candidates: list[dict[str, Any]],
    config: RuntimeConfig,
    market_context: dict[str, Any],
) -> StrategyEvaluationBatch:
    registry = build_strategy_registry()
    signals: list[StrategySignal] = []
    rejection_events: list[dict[str, Any]] = []
    evaluation_context = {**market_context, "strategy_rejections": rejection_events}
    profile_count = 0
    for strategy in registry:
        profiles = strategy.build_profiles(config)
        profile_count += len(profiles)
        for profile in profiles:
            if _profile_should_report_no_fresh_market_data(
                profile=profile,
                market_context=evaluation_context,
            ):
                rejection_events.append(
                    {
                        "strategy_id": profile.strategy_id,
                        "strategy_family": profile.family,
                        "profile_id": profile.profile_id,
                        "reason": "strategy.skipped_no_fresh_market_data",
                        "symbol": "",
                        "asset_class": ",".join(profile.asset_classes),
                        "canonical_instrument_id": "",
                        "metrics": {
                            "required_asset_classes": list(profile.asset_classes),
                        },
                    }
                )
            signals.extend(
                strategy.evaluate_profile(
                    profile=profile,
                    candidates=candidates,
                    market_context=evaluation_context,
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
        rejection_summary=_summarize_rejections(rejection_events),
    )


def build_strategy_registry() -> list[StrategyDefinition]:
    return [
        MomentumStrategy(),
        MomentumVolatilityBreakoutStrategy(),
        MeanReversionStrategy(),
        CryptoMomentumStrategy(),
        CryptoPullbackStrategy(),
        CryptoResearchStrategy(),
        LiquidityProbeStrategy(),
    ]


def _profile_should_report_no_fresh_market_data(
    *,
    profile: StrategyProfile,
    market_context: dict[str, Any],
) -> bool:
    fresh_sources = market_context.get("market_data_source_used_for_strategy", {})
    if not isinstance(fresh_sources, dict):
        fresh_sources = {}
    stale_exclusions = market_context.get("candidates_excluded_due_to_stale_source_by_asset_class", {})
    if not isinstance(stale_exclusions, dict):
        stale_exclusions = {}
    any_required_asset_is_fresh = any(
        str(fresh_sources.get(asset_class, "")).strip()
        for asset_class in profile.asset_classes
    )
    if any_required_asset_is_fresh:
        return False
    return any(int(stale_exclusions.get(asset_class, 0) or 0) > 0 for asset_class in profile.asset_classes)


def _summarize_rejections(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {
            "total_rejections": 0,
            "by_strategy_reason": [],
            "samples": [],
        }

    counts: dict[tuple[str, str], int] = {}
    samples: list[dict[str, Any]] = []
    for event in events:
        strategy_id = str(event.get("strategy_id") or "")
        reason = str(event.get("reason") or "")
        key = (strategy_id, reason)
        counts[key] = counts.get(key, 0) + 1
        if len(samples) < 12:
            samples.append(
                {
                    "strategy_id": strategy_id,
                    "profile_id": event.get("profile_id", ""),
                    "reason": reason,
                    "symbol": event.get("symbol", ""),
                    "asset_class": event.get("asset_class", ""),
                    "canonical_instrument_id": event.get("canonical_instrument_id", ""),
                    "metrics": event.get("metrics", {}),
                }
            )

    by_strategy_reason = [
        {
            "strategy_id": strategy_id,
            "reason": reason,
            "count": count,
        }
        for (strategy_id, reason), count in counts.items()
    ]
    by_strategy_reason.sort(
        key=lambda item: (int(item["count"]), item["strategy_id"], item["reason"]),
        reverse=True,
    )
    return {
        "total_rejections": len(events),
        "by_strategy_reason": by_strategy_reason[:25],
        "samples": samples,
    }


__all__ = [
    "CryptoMomentumStrategy",
    "CryptoPullbackStrategy",
    "CryptoResearchStrategy",
    "LiquidityProbeStrategy",
    "MeanReversionStrategy",
    "MomentumStrategy",
    "MomentumVolatilityBreakoutStrategy",
    "StrategyDefinition",
    "StrategyEvaluationBatch",
    "StrategyProfile",
    "StrategySignal",
    "build_strategy_registry",
    "evaluate_strategies",
]
