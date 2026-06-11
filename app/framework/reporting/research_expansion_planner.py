from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from app.framework.reporting.strategy_portfolio_research_planner import (
    DEFAULT_RESEARCH_EXPANSION_COMMAND,
    StrategyPortfolioResearchPlannerReport,
)
from app.framework.reporting.strategy_variant_research import StrategyVariantResearchService
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


SAFETY_STATEMENT = "Research-only expansion planner. No paper trades, approvals, live settings, thresholds, or promotion policy were changed."
_CANDIDATE_METADATA_KEY = "__research_candidate_metadata__"
_FAILED_GENERATED_STATUSES = {
    "no_viable_signal_after_variant_research",
    "insufficient_history_after_variant_research",
    "deprioritise_until_new_data",
    "no_viable_signal_after_precompute",
    "deprioritise",
    "retire_candidate",
    "insufficient_data_after_precompute",
}
_FAILED_FAMILY_PREFIXES = (
    "mean_reversion.snapback",
    "liquidity_probe.steady_flow",
    "momentum.strong",
    "momentum.balanced",
    "crypto_research.dip_rebound",
    "crypto_research.range_breakout",
    "crypto_pullback",
)


class ResearchExpansionPlannerReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(
            config=self.config,
            read_only=True,
            skip_schema_bootstrap=True,
            query_timeout_ms=15_000,
            lock_timeout_ms=None,
        )
        self.research_usage_ledger = usage_ledger or UsageLedger(
            config=self.config,
            read_only=False,
            skip_schema_bootstrap=True,
            query_timeout_ms=15_000,
            lock_timeout_ms=5_000,
        )
        self.portfolio_planner = StrategyPortfolioResearchPlannerReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
            operator_mode=True,
        )
        self.variant_service = StrategyVariantResearchService(
            config=self.config,
            usage_ledger=self.research_usage_ledger,
        )

    def build_report(self) -> dict[str, Any]:
        planner = self.portfolio_planner.build_report()
        generated_specs = self._persist_generated_specs(planner=planner)
        refreshed_planner = (
            StrategyPortfolioResearchPlannerReport(
                config=self.config,
                usage_ledger=self.usage_ledger,
                operator_mode=True,
            ).build_report()
            if generated_specs
            and hasattr(self.usage_ledger, "list_strategy_variant_definitions")
            else planner
        )
        planner = refreshed_planner
        ranked = list(planner.get("ranked_strategies", []) or [])
        selected = dict(planner.get("next_actionable_research_candidate") or {})
        expansion = dict(planner.get("research_expansion", {}) or {})
        next_action = str(expansion.get("next_research_expansion_action", "") or "")
        if not next_action:
            if selected:
                next_action = "continue_current_strategy_research"
            elif str(planner.get("research_universe_status", "") or "") == "blocked_on_data_or_runtime":
                next_action = "wait_for_new_market_data"
            else:
                next_action = "generate_new_strategy_family_research_only"
        return {
            "title": "Research Expansion Planner",
            "portfolio_research_status": str(planner.get("portfolio_research_status", "") or ""),
            "research_universe_status": str(planner.get("research_universe_status", "") or ""),
            "current_strategy_universe_status": str(planner.get("research_universe_status", "") or ""),
            "next_research_expansion_action": next_action,
            "next_required_operator_action": str(
                expansion.get("next_required_operator_action", "")
                or planner.get("next_required_operator_action", "")
                or "generate_new_research_candidates"
            ),
            "next_recommended_command": str(
                (generated_specs[0].get("next_recommended_command", "") if generated_specs else "")
                or expansion.get("next_recommended_command", "")
                or DEFAULT_RESEARCH_EXPANSION_COMMAND
            ),
            "next_generated_candidate": self._identity_string(generated_specs[0]) if generated_specs else "",
            "previous_generated_candidate_excluded": "yes" if generated_specs and generated_specs[0].get("excluded_candidate") else "no",
            "excluded_candidate": str(generated_specs[0].get("excluded_candidate", "") or "") if generated_specs else "",
            "exclusion_reason": str(generated_specs[0].get("exclusion_reason", "") or "") if generated_specs else "",
            "generated_candidate_specs": generated_specs,
            "command_allowlist_status": (
                "allowlisted_research_only"
                if generated_specs
                and all(str(item.get("command_execution_mode", "") or "") == "allowlisted_research_only" for item in generated_specs)
                else "not_generated"
            ),
            "recommendations": self._recommendations(
                planner=planner,
                ranked=ranked,
            ),
            "selected_next_strategy": selected,
            "paper_candidate_status": "blocked",
            "paper_trading_allowed": "no",
            "live_state": "unchanged",
            "threshold_state": "unchanged",
            "promotion_policy_state": "unchanged",
            "safety_statement": SAFETY_STATEMENT,
        }

    def _recommendations(self, *, planner: dict[str, Any], ranked: list[dict[str, Any]]) -> list[str]:
        universe = str(planner.get("research_universe_status", "") or "")
        runtime_action = dict(planner.get("next_data_runtime_action", {}) or {})
        recommendations: list[str] = []
        if universe == "exhausted_current_strategy_set":
            recommendations.extend(
                [
                    "generate new strategy family candidates from recent market behavior",
                    "test alternate crypto timeframes research-only",
                    "test alternate holding windows research-only",
                ]
            )
            if str(runtime_action.get("action", "") or "") == "adjust_signal_generation_research_only":
                recommendations.append("widen signal definitions research-only for zero-sample candidates")
        if universe in {"blocked_on_data_or_runtime", "waiting_for_new_data"}:
            recommendations.append("import or backfill more historical data if sample size remains the limiting factor")
            recommendations.append("wait_for_new_market_data if no bounded research action remains")
        if not recommendations:
            recommendations.append("continue the current bounded research path without changing paper/live state")
        return recommendations

    def render(self) -> str:
        report = self.build_report()
        lines = [
            str(report.get("title", "Research Expansion Planner")),
            f"portfolio_research_status={report.get('portfolio_research_status', '') or ''}",
            f"research_universe_status={report.get('research_universe_status', '') or ''}",
            f"next_research_expansion_action={report.get('next_research_expansion_action', '') or ''}",
            f"next_required_operator_action={report.get('next_required_operator_action', '') or ''}",
            f"next_recommended_command={report.get('next_recommended_command', '') or DEFAULT_RESEARCH_EXPANSION_COMMAND}",
            f"next_generated_candidate={report.get('next_generated_candidate', '') or ''}",
            f"previous_generated_candidate_excluded={report.get('previous_generated_candidate_excluded', '') or 'no'}",
            f"excluded_candidate={report.get('excluded_candidate', '') or ''}",
            f"exclusion_reason={report.get('exclusion_reason', '') or ''}",
        ]
        for spec in list(report.get("generated_candidate_specs", []) or []):
            lines.append(
                "generated_candidate_spec="
                f"{spec.get('candidate_id', '')}|"
                f"{spec.get('base_strategy_id', '')}/"
                f"{spec.get('profile_id', '')}/"
                f"{spec.get('timeframe', '')}|"
                f"{spec.get('command_execution_mode', '')}"
            )
        for recommendation in list(report.get("recommendations", []) or []):
            lines.append(f"recommendation={recommendation}")
        lines.append(str(report.get("safety_statement", "")))
        return "\n".join(lines)

    def _persist_generated_specs(self, *, planner: dict[str, Any]) -> list[dict[str, Any]]:
        specs = self._build_generated_candidate_specs(planner=planner)
        if (
            not specs
            or not hasattr(self, "research_usage_ledger")
            or not hasattr(self.research_usage_ledger, "ensure_strategy_variant_definition")
        ):
            return specs
        persisted: list[dict[str, Any]] = []
        now = datetime.now().astimezone()
        for spec in specs:
            if not str(spec.get("candidate_id", "") or "").strip():
                persisted.append(dict(spec))
                continue
            existing = self._existing_generated_definition(spec=spec)
            if existing:
                persisted.append(
                    {
                        **spec,
                        "persisted_variant_id": str(existing.get("variant_id", "") or spec.get("candidate_id", "") or ""),
                    }
                )
                continue
            params = dict(spec.get("params", {}) or {})
            params[_CANDIDATE_METADATA_KEY] = {
                "candidate_id": str(spec.get("candidate_id", "") or ""),
                "source_profile_id": str(spec.get("source_profile_id", "") or spec.get("profile_id", "") or ""),
                "label": str(spec.get("label", "") or ""),
                "hypothesis": str(spec.get("hypothesis", "") or ""),
                "research_only": True,
                "generated_at": now.isoformat(),
                "actionable_generated_candidate": True,
            }
            stored = self.research_usage_ledger.ensure_strategy_variant_definition(
                variant_id=str(spec.get("candidate_id", "") or ""),
                base_strategy_id=str(spec.get("base_strategy_id", "") or ""),
                profile_id=str(spec.get("profile_id", "") or ""),
                timeframe=str(spec.get("timeframe", "") or ""),
                params=params,
                created_at=now,
                created_by="research_expansion_planner",
                generation_reason="research_expansion_candidate",
                evaluation_status="pending",
                notes=json.dumps(spec, sort_keys=True),
            )
            persisted.append({**spec, "persisted_variant_id": str(stored.get("variant_id", "") or spec.get("candidate_id", "") or "")})
        return persisted

    def _existing_generated_definition(self, *, spec: dict[str, Any]) -> dict[str, Any]:
        if not hasattr(self.research_usage_ledger, "list_strategy_variant_definitions"):
            return {}
        rows = self.research_usage_ledger.list_strategy_variant_definitions(
            base_strategy_id=str(spec.get("base_strategy_id", "") or ""),
            profile_id=str(spec.get("profile_id", "") or ""),
            timeframe=str(spec.get("timeframe", "") or ""),
        )
        candidate_id = str(spec.get("candidate_id", "") or "")
        for row in rows:
            if str(row.get("variant_id", "") or "") == candidate_id:
                return dict(row)
            params = dict(row.get("params_json", {}) or {})
            metadata = dict(params.get(_CANDIDATE_METADATA_KEY, {}) or {})
            if str(metadata.get("candidate_id", "") or "") == candidate_id:
                return dict(row)
        return {}

    def _build_generated_candidate_specs(self, *, planner: dict[str, Any]) -> list[dict[str, Any]]:
        expansion = dict(planner.get("research_expansion", {}) or {})
        universe = str(planner.get("research_universe_status", "") or "")
        portfolio_status = str(planner.get("portfolio_research_status", "") or "")
        next_action = str(expansion.get("next_research_expansion_action", "") or "")
        should_generate_new_family = (
            next_action == "generate_new_strategy_family_research_only"
            or (
                portfolio_status == "no_actionable_candidate"
                and universe in {"exhausted_current_strategy_set", "waiting_for_new_data"}
                and next_action != "widen_range_breakout_signal_search_research_only"
            )
        )
        if not should_generate_new_family and next_action != "widen_range_breakout_signal_search_research_only":
            return []
        if not hasattr(self, "variant_service"):
            return []
        if next_action != "widen_range_breakout_signal_search_research_only":
            new_family_spec = self._liquidation_wick_reclaim_confirmed_spec(planner=planner)
            if new_family_spec:
                return [new_family_spec]
        exhausted = self._failed_generated_candidates(planner=planner)
        baseline = self.variant_service._resolve_profile(  # noqa: SLF001
            base_strategy_id="crypto_research.range_breakout",
            profile_id="range_breakout",
            timeframe="15Min",
        )
        builders = (
            self._range_breakout_compression_release_spec,
            self._range_breakout_trend_reclaim_spec,
        )
        exclusions: list[dict[str, str]] = []
        for builder in builders:
            spec, exclusion = builder(
                baseline=baseline,
                exhausted=exhausted,
            )
            if exclusion:
                exclusions.append(exclusion)
            if spec:
                if exclusions:
                    spec["excluded_candidate"] = exclusions[-1]["candidate"]
                    spec["exclusion_reason"] = exclusions[-1]["reason"]
                return [spec]
        return [self._no_safe_generated_candidate_spec(exclusions=exclusions)] if exclusions else []

    def _liquidation_wick_reclaim_confirmed_spec(self, *, planner: dict[str, Any]) -> dict[str, Any] | None:
        baseline = self.variant_service._resolve_profile(  # noqa: SLF001
            base_strategy_id="crypto_research.liquidation_wick_reclaim",
            profile_id="liquidation_wick_reclaim",
            timeframe="15Min",
        )
        candidate_id = "generated.crypto_research.liquidation_wick_reclaim.liquidation_wick_reclaim_confirmed.15Min.v1"
        existing = self._existing_generated_definition(
            spec={
                "candidate_id": candidate_id,
                "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
                "profile_id": "liquidation_wick_reclaim_confirmed",
                "timeframe": "15Min",
            }
        )
        if existing:
            return None
        params = dict(baseline.parameters)
        params.update(
            {
                "min_flush_pct": 1.15,
                "max_flush_pct": max(float(params.get("max_flush_pct", 4.0)), 5.0),
                "min_body_reclaim_ratio": 0.62,
                "min_close_to_high_ratio": 0.78,
                "max_close_below_vwap_pct": 0.1,
                "min_volume_ratio": 1.7,
                "min_atr_pct": 0.45,
                "max_atr_pct": min(float(params.get("max_atr_pct", 4.0)), 4.5),
                "holding_window_minutes": 180,
            }
        )
        next_command = (
            ".venv-mac/bin/python main.py --run-strategy-variant-research "
            "--base-strategy crypto_research.liquidation_wick_reclaim "
            "--profile-id liquidation_wick_reclaim_confirmed --timeframe 15Min"
        )
        return {
            "candidate_id": candidate_id,
            "base_strategy_id": "crypto_research.liquidation_wick_reclaim",
            "source_profile_id": "liquidation_wick_reclaim",
            "profile_id": "liquidation_wick_reclaim_confirmed",
            "label": "Crypto Research Liquidation Wick Reclaim Confirmed",
            "timeframe": "15Min",
            "asset_class": "crypto",
            "hypothesis": (
                "Recent crypto behavior has included sharp intraday flushes that fail to continue lower and instead "
                "reclaim most of the candle body quickly. A research-only liquidation-wick reclaim profile may capture "
                "that reversal shape without retrying broad dip buying or breakout continuation."
            ),
            "signal_definition": (
                "Research-only 15Min crypto reversal profile that requires a large negative flush, strong lower-wick "
                "reclaim, a close back near the bar high, elevated volume, and a close that is no more than 0.1% below VWAP."
            ),
            "entry_rules": [
                "Require technical_context_ready and crypto identity/spread/liquidity gates to remain true.",
                "Require movement_pct <= -1.15% so the setup reflects an actual liquidation-style flush, not a shallow dip.",
                "Require the close to reclaim at least 62% of the full candle range from the bar low.",
                "Require the close to finish within the top 22% of the candle range to reject failed-continuation bars.",
                "Require volume_ratio_20 >= 1.7 and atr_pct_20 >= 0.45 to focus on genuine high-volatility shakeouts.",
                "Require the close to be at or above VWAP minus 0.1% so the bar has already reclaimed intrabar value.",
            ],
            "exit_rules": [
                "Research-only replay exits keep the existing managed target framework for crypto research variants.",
                "Use a 180 minute holding window to test whether post-flush reversals resolve within the same intraday regime.",
            ],
            "stop_rules": [
                f"Keep stop_loss_pct at {baseline.stop_loss_pct} from the bounded crypto research envelope.",
                f"Keep target_multiple at {baseline.target_multiple} from the bounded crypto research envelope.",
            ],
            "holding_window": "180 minutes",
            "parameters_to_sweep": {
                "min_flush_pct": [1.15, 1.4, 1.75],
                "min_body_reclaim_ratio": [0.62, 0.68, 0.74],
                "min_close_to_high_ratio": [0.78, 0.82, 0.86],
                "min_volume_ratio": [1.7, 1.9, 2.1],
                "max_close_below_vwap_pct": [0.1, 0.05, 0.0],
                "holding_window_minutes": [120, 180, 240],
            },
            "risk_notes": [
                "Research-only candidate. Not approved for paper or live.",
                "Paper thresholds, live settings, and promotion policy remain unchanged.",
                "No paper orders or live orders may be created from this candidate.",
            ],
            "why_this_is_different_from_failed_candidates": (
                "This is a new crypto liquidation-wick reclaim family, not a retry of snapback, liquidity probe, "
                "momentum strong/balanced, dip_rebound, crypto_pullback, or range_breakout. It looks for oversold "
                "flush-and-reclaim structure with bar-shape and VWAP confirmation, rather than broad dip buying, "
                "trend continuation, or breakout expansion. Distinct failed families considered: "
                f"{self._distinct_failed_family_list(planner=planner)}."
            ),
            "expected_sample_source": (
                "Persisted crypto 15Min historical bars with open/high/low/close, vwap, movement_pct, volume_ratio_20, "
                "atr_pct_20, technical_context_ready, and sufficient forward bars for a 180 minute holding window."
            ),
            "next_recommended_command": next_command,
            "command_execution_mode": "allowlisted_research_only",
            "operator_review_reason": "",
            "paper_candidate_status": "blocked",
            "paper_trading_allowed": "no",
            "allowlist_status": "allowlisted_research_only",
            "generation_decision": "generate_distinct_candidate",
            "params": params,
        }

    def _failed_generated_candidates(self, *, planner: dict[str, Any]) -> dict[tuple[str, str, str], dict[str, str]]:
        exhausted: dict[tuple[str, str, str], dict[str, str]] = {}
        for item in list(planner.get("ranked_strategies", []) or []):
            metadata = dict(item.get("generated_candidate_metadata") or {})
            if not metadata:
                continue
            status = str(item.get("research_status", "") or "")
            if status not in _FAILED_GENERATED_STATUSES:
                continue
            identity = (
                str(item.get("base_strategy_id", "") or ""),
                str(item.get("profile_id", "") or ""),
                str(item.get("timeframe", "") or ""),
            )
            exhausted[identity] = {
                "candidate": self._identity_string(item),
                "reason": str(
                    (dict(item.get("generated_candidate_zero_sample_outcome") or {}).get("reason", ""))
                    or status
                ),
            }
        return exhausted

    def _range_breakout_compression_release_spec(
        self,
        *,
        baseline: Any,
        exhausted: dict[tuple[str, str, str], dict[str, str]],
    ) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
        identity = (
            "crypto_research.range_breakout",
            "range_breakout_compression_release",
            "1Hour",
        )
        if identity in exhausted:
            return None, exhausted[identity]
        params = dict(baseline.parameters)
        params.update(
            {
                "min_movement_pct": 0.16,
                "min_discovery_score": max(2.8, float(params.get("min_discovery_score", 3.0))),
                "min_volume_ratio": 1.35,
                "min_atr_pct": 0.14,
                "max_atr_pct": min(1.8, float(params.get("max_atr_pct", 3.0))),
                "holding_window_minutes": max(180, int(baseline.holding_window_minutes)),
            }
        )
        next_command = (
            ".venv-mac/bin/python main.py --run-strategy-variant-research "
            "--base-strategy crypto_research.range_breakout "
            "--profile-id range_breakout_compression_release --timeframe 1Hour"
        )
        return {
            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_compression_release.1Hour.v1",
            "base_strategy_id": "crypto_research.range_breakout",
            "source_profile_id": "range_breakout",
            "profile_id": "range_breakout_compression_release",
            "label": "Crypto Research Range Breakout Compression Release",
            "timeframe": "1Hour",
            "asset_class": "crypto",
            "hypothesis": (
                "The failed 15Min widened-breakout profile suggests intraday history is too thin for broad signal "
                "relaxation, so the next safe test is a slower 1Hour breakout that requires tighter pre-breakout "
                "compression and stronger participation before release."
            ),
            "signal_definition": (
                "Research-only 1Hour breakout profile that still requires technical_context_ready and price_trigger_20, "
                "but shifts from a permissive wide-signal gate to a compression-release gate with stronger volume, "
                "higher directional movement, and a lower ATR floor tuned for hourly bars."
            ),
            "entry_rules": [
                "Require technical_context_ready and price_trigger_20 to remain true.",
                "Shift timeframe to 1Hour because the failed 15Min candidate exhausted available history without producing samples.",
                "Raise min_movement_pct to 0.16 so only clearer breakouts enter the replay set.",
                "Raise min_volume_ratio to 1.35 to require stronger participation than the failed wide-signal profile.",
                "Lower min_atr_pct to 0.14 on 1Hour bars so compressed setups can still qualify before full expansion.",
            ],
            "exit_rules": [
                "Research-only replay exits continue to use the existing range breakout managed target logic.",
                "Extend holding window to 180 minutes to match slower post-breakout continuation on 1Hour bars.",
            ],
            "stop_rules": [
                f"Keep stop_loss_pct at {baseline.stop_loss_pct} from the existing crypto research envelope.",
                f"Keep target_multiple at {baseline.target_multiple} from the existing crypto research envelope.",
            ],
            "holding_window": "180 minutes",
            "parameters_to_sweep": {
                "min_movement_pct": [0.16, 0.20, 0.24],
                "min_volume_ratio": [1.35, 1.5, 1.65],
                "min_atr_pct": [0.14, 0.18, 0.22],
                "holding_window_minutes": [180, 240, 360],
            },
            "risk_notes": [
                "Research-only candidate. Not approved for paper or live.",
                "Paper thresholds, live settings, and promotion policy remain unchanged.",
                "Crypto identity, spread, trade-count, and discovery gates stay in force.",
            ],
            "why_this_is_different_from_failed_candidates": (
                "This excludes the failed generated candidate crypto_research.range_breakout/range_breakout_wide_signal/15Min "
                "and avoids regenerating unchanged versions of either failed generated profile "
                "crypto_research.range_breakout/range_breakout_wide_signal/15Min or "
                "crypto_research.range_breakout/range_breakout_compression_release/1Hour unless newer evidence exists. "
                "It also avoids the previously failed snapback 1Hour concentration-fragile branch, snapback 15Min no-progress "
                "branch, liquidity_probe 15Min negative branch, momentum strong/balanced negative branches, and dip_rebound "
                "15Min weak post-precompute branch by staying in a distinct crypto range_breakout family/profile with a "
                "timeframe-shifted compression-release hypothesis."
            ),
            "expected_sample_source": (
                "Persisted crypto 1Hour historical bars with technical_context_ready, price_trigger_20, "
                "volume_ratio_20, atr_pct_20, and sufficient post-trigger holding-window coverage."
            ),
            "next_recommended_command": next_command,
            "command_execution_mode": "allowlisted_research_only",
            "operator_review_reason": "",
            "paper_candidate_status": "blocked",
            "paper_trading_allowed": "no",
            "allowlist_status": "allowlisted_research_only",
            "generation_decision": "generate_distinct_candidate",
            "params": params,
        }, None

    def _range_breakout_trend_reclaim_spec(
        self,
        *,
        baseline: Any,
        exhausted: dict[tuple[str, str, str], dict[str, str]],
    ) -> tuple[dict[str, Any] | None, dict[str, str] | None]:
        identity = (
            "crypto_research.range_breakout",
            "range_breakout_trend_reclaim",
            "4Hour",
        )
        if identity in exhausted:
            return None, exhausted[identity]
        params = dict(baseline.parameters)
        params.update(
            {
                "min_movement_pct": 0.28,
                "min_discovery_score": max(3.0, float(params.get("min_discovery_score", 3.0))),
                "min_volume_ratio": 1.45,
                "min_atr_pct": 0.18,
                "max_atr_pct": min(2.2, float(params.get("max_atr_pct", 3.0))),
                "holding_window_minutes": max(360, int(baseline.holding_window_minutes)),
            }
        )
        next_command = (
            ".venv-mac/bin/python main.py --run-strategy-variant-research "
            "--base-strategy crypto_research.range_breakout "
            "--profile-id range_breakout_trend_reclaim --timeframe 4Hour"
        )
        return {
            "candidate_id": "generated.crypto_research.range_breakout.range_breakout_trend_reclaim.4Hour.v1",
            "base_strategy_id": "crypto_research.range_breakout",
            "source_profile_id": "range_breakout",
            "profile_id": "range_breakout_trend_reclaim",
            "label": "Crypto Research Range Breakout Trend Reclaim",
            "timeframe": "4Hour",
            "asset_class": "crypto",
            "hypothesis": (
                "If both faster generated breakout candidates failed with zero usable samples, the next bounded test "
                "should shift to higher-timeframe reclaim behavior where breakouts are confirmed by sustained trend re-entry."
            ),
            "signal_definition": (
                "Research-only 4Hour breakout reclaim profile that keeps the existing breakout envelope but requires "
                "stronger movement, stronger volume confirmation, and a longer holding window aligned to higher-timeframe continuation."
            ),
            "entry_rules": [
                "Require technical_context_ready and price_trigger_20 to remain true.",
                "Shift timeframe to 4Hour to test whether higher-timeframe reclaim structures produce bounded usable samples.",
                "Raise min_movement_pct to 0.28 so only stronger reclaim moves enter the replay set.",
                "Raise min_volume_ratio to 1.45 to require stronger participation than lower-timeframe generated candidates.",
            ],
            "exit_rules": [
                "Research-only replay exits continue to use the existing range breakout managed target logic.",
                "Extend holding window to 360 minutes to fit slower continuation on 4Hour bars.",
            ],
            "stop_rules": [
                f"Keep stop_loss_pct at {baseline.stop_loss_pct} from the existing crypto research envelope.",
                f"Keep target_multiple at {baseline.target_multiple} from the existing crypto research envelope.",
            ],
            "holding_window": "360 minutes",
            "parameters_to_sweep": {
                "min_movement_pct": [0.28, 0.32, 0.36],
                "min_volume_ratio": [1.45, 1.6, 1.75],
                "min_atr_pct": [0.18, 0.22, 0.26],
                "holding_window_minutes": [360, 480, 720],
            },
            "risk_notes": [
                "Research-only candidate. Not approved for paper or live.",
                "Paper thresholds, live settings, and promotion policy remain unchanged.",
                "Crypto identity, spread, trade-count, and discovery gates stay in force.",
            ],
            "why_this_is_different_from_failed_candidates": (
                "This candidate is distinct from the failed generated wide-signal and compression-release breakout profiles "
                "because it shifts both the timeframe and the signal shape to a slower reclaim hypothesis."
            ),
            "expected_sample_source": (
                "Persisted crypto 4Hour historical bars with technical_context_ready, price_trigger_20, "
                "volume_ratio_20, atr_pct_20, and sufficient post-trigger holding-window coverage."
            ),
            "next_recommended_command": next_command,
            "command_execution_mode": "allowlisted_research_only",
            "operator_review_reason": "",
            "paper_candidate_status": "blocked",
            "paper_trading_allowed": "no",
            "allowlist_status": "allowlisted_research_only",
            "generation_decision": "generate_distinct_candidate",
            "params": params,
        }, None

    def _no_safe_generated_candidate_spec(self, *, exclusions: list[dict[str, str]]) -> dict[str, Any]:
        last = exclusions[-1] if exclusions else {"candidate": "", "reason": ""}
        return {
            "candidate_id": "",
            "base_strategy_id": "",
            "source_profile_id": "",
            "profile_id": "",
            "timeframe": "",
            "hypothesis": "",
            "signal_definition": "",
            "parameters_to_sweep": {},
            "why_this_is_different_from_failed_candidates": (
                "All currently known generated range breakout candidates are already terminally failed without newer evidence."
            ),
            "expected_sample_source": "",
            "next_recommended_command": DEFAULT_RESEARCH_EXPANSION_COMMAND,
            "command_execution_mode": "allowlisted_research_only",
            "operator_review_reason": "wait_for_new_market_data",
            "paper_candidate_status": "blocked",
            "paper_trading_allowed": "no",
            "allowlist_status": "allowlisted_research_only",
            "generation_decision": "wait_for_new_market_data",
            "params": {},
            "excluded_candidate": str(last.get("candidate", "") or ""),
            "exclusion_reason": str(last.get("reason", "") or ""),
        }

    def _identity_string(self, item: dict[str, Any]) -> str:
        return (
            f"{str(item.get('base_strategy_id', '') or '')}/"
            f"{str(item.get('profile_id', '') or '')}/"
            f"{str(item.get('timeframe', '') or '')}"
        ).strip("/")

    def _distinct_failed_family_list(self, *, planner: dict[str, Any]) -> str:
        seen: list[str] = []
        for item in list(planner.get("ranked_strategies", []) or []):
            strategy_id = str(item.get("base_strategy_id", "") or "")
            if any(strategy_id.startswith(prefix) for prefix in _FAILED_FAMILY_PREFIXES) and strategy_id not in seen:
                seen.append(strategy_id)
        return ", ".join(seen or list(_FAILED_FAMILY_PREFIXES))
