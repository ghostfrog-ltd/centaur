from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta
import hashlib
import json
from statistics import mean
from time import monotonic
from typing import Any

from app.framework.engine.candidate_engine import rank_candidates
from app.framework.engine.replay import (
    _eligible_replay_timestamps,
    _enrich_replay_candidates_with_technicals,
    _max_checkpoint_window_minutes,
    _recent_strategy_keys,
    _replay_tick_id,
    _safe_slug,
    _supported_checkpoint_windows,
    _timeframe_to_minutes,
)
from app.framework.engine.shadow import build_shadow_proposals, evaluate_shadow_checkpoint
from app.framework.reporting.console import ScreenLogger
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger
from app.framework.strategies.base import StrategyProfile
from app.framework.strategies.common import liquidity_component
from app.framework.strategies.registry import build_strategy_registry


SAFE_RECOMMENDED_STATUS = (
    "pending",
    "evaluated",
    "rejected",
    "paper_candidate_requires_manual_approval",
)
_GENERATED_CANDIDATE_METADATA_KEY = "__research_candidate_metadata__"


class StrategyVariantResearchService:
    """Research-only strategy variant generation and replay evaluation."""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
        logger: ScreenLogger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        replay_budget_seconds = max(
            1,
            int(getattr(self.config, "research_runtime_budget_seconds", 20) or 20),
        )
        self.usage_ledger = usage_ledger or UsageLedger(
            config=self.config,
            query_timeout_ms=min(60_000, replay_budget_seconds * 1_000),
            lock_timeout_ms=min(10_000, max(1_000, replay_budget_seconds * 250)),
        )
        self.logger = logger or ScreenLogger()

    def safe_variable_params(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
    ) -> list[dict[str, Any]]:
        baseline = self._resolve_profile(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        if base_strategy_id == "crypto_momentum.trend":
            return [
                {
                    "name": "min_movement_pct",
                    "current": baseline.parameters["min_movement_pct"],
                    "reason": "controls how much positive movement is required before momentum logic activates",
                },
                {
                    "name": "max_movement_pct",
                    "current": baseline.parameters["max_movement_pct"],
                    "reason": "caps stretched continuation entries so replay can test whether late entries are the problem",
                },
                {
                    "name": "min_discovery_score",
                    "current": baseline.parameters["min_discovery_score"],
                    "reason": "tightens or loosens the existing discovery evidence gate within the same family",
                },
                {
                    "name": "min_trade_count",
                    "current": baseline.parameters["min_trade_count"],
                    "reason": "adjusts the liquidity floor without changing the strategy family",
                },
                {
                    "name": "stop_loss_pct",
                    "current": baseline.stop_loss_pct,
                    "reason": "tests conservative crypto momentum risk distance in replay only",
                },
                {
                    "name": "target_multiple",
                    "current": baseline.target_multiple,
                    "reason": "tests whether winner size is constrained by the current target multiple",
                },
                {
                    "name": "holding_window_minutes",
                    "current": baseline.holding_window_minutes,
                    "reason": "research-only replay hold override for diagnosing whether exits are too early or too late",
                },
            ]
        if str(baseline.family or "") == "crypto_pullback":
            return [
                {
                    "name": "max_pullback_pct",
                    "current": baseline.parameters["max_pullback_pct"],
                    "reason": "controls how deep a downside move can be before the watch-only crypto pullback profile stops considering it a comparable setup",
                },
                {
                    "name": "min_discovery_score",
                    "current": baseline.parameters["min_discovery_score"],
                    "reason": "keeps weak discovery evidence from entering the same crypto pullback watch family",
                },
                {
                    "name": "preferred_min_trade_count",
                    "current": baseline.parameters["preferred_min_trade_count"],
                    "reason": "tests whether a higher crypto trade-count preference improves replay quality without changing the research-only execution boundary",
                },
                {
                    "name": "stop_loss_pct",
                    "current": baseline.stop_loss_pct,
                    "reason": "adjusts the existing crypto pullback risk distance conservatively in replay only",
                },
                {
                    "name": "target_multiple",
                    "current": baseline.target_multiple,
                    "reason": "adjusts the current crypto pullback recovery target without introducing new indicators",
                },
                {
                    "name": "holding_window_minutes",
                    "current": baseline.holding_window_minutes,
                    "reason": "research-only replay hold override for diagnosing whether the watch window is too short for slower crypto pullback reversals",
                },
            ]
        if str(baseline.family or "") == "crypto_research" and profile_id == "dip_rebound":
            return [
                {
                    "name": "min_pullback_pct",
                    "current": baseline.parameters["min_pullback_pct"],
                    "reason": "tests whether the crypto dip rebound profile activates too early on shallow pullbacks.",
                },
                {
                    "name": "max_pullback_pct",
                    "current": baseline.parameters["max_pullback_pct"],
                    "reason": "tests whether deeper crypto dips should still be considered comparable rebound setups.",
                },
                {
                    "name": "min_discovery_score",
                    "current": baseline.parameters["min_discovery_score"],
                    "reason": "keeps weak discovery evidence from entering the same crypto research family.",
                },
                {
                    "name": "min_trade_count",
                    "current": baseline.parameters["min_trade_count"],
                    "reason": "tests whether a higher liquidity floor improves replay quality for dip rebound evidence.",
                },
                {
                    "name": "stop_loss_pct",
                    "current": baseline.stop_loss_pct,
                    "reason": "adjusts the current crypto dip rebound risk distance conservatively in replay only.",
                },
                {
                    "name": "target_multiple",
                    "current": baseline.target_multiple,
                    "reason": "tests whether the current rebound target is too ambitious or too conservative.",
                },
                {
                    "name": "holding_window_minutes",
                    "current": baseline.holding_window_minutes,
                    "reason": "research-only replay hold override for diagnosing whether rebounds need more time to resolve.",
                },
            ]
        params: list[dict[str, Any]] = []
        if "max_movement_pct" in baseline.parameters:
            params.append(
                {
                    "name": "max_movement_pct",
                    "current": baseline.parameters["max_movement_pct"],
                    "reason": "controls how deep the pullback must be before the strategy activates",
                }
            )
        if "min_discovery_score" in baseline.parameters:
            params.append(
                {
                    "name": "min_discovery_score",
                    "current": baseline.parameters["min_discovery_score"],
                    "reason": "keeps weak discovery evidence from entering the same strategy family",
                }
            )
        if "min_trade_count" in baseline.parameters:
            params.append(
                {
                    "name": "min_trade_count",
                    "current": baseline.parameters["min_trade_count"],
                    "reason": "tightens or loosens the existing liquidity floor without changing semantics",
                }
            )
        params.extend(
            [
                {
                    "name": "stop_loss_pct",
                    "current": baseline.stop_loss_pct,
                    "reason": "adjusts existing risk distance conservatively inside the same family",
                },
                {
                    "name": "target_multiple",
                    "current": baseline.target_multiple,
                    "reason": "adjusts the current take-profit multiple without adding new indicators",
                },
            ]
        )
        if "min_expected_net_move_pct" in baseline.parameters:
            params.append(
                {
                    "name": "min_expected_net_move_pct",
                    "current": baseline.parameters["min_expected_net_move_pct"],
                    "reason": "keeps cost-aware variants from taking moves too small to survive friction",
                }
            )
        params.append(
            {
                "name": "holding_window_minutes",
                "current": baseline.holding_window_minutes,
                "reason": "research-only replay hold override for diagnosing whether exits are too early or too late",
            }
        )
        return params

    def run_research(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
        created_by: str = "strategy_variant_research",
        bounded_diagnosis: bool = False,
    ) -> dict[str, Any]:
        candidate_snapshot_before = self._generated_candidate_snapshot(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        profile = self._resolve_profile(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        persisted_base_strategy_id = self._persisted_base_strategy_id(
            requested_base_strategy_id=base_strategy_id,
            profile=profile,
        )
        now = datetime.now().astimezone()
        replay_budget_seconds = max(
            1,
            int(getattr(self.config, "research_runtime_budget_seconds", 20) or 20),
        )
        runtime_deadline = monotonic() + replay_budget_seconds
        replay_days = max(
            1,
            int(
                getattr(
                    self.config,
                    "diagnosis_replay_default_days" if bounded_diagnosis else "historical_replay_default_days",
                    self.config.historical_replay_default_days,
                ) or self.config.historical_replay_default_days
            ),
        )
        shared_end_at = now
        shared_start_at = now - timedelta(days=replay_days)
        history_cache: dict[tuple[Any, ...], dict[str, Any]] = {}
        variants = self._ensure_variants(
            profile=profile,
            persisted_base_strategy_id=persisted_base_strategy_id,
            timeframe=timeframe,
            created_at=now,
            created_by=created_by,
        )
        baseline = next(item for item in variants if item["generation_reason"] == "baseline_profile")
        baseline_metrics = self._evaluate_variant(
            profile=self._profile_from_variant(profile=profile, variant=baseline),
            variant=baseline,
            persisted_base_strategy_id=persisted_base_strategy_id,
            timeframe=timeframe,
            replay_id=f"variant-baseline-{now.strftime('%Y%m%d-%H%M%S')}",
            start_at=shared_start_at,
            end_at=shared_end_at,
            runtime_deadline=runtime_deadline,
            bounded_diagnosis=bounded_diagnosis,
            history_cache=history_cache,
        )
        persisted = [
            self._persist_evaluation(
                evaluation=self._finalize_evaluation(
                    evaluation=baseline_metrics,
                    variant=baseline,
                    baseline=baseline_metrics,
                ),
            )
        ]
        if bounded_diagnosis:
            return {
                "base_strategy_id": base_strategy_id,
                "profile_id": profile_id,
                "timeframe": timeframe,
                "safe_variable_params": self.safe_variable_params(
                    base_strategy_id=base_strategy_id,
                    profile_id=profile_id,
                    timeframe=timeframe,
                ),
                "variants_generated": len(variants) - 1,
                "variants_total_including_baseline": len(variants),
                "baseline_variant_id": baseline["variant_id"],
                "baseline_metrics": persisted[0],
                "evaluations": persisted,
                "runtime_budget_seconds": replay_budget_seconds,
                "diagnosis_scope": "baseline_only_bounded_runtime",
            }
        for variant in variants:
            if variant["variant_id"] == baseline["variant_id"]:
                continue
            evaluation = self._evaluate_variant(
                profile=self._profile_from_variant(profile=profile, variant=variant),
                variant=variant,
                persisted_base_strategy_id=persisted_base_strategy_id,
                timeframe=timeframe,
                replay_id=f"variant-grid-{now.strftime('%Y%m%d-%H%M%S')}",
                start_at=shared_start_at,
                end_at=shared_end_at,
                runtime_deadline=runtime_deadline,
                bounded_diagnosis=bounded_diagnosis,
                history_cache=history_cache,
            )
            persisted.append(
                self._persist_evaluation(
                    evaluation=self._finalize_evaluation(
                        evaluation=evaluation,
                        variant=variant,
                        baseline=baseline_metrics,
                    ),
                )
            )
        runtime_summary = self._research_runtime_summary(
            evaluations=persisted,
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        candidate_id = self._generated_candidate_id(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        candidate_update = self._persist_generated_candidate_execution_result(
            candidate_id=candidate_id,
            runtime_summary=runtime_summary,
            variants_generated=len(variants) - 1,
            evaluated_rows=persisted,
            snapshot_before=candidate_snapshot_before,
        )
        return {
            "candidate_id": candidate_id,
            "lifecycle_status": str(candidate_update.get("lifecycle_status_after", "") or "variant_research_pending"),
            "base_strategy_id": base_strategy_id,
            "profile_id": profile_id,
            "timeframe": timeframe,
            "safe_variable_params": self.safe_variable_params(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
            ),
            "variants_generated": len(variants) - 1,
            "variants_total_including_baseline": len(variants),
            "baseline_variant_id": baseline["variant_id"],
            "baseline_metrics": persisted[0],
            "evaluations": persisted,
            "runtime_budget_seconds": replay_budget_seconds if bounded_diagnosis else None,
            **candidate_update,
            **runtime_summary,
        }

    def diagnose_variants(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
    ) -> dict[str, Any]:
        definitions = self.usage_ledger.list_strategy_variant_definitions(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        evaluations = self.usage_ledger.list_strategy_variant_evaluations(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            limit=500,
        )
        latest_by_variant: dict[str, dict[str, Any]] = {}
        for evaluation in evaluations:
            variant_id = str(evaluation.get("variant_id", "") or "")
            if variant_id and variant_id not in latest_by_variant:
                latest_by_variant[variant_id] = evaluation
        baseline_definition = next(
            (item for item in definitions if item.get("generation_reason") == "baseline_profile"),
            None,
        )
        baseline_variant_id = str((baseline_definition or {}).get("variant_id", "") or "")
        baseline_evaluation = latest_by_variant.get(baseline_variant_id, {})
        baseline_raw = dict(baseline_evaluation.get("raw_json", {}) or {})
        baseline_decision_hash = str((baseline_raw.get("diagnostics", {}) or {}).get("decision_set_hash", "") or "")
        baseline_metrics_fingerprint = self._metrics_fingerprint(baseline_evaluation)
        rows: list[dict[str, Any]] = []
        for definition in definitions:
            variant_id = str(definition.get("variant_id", "") or "")
            evaluation = latest_by_variant.get(variant_id, {})
            raw = dict(evaluation.get("raw_json", {}) or {})
            diagnostics = dict(raw.get("diagnostics", {}) or {})
            metrics_fingerprint = self._metrics_fingerprint(evaluation)
            rows.append(
                {
                    "variant_id": variant_id,
                    "generation_reason": str(definition.get("generation_reason", "") or ""),
                    "params_json": dict(definition.get("params_json", {}) or {}),
                    "params_hash": str(diagnostics.get("params_hash", self._params_hash(dict(definition.get("params_json", {}) or {}))) or ""),
                    "generated_signal_count": int(diagnostics.get("generated_signal_count", 0) or 0),
                    "generated_proposal_count": int(diagnostics.get("generated_proposal_count", 0) or 0),
                    "usable_decision_count": int(diagnostics.get("usable_decision_count", 0) or 0),
                    "data_adequacy": dict(diagnostics.get("data_adequacy", {}) or {}),
                    "rejected_by_param_filter_count": int(diagnostics.get("rejected_by_param_filter_count", 0) or 0),
                    "symbols_with_decisions": list(diagnostics.get("symbols_with_decisions", []) or []),
                    "first_decision_fingerprint": str(diagnostics.get("first_decision_fingerprint", "") or ""),
                    "decision_set_hash": str(diagnostics.get("decision_set_hash", "") or ""),
                    "metrics_fingerprint": metrics_fingerprint,
                    "decision_set_differs_from_baseline": (
                        bool(baseline_decision_hash)
                        and str(diagnostics.get("decision_set_hash", "") or "") != baseline_decision_hash
                    ),
                    "metrics_differ_from_baseline": (
                        bool(baseline_metrics_fingerprint)
                        and metrics_fingerprint != baseline_metrics_fingerprint
                    ),
                    "warning": self._diagnostic_warning(
                        variant_id=variant_id,
                        baseline_variant_id=baseline_variant_id,
                        params_hash=str(diagnostics.get("params_hash", "") or ""),
                        baseline_params_hash=str((baseline_raw.get("diagnostics", {}) or {}).get("params_hash", "") or ""),
                        decision_set_hash=str(diagnostics.get("decision_set_hash", "") or ""),
                        baseline_decision_set_hash=baseline_decision_hash,
                        metrics_fingerprint=metrics_fingerprint,
                        baseline_metrics_fingerprint=baseline_metrics_fingerprint,
                    ),
                    "recommended_status": str(evaluation.get("recommended_status", "pending") or "pending"),
                }
            )
        return {
            "title": "Strategy Variant Diagnostics",
            "base_strategy_id": base_strategy_id,
            "profile_id": profile_id,
            "timeframe": timeframe,
            "baseline_variant_id": baseline_variant_id,
            "baseline_params_hash": str((baseline_raw.get("diagnostics", {}) or {}).get("params_hash", "") or ""),
            "rows": rows,
            "safety_statement": "Research-only diagnostic. No paper or live approval has been changed.",
        }

    def _resolve_profile(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
    ) -> StrategyProfile:
        direct = self._resolve_registry_profile(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
        )
        if direct is not None:
            return direct
        generated = self._resolve_generated_candidate_profile(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        if generated is not None:
            return generated
        raise ValueError(f"Unsupported strategy/profile: {base_strategy_id}/{profile_id}")

    def _resolve_registry_profile(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
    ) -> StrategyProfile | None:
        for strategy in build_strategy_registry():
            for profile in strategy.build_profiles(self.config):
                if profile.profile_id != profile_id:
                    continue
                if profile.strategy_id == base_strategy_id:
                    return profile
                if str(profile.family or "") == base_strategy_id:
                    return profile
                if profile.strategy_id.startswith(f"{base_strategy_id}."):
                    return profile
        return None

    def _resolve_generated_candidate_profile(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
    ) -> StrategyProfile | None:
        if not hasattr(self.usage_ledger, "list_strategy_variant_definitions"):
            return None
        definitions = list(
            self.usage_ledger.list_strategy_variant_definitions(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
            )
        )
        for definition in reversed(definitions):
            params = dict(definition.get("params_json", {}) or {})
            metadata = dict(params.get(_GENERATED_CANDIDATE_METADATA_KEY, {}) or {})
            source_profile_id = str(metadata.get("source_profile_id", "") or "")
            if not source_profile_id:
                continue
            baseline = self._resolve_registry_profile(
                base_strategy_id=base_strategy_id,
                profile_id=source_profile_id,
            )
            if baseline is None:
                continue
            generated_params = {
                key: value
                for key, value in params.items()
                if key != _GENERATED_CANDIDATE_METADATA_KEY
            }
            return replace(
                baseline,
                profile_id=profile_id,
                label=str(metadata.get("label", "") or f"{baseline.label} ({profile_id})"),
                holding_window_minutes=int(
                    generated_params.get("holding_window_minutes", baseline.holding_window_minutes)
                    or baseline.holding_window_minutes
                ),
                stop_loss_pct=float(generated_params.get("stop_loss_pct", baseline.stop_loss_pct) or baseline.stop_loss_pct),
                target_multiple=float(generated_params.get("target_multiple", baseline.target_multiple) or baseline.target_multiple),
                min_signal_score=float(generated_params.get("min_signal_score", baseline.min_signal_score) or baseline.min_signal_score),
                parameters=generated_params,
            )
        return None

    def _generated_candidate_id(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
    ) -> str:
        if not hasattr(self.usage_ledger, "list_strategy_variant_definitions"):
            return ""
        definitions = list(
            self.usage_ledger.list_strategy_variant_definitions(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
            )
        )
        for definition in reversed(definitions):
            params = dict(definition.get("params_json", {}) or {})
            metadata = dict(params.get(_GENERATED_CANDIDATE_METADATA_KEY, {}) or {})
            if metadata:
                return str(definition.get("variant_id", "") or "")
        return ""

    def _ensure_variants(
        self,
        *,
        profile: StrategyProfile,
        persisted_base_strategy_id: str | None = None,
        timeframe: str,
        created_at: datetime,
        created_by: str,
    ) -> list[dict[str, Any]]:
        baseline_params = self._variant_params_from_profile(profile)
        baseline = self.usage_ledger.ensure_strategy_variant_definition(
            variant_id=self._build_variant_id(
                base_strategy_id=persisted_base_strategy_id or profile.strategy_id,
                profile_id=profile.profile_id,
                timeframe=timeframe,
                params=baseline_params,
            ),
            base_strategy_id=persisted_base_strategy_id or profile.strategy_id,
            profile_id=profile.profile_id,
            timeframe=timeframe,
            params=baseline_params,
            created_at=created_at,
            created_by=created_by,
            generation_reason="baseline_profile",
            evaluation_status="pending",
        )
        variants = [baseline]
        seen_hashes = {self._params_hash(baseline["params_json"])}
        variant_specs = self._variant_specs_for_profile(profile)
        for reason, overrides in variant_specs:
            params = {**baseline_params, **overrides}
            params_hash = self._params_hash(params)
            if params_hash in seen_hashes:
                continue
            seen_hashes.add(params_hash)
            variants.append(
                self.usage_ledger.ensure_strategy_variant_definition(
                    variant_id=self._build_variant_id(
                        base_strategy_id=persisted_base_strategy_id or profile.strategy_id,
                        profile_id=profile.profile_id,
                        timeframe=timeframe,
                        params=params,
                    ),
                    base_strategy_id=persisted_base_strategy_id or profile.strategy_id,
                    profile_id=profile.profile_id,
                    timeframe=timeframe,
                    params=params,
                    created_at=created_at,
                    created_by=created_by,
                    generation_reason=reason,
                    parent_variant_id=baseline["variant_id"],
                    evaluation_status="pending",
                )
            )
        return variants

    def _evaluate_variant(
        self,
        *,
        profile: StrategyProfile,
        variant: dict[str, Any],
        persisted_base_strategy_id: str | None = None,
        timeframe: str,
        replay_id: str,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        runtime_deadline: float | None = None,
        bounded_diagnosis: bool = False,
        history_cache: dict[tuple[Any, ...], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        collected = self.collect_variant_outcomes(
            profile=profile,
            variant=variant,
            timeframe=timeframe,
            replay_id=replay_id,
            start_at=start_at,
            end_at=end_at,
            runtime_deadline=runtime_deadline,
            bounded_diagnosis=bounded_diagnosis,
            history_cache=history_cache,
        )
        outcomes = list(collected["outcomes"])
        diagnostics = dict(collected["diagnostics"])
        candidates_evaluated = int(collected["candidates_evaluated"])
        proposals_count = int(collected["proposals_count"])
        symbols_tested = set(collected["symbols_tested"])
        gross_returns = [float(item.get("gross_realized_return_pct", 0.0) or 0.0) for item in outcomes]
        net_returns = [float(item.get("realized_return_pct", 0.0) or 0.0) for item in outcomes]
        winners = [value for value in net_returns if value > 0]
        losers = [value for value in net_returns if value < 0]
        fixed_costs = [float(item.get("fixed_friction_return_pct", 0.0) or 0.0) for item in outcomes]
        spread_costs = [
            float(item.get("execution_spread_bps", 0.0) or 0.0) / 100.0
            for item in outcomes
        ]
        slippage_costs = [
            (
                float(item.get("entry_slippage_bps", 0.0) or 0.0)
                + float(item.get("exit_slippage_bps", 0.0) or 0.0)
            )
            / 100.0
            for item in outcomes
        ]
        return {
            "raw": {
                "variant_id": variant["variant_id"],
                "sample_size": len(outcomes),
                "symbols_tested": sorted(symbols_tested),
                "candidates_evaluated": candidates_evaluated,
                "proposals_created": proposals_count,
                "gross_positive_net_negative_count": int(
                    sum(
                        1
                        for item in outcomes
                        if float(item.get("gross_realized_return_pct", 0.0) or 0.0) > 0
                        and float(item.get("realized_return_pct", 0.0) or 0.0) < 0
                    )
                ),
                "average_winner": round(self._mean(winners), 6) if winners else 0.0,
                "average_loser": round(self._mean(losers), 6) if losers else 0.0,
                "target_hit_count": int(sum(1 for item in outcomes if str(item.get("outcome_status", "")) == "target_hit")),
                "stop_hit_count": int(sum(1 for item in outcomes if str(item.get("outcome_status", "")) == "stop_hit")),
                "time_exit_count": int(sum(1 for item in outcomes if str(item.get("outcome_status", "")) == "time_exit")),
                "diagnostics": diagnostics,
            },
            "variant_id": variant["variant_id"],
            "base_strategy_id": persisted_base_strategy_id or profile.strategy_id,
            "profile_id": profile.profile_id,
            "timeframe": timeframe,
            "replay_id": replay_id,
            "dataset_id": str(diagnostics.get("dataset_id", "") or self._dataset_id(profile=profile, timeframe=timeframe)),
            "asset_class": str(profile.asset_classes[0] if profile.asset_classes else "unknown"),
            "symbols_tested": sorted(symbols_tested),
            "sample_size": len(outcomes),
            "gross_return": round(self._mean(gross_returns), 6),
            "net_return_after_costs": round(self._mean(net_returns), 6),
            "fees_cost": round(self._mean(fixed_costs), 6),
            "spread_cost": round(self._mean(spread_costs), 6),
            "slippage_cost": round(self._mean(slippage_costs), 6),
            "win_rate": round(self._win_rate(outcomes), 6),
            "drawdown": round(self._mean([abs(float(item.get("max_adverse_excursion_pct", 0.0) or 0.0)) for item in outcomes]), 6) if outcomes else None,
            "gross_positive_net_negative_count": int(
                sum(
                    1
                    for item in outcomes
                    if float(item.get("gross_realized_return_pct", 0.0) or 0.0) > 0
                    and float(item.get("realized_return_pct", 0.0) or 0.0) < 0
                )
            ),
            "average_winner": round(self._mean(winners), 6) if winners else 0.0,
            "average_loser": round(self._mean(losers), 6) if losers else 0.0,
            "target_hit_count": int(sum(1 for item in outcomes if str(item.get("outcome_status", "")) == "target_hit")),
            "stop_hit_count": int(sum(1 for item in outcomes if str(item.get("outcome_status", "")) == "stop_hit")),
            "time_exit_count": int(sum(1 for item in outcomes if str(item.get("outcome_status", "")) == "time_exit")),
            "candidates_evaluated": candidates_evaluated,
            "proposals_created": proposals_count,
            "evaluated_at": datetime.now().astimezone(),
        }

    def collect_variant_outcomes(
        self,
        *,
        profile: StrategyProfile,
        variant: dict[str, Any],
        timeframe: str,
        replay_id: str,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        symbols: list[str] | None = None,
        runtime_deadline: float | None = None,
        bounded_diagnosis: bool = False,
        history_cache: dict[tuple[Any, ...], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        history = self._load_variant_history(
            profile=profile,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
            symbols=symbols,
            runtime_deadline=runtime_deadline,
            bounded_diagnosis=bounded_diagnosis,
            history_cache=history_cache,
        )
        if history.get("runtime_blocked"):
            return {
                "outcomes": [],
                "proposal_rows": [],
                "candidates_evaluated": 0,
                "proposals_count": 0,
                "symbols_tested": [],
                "diagnostics": {
                    "params_hash": self._params_hash(dict(variant.get("params_json", {}) or {})),
                    "dataset_id": str(history.get("dataset_id", "") or self._dataset_id(profile=profile, timeframe=timeframe)),
                    "generated_signal_count": 0,
                    "generated_proposal_count": 0,
                    "usable_decision_count": 0,
                    "rejected_by_param_filter_count": 0,
                    "symbols_with_decisions": [],
                    "first_decision_fingerprint": "",
                    "decision_set_hash": "",
                    "runtime_blocked": True,
                    "runtime_blocker": str(history.get("runtime_blocker", "") or ""),
                    "data_adequacy": self._build_data_adequacy(
                        profile=profile,
                        timeframe=timeframe,
                        history=history,
                        generated_signal_count=0,
                        generated_proposal_count=0,
                        usable_decision_count=0,
                    ),
                },
            }
        strategy = self._strategy_for_profile(profile)
        proposals_count = 0
        signal_count = 0
        outcomes: list[dict[str, Any]] = []
        symbols_tested: set[str] = set()
        candidates_evaluated = 0
        observed_candidate_count = 0
        rejected_by_param_filter_count = 0
        strategy_rejections: list[dict[str, Any]] = []
        previous_by_symbol: dict[tuple[str, str], dict[str, Any]] = {}
        recent_proposal_times: dict[tuple[str, str, str], datetime] = {}
        decision_fingerprints: list[str] = []
        proposal_rows: list[dict[str, Any]] = []
        required_fields = self._required_fields_for_profile(profile)
        feature_availability = self._empty_feature_availability()
        missing_required_fields: set[str] = set()

        for replay_timestamp in history["eligible_timestamps"]:
            current_rows = list(history["grouped_by_timestamp"].get(replay_timestamp, []))
            if not current_rows:
                continue
            ranked = rank_candidates(
                current_rows=current_rows,
                previous_by_symbol=previous_by_symbol,
                target_count=self.config.discovery_target_count,
            )
            candidate_dicts = [item.as_dict() for item in ranked]
            for row in current_rows:
                previous_by_symbol[(str(row["source"]), str(row["symbol"]))] = row
            if not candidate_dicts:
                continue
            enriched_candidates = _enrich_replay_candidates_with_technicals(
                candidates=candidate_dicts,
                bars_by_symbol=history["bars_by_symbol"],
                timestamps_by_symbol=history["timestamps_by_symbol"],
                replay_timestamp=replay_timestamp,
                lookback_periods=20,
            )
            observed_candidate_count += len(enriched_candidates)
            self._update_feature_observability(
                feature_availability=feature_availability,
                missing_required_fields=missing_required_fields,
                required_fields=required_fields,
                candidates=enriched_candidates,
            )
            candidates_evaluated += len(enriched_candidates)
            signal_dicts = [
                item.as_dict(
                    tick_id=_replay_tick_id(
                        timeframe=_safe_slug(timeframe),
                        replay_timestamp=replay_timestamp,
                    )
                )
                for item in strategy.evaluate_profile(
                    profile=profile,
                    candidates=enriched_candidates,
                    market_context={
                        "market_gate": {"can_scan": True, "reason": "historical_replay"},
                        "account_equity": 100000.0,
                        "replay_timeframe": timeframe,
                        "strategy_rejections": strategy_rejections,
                    },
                )
                if int(item.holding_window_minutes) >= _timeframe_to_minutes(timeframe)
            ]
            signal_count += len(signal_dicts)
            rejected_by_param_filter_count += max(0, len(enriched_candidates) - len(signal_dicts))
            if not signal_dicts:
                continue
            proposals = build_shadow_proposals(
                tick_id=f"{replay_id}:{variant['variant_id']}",
                proposed_at=replay_timestamp,
                strategy_signals=signal_dicts,
                recent_strategy_keys=_recent_strategy_keys(
                    recent_proposal_times=recent_proposal_times,
                    as_of=replay_timestamp,
                    cooldown_minutes=self.config.shadow_proposal_cooldown_minutes,
                ),
                proposal_limit=self.config.shadow_proposal_limit,
                min_signal_score=self.config.shadow_min_opportunity_score,
                checkpoint_windows=history["supported_windows"],
            )
            if not proposals:
                continue
            candidate_context_by_key = {
                (str(item.get("source", "")), str(item.get("symbol", "")).upper()): item
                for item in enriched_candidates
            }
            for proposal in proposals:
                proposals_count += 1
                symbols_tested.add(str(proposal.get("symbol", "")).upper())
                decision_fingerprint = self._decision_fingerprint(proposal=proposal)
                decision_fingerprints.append(decision_fingerprint)
                proposal_rows.append(dict(proposal))
                recent_proposal_times[
                    (
                        str(proposal.get("strategy_id", "")),
                        str(proposal.get("source", "")),
                        str(proposal.get("symbol", "")),
                    )
                ] = replay_timestamp
                context = candidate_context_by_key.get(
                    (str(proposal.get("source", "")), str(proposal.get("symbol", "")).upper()),
                    {},
                )
                trade_count = self._to_int(context.get("trade_count"))
                volume = self._to_int(context.get("volume"))
                volume_gbp = self._to_float(context.get("volume_gbp"))
                if volume_gbp is None:
                    close_price_gbp = self._to_float(context.get("close_price_gbp"))
                    if close_price_gbp is not None and volume is not None:
                        volume_gbp = close_price_gbp * volume
                proposal["movement_pct"] = self._to_float(context.get("movement_pct"))
                proposal["trade_count"] = trade_count
                proposal["volume"] = volume
                proposal["volume_gbp"] = volume_gbp
                proposal["liquidity_score"] = liquidity_component(volume=volume, trade_count=trade_count)
                symbol_key = (str(proposal["source"]), str(proposal["symbol"]))
                symbol_history = list(history["bars_by_symbol"].get(symbol_key, []))
                symbol_timestamps = list(history["timestamps_by_symbol"].get(symbol_key, []))
                if not symbol_history or not symbol_timestamps:
                    continue
                future_index = bisect_left(symbol_timestamps, replay_timestamp)
                future_bars = symbol_history[future_index:]
                if not future_bars:
                    continue
                for checkpoint in proposal.get("checkpoint_windows", []):
                    if int(checkpoint.get("checkpoint_minutes", 0) or 0) != int(profile.holding_window_minutes):
                        continue
                    due_at = datetime.fromisoformat(str(checkpoint["due_at"]))
                    outcome = evaluate_shadow_checkpoint(
                        checkpoint={
                            "proposal_id": proposal["proposal_id"],
                            "checkpoint_code": checkpoint["checkpoint_code"],
                            "checkpoint_minutes": checkpoint["checkpoint_minutes"],
                            "due_at": checkpoint["due_at"],
                            "proposed_at": proposal["proposed_at"],
                            "source": proposal["source"],
                            "symbol": proposal["symbol"],
                            "asset_class": proposal["asset_class"],
                            "entry_price": proposal["entry_price"],
                            "entry_price_gbp": proposal.get("entry_price_gbp"),
                            "stop_loss_price": proposal["stop_loss_price"],
                            "target_price": proposal["target_price"],
                            "environment": "paper",
                            "mode": "shadow",
                            "source_environment": "backtest",
                            "data_provider": "historical_store",
                            "execution_provider": "simulator",
                            "risk_pct": proposal.get("risk_pct", 0),
                            "holding_window_code": proposal["holding_window_code"],
                            "holding_window_minutes": proposal["holding_window_minutes"],
                            "break_even_trigger_price": proposal.get("break_even_trigger_price"),
                            "trailing_stop_mode": proposal.get("trailing_stop_mode"),
                            "raw_json": proposal,
                        },
                        bars=future_bars,
                        as_of=due_at + timedelta(minutes=_timeframe_to_minutes(timeframe)),
                        execution_spread_bps=self.config.shadow_execution_spread_bps,
                        entry_slippage_bps=self.config.shadow_entry_slippage_bps,
                        exit_slippage_bps=self.config.shadow_exit_slippage_bps,
                        fixed_round_trip_cost_usd=self.config.shadow_fixed_round_trip_cost_usd,
                        reference_notional_usd=self.config.paper_execution_default_notional_usd,
                        profit_target_ladder_pct=self.config.shadow_profit_target_ladder_pct,
                    )
                    if outcome is not None:
                        enriched_outcome = dict(outcome)
                        enriched_outcome["proposal_context"] = dict(proposal)
                        enriched_outcome["replay_timestamp"] = replay_timestamp.isoformat()
                        outcomes.append(enriched_outcome)

        bars_available_per_symbol = self._bars_available_per_symbol(
            history=history,
            requested_symbols=list(history.get("requested_symbols", []) or []),
        )
        rejection_reason_by_symbol = self._rejection_reason_by_symbol(strategy_rejections)
        eligible_symbols_after_filters = len(
            [
                symbol
                for symbol, stats in bars_available_per_symbol.items()
                if int(stats.get("bars_in_replay_window", 0) or 0) > 0
            ]
        )
        diagnostics = {
            "params_hash": self._params_hash(dict(variant.get("params_json", {}) or {})),
            "dataset_id": str(history.get("dataset_id", "") or self._dataset_id(profile=profile, timeframe=timeframe)),
            "generated_signal_count": signal_count,
            "generated_proposal_count": proposals_count,
            "usable_decision_count": len(outcomes),
            "rejected_by_param_filter_count": rejected_by_param_filter_count,
            "symbols_with_decisions": sorted(symbols_tested),
            "first_decision_fingerprint": decision_fingerprints[0] if decision_fingerprints else "",
            "decision_set_hash": self._decision_set_hash(decision_fingerprints),
            "bars_loaded": int(history.get("total_bars", 0) or 0),
            "requested_symbols": list(history.get("requested_symbols", []) or []),
            "stored_symbols_seen": list(history.get("symbols_covered", []) or []),
            "bars_symbols_seen": len(list(history.get("symbols_covered", []) or [])),
            "normalized_symbol_mapping": list(history.get("requested_symbol_mapping", []) or []),
            "source_filters": list(history.get("source_filters", []) or []),
            "asset_class_filter": str(history.get("asset_class_filter", "") or ""),
            "timeframe_filter": str(history.get("timeframe_filter", "") or timeframe),
            "replay_window_start": self._iso_or_none(history.get("requested_start_at")),
            "replay_window_end": self._iso_or_none(history.get("requested_end_at")),
            "effective_window_end": self._iso_or_none(history.get("effective_end_at")),
            "warmup_bars_required": 20,
            "lookahead_minutes": int(history.get("lookahead_minutes", 0) or 0),
            "configured_max_bars_per_symbol": int(history.get("configured_max_bars_per_symbol", 0) or 0),
            "required_bars_per_symbol": int(history.get("required_bars_per_symbol", 0) or 0),
            "effective_max_bars_per_symbol": int(history.get("effective_max_bars_per_symbol", 0) or 0),
            "bars_available_per_symbol": bars_available_per_symbol,
            "per_symbol_rejection_reason": rejection_reason_by_symbol,
            "symbols_requested_count": len(list(history.get("requested_symbols", []) or [])),
            "eligible_replay_timestamps_count": len(list(history.get("eligible_timestamps", []) or [])),
            "eligible_symbols_after_filters": eligible_symbols_after_filters,
            "observed_candidate_count": observed_candidate_count,
            "feature_availability": feature_availability,
            "missing_required_fields": sorted(missing_required_fields),
        }
        diagnostics["data_adequacy"] = self._build_data_adequacy(
            profile=profile,
            timeframe=timeframe,
            history=history,
            generated_signal_count=signal_count,
            generated_proposal_count=proposals_count,
            usable_decision_count=len(outcomes),
        )
        return {
            "outcomes": outcomes,
            "proposal_rows": proposal_rows,
            "candidates_evaluated": candidates_evaluated,
            "proposals_count": proposals_count,
            "symbols_tested": sorted(symbols_tested),
            "diagnostics": diagnostics,
        }

    def _finalize_evaluation(
        self,
        *,
        evaluation: dict[str, Any],
        variant: dict[str, Any],
        baseline: dict[str, Any],
    ) -> dict[str, Any]:
        beats_baseline = (
            float(evaluation.get("net_return_after_costs", 0.0) or 0.0)
            > float(baseline.get("net_return_after_costs", 0.0) or 0.0)
            and float(evaluation.get("win_rate", 0.0) or 0.0)
            >= float(baseline.get("win_rate", 0.0) or 0.0)
        )
        beats_thresholds = (
            int(evaluation.get("sample_size", 0) or 0) >= int(self.config.research_min_proposals)
            and float(evaluation.get("net_return_after_costs", 0.0) or 0.0)
            >= float(self.config.research_min_net_return_pct)
            and float(evaluation.get("win_rate", 0.0) or 0.0)
            >= float(self.config.research_min_net_win_rate)
        )
        recommended_status = "rejected"
        if (
            variant["generation_reason"] != "baseline_profile"
            and beats_baseline
            and beats_thresholds
            and int(evaluation.get("sample_size", 0) or 0) > 0
        ):
            recommended_status = "paper_candidate_requires_manual_approval"
        elif int(evaluation.get("sample_size", 0) or 0) > 0:
            recommended_status = "evaluated"
        return {
            **evaluation,
            "evaluation_id": self._evaluation_id(
                variant_id=variant["variant_id"],
                replay_id=str(evaluation.get("replay_id", "") or ""),
                evaluated_at=evaluation["evaluated_at"],
            ),
            "baseline_variant_id": baseline["variant_id"],
            "baseline_strategy_key": f"{variant['base_strategy_id']}/{variant['profile_id']}/{variant['timeframe']}",
            "baseline_net_return_after_costs": float(
                baseline.get("net_return_after_costs", 0.0) or 0.0
            ),
            "baseline_win_rate": float(baseline.get("win_rate", 0.0) or 0.0),
            "beats_baseline": beats_baseline,
            "beats_thresholds": beats_thresholds,
            "recommended_status": recommended_status,
            "notes": "Research-only. No paper or live approval has been changed.",
        }

    def _persist_evaluation(self, *, evaluation: dict[str, Any]) -> dict[str, Any]:
        return self.usage_ledger.record_strategy_variant_evaluation(**evaluation)

    def _generated_candidate_snapshot(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
    ) -> dict[str, Any]:
        candidate_id = self._generated_candidate_id(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        if not candidate_id or not hasattr(self.usage_ledger, "list_strategy_variant_definitions"):
            return {
                "candidate_id": candidate_id,
                "lifecycle_status": "",
                "evaluation_status": "",
            }
        for row in reversed(
            list(
                self.usage_ledger.list_strategy_variant_definitions(
                    base_strategy_id=base_strategy_id,
                    profile_id=profile_id,
                    timeframe=timeframe,
                )
            )
        ):
            if str(row.get("variant_id", "") or "") != candidate_id:
                continue
            notes_payload = self._variant_definition_notes_payload(row.get("notes"))
            return {
                "candidate_id": candidate_id,
                "lifecycle_status": str(notes_payload.get("lifecycle_status", "") or ""),
                "evaluation_status": str(
                    row.get("evaluation_status", "")
                    or notes_payload.get("evaluation_status", "")
                    or ""
                ),
            }
        return {
            "candidate_id": candidate_id,
            "lifecycle_status": "",
            "evaluation_status": "",
        }

    def _persist_generated_candidate_execution_result(
        self,
        *,
        candidate_id: str,
        runtime_summary: dict[str, Any],
        variants_generated: int,
        evaluated_rows: list[dict[str, Any]],
        snapshot_before: dict[str, Any],
    ) -> dict[str, Any]:
        if not candidate_id:
            return {
                "lifecycle_status_before": str(snapshot_before.get("lifecycle_status", "") or ""),
                "lifecycle_status_after": "",
                "evaluation_status_before": str(snapshot_before.get("evaluation_status", "") or ""),
                "evaluation_status_after": "",
                "generated_candidate_evidence_at": "",
            }
        latest_evaluated_at = self._latest_evaluated_at(evaluated_rows)
        lifecycle_status, evaluation_status, research_status = self._generated_candidate_status_from_runtime(
            runtime_summary=runtime_summary,
        )
        notes = {
            "lifecycle_status": lifecycle_status,
            "evaluation_status": evaluation_status,
            "research_status": research_status,
            "variants_generated": int(variants_generated or 0),
            "variants_evaluated": int(runtime_summary.get("variants_evaluated", 0) or 0),
            "baseline_sample_size": int(runtime_summary.get("baseline_sample_size", 0) or 0),
            "best_variant_sample_size": int(runtime_summary.get("best_variant_sample_size", 0) or 0),
            "runtime_status": str(runtime_summary.get("runtime_status", "") or ""),
            "runtime_blocker": str(runtime_summary.get("runtime_blocker", "") or ""),
            "generated_candidate_evidence_at": latest_evaluated_at.isoformat() if latest_evaluated_at else "",
            "updated_at": datetime.now().astimezone().isoformat(),
        }
        self.usage_ledger.update_strategy_variant_definition_status(
            variant_id=candidate_id,
            evaluation_status=evaluation_status,
            latest_evaluation_at=latest_evaluated_at,
            notes=json.dumps(notes, sort_keys=True),
        )
        return {
            "lifecycle_status_before": str(snapshot_before.get("lifecycle_status", "") or ""),
            "lifecycle_status_after": lifecycle_status,
            "evaluation_status_before": str(snapshot_before.get("evaluation_status", "") or ""),
            "evaluation_status_after": evaluation_status,
            "research_status_after": research_status,
            "generated_candidate_evidence_at": notes["generated_candidate_evidence_at"],
        }

    def _generated_candidate_status_from_runtime(
        self,
        *,
        runtime_summary: dict[str, Any],
    ) -> tuple[str, str, str]:
        runtime_status = str(runtime_summary.get("runtime_status", "") or "")
        if runtime_status == "runtime_blocked":
            return ("runtime_blocked", "runtime_blocked", "runtime_blocked")
        baseline_sample_size = int(runtime_summary.get("baseline_sample_size", 0) or 0)
        best_variant_sample_size = int(runtime_summary.get("best_variant_sample_size", 0) or 0)
        if baseline_sample_size > 0 or best_variant_sample_size > 0:
            return ("variant_research_completed", "evaluated", "variant_research_completed")
        zero_sample_reason = str(runtime_summary.get("zero_sample_reason", "") or "")
        runtime_blocker = str(runtime_summary.get("runtime_blocker", "") or "")
        research_status = (
            "insufficient_history_after_variant_research"
            if runtime_blocker == "insufficient_crypto_history"
            or zero_sample_reason == "coverage_scan_found_bars_but_history_window_was_too_thin_for_range_breakout_replay"
            else "no_viable_signal_after_variant_research"
        )
        return ("variant_research_completed", "evaluated_no_samples", research_status)

    def _latest_evaluated_at(self, rows: list[dict[str, Any]]) -> datetime | None:
        latest: datetime | None = None
        for row in rows:
            evaluated_at = row.get("evaluated_at")
            if not isinstance(evaluated_at, datetime):
                continue
            if latest is None or evaluated_at > latest:
                latest = evaluated_at
        return latest

    def _variant_definition_notes_payload(self, raw_notes: Any) -> dict[str, Any]:
        text = str(raw_notes or "").strip()
        if not text:
            return {}
        try:
            payload = json.loads(text)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _profile_from_variant(
        self,
        *,
        profile: StrategyProfile,
        variant: dict[str, Any],
    ) -> StrategyProfile:
        params = dict(variant["params_json"])
        holding_window_minutes = int(params.get("holding_window_minutes", profile.holding_window_minutes) or profile.holding_window_minutes)
        parameter_overrides = {
            key: value
            for key, value in params.items()
            if key not in {"holding_window_minutes", "stop_loss_pct", "target_multiple"}
        }
        return replace(
            profile,
            holding_window_code=self._holding_window_code(holding_window_minutes),
            holding_window_minutes=holding_window_minutes,
            stop_loss_pct=float(params.get("stop_loss_pct", profile.stop_loss_pct)),
            target_multiple=float(params.get("target_multiple", profile.target_multiple)),
            parameters={**profile.parameters, **parameter_overrides},
        )

    def _variant_params_from_profile(self, profile: StrategyProfile) -> dict[str, Any]:
        params = {
            "stop_loss_pct": float(profile.stop_loss_pct),
            "target_multiple": float(profile.target_multiple),
        }
        for key, value in profile.parameters.items():
            if key == "estimated_round_trip_cost_pct":
                continue
            if isinstance(value, bool):
                params[key] = value
            elif isinstance(value, int):
                params[key] = int(value)
            elif isinstance(value, float):
                if value == 0.0:
                    continue
                params[key] = float(value)
        return params

    def _holding_window_code(self, minutes: int) -> str:
        minute_value = max(1, int(minutes or 0))
        if minute_value % (60 * 24 * 7) == 0:
            return f"{minute_value // (60 * 24 * 7)}w"
        if minute_value % (60 * 24) == 0:
            return f"{minute_value // (60 * 24)}d"
        if minute_value % 60 == 0:
            return f"{minute_value // 60}h"
        return f"{minute_value}m"

    def _load_variant_history(
        self,
        *,
        profile: StrategyProfile,
        timeframe: str,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        symbols: list[str] | None = None,
        runtime_deadline: float | None = None,
        bounded_diagnosis: bool = False,
        history_cache: dict[tuple[Any, ...], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        resolved_end_at = end_at or datetime.now().astimezone()
        replay_days = max(
            1,
            int(
                getattr(
                    self.config,
                    "diagnosis_replay_default_days" if bounded_diagnosis else "historical_replay_default_days",
                    self.config.historical_replay_default_days,
                ) or self.config.historical_replay_default_days
            ),
        )
        resolved_start_at = start_at or (resolved_end_at - timedelta(days=replay_days))
        supported_windows = _supported_checkpoint_windows(
            timeframe=timeframe,
            checkpoint_windows=self.config.shadow_checkpoint_windows,
        )
        lookahead_minutes = _max_checkpoint_window_minutes(supported_windows)
        asset_classes = set(profile.asset_classes)
        asset_class = "crypto" if "crypto" in asset_classes and "equity" not in asset_classes else "equity"
        if "crypto" in asset_classes and "equity" not in asset_classes:
            sources = ["alpaca_crypto_data"]
            default_symbols = list(self.config.discovery_crypto_symbols)
        else:
            sources = ["alpaca_market_data"]
            default_symbols = list(self.config.discovery_equity_symbols)
        resolved_symbols = list(symbols or default_symbols)
        if symbols is None:
            try:
                resolved_symbols = self._bounded_target_symbols(
                    asset_class=asset_class,
                    timeframe=timeframe,
                    start_at=resolved_start_at,
                    end_at=resolved_end_at,
                    default_symbols=resolved_symbols,
                    bounded_diagnosis=bounded_diagnosis,
                )
            except Exception as exc:
                if self._is_runtime_budget_blocker(exc):
                    return self._runtime_blocked_history(
                        profile=profile,
                        timeframe=timeframe,
                        requested_start_at=resolved_start_at,
                        requested_end_at=resolved_end_at,
                        requested_symbols=resolved_symbols,
                        runtime_blocker="historical_bar_read_timeout",
                )
                raise
        bounded_symbols = [str(symbol).upper() for symbol in resolved_symbols]
        cache_key = (
            profile.strategy_id,
            profile.profile_id,
            timeframe,
            resolved_start_at.isoformat(),
            resolved_end_at.isoformat(),
            tuple(bounded_symbols),
            bool(bounded_diagnosis),
        )
        if history_cache is not None and cache_key in history_cache:
            return history_cache[cache_key]
        if runtime_deadline is not None and monotonic() >= runtime_deadline:
            return self._runtime_blocked_history(
                profile=profile,
                timeframe=timeframe,
                requested_start_at=resolved_start_at,
                requested_end_at=resolved_end_at,
                requested_symbols=resolved_symbols,
                runtime_blocker="historical_bar_read_timeout",
            )
        try:
            max_symbols = max(
                1,
                int(
                    getattr(
                        self.config,
                        "strategy_variant_research_symbol_limit",
                        len(bounded_symbols) or 1,
                    )
                    or len(bounded_symbols)
                    or 1
                ),
            )
            configured_max_bars_per_symbol = max(
                1,
                int(getattr(self.config, "strategy_variant_research_max_bars_per_symbol", 400) or 400),
            )
            required_bars_per_symbol = self._required_bars_per_symbol(
                timeframe=timeframe,
                start_at=resolved_start_at,
                end_at=resolved_end_at,
                lookahead_minutes=lookahead_minutes,
                lookback_periods=20,
            )
            max_bars_per_symbol = max(configured_max_bars_per_symbol, required_bars_per_symbol)
            bounded_symbols = bounded_symbols[:max_symbols]
            rows = self.usage_ledger.list_historical_bars(
                timeframe=timeframe,
                sources=sources,
                start_at=resolved_start_at,
                end_at=resolved_end_at + timedelta(minutes=lookahead_minutes),
                symbols=bounded_symbols,
                per_symbol_limit=max_bars_per_symbol,
                limit=max_symbols * max_bars_per_symbol,
            )
        except Exception as exc:
            if self._is_runtime_budget_blocker(exc):
                return self._runtime_blocked_history(
                    profile=profile,
                    timeframe=timeframe,
                    requested_start_at=resolved_start_at,
                    requested_end_at=resolved_end_at,
                    requested_symbols=bounded_symbols,
                    runtime_blocker="historical_bar_read_timeout",
                )
            raise
        grouped_by_timestamp: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
        bars_by_symbol: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        timestamps_by_symbol: dict[tuple[str, str], list[datetime]] = defaultdict(list)
        for row in rows:
            bar_timestamp = row.get("bar_timestamp")
            if not isinstance(bar_timestamp, datetime):
                continue
            normalized = dict(row)
            normalized["captured_at"] = bar_timestamp
            grouped_by_timestamp[bar_timestamp].append(normalized)
            key = (str(normalized.get("source", "")), str(normalized.get("symbol", "")))
            bars_by_symbol[key].append(normalized)
            timestamps_by_symbol[key].append(bar_timestamp)
        ordered_timestamps = sorted(grouped_by_timestamp.keys())
        replay_timestamps = [
            timestamp
            for timestamp in ordered_timestamps
            if resolved_start_at <= timestamp < resolved_end_at
        ]
        stored_symbols_seen = sorted(
            {
                str(row.get("symbol", "") or "").upper()
                for row in rows
                if str(row.get("symbol", "") or "").strip()
            }
        )
        history = {
            "grouped_by_timestamp": grouped_by_timestamp,
            "bars_by_symbol": bars_by_symbol,
            "timestamps_by_symbol": timestamps_by_symbol,
            "eligible_timestamps": _eligible_replay_timestamps(
                timestamps=ordered_timestamps,
                replay_timestamps=replay_timestamps,
                supported_windows=supported_windows,
                max_timestamps=self.config.historical_replay_max_timestamps,
            ),
            "supported_windows": supported_windows,
            "dataset_id": self._dataset_id(profile=profile, timeframe=timeframe),
            "requested_start_at": resolved_start_at,
            "requested_end_at": resolved_end_at,
            "effective_end_at": resolved_end_at + timedelta(minutes=lookahead_minutes),
            "earliest_bar_timestamp": ordered_timestamps[0] if ordered_timestamps else None,
            "latest_bar_timestamp": ordered_timestamps[-1] if ordered_timestamps else None,
            "total_bars": len(rows),
            "symbols_covered": stored_symbols_seen,
            "requested_symbols": bounded_symbols,
            "requested_symbol_mapping": [
                {
                    "requested_symbol": str(symbol),
                    "normalized_symbol": str(symbol).upper(),
                    "matched_stored_symbol": str(symbol).upper() in stored_symbols_seen,
                }
                for symbol in bounded_symbols
            ],
            "source_filters": list(sources),
            "asset_class_filter": asset_class,
            "timeframe_filter": timeframe,
            "lookahead_minutes": lookahead_minutes,
            "configured_max_bars_per_symbol": configured_max_bars_per_symbol,
            "required_bars_per_symbol": required_bars_per_symbol,
            "effective_max_bars_per_symbol": max_bars_per_symbol,
        }
        if history_cache is not None:
            history_cache[cache_key] = history
        return history

    def _required_bars_per_symbol(
        self,
        *,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
        lookahead_minutes: int,
        lookback_periods: int,
    ) -> int:
        timeframe_minutes = max(1, _timeframe_to_minutes(timeframe))
        span_minutes = max(
            timeframe_minutes,
            int((end_at - start_at).total_seconds() // 60) + max(0, int(lookahead_minutes or 0)),
        )
        replay_bars = max(1, (span_minutes + timeframe_minutes - 1) // timeframe_minutes)
        return replay_bars + max(0, int(lookback_periods or 0)) + 1

    def _bounded_target_symbols(
        self,
        *,
        asset_class: str,
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
        default_symbols: list[str],
        bounded_diagnosis: bool,
    ) -> list[str]:
        max_symbols = max(
            1,
            int(
                getattr(
                    self.config,
                    "diagnosis_replay_symbol_limit" if bounded_diagnosis else "strategy_variant_research_symbol_limit",
                    12,
                ) or 12
            ),
        )
        coverage_rows = self.usage_ledger.summarize_historical_bar_coverage(
            asset_class=asset_class,
            symbols=default_symbols,
            timeframes=[timeframe],
        )
        ranked = sorted(
            [
                row for row in coverage_rows
                if self._to_int(row.get("row_count"))
                and isinstance(row.get("latest_bar_timestamp"), datetime)
                and row["latest_bar_timestamp"] >= start_at
                and isinstance(row.get("earliest_bar_timestamp"), datetime)
                and row["earliest_bar_timestamp"] <= end_at
            ],
            key=lambda row: (
                row.get("latest_bar_timestamp"),
                int(row.get("row_count", 0) or 0),
                str(row.get("symbol", "") or ""),
            ),
            reverse=True,
        )
        selected = [str(row.get("symbol", "") or "").upper() for row in ranked[:max_symbols] if str(row.get("symbol", "") or "").strip()]
        return selected or [str(symbol).upper() for symbol in default_symbols[:max_symbols]]

    def _runtime_blocked_history(
        self,
        *,
        profile: StrategyProfile,
        timeframe: str,
        requested_start_at: datetime,
        requested_end_at: datetime,
        requested_symbols: list[str],
        runtime_blocker: str,
    ) -> dict[str, Any]:
        return {
            "grouped_by_timestamp": {},
            "bars_by_symbol": {},
            "timestamps_by_symbol": {},
            "eligible_timestamps": [],
            "supported_windows": _supported_checkpoint_windows(
                timeframe=timeframe,
                checkpoint_windows=self.config.shadow_checkpoint_windows,
            ),
            "dataset_id": self._dataset_id(profile=profile, timeframe=timeframe),
            "requested_start_at": requested_start_at,
            "requested_end_at": requested_end_at,
            "effective_end_at": requested_end_at,
            "earliest_bar_timestamp": None,
            "latest_bar_timestamp": None,
            "total_bars": 0,
            "symbols_covered": [],
            "requested_symbols": [str(symbol).upper() for symbol in requested_symbols],
            "requested_symbol_mapping": [
                {
                    "requested_symbol": str(symbol),
                    "normalized_symbol": str(symbol).upper(),
                    "matched_stored_symbol": False,
                }
                for symbol in requested_symbols
            ],
            "runtime_blocked": True,
            "runtime_blocker": runtime_blocker,
        }

    def _persisted_base_strategy_id(
        self,
        *,
        requested_base_strategy_id: str,
        profile: StrategyProfile,
    ) -> str:
        if requested_base_strategy_id:
            return requested_base_strategy_id
        return str(profile.family or profile.strategy_id)

    def _build_data_adequacy(
        self,
        *,
        profile: StrategyProfile,
        timeframe: str,
        history: dict[str, Any],
        generated_signal_count: int,
        generated_proposal_count: int,
        usable_decision_count: int,
    ) -> dict[str, Any]:
        if history.get("runtime_blocked"):
            return {
                "dataset_id": str(history.get("dataset_id", "") or self._dataset_id(profile=profile, timeframe=timeframe)),
                "timeframe": timeframe,
                "days_covered": 0.0,
                "symbols_covered": list(history.get("symbols_covered", []) or []),
                "total_bars": int(history.get("total_bars", 0) or 0),
                "eligible_signal_count": int(generated_signal_count or 0),
                "generated_proposal_count": int(generated_proposal_count or 0),
                "usable_decision_count": int(usable_decision_count or 0),
                "zero_decision_reason": str(history.get("runtime_blocker", "") or "historical_bar_read_timeout"),
                "earliest_bar_timestamp": None,
                "latest_bar_timestamp": None,
            }
        requested_start_at = history.get("requested_start_at")
        requested_end_at = history.get("requested_end_at")
        earliest_bar_timestamp = history.get("earliest_bar_timestamp")
        latest_bar_timestamp = history.get("latest_bar_timestamp")
        symbols_covered = list(history.get("symbols_covered", []) or [])
        requested_symbols = list(history.get("requested_symbols", []) or [])
        total_bars = int(history.get("total_bars", 0) or 0)
        eligible_timestamps = int(len(list(history.get("eligible_timestamps", []) or [])))
        days_covered = 0.0
        if isinstance(earliest_bar_timestamp, datetime) and isinstance(latest_bar_timestamp, datetime):
            days_covered = round(
                max(0.0, (latest_bar_timestamp - earliest_bar_timestamp).total_seconds() / 86400.0),
                6,
            )
        reason = ""
        if usable_decision_count <= 0:
            if not requested_symbols:
                reason = "no_symbols_available"
            elif total_bars <= 0:
                reason = "no_bars_for_timeframe"
            elif "crypto" in set(profile.asset_classes) and isinstance(requested_start_at, datetime) and isinstance(requested_end_at, datetime):
                requested_days = max(1.0, (requested_end_at - requested_start_at).total_seconds() / 86400.0)
                if days_covered < requested_days * 0.8:
                    reason = "insufficient_crypto_history"
            if not reason and generated_signal_count <= 0 and eligible_timestamps > 0:
                reason = "strategy_filters_too_strict"
            if not reason and generated_proposal_count <= 0:
                reason = "no_qualifying_setups_in_window"
            if not reason:
                reason = "unknown_zero_decision_reason"
        return {
            "dataset_id": str(history.get("dataset_id", "") or self._dataset_id(profile=profile, timeframe=timeframe)),
            "timeframe": timeframe,
            "days_covered": days_covered,
            "symbols_covered": symbols_covered,
            "total_bars": total_bars,
            "eligible_signal_count": int(generated_signal_count or 0),
            "generated_proposal_count": int(generated_proposal_count or 0),
            "usable_decision_count": int(usable_decision_count or 0),
            "zero_decision_reason": reason,
            "earliest_bar_timestamp": earliest_bar_timestamp.isoformat() if isinstance(earliest_bar_timestamp, datetime) else None,
            "latest_bar_timestamp": latest_bar_timestamp.isoformat() if isinstance(latest_bar_timestamp, datetime) else None,
        }

    def _replay_window_days_delta(self) -> timedelta:
        return timedelta(days=max(1, self.config.historical_replay_default_days))

    def _build_variant_id(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        params: dict[str, Any],
    ) -> str:
        digest = hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()[:12]
        return f"{base_strategy_id}:{profile_id}:{timeframe}:{digest}"

    def _params_hash(self, params: dict[str, Any]) -> str:
        return hashlib.sha256(json.dumps(params, sort_keys=True).encode("utf-8")).hexdigest()

    def _decision_fingerprint(self, *, proposal: dict[str, Any]) -> str:
        payload = {
            "symbol": str(proposal.get("symbol", "") or ""),
            "source": str(proposal.get("source", "") or ""),
            "entry_price": round(float(proposal.get("entry_price", 0.0) or 0.0), 8),
            "stop_loss_price": round(float(proposal.get("stop_loss_price", 0.0) or 0.0), 8),
            "target_price": round(float(proposal.get("target_price", 0.0) or 0.0), 8),
            "movement_pct": proposal.get("movement_pct"),
            "trade_count": proposal.get("trade_count"),
            "discovery_score": proposal.get("discovery_score"),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]

    def _decision_set_hash(self, fingerprints: list[str]) -> str:
        if not fingerprints:
            return ""
        ordered = sorted(str(item) for item in fingerprints if str(item or "").strip())
        return hashlib.sha256("|".join(ordered).encode("utf-8")).hexdigest()[:24]

    def _research_runtime_summary(
        self,
        *,
        evaluations: list[dict[str, Any]],
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
    ) -> dict[str, Any]:
        if not evaluations:
            return {}
        baseline = dict(evaluations[0] or {})
        best = max(
            evaluations,
            key=lambda item: (
                float(item.get("net_return_after_costs", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                int(item.get("sample_size", 0) or 0),
            ),
        )
        raw_payload = dict(baseline.get("raw_json", {}) or baseline.get("raw", {}) or {})
        baseline_diag = dict((raw_payload.get("diagnostics", {}) or {}) )
        runtime_blocker = str((baseline_diag.get("data_adequacy", {}) or {}).get("zero_decision_reason", "") or "")
        baseline_data_adequacy = dict((baseline_diag.get("data_adequacy", {}) or {}))
        symbols_tested = list(baseline.get("symbols_tested", []) or [])
        coverage_symbols_seen = int(baseline_diag.get("bars_symbols_seen", 0) or len(list(baseline_diag.get("symbols_loaded", []) or [])))
        eligible_symbols_after_filters = int(baseline_diag.get("eligible_symbols_after_filters", 0) or len(symbols_tested))
        symbols_processed_for_strategy = len(symbols_tested)
        feature_availability = dict(baseline_diag.get("feature_availability", {}) or {})
        missing_required_fields = sorted(str(item) for item in (baseline_diag.get("missing_required_fields", []) or []) if str(item or "").strip())
        eligible_replay_timestamps_count = int(baseline_diag.get("eligible_replay_timestamps_count", 0) or 0)
        observed_candidate_count = int(baseline_diag.get("observed_candidate_count", 0) or 0)
        history_coverage_reason = (
            "coverage_scan_loaded_bars_but_requested_history_window_remained_insufficient"
            if runtime_blocker == "insufficient_crypto_history"
            else (
                "coverage_scan_loaded_bars_for_requested_symbol_universe"
                if int(baseline_diag.get("bars_loaded", 0) or 0) > 0
                else "no_history_coverage_found"
            )
        )
        zero_sample_reason = ""
        if symbols_processed_for_strategy <= 0:
            if runtime_blocker == "insufficient_crypto_history":
                zero_sample_reason = "coverage_scan_found_bars_but_history_window_was_too_thin_for_range_breakout_replay"
            elif eligible_symbols_after_filters <= 0:
                zero_sample_reason = "no_symbols_passed_signal_or_setup_filters"
            elif coverage_symbols_seen <= 0:
                zero_sample_reason = "symbol_selection_failed"
            else:
                zero_sample_reason = "no_symbols_had_enough_usable_range_breakout_setups"
        runtime_status = "runtime_blocked" if runtime_blocker == "historical_bar_read_timeout" else "completed"
        no_progress_classification = self._classify_no_progress_runtime(
            runtime_status=runtime_status,
            runtime_blocker=runtime_blocker,
            baseline_sample_size=int(baseline.get("sample_size", 0) or 0),
            best_variant_sample_size=int(best.get("sample_size", 0) or 0),
            data_adequacy=baseline_data_adequacy,
            missing_required_fields=missing_required_fields,
        )
        next_required_action = self._next_required_action_for_no_progress(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            classification=no_progress_classification,
            missing_required_fields=missing_required_fields,
        )
        next_recommended_command = ".venv-mac/bin/python main.py --strategy-portfolio-research-planner"
        if runtime_status == "runtime_blocked":
            if base_strategy_id == "crypto_research.range_breakout" and profile_id == "range_breakout" and timeframe == "15Min":
                next_required_action = "precompute_specific_range_breakout_15Min_replay_cache"
            else:
                next_required_action = "optimise_or_precompute_replay_dataset"
            next_recommended_command = ".venv-mac/bin/python main.py --optimise-or-precompute-replay-dataset"
        elif int(baseline.get("sample_size", 0) or 0) > 0 or int(best.get("sample_size", 0) or 0) > 0:
            next_recommended_command = (
                ".venv-mac/bin/python main.py --diagnose-next-best-strategy "
                f"--base-strategy {base_strategy_id} --profile-id {profile_id} --timeframe {timeframe}"
            )
        no_progress_reason = self._no_progress_reason(
            classification=no_progress_classification,
            runtime_blocker=runtime_blocker,
            missing_required_fields=missing_required_fields,
            eligible_replay_timestamps_count=eligible_replay_timestamps_count,
            observed_candidate_count=observed_candidate_count,
        )
        return {
            "symbols_processed": len(list(baseline.get("symbols_tested", []) or [])),
            "bars_read": int(baseline_diag.get("bars_loaded", 0) or 0),
            "coverage_symbols_seen": coverage_symbols_seen,
            "eligible_symbols_after_filters": eligible_symbols_after_filters,
            "symbols_processed_for_strategy": symbols_processed_for_strategy,
            "zero_sample_reason": zero_sample_reason,
            "history_coverage_reason": history_coverage_reason,
            "variants_evaluated": len(evaluations),
            "baseline_sample_size": int(baseline.get("sample_size", 0) or 0),
            "best_variant_id": str(best.get("variant_id", "") or ""),
            "best_variant_sample_size": int(best.get("sample_size", 0) or 0),
            "best_variant_net_return_after_costs": float(best.get("net_return_after_costs", 0.0) or 0.0),
            "best_variant_win_rate": float(best.get("win_rate", 0.0) or 0.0),
            "best_variant_drawdown": best.get("drawdown"),
            "runtime_status": runtime_status,
            "runtime_blocker": runtime_blocker,
            "no_progress_classification": no_progress_classification,
            "no_progress_reason": no_progress_reason,
            "next_required_action": next_required_action,
            "next_recommended_command": next_recommended_command,
            "missing_required_fields": missing_required_fields,
            "feature_availability": feature_availability,
            "eligible_replay_timestamps_count": eligible_replay_timestamps_count,
            "observed_candidate_count": observed_candidate_count,
        }

    def _required_fields_for_profile(self, profile: StrategyProfile) -> set[str]:
        if profile.profile_id == "liquidation_wick_reclaim" or profile.profile_id.startswith("liquidation_wick_reclaim_"):
            return {"movement_pct", "volume_ratio_20", "atr_pct_20", "vwap"}
        return set()

    def _bars_available_per_symbol(
        self,
        *,
        history: dict[str, Any],
        requested_symbols: list[str],
    ) -> dict[str, dict[str, Any]]:
        requested_start_at = history.get("requested_start_at")
        requested_end_at = history.get("requested_end_at")
        summary: dict[str, dict[str, Any]] = {}
        for symbol in requested_symbols:
            normalized_symbol = str(symbol or "").upper()
            symbol_bars: list[dict[str, Any]] = []
            for (source, seen_symbol), rows in dict(history.get("bars_by_symbol", {}) or {}).items():
                if str(seen_symbol or "").upper() != normalized_symbol:
                    continue
                symbol_bars.extend(list(rows or []))
            ordered = sorted(
                [
                    row for row in symbol_bars
                    if isinstance(row.get("bar_timestamp"), datetime)
                ],
                key=lambda row: row["bar_timestamp"],
            )
            replay_rows = [
                row
                for row in ordered
                if isinstance(requested_start_at, datetime)
                and isinstance(requested_end_at, datetime)
                and requested_start_at <= row["bar_timestamp"] < requested_end_at
            ]
            summary[normalized_symbol] = {
                "bars_in_effective_window": len(ordered),
                "bars_in_replay_window": len(replay_rows),
                "earliest_bar_timestamp": self._iso_or_none(ordered[0].get("bar_timestamp") if ordered else None),
                "latest_bar_timestamp": self._iso_or_none(ordered[-1].get("bar_timestamp") if ordered else None),
            }
        return summary

    def _rejection_reason_by_symbol(
        self,
        rejection_events: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        counts: dict[str, dict[str, int]] = defaultdict(dict)
        for event in rejection_events:
            symbol = str(event.get("symbol", "") or "").upper().strip()
            reason = str(event.get("reason", "") or "").strip()
            if not symbol or not reason:
                continue
            counts[symbol][reason] = counts[symbol].get(reason, 0) + 1
        summary: dict[str, dict[str, Any]] = {}
        for symbol, reason_counts in counts.items():
            top_reason, top_count = max(
                reason_counts.items(),
                key=lambda item: (int(item[1]), item[0]),
            )
            summary[symbol] = {
                "top_reason": top_reason,
                "top_reason_count": int(top_count),
                "all_reasons": [
                    {"reason": reason, "count": int(count)}
                    for reason, count in sorted(
                        reason_counts.items(),
                        key=lambda item: (-int(item[1]), item[0]),
                    )
                ],
            }
        return summary

    def _iso_or_none(self, value: Any) -> str | None:
        if isinstance(value, datetime):
            return value.isoformat()
        return None

    def _empty_feature_availability(self) -> dict[str, bool]:
        return {
            "vwap": False,
            "movement_pct": False,
            "volume_ratio_20": False,
            "atr_pct_20": False,
        }

    def _update_feature_observability(
        self,
        *,
        feature_availability: dict[str, bool],
        missing_required_fields: set[str],
        required_fields: set[str],
        candidates: list[dict[str, Any]],
    ) -> None:
        if not candidates:
            return
        for candidate in candidates:
            for field_name in tuple(feature_availability.keys()):
                if candidate.get(field_name) not in (None, ""):
                    feature_availability[field_name] = True
            for field_name in required_fields:
                if candidate.get(field_name) in (None, ""):
                    missing_required_fields.add(field_name)

    def _classify_no_progress_runtime(
        self,
        *,
        runtime_status: str,
        runtime_blocker: str,
        baseline_sample_size: int,
        best_variant_sample_size: int,
        data_adequacy: dict[str, Any],
        missing_required_fields: list[str],
    ) -> str:
        if runtime_status == "runtime_blocked":
            return "runtime_blocked"
        if baseline_sample_size > 0 or best_variant_sample_size > 0:
            return "variant_research_not_consumed"
        if missing_required_fields:
            return "missing_required_features"
        zero_decision_reason = str(data_adequacy.get("zero_decision_reason", "") or runtime_blocker)
        if zero_decision_reason in {
            "insufficient_crypto_history",
            "insufficient_history",
            "insufficient_market_history",
            "no_bars_for_timeframe",
            "no_symbols_available",
        }:
            return "insufficient_history"
        if zero_decision_reason == "strategy_filters_too_strict":
            return "signal_rules_too_strict"
        if zero_decision_reason in {"no_qualifying_setups_in_window", "unknown_zero_decision_reason"}:
            return "no_usable_signals"
        return "no_usable_signals"

    def _next_required_action_for_no_progress(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        classification: str,
        missing_required_fields: list[str],
    ) -> str:
        if classification == "missing_required_features":
            if (
                str(base_strategy_id).startswith("crypto_")
                and timeframe == "15Min"
                and any(field in {"vwap", "volume_ratio_20", "atr_pct_20", "movement_pct"} for field in missing_required_fields)
            ):
                return "compute_crypto_15Min_vwap_features"
            return "compute_required_replay_features"
        if classification == "signal_rules_too_strict":
            if base_strategy_id == "crypto_research.liquidation_wick_reclaim":
                return "widen_liquidation_wick_reclaim_signal_research_only"
            return "widen_signal_generation_research_only"
        if classification == "insufficient_history":
            if str(base_strategy_id).startswith("crypto_"):
                return f"backfill_or_resample_crypto_{timeframe}_bars"
            return "backfill_or_resample_market_history"
        if classification == "variant_research_not_consumed":
            return "send_to_diagnosis"
        if classification == "runtime_blocked":
            return "optimise_or_precompute_replay_dataset"
        return "return_to_expansion_planner"

    def _no_progress_reason(
        self,
        *,
        classification: str,
        runtime_blocker: str,
        missing_required_fields: list[str],
        eligible_replay_timestamps_count: int,
        observed_candidate_count: int,
    ) -> str:
        if classification == "runtime_blocked":
            return f"variant research runtime blocked by {runtime_blocker or 'historical_bar_read_timeout'}"
        if classification == "missing_required_features":
            return f"required replay features missing: {', '.join(missing_required_fields)}"
        if classification == "insufficient_history":
            return (
                "history coverage was too thin to open any eligible replay windows"
                if eligible_replay_timestamps_count <= 0
                else "history coverage remained insufficient for this replay window"
            )
        if classification == "signal_rules_too_strict":
            return "bounded replay windows existed, but signal filters produced zero eligible signals"
        if classification == "variant_research_not_consumed":
            return "variant research produced nonzero samples and should move to diagnosis instead of another expansion step"
        if observed_candidate_count <= 0:
            return "variant research read history but produced no observed replay candidates"
        return "variant research produced no usable replay decisions after evaluating observed candidates"

    def _metrics_fingerprint(self, evaluation: dict[str, Any]) -> str:
        if not evaluation:
            return ""
        payload = {
            "sample_size": int(evaluation.get("sample_size", 0) or 0),
            "net_return_after_costs": round(float(evaluation.get("net_return_after_costs", 0.0) or 0.0), 6),
            "win_rate": round(float(evaluation.get("win_rate", 0.0) or 0.0), 6),
            "drawdown": (
                round(float(evaluation.get("drawdown", 0.0) or 0.0), 6)
                if evaluation.get("drawdown") is not None
                else None
            ),
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode("utf-8")).hexdigest()[:24]

    def _diagnostic_warning(
        self,
        *,
        variant_id: str,
        baseline_variant_id: str,
        params_hash: str,
        baseline_params_hash: str,
        decision_set_hash: str,
        baseline_decision_set_hash: str,
        metrics_fingerprint: str,
        baseline_metrics_fingerprint: str,
    ) -> str:
        if not variant_id or variant_id == baseline_variant_id:
            return ""
        if (
            params_hash
            and baseline_params_hash
            and params_hash != baseline_params_hash
            and decision_set_hash
            and decision_set_hash == baseline_decision_set_hash
            and metrics_fingerprint
            and metrics_fingerprint == baseline_metrics_fingerprint
        ):
            return "params_differ_but_decisions_and_metrics_match"
        if (
            params_hash
            and baseline_params_hash
            and params_hash != baseline_params_hash
            and decision_set_hash
            and decision_set_hash == baseline_decision_set_hash
        ):
            return "params_differ_but_decision_set_matches_baseline"
        return ""

    def _dataset_id(self, *, profile: StrategyProfile, timeframe: str) -> str:
        prefix = "historical_crypto_bars" if "crypto" in set(profile.asset_classes) else "historical_equity_bars"
        return f"{prefix}:{timeframe}:{max(1, self.config.historical_replay_default_days)}d"

    def _strategy_for_profile(self, profile: StrategyProfile):
        for strategy in build_strategy_registry():
            for candidate_profile in strategy.build_profiles(self.config):
                if candidate_profile.strategy_id == profile.strategy_id and candidate_profile.profile_id == profile.profile_id:
                    return strategy
                if (
                    candidate_profile.strategy_id == profile.strategy_id
                    and str(candidate_profile.family or "") == str(profile.family or "")
                ):
                    return strategy
                if (
                    str(candidate_profile.family or "") == str(profile.strategy_id or "")
                    and str(candidate_profile.family or "") == str(profile.family or "")
                ):
                    return strategy
        raise ValueError(f"Unsupported strategy/profile: {profile.strategy_id}/{profile.profile_id}")

    def _variant_specs_for_profile(self, profile: StrategyProfile) -> list[tuple[str, dict[str, Any]]]:
        if profile.strategy_id == "crypto_momentum.trend":
            return [
                ("higher_entry_movement_020", {"min_movement_pct": 0.20}),
                ("higher_entry_movement_025", {"min_movement_pct": 0.25}),
                ("lower_max_movement_200", {"max_movement_pct": 2.0}),
                ("higher_discovery_30", {"min_discovery_score": 3.0}),
                ("higher_trade_count_3", {"min_trade_count": 3}),
                ("wider_stop_115_tp_220", {"stop_loss_pct": round(profile.stop_loss_pct * 1.15, 6), "target_multiple": round(profile.target_multiple + 0.2, 6)}),
                ("tighter_stop_090_tp_180", {"stop_loss_pct": round(max(0.005, profile.stop_loss_pct * 0.9), 6), "target_multiple": round(max(1.5, profile.target_multiple - 0.2), 6)}),
                ("holding_window_240", {"holding_window_minutes": 240}),
                ("holding_window_1440", {"holding_window_minutes": 1440}),
            ]
        if str(profile.family or "") == "crypto_pullback":
            return [
                ("deeper_pullback_200", {"max_pullback_pct": 2.0}),
                ("tighter_pullback_150", {"max_pullback_pct": 1.5}),
                ("higher_discovery_35", {"min_discovery_score": 3.5}),
                ("higher_trade_count_4", {"preferred_min_trade_count": 4}),
                ("higher_volume_100k", {"preferred_min_volume_gbp": 100_000.0}),
                ("tighter_spread_020", {"max_spread_pct": 0.20}),
                ("wider_stop_115_tp_220", {"stop_loss_pct": round(profile.stop_loss_pct * 1.15, 6), "target_multiple": round(profile.target_multiple + 0.2, 6)}),
                ("tighter_stop_090_tp_180", {"stop_loss_pct": round(max(0.005, profile.stop_loss_pct * 0.9), 6), "target_multiple": round(max(1.5, profile.target_multiple - 0.2), 6)}),
                ("holding_window_240", {"holding_window_minutes": 240}),
                ("holding_window_1440", {"holding_window_minutes": 1440}),
                ("holding_window_10080", {"holding_window_minutes": 10080}),
            ]
        if str(profile.family or "") == "crypto_research" and profile.profile_id == "dip_rebound":
            return [
                ("shallower_entry_020", {"min_pullback_pct": 0.20}),
                ("deeper_entry_035", {"min_pullback_pct": 0.35}),
                ("deeper_max_pullback_300", {"max_pullback_pct": 3.0}),
                ("tighter_max_pullback_175", {"max_pullback_pct": 1.75}),
                ("higher_discovery_30", {"min_discovery_score": 3.0}),
                ("higher_trade_count_3", {"min_trade_count": 3}),
                ("wider_stop_115_tp_220", {"stop_loss_pct": round(profile.stop_loss_pct * 1.15, 6), "target_multiple": round(profile.target_multiple + 0.2, 6)}),
                ("tighter_stop_090_tp_180", {"stop_loss_pct": round(max(0.005, profile.stop_loss_pct * 0.9), 6), "target_multiple": round(max(1.5, profile.target_multiple - 0.2), 6)}),
                ("holding_window_240", {"holding_window_minutes": 240}),
                ("holding_window_1440", {"holding_window_minutes": 1440}),
                ("holding_window_4320", {"holding_window_minutes": 4320}),
            ]
        return [
            ("deeper_pullback_020", {"max_movement_pct": -0.20}),
            ("deeper_pullback_022", {"max_movement_pct": -0.22}),
            ("higher_discovery_45", {"min_discovery_score": 4.5}),
            ("higher_trade_count_50", {"min_trade_count": 50}),
            ("wider_stop_205_tp_185", {"stop_loss_pct": round(profile.stop_loss_pct * 1.14, 6), "target_multiple": round(profile.target_multiple + 0.1, 6)}),
            ("deeper_pullback_020_trade_count_50", {"max_movement_pct": -0.20, "min_trade_count": 50}),
            ("cost_aware_expected_move_025", {"min_expected_net_move_pct": 0.25}),
            ("cost_aware_expected_move_050", {"min_expected_net_move_pct": 0.50}),
            ("cost_aware_expected_move_075", {"min_expected_net_move_pct": 0.75}),
            ("cost_aware_expected_move_100", {"min_expected_net_move_pct": 1.00}),
            ("cost_aware_expected_move_050_trade_count_50", {"min_expected_net_move_pct": 0.50, "min_trade_count": 50}),
            ("cost_aware_expected_move_075_trade_count_75", {"min_expected_net_move_pct": 0.75, "min_trade_count": 75}),
            ("holding_window_240", {"holding_window_minutes": 240}),
            ("holding_window_1440", {"holding_window_minutes": 1440}),
            ("holding_window_10080", {"holding_window_minutes": 10080}),
        ]

    def _evaluation_id(self, *, variant_id: str, replay_id: str, evaluated_at: datetime) -> str:
        payload = f"{variant_id}|{replay_id}|{evaluated_at.isoformat()}"
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]

    def _mean(self, values: list[float]) -> float:
        return mean(values) if values else 0.0

    def _win_rate(self, outcomes: list[dict[str, Any]]) -> float:
        realized = [float(item.get("realized_return_pct", 0.0) or 0.0) for item in outcomes]
        return (sum(1 for value in realized if value > 0) / len(realized)) if realized else 0.0

    def _to_float(self, value: Any) -> float | None:
        try:
            if value in (None, ""):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_int(self, value: Any) -> int | None:
        try:
            if value in (None, ""):
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _is_runtime_budget_blocker(self, exc: Exception) -> bool:
        message = str(exc or "").lower()
        return (
            "lock timeout" in message
            or "statement timeout" in message
            or "canceling statement due to lock timeout" in message
            or "canceling statement due to statement timeout" in message
        )


class StrategyVariantResearchReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)
        self.service = StrategyVariantResearchService(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )

    def build_report(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
    ) -> dict[str, Any]:
        definitions = self.usage_ledger.list_strategy_variant_definitions(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        evaluations = self.usage_ledger.list_strategy_variant_evaluations(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            limit=500,
        )
        latest_by_variant: dict[str, dict[str, Any]] = {}
        for evaluation in evaluations:
            variant_id = str(evaluation.get("variant_id", "") or "")
            if variant_id and variant_id not in latest_by_variant:
                latest_by_variant[variant_id] = evaluation
        baseline_definition = next(
            (item for item in definitions if item.get("generation_reason") == "baseline_profile"),
            None,
        )
        baseline_metrics = latest_by_variant.get(str((baseline_definition or {}).get("variant_id", "") or ""), {})
        baseline_raw = dict(baseline_metrics.get("raw_json", {}) or {})
        baseline_diagnostics = dict(baseline_raw.get("diagnostics", {}) or {})
        ranked = sorted(
            latest_by_variant.values(),
            key=lambda item: (
                float(item.get("net_return_after_costs", 0.0) or 0.0),
                float(item.get("win_rate", 0.0) or 0.0),
                -float(item.get("drawdown", 0.0) or 0.0),
            ),
            reverse=True,
        )
        return {
            "title": "Strategy Variant Research Report",
            "base_strategy_id": base_strategy_id,
            "profile_id": profile_id,
            "timeframe": timeframe,
            "safe_variable_params": self.service.safe_variable_params(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
            ),
            "baseline": {
                "variant_id": (baseline_definition or {}).get("variant_id", ""),
                "params_json": (baseline_definition or {}).get("params_json", {}),
                "metrics": baseline_metrics,
                "data_adequacy": dict(baseline_diagnostics.get("data_adequacy", {}) or {}),
            },
            "variants_generated": max(0, len(definitions) - 1),
            "variants_evaluated": len(latest_by_variant),
            "variants": [
                {
                    "variant_id": item.get("variant_id", ""),
                    "params_json": next(
                        (
                            definition.get("params_json", {})
                            for definition in definitions
                            if definition.get("variant_id") == item.get("variant_id")
                        ),
                        {},
                    ),
                    "sample_size": int(item.get("sample_size", 0) or 0),
                    "gross_return_before_costs": float(item.get("gross_return", 0.0) or 0.0),
                    "net_return_after_costs": float(item.get("net_return_after_costs", 0.0) or 0.0),
                    "average_winner": float(item.get("average_winner") or (dict(item.get("raw_json", {}) or {}).get("average_winner", 0.0)) or 0.0),
                    "average_loser": float(item.get("average_loser") or (dict(item.get("raw_json", {}) or {}).get("average_loser", 0.0)) or 0.0),
                    "win_rate": float(item.get("win_rate", 0.0) or 0.0),
                    "drawdown": item.get("drawdown"),
                    "gross_positive_net_negative_count": int(
                        item.get("gross_positive_net_negative_count")
                        or (dict(item.get("raw_json", {}) or {}).get("gross_positive_net_negative_count", 0))
                        or 0
                    ),
                    "target_hit_count": int((dict(item.get("raw_json", {}) or {}).get("target_hit_count", 0)) or 0),
                    "stop_hit_count": int((dict(item.get("raw_json", {}) or {}).get("stop_hit_count", 0)) or 0),
                    "time_exit_count": int((dict(item.get("raw_json", {}) or {}).get("time_exit_count", 0)) or 0),
                    "symbols_tested": list(item.get("symbols_tested", []) or []),
                    "data_adequacy": dict((dict(item.get("raw_json", {}) or {}).get("diagnostics", {}) or {}).get("data_adequacy", {}) or {}),
                    "beats_baseline": bool(item.get("beats_baseline")),
                    "beats_thresholds": bool(item.get("beats_thresholds")),
                    "recommended_status": str(item.get("recommended_status", "pending") or "pending"),
                }
                for item in ranked
            ],
            "safety_statement": "Research-only. No paper or live approval has been changed.",
        }

    def render(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
    ) -> str:
        report = self.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        lines = [
            str(report["title"]),
            f"base_strategy={report['base_strategy_id']} | profile={report['profile_id']} | timeframe={report['timeframe']}",
            f"baseline_variant_id={report['baseline'].get('variant_id', '-')}",
            (
                "baseline_metrics="
                f"gross_return_before_costs={report['baseline'].get('metrics', {}).get('gross_return', 0.0)}"
                f" | gross_positive_net_negative={report['baseline'].get('metrics', {}).get('gross_positive_net_negative_count', 0)}"
                f" | "
                f"net_return_after_costs={report['baseline'].get('metrics', {}).get('net_return_after_costs', 0.0)}"
                f" | average_winner={report['baseline'].get('metrics', {}).get('average_winner', 0.0)}"
                f" | average_loser={report['baseline'].get('metrics', {}).get('average_loser', 0.0)}"
                f" | win_rate={report['baseline'].get('metrics', {}).get('win_rate', 0.0)}"
                f" | sample_size={report['baseline'].get('metrics', {}).get('sample_size', 0)}"
            ),
            f"variants_generated={report['variants_generated']} | variants_evaluated={report['variants_evaluated']}",
            "Top Variants",
        ]
        for item in report["variants"][:10]:
            lines.append(
                f"- variant_id={item['variant_id']} | sample_size={item['sample_size']} | "
                f"gross_return_before_costs={item['gross_return_before_costs']} | "
                f"net_return_after_costs={item['net_return_after_costs']} | average_winner={item['average_winner']} | average_loser={item['average_loser']} | "
                f"win_rate={item['win_rate']} | drawdown={item['drawdown']} | gross_positive_net_negative={item['gross_positive_net_negative_count']} | "
                f"target_hit_count={item['target_hit_count']} | stop_hit_count={item['stop_hit_count']} | time_exit_count={item['time_exit_count']} | "
                f"beats_baseline={'yes' if item['beats_baseline'] else 'no'} | "
                f"beats_thresholds={'yes' if item['beats_thresholds'] else 'no'} | "
                f"recommended_status={item['recommended_status']} | symbols_tested={','.join(item['symbols_tested']) or '-'} | "
                f"params_json={json.dumps(item['params_json'], sort_keys=True)}"
            )
        lines.append(report["safety_statement"])
        return "\n".join(lines)


class StrategyVariantDiagnosticsReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)
        self.service = StrategyVariantResearchService(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )

    def build_report(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
    ) -> dict[str, Any]:
        return self.service.diagnose_variants(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )

    def render(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
    ) -> str:
        report = self.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        lines = [
            str(report.get("title", "Strategy Variant Diagnostics")),
            f"base_strategy={report.get('base_strategy_id', '-')}"
            f" | profile={report.get('profile_id', '-')}"
            f" | timeframe={report.get('timeframe', '-')}",
            f"baseline_variant_id={report.get('baseline_variant_id', '-')}"
            f" | baseline_params_hash={report.get('baseline_params_hash', '-') or '-'}",
        ]
        for item in report.get("rows", []) or []:
            lines.append(
                f"- variant_id={item.get('variant_id', '-')}"
                f" | params_hash={item.get('params_hash', '-')}"
                f" | generated_signal_count={int(item.get('generated_signal_count', 0) or 0)}"
                f" | generated_proposal_count={int(item.get('generated_proposal_count', 0) or 0)}"
                f" | usable_decision_count={int(item.get('usable_decision_count', 0) or 0)}"
                f" | rejected_by_param_filter_count={int(item.get('rejected_by_param_filter_count', 0) or 0)}"
                f" | decision_set_hash={item.get('decision_set_hash', '-') or '-'}"
                f" | decision_set_differs_from_baseline={'yes' if item.get('decision_set_differs_from_baseline') else 'no'}"
                f" | metrics_differ_from_baseline={'yes' if item.get('metrics_differ_from_baseline') else 'no'}"
                f" | warning={item.get('warning', '-') or '-'}"
            )
        lines.append(str(report.get("safety_statement", "")))
        return "\n".join(lines)
