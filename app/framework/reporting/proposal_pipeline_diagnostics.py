from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from math import log10
from typing import Any

from app.framework.engine.fitness_engine import allocate_strategy_signals
from app.framework.runtime.models import TickContext
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger
from app.framework.strategies.common import (
    has_strategy_identity,
    liquidity_component,
    normalized_asset_class,
)
from app.framework.strategies.registry import build_strategy_registry
from app.heartbeat.support import (
    _account_state_key_for_broker,
    _active_paper_broker_ids,
    _build_live_trade_approval,
    _build_paper_trade_approval,
    _earned_slot_policy,
    _live_runtime_allows_broker_reads,
    _orders_state_key_for_broker,
    _paper_allocation_suppress_thresholds,
    _paper_lane_position_state,
    _paper_protection_state_key_for_broker,
    _slot_size_native_for_broker,
)


class ProposalPipelineDiagnosticsReport:
    """Read-only report for where allowed strategies are getting filtered out."""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_report(self) -> dict[str, Any]:
        latest_tick = self.usage_ledger.get_latest_tick_run()
        if latest_tick is None:
            return {
                "status": "no_tick",
                "reason": "No persisted control tick is available yet.",
            }

        snapshot = self._as_dict(latest_tick.get("state_snapshot_json"))
        tick_id = str(latest_tick.get("tick_id", "") or "")
        started_at = self._as_datetime(latest_tick.get("started_at")) or datetime.now().astimezone()
        checked_at = self._as_datetime(latest_tick.get("ended_at")) or datetime.now().astimezone()
        context = TickContext(
            tick_id=tick_id or checked_at.strftime("%Y%m%d-%H%M%S"),
            started_at=started_at,
            config=self.config,
            usage_ledger=self.usage_ledger,
            state=snapshot,
        )

        registry_profiles: dict[str, tuple[Any, Any]] = {}
        for strategy in build_strategy_registry():
            for profile in strategy.build_profiles(self.config):
                registry_profiles[profile.strategy_id] = (strategy, profile)

        paper_allowed = tuple(self.config.paper_execution_allowed_strategies)
        live_allowed = tuple(self.config.live_execution_allowed_strategies)
        target_strategy_ids = self._ordered_unique(
            [
                *paper_allowed,
                *live_allowed,
                *self._diagnostic_strategy_ids(registry_profiles),
            ]
        )
        selected_strategy_candidates = self._strategy_selected_candidates(snapshot=snapshot)
        enriched_candidates = self._candidate_list(
            snapshot,
            eligible_candidates=selected_strategy_candidates,
        )
        universe = self._universe_overview(snapshot=snapshot)
        candidate_details = self._candidate_diagnostics(snapshot=snapshot)
        asset_coverage = self._asset_class_coverage(snapshot=snapshot)
        queue_diagnostics = self._queue_diagnostics()
        recent_strategy_keys = self.usage_ledger.list_recent_shadow_proposal_keys(
            since=started_at - timedelta(minutes=self.config.shadow_proposal_cooldown_minutes)
        )
        fitness_summaries = list(
            self._as_dict(snapshot.get("strategy_fitness")).get("summaries", []) or []
        )

        strategies: list[dict[str, Any]] = []
        for strategy_id in target_strategy_ids:
            strategy_entry = registry_profiles.get(strategy_id)
            if strategy_entry is None:
                strategies.append(
                    {
                        "strategy_id": strategy_id,
                        "registered": False,
                        "paper_execution_allowed": strategy_id in paper_allowed,
                        "paper_research_allowed": False,
                        "live_execution_allowed": strategy_id in live_allowed,
                        "symbols_scanned": 0,
                        "scanned_symbols": [],
                        "enough_data": 0,
                        "raw_signals": 0,
                        "final_proposals": 0,
                        "paper_approved": 0,
                        "live_approved": 0,
                        "rejections": {"strategy_not_registered": 1},
                        "closest_misses": [],
                    }
                )
                continue

            strategy, profile = strategy_entry
            strategy_report = self._diagnose_strategy(
                context=context,
                strategy=strategy,
                profile=profile,
                enriched_candidates=enriched_candidates,
                snapshot=snapshot,
                fitness_summaries=fitness_summaries,
                recent_strategy_keys=recent_strategy_keys,
                paper_allowed=strategy_id in paper_allowed,
                live_allowed=strategy_id in live_allowed,
            )
            strategies.append(strategy_report)

        integrity = self._proposal_data_integrity(
            snapshot=snapshot,
            candidate_details=candidate_details,
            strategies=strategies,
            queue_diagnostics=queue_diagnostics,
        )

        strategy_coverage = self._strategy_coverage(
            snapshot=snapshot,
            strategy_ids=target_strategy_ids,
            registry_profiles=registry_profiles,
        )

        return {
            "status": "ok",
            "tick_id": tick_id,
            "checked_at": checked_at.isoformat(),
            "snapshot_started_at": started_at.isoformat(),
            "backend": self.usage_ledger.backend,
            "selected_for_strategy_eval_count": len(enriched_candidates),
            "universe": universe,
            "asset_coverage": asset_coverage,
            "strategy_coverage": strategy_coverage,
            "queue_diagnostics": queue_diagnostics,
            "candidate_details": candidate_details,
            "proposal_data_integrity": integrity,
            "paper_allowed_strategies": list(paper_allowed),
            "live_allowed_strategies": list(live_allowed),
            "strategies": strategies,
            "summary": self._build_summary(
                strategies=strategies,
                candidate_count=len(enriched_candidates),
                universe=universe,
                queue_diagnostics=queue_diagnostics,
            ),
        }

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        report = report or self.build_report()
        if report.get("status") != "ok":
            return (
                "Proposal Pipeline Diagnostics\n"
                f"Status: {report.get('status', 'unknown')}\n"
                f"Reason: {report.get('reason', '-')}"
            )

        lines = [
            "Proposal Pipeline Diagnostics",
            (
                f"tick_id={report.get('tick_id', '-')}"
                f" | backend={report.get('backend', '-')}"
                f" | checked_at={report.get('checked_at', '-')}"
                f" | selected_for_strategy_eval={int(report.get('selected_for_strategy_eval_count', 0) or 0)}"
                f" | proposal_data_integrity={self._as_dict(report.get('proposal_data_integrity')).get('status', '-')}"
            ),
        ]
        integrity = self._as_dict(report.get("proposal_data_integrity"))
        lines.extend(
            [
                f"- proposal_data_integrity_failure_reasons={','.join(integrity.get('failure_reasons', []) or []) or 'none'}",
                f"- stale_or_account_only_selected_count={int(integrity.get('stale_or_account_only_selected_count', 0) or 0)}",
                f"- stale_or_account_only_with_strategy_batch_index_count={int(integrity.get('stale_or_account_only_with_strategy_batch_index_count', 0) or 0)}",
                f"- stale_or_account_only_in_strategy_misses_count={int(integrity.get('stale_or_account_only_in_strategy_misses_count', 0) or 0)}",
                f"- stale_or_account_only_in_symbols_scanned_count={int(integrity.get('stale_or_account_only_in_symbols_scanned_count', 0) or 0)}",
                f"- queue_health_affects_proposal_data_integrity={'yes' if integrity.get('queue_health_affects_proposal_data_integrity') else 'no'}",
            ]
        )
        universe = self._as_dict(report.get("universe"))
        lines.extend(
            [
                "",
                "Universe",
                f"- total_candidates_discovered={int(universe.get('total_candidates_discovered', 0) or 0)}",
                f"- stale_or_account_only_candidates={int(universe.get('stale_or_account_only_candidates', 0) or 0)}",
                f"- eligible_for_strategy_evaluation={int(universe.get('eligible_for_strategy_evaluation', 0) or 0)}",
                f"- selected_for_fast_strategy_evaluation={int(universe.get('selected_for_fast_strategy_evaluation', 0) or 0)}",
                f"- newly_enriched_this_tick={int(universe.get('newly_enriched_this_tick', 0) or 0)}",
                f"- actual_new_enrichments={int(universe.get('actual_new_enrichments', 0) or 0)}",
                f"- already_enriched_but_reused_candidates={int(universe.get('already_enriched_but_reused_candidates', 0) or 0)}",
                f"- deferred_candidates_not_in_fast_batch={int(universe.get('deferred_candidates_not_in_fast_batch', 0) or 0)}",
                f"- actually_enqueued_slow_jobs={int(universe.get('actually_enqueued_slow_jobs', 0) or 0)}",
                f"- queue_rows_reused_by_work_key={int(universe.get('queue_rows_reused_by_work_key', 0) or 0)}",
                f"- latest_market_data_at={universe.get('latest_market_data_at', '-')}",
                f"- candidates_with_price_history={int(universe.get('candidates_with_price_history', 0) or 0)}",
                f"- candidates_with_technical_context_ready={int(universe.get('candidates_with_technical_context_ready', 0) or 0)}",
                f"- symbols_with_only_one_distinct_bar={int(universe.get('symbols_with_only_one_distinct_bar', 0) or 0)}",
                f"- symbols_where_previous_close_equals_close={int(universe.get('symbols_where_previous_close_equals_close', 0) or 0)}",
                f"- stale_source_warning={'yes' if universe.get('stale_source_warning') else 'no'}",
                f"- candidates_excluded_due_to_stale_source={int(universe.get('candidates_excluded_due_to_stale_source', 0) or 0)}",
            ]
        )
        if "candidates_excluded_due_to_account_only_source" in universe:
            lines.append(
                f"- candidates_excluded_due_to_account_only_source={int(universe.get('candidates_excluded_due_to_account_only_source', 0) or 0)}"
            )
        source_freshness_status = self._as_dict(universe.get("source_freshness_status"))
        if source_freshness_status:
            rendered = ", ".join(
                f"{source}={self._as_dict(status).get('status', '-')}"
                for source, status in source_freshness_status.items()
            )
            lines.append(f"- source_freshness_status={rendered}")
        stale_sources_excluded = universe.get("stale_sources_excluded", []) or []
        if stale_sources_excluded:
            lines.append(
                f"- stale_sources_excluded={','.join(str(item) for item in stale_sources_excluded)}"
            )
        market_data_source_used_for_strategy = self._as_dict(
            universe.get("market_data_source_used_for_strategy")
        )
        if market_data_source_used_for_strategy:
            rendered = ", ".join(
                f"{asset_class}={source}"
                for asset_class, source in market_data_source_used_for_strategy.items()
            )
            lines.append(f"- market_data_source_used_for_strategy={rendered}")
        account_data_source_used_for_positions = self._as_dict(
            universe.get("account_data_source_used_for_positions")
        )
        if account_data_source_used_for_positions:
            rendered = ", ".join(
                f"{account}={source}"
                for account, source in account_data_source_used_for_positions.items()
            )
            lines.append(f"- account_data_source_used_for_positions={rendered}")
        newest_bar_age_by_source = self._as_dict(universe.get("newest_bar_age_by_source"))
        if newest_bar_age_by_source:
            rendered = ", ".join(f"{source}={age}" for source, age in newest_bar_age_by_source.items())
            lines.append(f"- newest_bar_age_by_source={rendered}")
        bars_available_by_source = self._as_dict(universe.get("bars_available_by_source"))
        if bars_available_by_source:
            rendered = ", ".join(f"{source}={count}" for source, count in bars_available_by_source.items())
            lines.append(f"- bars_available_by_source={rendered}")
        skipped_enqueue_reasons = self._as_dict(universe.get("skipped_enqueue_reasons"))
        if skipped_enqueue_reasons:
            rendered_reasons = ", ".join(
                f"{reason}={int(count or 0)}"
                for reason, count in skipped_enqueue_reasons.items()
                if int(count or 0) > 0
            )
            lines.append(f"- skipped_enqueue_reasons={rendered_reasons or 'none'}")
        if universe.get("selection_policy"):
            lines.append(f"- selection_policy={universe.get('selection_policy')}")
        if universe.get("queue_state_note"):
            lines.append(f"- queue_note={universe.get('queue_state_note')}")

        asset_coverage = self._as_dict(report.get("asset_coverage"))
        lines.extend(
            [
                "",
                "Asset Coverage",
                f"- total_equity_candidates={int(asset_coverage.get('total_equity_candidates', 0) or 0)}",
                f"- total_crypto_candidates={int(asset_coverage.get('total_crypto_candidates', 0) or 0)}",
                f"- selected_equity_candidates={int(asset_coverage.get('selected_equity_candidates', 0) or 0)}",
                f"- selected_crypto_candidates={int(asset_coverage.get('selected_crypto_candidates', 0) or 0)}",
                f"- queued_equity_candidates={int(asset_coverage.get('queued_equity_candidates', 0) or 0)}",
                f"- queued_crypto_candidates={int(asset_coverage.get('queued_crypto_candidates', 0) or 0)}",
            ]
        )
        if asset_coverage.get("selection_note"):
            lines.append(f"- selection_note={asset_coverage.get('selection_note')}")

        for row in report.get("strategies", []):
            item = self._as_dict(row)
            lines.extend(
                [
                    "",
                    f"strategy: {item.get('strategy_id', '-')}",
                    f"registered: {'yes' if item.get('registered') else 'no'}",
                    f"paper_execution_allowed: {'yes' if item.get('paper_execution_allowed') else 'no'}",
                    f"paper_research_allowed: {'yes' if item.get('paper_research_allowed') else 'no'}",
                    f"live_execution_allowed: {'yes' if item.get('live_execution_allowed') else 'no'}",
                    f"research_only: {'yes' if item.get('research_only') else 'no'}",
                    f"symbols_scanned: {int(item.get('symbols_scanned', 0) or 0)}",
                    f"enough_data: {int(item.get('enough_data', 0) or 0)}",
                    f"raw_signals: {int(item.get('raw_signals', 0) or 0)}",
                    f"final_proposals: {int(item.get('final_proposals', 0) or 0)}",
                    f"paper_approved: {int(item.get('paper_approved', 0) or 0)}",
                    f"live_approved: {int(item.get('live_approved', 0) or 0)}",
                    "rejected_by_stage:",
                ]
            )
            rejections = item.get("rejections", {}) or {}
            if rejections:
                for reason, count in sorted(
                    rejections.items(),
                    key=lambda entry: (-int(entry[1]), str(entry[0])),
                ):
                    lines.append(f"- {reason}: {int(count or 0)}")
            else:
                lines.append("- none")

            lines.append("closest_misses:")
            misses = item.get("closest_misses", []) or []
            if misses:
                for miss in misses[:5]:
                    miss_item = self._as_dict(miss)
                    detail = str(miss_item.get("detail", "") or "").strip()
                    lines.append(
                        (
                            f"- {miss_item.get('symbol', '-') or '-'}"
                            f" | stage={miss_item.get('stage', '-')}"
                            f" | blocker={miss_item.get('reason', '-')}"
                            f" | threshold={miss_item.get('threshold', '-')}"
                            f" | actual={miss_item.get('actual', '-')}"
                            f" | gap={miss_item.get('gap', '-')}"
                            + (f" | detail={detail}" if detail else "")
                        )
                    )
            else:
                lines.append("- none")

            crypto_gate_details = item.get("crypto_gate_details", []) or []
            if crypto_gate_details:
                lines.append("crypto_gate_details:")
                for gate_row in crypto_gate_details:
                    detail = self._as_dict(gate_row)
                    lines.append(
                        (
                            f"- {detail.get('symbol', '-')}"
                            f" | first_failed_gate={detail.get('first_failed_gate', '-')}"
                            f" | movement_pct={detail.get('movement_pct', '-')}"
                            f" | discovery_score={detail.get('discovery_score', '-')}"
                            f" | liquidity_score={detail.get('liquidity_score', '-')}"
                            f" | volume={detail.get('volume', '-')}"
                            f" | volume_score={detail.get('volume_score', '-')}"
                            f" | trade_count={detail.get('trade_count', '-')}"
                            f" | spread_pct={detail.get('spread_pct', '-')}"
                            f" | volume_gbp={detail.get('volume_gbp', '-')}"
                            f" | signal_score={detail.get('signal_score', '-')}"
                            f" | final_blocker={detail.get('final_blocker', '-')}"
                        )
                    )
                    for check in detail.get("checks", []) or []:
                        check_item = self._as_dict(check)
                        lines.append(
                            (
                                f"- {detail.get('symbol', '-')}"
                                f" | check={check_item.get('name', '-')}"
                                f" | pass={'yes' if check_item.get('passed') else 'no'}"
                                f" | threshold={check_item.get('threshold', '-')}"
                                f" | actual={check_item.get('actual', '-')}"
                            )
                        )

            pullback_gate_details = item.get("pullback_gate_details", []) or []
            if pullback_gate_details:
                lines.append("pullback_gate_details:")
                for gate_row in pullback_gate_details:
                    detail = self._as_dict(gate_row)
                    lines.append(
                        (
                            f"- {detail.get('symbol', '-')}"
                            f" | first_failed_gate={detail.get('first_failed_gate', '-')}"
                            f" | movement_pct={detail.get('movement_pct', '-')}"
                            f" | discovery_score={detail.get('discovery_score', '-')}"
                            f" | liquidity_score={detail.get('liquidity_score', '-')}"
                            f" | volume={detail.get('volume', '-')}"
                            f" | volume_gbp={detail.get('volume_gbp', '-')}"
                            f" | trade_count={detail.get('trade_count', '-')}"
                            f" | spread_pct={detail.get('spread_pct', '-')}"
                            f" | signal_score={detail.get('signal_score', '-')}"
                            f" | final_blocker={detail.get('final_blocker', '-')}"
                            f" | paper_research_eligible={'yes' if detail.get('paper_research_eligible') else 'no'}"
                            f" | paper_execution_allowed={'yes' if detail.get('paper_execution_allowed') else 'no'}"
                            f" | paper_research_allowed={'yes' if detail.get('paper_research_allowed') else 'no'}"
                            f" | live_execution_allowed={'yes' if detail.get('live_execution_allowed') else 'no'}"
                            f" | research_only={'yes' if detail.get('research_only') else 'no'}"
                        )
                    )
                    for check in detail.get("checks", []) or []:
                        check_item = self._as_dict(check)
                        lines.append(
                            (
                                f"- {detail.get('symbol', '-')}"
                                f" | check={check_item.get('name', '-')}"
                                f" | pass={'yes' if check_item.get('passed') else 'no'}"
                                f" | blocking={'yes' if check_item.get('blocking', True) else 'no'}"
                                f" | threshold={check_item.get('threshold', '-')}"
                                f" | actual={check_item.get('actual', '-')}"
                            )
                        )

        lines.append("")
        lines.append("Strategy Coverage")
        strategy_coverage = report.get("strategy_coverage", []) or []
        if strategy_coverage:
            for item in strategy_coverage:
                coverage = self._as_dict(item)
                lines.append(
                    (
                        f"- {coverage.get('strategy_id', '-')}"
                        f" | required_asset_class={coverage.get('required_asset_class', '-')}"
                        f" | available_matching_candidates={coverage.get('available_matching_candidates', 0)}"
                        f" | selected_matching_candidates={coverage.get('selected_matching_candidates', 0)}"
                        f" | skipped_because_no_selected_candidates={'yes' if coverage.get('skipped_because_no_selected_candidates') else 'no'}"
                    )
                )
        else:
            lines.append("- none")

        queue_diagnostics = self._as_dict(report.get("queue_diagnostics"))
        lines.extend(
            [
                "",
                "Slow Queue",
                f"- current_pending_count={int(queue_diagnostics.get('current_pending_count', 0) or 0)}",
                f"- current_processing_count={int(queue_diagnostics.get('current_processing_count', 0) or 0)}",
                f"- pending_cap={int(queue_diagnostics.get('pending_cap', 0) or 0)}",
                f"- oldest_pending_item_age={queue_diagnostics.get('oldest_pending_item_age', '-')}",
                f"- expired_pending_count={int(queue_diagnostics.get('expired_pending_count', 0) or 0)}",
                f"- failed_count={int(queue_diagnostics.get('failed_count', 0) or 0)}",
                f"- terminal_slow_jobs={int(queue_diagnostics.get('terminal_count', 0) or 0)}",
                f"- processed_last_hour={int(queue_diagnostics.get('processed_last_hour', 0) or 0)}",
                f"- processed_last_24h={int(queue_diagnostics.get('processed_last_24h', 0) or 0)}",
                f"- last_processed_at={queue_diagnostics.get('last_processed_at', '-')}",
                f"- queue_health={queue_diagnostics.get('queue_health', '-')}",
                f"- pending_rows_are_being_processed={'yes' if queue_diagnostics.get('pending_rows_are_being_processed') else 'no'}",
                f"- queue_is_draining_over_time={'yes' if queue_diagnostics.get('queue_is_draining_over_time') else 'no'}",
                f"- candidates_can_get_stuck_permanently={'yes' if queue_diagnostics.get('candidates_can_get_stuck_permanently') else 'no'}",
            ]
        )
        if queue_diagnostics.get("note"):
            lines.append(f"- note={queue_diagnostics.get('note')}")

        candidate_details = report.get("candidate_details", []) or []
        lines.append("")
        lines.append("Candidate Batch")
        if candidate_details:
            for item in candidate_details[:12]:
                candidate = self._as_dict(item)
                lines.append(
                    (
                        f"- {candidate.get('symbol', '-')}"
                        f" | source={candidate.get('source', '-')}"
                        f" | discovery_rank={candidate.get('discovery_rank', '-')}"
                        f" | eligible_rank={candidate.get('eligible_rank', '-')}"
                        f" | selected={'yes' if candidate.get('selected') else 'no'}"
                        f" | strategy_batch_index={candidate.get('strategy_batch_index', '-')}"
                        f" | queue_position={candidate.get('queue_position', '-')}"
                        f" | exclusion_reason={candidate.get('exclusion_reason', '-')}"
                        f" | movement_pct={candidate.get('movement_pct', '-')}"
                        f" | current_bar_timestamp={candidate.get('current_bar_timestamp', '-')}"
                        f" | previous_bar_timestamp={candidate.get('previous_bar_timestamp', '-')}"
                        f" | previous_close_price={candidate.get('previous_close_price', '-')}"
                        f" | close_price={candidate.get('close_price', '-')}"
                        f" | number_of_bars_available={candidate.get('number_of_bars_available', '-')}"
                        f" | newest_bar_age={candidate.get('newest_bar_age', '-')}"
                        f" | technical_context_ready={candidate.get('technical_context_ready', '-')}"
                        f" | last_enriched_at={candidate.get('last_enriched_at', '-')}"
                    )
                )
        else:
            lines.append("- none")

        summary = self._as_dict(report.get("summary"))
        lines.extend(
            [
                "",
                "Summary",
                f"- primary_issue={summary.get('primary_issue', '-')}",
                f"- explanation={summary.get('explanation', '-')}",
            ]
        )
        for point in summary.get("notes", []) or []:
            lines.append(f"- {point}")

        return "\n".join(lines)

    def _diagnose_strategy(
        self,
        *,
        context: TickContext,
        strategy: Any,
        profile: Any,
        enriched_candidates: list[dict[str, Any]],
        snapshot: dict[str, Any],
        fitness_summaries: list[dict[str, Any]],
        recent_strategy_keys: set[tuple[str, str, str]],
        paper_allowed: bool,
        live_allowed: bool,
    ) -> dict[str, Any]:
        in_scope_candidates = [
            candidate
            for candidate in enriched_candidates
            if normalized_asset_class(candidate) in profile.asset_classes
        ]
        rejection_events: list[dict[str, Any]] = []
        strategy_context = {
            "market_gate": self._as_dict(context.state.get("market_gate")),
            "account_equity": self._as_dict(context.state.get("alpaca_account")).get("summary", {}).get("equity"),
            "strategy_rejections": rejection_events,
        }
        raw_signals = []
        for candidate in in_scope_candidates:
            signal = strategy.evaluate_candidate(
                profile=profile,
                candidate=candidate,
                market_context=strategy_context,
            )
            if signal is not None:
                raw_signals.append(signal)

        raw_signals.sort(
            key=lambda item: (item.signal_score, item.confidence, item.symbol),
            reverse=True,
        )
        limited_signals = raw_signals[: max(1, int(profile.max_signals_per_tick))]
        overflow_signals = raw_signals[max(1, int(profile.max_signals_per_tick)) :]
        signal_dicts = [
            item.with_rank(index).as_dict(tick_id=context.tick_id)
            for index, item in enumerate(limited_signals, start=1)
        ]

        allocation_signals, allocation_stats = self._allocate_signals_for_current_lane(
            context=context,
            signal_dicts=signal_dicts,
            fitness_summaries=fitness_summaries,
        )
        proposal_stage = self._diagnose_shadow_proposals(
            context=context,
            strategy_signals=allocation_signals,
            recent_strategy_keys=recent_strategy_keys,
        )
        paper_stage = self._diagnose_paper_stage(
            context=context,
            proposals=proposal_stage["proposals"] if paper_allowed else [],
        )
        live_stage = self._diagnose_live_stage(
            context=context,
            proposals=proposal_stage["proposals"] if live_allowed else [],
        )

        rejections: Counter[str] = Counter()
        for event in rejection_events:
            rejections[f"strategy.{event.get('reason', 'unknown')}"] += 1
        if overflow_signals:
            rejections["strategy.max_signals_per_tick"] += len(overflow_signals)
        rejections["allocation.suppressed"] += int(allocation_stats.get("suppressed", 0) or 0)
        rejections.update(
            {
                f"proposal.{reason}": int(count or 0)
                for reason, count in proposal_stage["rejections"].items()
            }
        )
        rejections.update(
            {
                f"paper.{reason}": int(count or 0)
                for reason, count in paper_stage["rejections"].items()
            }
        )
        rejections.update(
            {
                f"live.{reason}": int(count or 0)
                for reason, count in live_stage["rejections"].items()
            }
        )

        enough_data = 0
        data_reasons = {
            "missing_instrument_identity",
            "missing_entry_price",
            "technical_context_not_ready",
            "missing_breakout_context",
            "missing_confirmation_context",
        }
        rejected_symbols = {
            (str(event.get("symbol", "")).upper(), str(event.get("reason", "")))
            for event in rejection_events
        }
        for candidate in in_scope_candidates:
            symbol = str(candidate.get("symbol", "")).upper()
            matching_data_rejection = any(
                rejected_symbol == symbol and reason in data_reasons
                for rejected_symbol, reason in rejected_symbols
            )
            if has_strategy_identity(candidate) and not matching_data_rejection:
                enough_data += 1

        closest_misses = self._closest_misses(
            profile=profile,
            rejection_events=rejection_events,
            suppressed_signals=allocation_stats.get("suppressed_signals", []),
            proposal_misses=proposal_stage["misses"],
            paper_misses=paper_stage["misses"],
            live_misses=live_stage["misses"],
        )
        crypto_gate_details: list[dict[str, Any]] = []
        pullback_gate_details: list[dict[str, Any]] = []
        if str(profile.strategy_id) == "crypto_momentum.trend":
            crypto_gate_details = self._crypto_momentum_gate_details(
                profile=profile,
                candidates=in_scope_candidates,
                rejection_events=rejection_events,
            )
        if str(profile.strategy_id) == "crypto_pullback.downside_reversal_watch":
            pullback_gate_details = self._crypto_pullback_gate_details(
                profile=profile,
                candidates=in_scope_candidates,
                rejection_events=rejection_events,
            )
        return {
            "strategy_id": profile.strategy_id,
            "registered": True,
            "paper_execution_allowed": paper_allowed,
            "paper_research_allowed": bool(profile.parameters.get("paper_allowed")),
            "live_execution_allowed": live_allowed,
            "research_only": bool(profile.parameters.get("research_only")),
            "symbols_scanned": len(in_scope_candidates),
            "scanned_symbols": [
                str(candidate.get("symbol", "")).strip().upper()
                for candidate in in_scope_candidates
                if str(candidate.get("symbol", "")).strip()
            ],
            "enough_data": enough_data,
            "raw_signals": len(raw_signals),
            "final_proposals": len(proposal_stage["proposals"]),
            "paper_approved": len(paper_stage["approved"]),
            "live_approved": len(live_stage["approved"]),
            "rejections": dict(rejections),
            "closest_misses": closest_misses,
            "crypto_gate_details": crypto_gate_details,
            "pullback_gate_details": pullback_gate_details,
        }

    def _allocate_signals_for_current_lane(
        self,
        *,
        context: TickContext,
        signal_dicts: list[dict[str, Any]],
        fitness_summaries: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        snapshot = self._as_dict(context.state.get("strategy_signals"))
        threshold_state = self._as_dict(snapshot.get("threshold_adaptive"))
        suppress_threshold = float(
            threshold_state.get(
                "effective_threshold",
                self.config.strategy_allocation_suppress_threshold,
            )
        )
        suppress_thresholds = _paper_allocation_suppress_thresholds(
            context,
            equity_threshold=suppress_threshold,
        )
        return allocate_strategy_signals(
            signals=signal_dicts,
            fitness_summaries=fitness_summaries,
            min_checkpoints=self.config.strategy_allocation_min_checkpoints,
            favor_threshold=self.config.strategy_allocation_favor_threshold,
            suppress_threshold=suppress_threshold,
            asset_class_suppress_thresholds=suppress_thresholds,
            high_score_override_enabled=False,
            high_score_override_min_score=(
                self.config.live_min_signal_score_to_trade
                if self.config.centaur_environment == "live"
                else self.config.paper_min_signal_score_to_trade
            ),
            high_score_override_fitness_margin=(
                self.config.live_execution_high_score_override_fitness_margin
                if self.config.centaur_environment == "live"
                else self.config.paper_execution_high_score_override_fitness_margin
            ),
            high_score_override_allowed_strategies=set(),
        )

    def _crypto_momentum_gate_details(
        self,
        *,
        profile: Any,
        candidates: list[dict[str, Any]],
        rejection_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rejection_by_symbol: dict[str, dict[str, Any]] = {}
        for event in rejection_events:
            symbol = str(event.get("symbol", "")).upper()
            if symbol and symbol not in rejection_by_symbol:
                rejection_by_symbol[symbol] = self._as_dict(event)

        rows: list[dict[str, Any]] = []
        for candidate in candidates:
            symbol = str(candidate.get("symbol", "")).upper()
            movement_pct = self._to_float(candidate.get("movement_pct"))
            discovery_score = self._to_float(candidate.get("discovery_score"))
            trade_count = self._to_int(candidate.get("trade_count"))
            volume = self._to_int(candidate.get("volume"))
            entry_price = self._to_float(candidate.get("close_price"))
            entry_price_gbp = self._to_float(candidate.get("close_price_gbp"))
            volume_gbp = self._to_float(candidate.get("volume_gbp"))
            if volume_gbp is None and entry_price_gbp is not None and volume is not None:
                volume_gbp = entry_price_gbp * volume
            spread_pct = self._to_float(candidate.get("spread_pct"))
            liquidity_score = liquidity_component(volume=volume, trade_count=trade_count)
            volume_score = self._volume_score(volume)
            signal_score = None
            if movement_pct is not None and discovery_score is not None:
                signal_score = round(
                    min(
                        100.0,
                        (movement_pct * 135.0)
                        + (discovery_score * 8.0)
                        + (liquidity_score * 4.0),
                    ),
                    6,
                )

            checks = [
                self._gate_check(
                    name="has_strategy_identity",
                    passed=has_strategy_identity(candidate),
                    threshold="required",
                    actual="yes" if has_strategy_identity(candidate) else "no",
                ),
                self._gate_check(
                    name="asset_class_allowed",
                    passed=normalized_asset_class(candidate) in profile.asset_classes,
                    threshold="crypto",
                    actual=normalized_asset_class(candidate) or "-",
                ),
                self._gate_check(
                    name="movement_min",
                    passed=movement_pct is not None and movement_pct >= float(profile.parameters["min_movement_pct"]),
                    threshold=self._fmt_num(profile.parameters["min_movement_pct"], 6),
                    actual=self._fmt_num(movement_pct, 6),
                ),
                self._gate_check(
                    name="movement_max",
                    passed=movement_pct is not None and movement_pct <= float(profile.parameters["max_movement_pct"]),
                    threshold=self._fmt_num(profile.parameters["max_movement_pct"], 6),
                    actual=self._fmt_num(movement_pct, 6),
                ),
                self._gate_check(
                    name="discovery_min",
                    passed=(discovery_score or 0.0) >= float(profile.parameters["min_discovery_score"]),
                    threshold=self._fmt_num(profile.parameters["min_discovery_score"], 6),
                    actual=self._fmt_num(discovery_score, 6),
                ),
                self._gate_check(
                    name="trade_count_min",
                    passed=(trade_count or 0) >= int(profile.parameters["min_trade_count"]),
                    threshold=str(int(profile.parameters["min_trade_count"])),
                    actual=str(trade_count if trade_count is not None else "-"),
                ),
                self._gate_check(
                    name="entry_price_valid",
                    passed=entry_price is not None and entry_price > 0,
                    threshold="> 0",
                    actual=self._fmt_num(entry_price, 6),
                ),
                self._gate_check(
                    name="volume_gbp_min",
                    passed=(
                        float(profile.parameters["min_volume_gbp"]) <= 0
                        or (volume_gbp is not None and volume_gbp >= float(profile.parameters["min_volume_gbp"]))
                    ),
                    threshold=self._fmt_num(profile.parameters["min_volume_gbp"], 2),
                    actual=self._fmt_num(volume_gbp, 2),
                ),
                self._gate_check(
                    name="spread_max",
                    passed=(
                        spread_pct is None
                        or spread_pct <= float(profile.parameters["max_spread_pct"])
                    ),
                    threshold=self._fmt_num(profile.parameters["max_spread_pct"], 6),
                    actual=self._fmt_num(spread_pct, 6),
                ),
                self._gate_check(
                    name="signal_score_min",
                    passed=signal_score is not None and signal_score >= float(profile.min_signal_score),
                    threshold=self._fmt_num(profile.min_signal_score, 6),
                    actual=self._fmt_num(signal_score, 6),
                ),
            ]

            rejection = rejection_by_symbol.get(symbol, {})
            final_blocker = str(rejection.get("reason", "") or "passed_all_strategy_gates")
            first_failed_gate = next(
                (
                    str(item.get("name", "") or "-")
                    for item in checks
                    if not bool(item.get("passed"))
                ),
                "passed_all_strategy_gates",
            )
            rows.append(
                {
                    "symbol": symbol,
                    "first_failed_gate": first_failed_gate,
                    "movement_pct": self._fmt_num(movement_pct, 6),
                    "discovery_score": self._fmt_num(discovery_score, 6),
                    "liquidity_score": self._fmt_num(liquidity_score, 6),
                    "volume": volume if volume is not None else "-",
                    "volume_score": self._fmt_num(volume_score, 6),
                    "trade_count": trade_count if trade_count is not None else "-",
                    "spread_pct": self._fmt_num(spread_pct, 6),
                    "volume_gbp": self._fmt_num(volume_gbp, 2),
                    "signal_score": self._fmt_num(signal_score, 6),
                    "final_blocker": final_blocker,
                    "checks": checks,
                }
            )
        return rows

    def _gate_check(
        self,
        *,
        name: str,
        passed: bool,
        threshold: str,
        actual: str,
        blocking: bool = True,
    ) -> dict[str, Any]:
        return {
            "name": name,
            "passed": passed,
            "threshold": threshold,
            "actual": actual,
            "blocking": blocking,
        }

    def _crypto_pullback_gate_details(
        self,
        *,
        profile: Any,
        candidates: list[dict[str, Any]],
        rejection_events: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rejection_by_symbol: dict[str, dict[str, Any]] = {}
        for event in rejection_events:
            symbol = str(event.get("symbol", "")).upper()
            if symbol and symbol not in rejection_by_symbol:
                rejection_by_symbol[symbol] = self._as_dict(event)

        rows: list[dict[str, Any]] = []
        preferred_trade_count = int(profile.parameters["preferred_min_trade_count"])
        preferred_volume_gbp = float(profile.parameters["preferred_min_volume_gbp"])
        for candidate in candidates:
            symbol = str(candidate.get("symbol", "")).upper()
            movement_pct = self._to_float(candidate.get("movement_pct"))
            discovery_score = self._to_float(candidate.get("discovery_score"))
            trade_count = self._to_int(candidate.get("trade_count"))
            volume = self._to_int(candidate.get("volume"))
            entry_price = self._to_float(candidate.get("close_price"))
            entry_price_gbp = self._to_float(candidate.get("close_price_gbp"))
            volume_gbp = self._to_float(candidate.get("volume_gbp"))
            if volume_gbp is None and entry_price_gbp is not None and volume is not None:
                volume_gbp = entry_price_gbp * volume
            spread_pct = self._to_float(candidate.get("spread_pct"))
            liquidity_score = liquidity_component(volume=volume, trade_count=trade_count)
            pullback_pct = abs(movement_pct) if movement_pct is not None else None
            signal_score = None
            if pullback_pct is not None and discovery_score is not None:
                trade_bonus = 4.0 if (trade_count or 0) >= preferred_trade_count else 0.0
                volume_bonus = 4.0 if (
                    volume_gbp is not None and volume_gbp >= preferred_volume_gbp
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

            checks = [
                self._gate_check(
                    name="has_strategy_identity",
                    passed=has_strategy_identity(candidate),
                    threshold="required",
                    actual="yes" if has_strategy_identity(candidate) else "no",
                ),
                self._gate_check(
                    name="asset_class_allowed",
                    passed=normalized_asset_class(candidate) in profile.asset_classes,
                    threshold="crypto",
                    actual=normalized_asset_class(candidate) or "-",
                ),
                self._gate_check(
                    name="movement_negative",
                    passed=movement_pct is not None and movement_pct < 0,
                    threshold="< 0",
                    actual=self._fmt_num(movement_pct, 6),
                ),
                self._gate_check(
                    name="pullback_min",
                    passed=(
                        pullback_pct is not None
                        and pullback_pct >= float(profile.parameters["min_pullback_pct"])
                    ),
                    threshold=self._fmt_num(profile.parameters["min_pullback_pct"], 6),
                    actual=self._fmt_num(pullback_pct, 6),
                ),
                self._gate_check(
                    name="pullback_max",
                    passed=(
                        pullback_pct is not None
                        and pullback_pct <= float(profile.parameters["max_pullback_pct"])
                    ),
                    threshold=self._fmt_num(profile.parameters["max_pullback_pct"], 6),
                    actual=self._fmt_num(pullback_pct, 6),
                ),
                self._gate_check(
                    name="discovery_min",
                    passed=(discovery_score or 0.0) >= float(profile.parameters["min_discovery_score"]),
                    threshold=self._fmt_num(profile.parameters["min_discovery_score"], 6),
                    actual=self._fmt_num(discovery_score, 6),
                ),
                self._gate_check(
                    name="entry_price_valid",
                    passed=entry_price is not None and entry_price > 0,
                    threshold="> 0",
                    actual=self._fmt_num(entry_price, 6),
                ),
                self._gate_check(
                    name="trade_count_preferred",
                    passed=(trade_count or 0) >= preferred_trade_count,
                    threshold=str(preferred_trade_count),
                    actual=str(trade_count if trade_count is not None else "-"),
                    blocking=False,
                ),
                self._gate_check(
                    name="volume_gbp_preferred",
                    passed=(
                        volume_gbp is not None and volume_gbp >= preferred_volume_gbp
                    ),
                    threshold=self._fmt_num(preferred_volume_gbp, 2),
                    actual=self._fmt_num(volume_gbp, 2),
                    blocking=False,
                ),
                self._gate_check(
                    name="spread_preferred",
                    passed=(
                        spread_pct is not None
                        and spread_pct <= float(profile.parameters["max_spread_pct"])
                    ),
                    threshold=self._fmt_num(profile.parameters["max_spread_pct"], 6),
                    actual=self._fmt_num(spread_pct, 6),
                    blocking=False,
                ),
                self._gate_check(
                    name="signal_score_min",
                    passed=signal_score is not None and signal_score >= float(profile.min_signal_score),
                    threshold=self._fmt_num(profile.min_signal_score, 6),
                    actual=self._fmt_num(signal_score, 6),
                ),
            ]

            rejection = rejection_by_symbol.get(symbol, {})
            final_blocker = str(rejection.get("reason", "") or "passed_all_strategy_gates")
            first_failed_gate = next(
                (
                    str(item.get("name", "") or "-")
                    for item in checks
                    if bool(item.get("blocking", True)) and not bool(item.get("passed"))
                ),
                "passed_all_strategy_gates",
            )
            rows.append(
                {
                    "symbol": symbol,
                    "first_failed_gate": first_failed_gate,
                    "movement_pct": self._fmt_num(movement_pct, 6),
                    "discovery_score": self._fmt_num(discovery_score, 6),
                    "liquidity_score": self._fmt_num(liquidity_score, 6),
                    "volume": volume if volume is not None else "-",
                    "trade_count": trade_count if trade_count is not None else "-",
                    "spread_pct": self._fmt_num(spread_pct, 6),
                    "volume_gbp": self._fmt_num(volume_gbp, 2),
                    "signal_score": self._fmt_num(signal_score, 6),
                    "final_blocker": final_blocker,
                    "paper_research_eligible": final_blocker == "passed_all_strategy_gates",
                    "paper_execution_allowed": False,
                    "paper_research_allowed": bool(profile.parameters.get("paper_allowed")),
                    "live_execution_allowed": bool(profile.parameters.get("live_allowed")),
                    "research_only": bool(profile.parameters.get("research_only")),
                    "checks": checks,
                }
            )
        return rows

    def _diagnostic_strategy_ids(
        self,
        registry_profiles: dict[str, tuple[Any, Any]],
    ) -> list[str]:
        return [
            strategy_id
            for strategy_id, (_, profile) in registry_profiles.items()
            if bool(getattr(profile, "parameters", {}).get("diagnostics_always_include"))
        ]

    def _volume_score(self, volume: int | None) -> float | None:
        if volume is None:
            return None
        return round(log10(max(0, volume) + 1), 6)

    def _diagnose_shadow_proposals(
        self,
        *,
        context: TickContext,
        strategy_signals: list[dict[str, Any]],
        recent_strategy_keys: set[tuple[str, str, str]],
    ) -> dict[str, Any]:
        rejections: Counter[str] = Counter()
        misses: list[dict[str, Any]] = []
        proposals: list[dict[str, Any]] = []
        ranked_signals = sorted(
            strategy_signals,
            key=lambda item: (
                float(item.get("signal_score", 0) or 0),
                float(item.get("confidence", 0) or 0),
                str(item.get("strategy_id", "")),
                str(item.get("symbol", "")),
            ),
            reverse=True,
        )
        for signal in ranked_signals:
            symbol = str(signal.get("symbol", "")).upper()
            source = str(signal.get("source", ""))
            strategy_id = str(signal.get("strategy_id", ""))
            if not symbol:
                rejections["missing_symbol"] += 1
                continue
            if (strategy_id, source, symbol) in recent_strategy_keys:
                rejections["cooldown_active"] += 1
                misses.append(
                    {
                        "symbol": symbol,
                        "stage": "proposal",
                        "reason": "cooldown_active",
                        "threshold": f"{self.config.shadow_proposal_cooldown_minutes}m cooldown",
                        "actual": "recent proposal exists",
                        "gap": "n/a",
                        "detail": f"{strategy_id}/{source}/{symbol}",
                        "_sort_gap": 999999.0,
                    }
                )
                continue
            signal_score = float(signal.get("signal_score", 0) or 0)
            if signal_score < float(self.config.shadow_min_opportunity_score):
                rejections["score_below_shadow_threshold"] += 1
                gap = float(self.config.shadow_min_opportunity_score) - signal_score
                misses.append(
                    {
                        "symbol": symbol,
                        "stage": "proposal",
                        "reason": "score_below_shadow_threshold",
                        "threshold": f">= {self.config.shadow_min_opportunity_score:.3f}",
                        "actual": f"{signal_score:.3f}",
                        "gap": f"{gap:.3f}",
                        "_sort_gap": gap,
                    }
                )
                continue
            if len(proposals) >= max(1, int(self.config.shadow_proposal_limit)):
                rejections["proposal_limit_reached"] += 1
                misses.append(
                    {
                        "symbol": symbol,
                        "stage": "proposal",
                        "reason": "proposal_limit_reached",
                        "threshold": f"top {int(self.config.shadow_proposal_limit)}",
                        "actual": "ranked below limit",
                        "gap": "n/a",
                        "_sort_gap": 999999.0,
                    }
                )
                continue
            proposal = {
                "proposal_id": f"{context.tick_id}-{strategy_id}-{source}-{symbol}",
                "tick_id": context.tick_id,
                "proposed_at": context.started_at.isoformat(),
                "strategy_id": strategy_id,
                "strategy_family": str(signal.get("strategy_family", "")),
                "profile_id": str(signal.get("profile_id", "")),
                "source": source,
                "symbol": symbol,
                "asset_class": str(signal.get("asset_class", "equity")),
                "direction": str(signal.get("direction", "long")),
                "entry_price": signal.get("entry_price"),
                "stop_loss_price": signal.get("stop_loss_price"),
                "target_price": signal.get("target_price"),
                "holding_window_code": str(signal.get("holding_window_code", "")),
                "holding_window_minutes": int(signal.get("holding_window_minutes", 0) or 0),
            }
            proposals.append(proposal)
        return {
            "proposals": proposals,
            "rejections": dict(rejections),
            "misses": misses,
        }

    def _diagnose_paper_stage(
        self,
        *,
        context: TickContext,
        proposals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not proposals:
            return self._stage_result(approved=[], rejected=[])
        rejected: list[dict[str, Any]] = []
        approved: list[dict[str, Any]] = []
        gate = self._as_dict(context.state.get("market_gate"))
        protection = self._as_dict(context.state.get("daily_protection"))
        if self.config.paper_execution_kill_switch:
            return self._blocked_stage("paper_kill_switch_on", proposals, stage="paper")
        if not self.config.paper_execution_enabled:
            return self._blocked_stage("paper_execution_disabled", proposals, stage="paper")
        if str(protection.get("system_status", "active")).lower() == "protected":
            return self._blocked_stage("daily_drawdown_limit_reached", proposals, stage="paper")
        if not gate.get("account_trade_ready", False):
            return self._blocked_stage(str(gate.get("reason", "account_not_ready")), proposals, stage="paper")

        paper_brokers = _active_paper_broker_ids(context)
        recent_trade_orders: list[dict[str, Any]] = []
        if "trading212_paper" in paper_brokers:
            list_recent_orders = getattr(
                context.usage_ledger,
                "list_recent_execution_lane_trade_orders",
                None,
            )
            if callable(list_recent_orders):
                recent_trade_orders = list(list_recent_orders(limit=500))

        for broker_id in paper_brokers:
            position_state = _paper_lane_position_state(
                context,
                broker_id,
                recent_orders=recent_trade_orders,
            )
            orders_summary = self._as_dict(
                self._as_dict(context.state.get(_orders_state_key_for_broker(broker_id))).get("summary")
            )
            protection_state = self._as_dict(context.state.get(_paper_protection_state_key_for_broker(broker_id)))
            if str(protection_state.get("system_status", "active")).lower() == "protected":
                rejected.extend(self._blocked_proposals(proposals, "daily_drawdown_limit_reached", stage="paper"))
                continue
            slot_policy = _earned_slot_policy(
                context=context,
                broker_id=broker_id,
                account_state_key=_account_state_key_for_broker(broker_id),
                base_max_positions=int(self.config.paper_execution_max_open_positions),
                slot_size_usd=_slot_size_native_for_broker(context, broker_id),
            )
            available_slots = max(
                0,
                int(slot_policy["effective_max_open_positions"])
                - int(position_state.get("open_positions", 0) or 0)
                - int(orders_summary.get("open_orders", 0) or 0),
            )
            if available_slots <= 0:
                rejected.extend(self._blocked_proposals(proposals, "max_open_positions_reached", stage="paper"))
                continue
            position_symbols = set(position_state.get("symbols", set()))
            open_order_symbols = {
                str(symbol).upper()
                for symbol in orders_summary.get("open_order_symbols", [])
                if symbol
            }
            lane_approved = 0
            for proposal in proposals:
                if broker_id == "trading212_paper" and str(proposal.get("asset_class", "")).lower() != "equity":
                    continue
                approval, rejection = _build_paper_trade_approval(
                    context=context,
                    proposal=proposal,
                    tick_id=context.tick_id,
                    config=self.config,
                    market_gate=gate,
                    position_symbols=position_symbols,
                    open_order_symbols=open_order_symbols,
                    broker_id=broker_id,
                )
                if rejection is not None:
                    rejected.append(
                        {
                            **rejection,
                            "stage": "paper",
                        }
                    )
                    continue
                if approval is None:
                    continue
                approved.append(approval)
                lane_approved += 1
                if lane_approved >= min(int(self.config.paper_execution_max_orders_per_tick), available_slots):
                    break
        return self._stage_result(approved=approved, rejected=rejected)

    def _diagnose_live_stage(
        self,
        *,
        context: TickContext,
        proposals: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not proposals:
            return self._stage_result(approved=[], rejected=[])
        gate = self._as_dict(context.state.get("market_gate"))
        protection = self._as_dict(context.state.get("live_daily_protection"))
        live_account_summary = self._as_dict(
            self._as_dict(context.state.get("alpaca_live_account")).get("summary")
        )
        positions_summary = self._as_dict(
            self._as_dict(context.state.get("alpaca_live_positions")).get("summary")
        )
        orders_summary = self._as_dict(
            self._as_dict(context.state.get("alpaca_live_orders")).get("summary")
        )
        if not _live_runtime_allows_broker_reads(context):
            return self._blocked_stage("runtime_mode_not_live", proposals, stage="live")
        if not self.config.live_execution_enabled:
            return self._blocked_stage("live_execution_disabled", proposals, stage="live")
        if self.config.live_execution_kill_switch:
            return self._blocked_stage("live_kill_switch_on", proposals, stage="live")
        if not self.config.alpaca_live_api_configured:
            return self._blocked_stage("alpaca_live_credentials_missing", proposals, stage="live")
        if self.config.live_execution_activation_ack != "LIVE_TRADING_APPROVED":
            return self._blocked_stage("activation_ack_missing", proposals, stage="live")
        if str(protection.get("system_status", "unknown")).lower() != "active":
            return self._blocked_stage(
                str(protection.get("reason", "live_daily_protection_blocked")),
                proposals,
                stage="live",
            )
        if not gate.get("account_trade_ready", False):
            return self._blocked_stage(str(gate.get("reason", "account_not_ready")), proposals, stage="live")
        if not self.config.live_execution_allowed_strategies:
            return self._blocked_stage("no_live_strategies_allowed", proposals, stage="live")

        position_symbols = {
            str(symbol).upper()
            for symbol in positions_summary.get("symbols", [])
            if symbol
        }
        open_order_symbols = {
            str(symbol).upper()
            for symbol in orders_summary.get("open_order_symbols", [])
            if symbol
        }
        open_positions = int(positions_summary.get("open_positions", 0) or 0)
        open_orders = int(orders_summary.get("open_orders", 0) or 0)
        slot_policy = _earned_slot_policy(
            context=context,
            broker_id="alpaca_live",
            account_state_key="alpaca_live_account",
            base_max_positions=int(self.config.live_execution_max_open_positions),
            slot_size_usd=float(self.config.live_execution_default_notional_usd),
        )
        available_slots = max(
            0,
            int(slot_policy["effective_max_open_positions"]) - open_positions - open_orders,
        )
        if available_slots <= 0:
            return self._blocked_stage("max_live_positions_reached", proposals, stage="live")

        approved: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        allowed_strategies = {
            str(strategy_id).lower()
            for strategy_id in self.config.live_execution_allowed_strategies
            if strategy_id
        }
        for proposal in proposals:
            strategy_id = str(proposal.get("strategy_id", "")).lower()
            if strategy_id not in allowed_strategies:
                rejected.append(
                    {
                        "symbol": str(proposal.get("symbol", "")).upper(),
                        "strategy_id": str(proposal.get("strategy_id", "")),
                        "reason": "strategy_not_allowed_live",
                        "stage": "live",
                    }
                )
                continue
            approval, rejection = _build_live_trade_approval(
                context=context,
                proposal=proposal,
                tick_id=context.tick_id,
                config=self.config,
                market_gate=gate,
                position_symbols=position_symbols,
                open_order_symbols=open_order_symbols,
            )
            if rejection is not None:
                rejected.append({**rejection, "stage": "live"})
                continue
            if approval is None:
                continue
            approved.append(approval)
            if len(approved) >= min(int(self.config.live_execution_max_orders_per_tick), available_slots):
                break
        return self._stage_result(approved=approved, rejected=rejected)

    def _stage_result(
        self,
        *,
        approved: list[dict[str, Any]],
        rejected: list[dict[str, Any]],
    ) -> dict[str, Any]:
        counts: Counter[str] = Counter()
        misses: list[dict[str, Any]] = []
        for item in rejected:
            reason = str(item.get("reason", "unknown") or "unknown")
            counts[reason] += 1
            misses.append(
                {
                    "symbol": str(item.get("symbol", "") or "-"),
                    "stage": str(item.get("stage", "risk") or "risk"),
                    "reason": reason,
                    "threshold": "gate",
                    "actual": "blocked",
                    "gap": "n/a",
                    "detail": str(item.get("broker_id", "") or ""),
                    "_sort_gap": 999999.0,
                }
            )
        return {"approved": approved, "rejections": dict(counts), "misses": misses}

    def _blocked_stage(
        self,
        reason: str,
        proposals: list[dict[str, Any]],
        *,
        stage: str,
    ) -> dict[str, Any]:
        return self._stage_result(
            approved=[],
            rejected=self._blocked_proposals(proposals, reason, stage=stage),
        )

    def _blocked_proposals(
        self,
        proposals: list[dict[str, Any]],
        reason: str,
        *,
        stage: str,
    ) -> list[dict[str, Any]]:
        if not proposals:
            return []
        return [
            {
                "symbol": str(proposal.get("symbol", "")).upper(),
                "strategy_id": str(proposal.get("strategy_id", "")),
                "reason": reason,
                "stage": stage,
            }
            for proposal in proposals
        ]

    def _closest_misses(
        self,
        *,
        profile: Any,
        rejection_events: list[dict[str, Any]],
        suppressed_signals: list[dict[str, Any]],
        proposal_misses: list[dict[str, Any]],
        paper_misses: list[dict[str, Any]],
        live_misses: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        misses: list[dict[str, Any]] = []
        for event in rejection_events:
            miss = self._strategy_rejection_to_miss(event)
            if miss is not None:
                misses.append(miss)
        for signal in suppressed_signals or []:
            composite = self._to_float(signal.get("fitness_composite_score"))
            threshold = self._to_float(signal.get("suppress_threshold_used"))
            if composite is None or threshold is None:
                continue
            gap = threshold - composite
            misses.append(
                {
                    "symbol": str(signal.get("symbol", "")).upper(),
                    "stage": "allocation",
                    "reason": "fitness_suppressed",
                    "threshold": f"> {threshold:.3f}",
                    "actual": f"{composite:.3f}",
                    "gap": f"{gap:.3f}",
                    "_sort_gap": gap,
                }
            )
        misses.extend(proposal_misses)
        misses.extend(paper_misses)
        misses.extend(live_misses)
        misses.sort(
            key=lambda item: (
                float(item.get("_sort_gap", 999999.0)),
                str(item.get("stage", "")),
                str(item.get("symbol", "")),
            )
        )
        trimmed: list[dict[str, Any]] = []
        for item in misses[:5]:
            trimmed.append({key: value for key, value in item.items() if not key.startswith("_")})
        return trimmed

    def _strategy_rejection_to_miss(self, event: dict[str, Any]) -> dict[str, Any] | None:
        metrics = self._as_dict(event.get("metrics"))
        reason = str(event.get("reason", "") or "")
        symbol = str(event.get("symbol", "") or "-").upper()
        if reason == "skipped_no_fresh_market_data":
            return None
        if reason == "movement_below_min":
            actual = self._to_float(metrics.get("movement_pct"))
            threshold = self._to_float(metrics.get("min_movement_pct"))
            if actual is None or threshold is None:
                return None
            gap = threshold - actual
            return self._threshold_miss(symbol, "strategy", reason, actual, f">= {threshold:.3f}", gap)
        if reason == "movement_above_max":
            actual = self._to_float(metrics.get("movement_pct"))
            threshold = self._to_float(metrics.get("max_movement_pct"))
            if actual is None or threshold is None:
                return None
            gap = actual - threshold
            return self._threshold_miss(symbol, "strategy", reason, actual, f"<= {threshold:.3f}", gap)
        if reason == "movement_above_snapback_max":
            actual = self._to_float(metrics.get("movement_pct"))
            threshold = self._to_float(metrics.get("max_movement_pct"))
            if actual is None or threshold is None:
                return None
            gap = actual - threshold
            return self._threshold_miss(symbol, "strategy", reason, actual, f"<= {threshold:.3f}", gap)
        if reason == "discovery_below_min":
            actual = self._to_float(metrics.get("discovery_score"))
            threshold = self._to_float(metrics.get("min_discovery_score"))
            if actual is None or threshold is None:
                return None
            gap = threshold - actual
            return self._threshold_miss(symbol, "strategy", reason, actual, f">= {threshold:.3f}", gap)
        if reason == "trade_count_below_min":
            actual = self._to_float(metrics.get("trade_count"))
            threshold = self._to_float(metrics.get("min_trade_count"))
            if actual is None or threshold is None:
                return None
            gap = threshold - actual
            return self._threshold_miss(symbol, "strategy", reason, actual, f">= {threshold:.0f}", gap)
        if reason == "score_below_min":
            actual = self._to_float(metrics.get("signal_score"))
            threshold = self._to_float(metrics.get("min_signal_score"))
            if actual is None or threshold is None:
                return None
            gap = threshold - actual
            return self._threshold_miss(symbol, "strategy", reason, actual, f">= {threshold:.3f}", gap)
        if reason == "volume_ratio_below_min":
            actual = self._to_float(metrics.get("volume_ratio"))
            threshold = self._to_float(metrics.get("volume_surge_multiple") or metrics.get("min_volume_ratio"))
            if actual is None or threshold is None:
                return None
            gap = threshold - actual
            return self._threshold_miss(symbol, "strategy", reason, actual, f"> {threshold:.3f}", gap)
        if reason == "atr_below_floor":
            actual = self._to_float(metrics.get("atr_pct"))
            threshold = self._to_float(metrics.get("atr_floor_pct"))
            if actual is None or threshold is None:
                return None
            gap = threshold - actual
            return self._threshold_miss(symbol, "strategy", reason, actual, f"> {threshold:.3f}", gap)
        if reason == "atr_above_max":
            actual = self._to_float(metrics.get("atr_pct"))
            threshold = self._to_float(metrics.get("max_atr_pct"))
            if actual is None or threshold is None:
                return None
            gap = actual - threshold
            return self._threshold_miss(symbol, "strategy", reason, actual, f"<= {threshold:.3f}", gap)
        if reason == "pullback_below_min":
            actual = self._to_float(metrics.get("pullback_pct"))
            threshold = self._to_float(metrics.get("min_pullback_pct"))
            if actual is None or threshold is None:
                return None
            gap = threshold - actual
            return self._threshold_miss(symbol, "strategy", reason, actual, f">= {threshold:.3f}", gap)
        if reason == "pullback_above_max":
            actual = self._to_float(metrics.get("pullback_pct"))
            threshold = self._to_float(metrics.get("max_pullback_pct"))
            if actual is None or threshold is None:
                return None
            gap = actual - threshold
            return self._threshold_miss(symbol, "strategy", reason, actual, f"<= {threshold:.3f}", gap)
        if reason == "volume_gbp_below_min":
            actual = self._to_float(metrics.get("volume_gbp"))
            threshold = self._to_float(metrics.get("min_volume_gbp"))
            if actual is None or threshold is None:
                return None
            gap = threshold - actual
            return self._threshold_miss(symbol, "strategy", reason, actual, f">= {threshold:.2f}", gap)
        if reason == "spread_above_max":
            actual = self._to_float(metrics.get("spread_pct"))
            threshold = self._to_float(metrics.get("max_spread_pct"))
            if actual is None or threshold is None:
                return None
            gap = actual - threshold
            return self._threshold_miss(symbol, "strategy", reason, actual, f"<= {threshold:.3f}", gap)
        return None

    def _threshold_miss(
        self,
        symbol: str,
        stage: str,
        reason: str,
        actual: float,
        threshold: str,
        gap: float,
    ) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "stage": stage,
            "reason": reason,
            "threshold": threshold,
            "actual": f"{actual:.3f}",
            "gap": f"{gap:.3f}",
            "_sort_gap": gap,
        }

    def _build_summary(
        self,
        *,
        strategies: list[dict[str, Any]],
        candidate_count: int,
        universe: dict[str, Any],
        queue_diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        if not strategies:
            return {
                "primary_issue": "allowlist mismatch",
                "explanation": "No execution-allowed strategies were found in the current config.",
                "notes": [],
            }

        total_data = sum(int(item.get("enough_data", 0) or 0) for item in strategies)
        total_raw = sum(int(item.get("raw_signals", 0) or 0) for item in strategies)
        total_proposals = sum(int(item.get("final_proposals", 0) or 0) for item in strategies)
        total_approvals = sum(
            int(item.get("paper_approved", 0) or 0) + int(item.get("live_approved", 0) or 0)
            for item in strategies
        )
        discovered_candidates = int(
            universe.get("total_candidates_discovered", universe.get("total_candidates", 0)) or 0
        )
        notes: list[str] = []
        if any(not bool(item.get("registered")) for item in strategies):
            primary = "allowlist mismatch"
            explanation = "At least one strategy in the execution allowlists is not registered in the strategy registry."
        elif discovered_candidates <= 0 or candidate_count <= 0 or total_data <= 0:
            primary = "no market data"
            explanation = "The latest persisted tick did not leave enough enriched candidate data for the allowed strategies to evaluate."
        elif int(universe.get("queue_saturated", 0) or 0):
            primary = "market conditions"
            explanation = "The fast path is rank-selecting candidates, and the advisory slow queue is currently saturated, so deferred coverage is not guaranteed."
        elif total_raw <= 0:
            primary = "strategy never firing"
            explanation = "The strategies had candidate data, but none of the currently allowlisted profiles produced a raw signal."
        elif total_proposals <= 0:
            primary = "filters too strict"
            explanation = "Raw signals existed, but allocation or proposal-stage filters removed them before any shadow proposal survived."
        elif total_approvals <= 0:
            primary = "proposal builder issue"
            explanation = "Shadow proposals survived, but downstream paper/live risk gates blocked all of them before approval."
        else:
            primary = "market conditions"
            explanation = "The pipeline is functioning end to end; remaining quiet periods look more like current market shape than a broken stage."

        for item in strategies:
            strategy_id = str(item.get("strategy_id", "") or "")
            if not item.get("registered"):
                notes.append(f"{strategy_id}: present in allowlist but missing from registry.")
                continue
            if int(item.get("raw_signals", 0) or 0) <= 0:
                notes.append(f"{strategy_id}: never reached a raw signal on the latest snapshot.")
            elif int(item.get("final_proposals", 0) or 0) <= 0:
                notes.append(f"{strategy_id}: raw signals existed, but proposal-stage filters still reduced output to zero.")
            elif int(item.get("paper_approved", 0) or 0) <= 0 and int(item.get("live_approved", 0) or 0) <= 0:
                notes.append(f"{strategy_id}: shadow proposals existed, but risk/execution gates blocked approvals.")
        if int(universe.get("queue_saturated", 0) or 0):
            notes.append("Slow enrichment queue is at or near its pending cap, so leftovers may not be enqueued for later advisory processing.")
        if int(queue_diagnostics.get("expired_pending_count", 0) or 0) > 0:
            notes.append("Some pending slow-enrichment rows are already expired but still present, which can starve new deferred candidates.")
        return {
            "primary_issue": primary,
            "explanation": explanation,
            "notes": notes[:6],
        }

    def _candidate_list(
        self,
        snapshot: dict[str, Any],
        *,
        eligible_candidates: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        if eligible_candidates is not None:
            return [self._as_dict(item) for item in eligible_candidates if isinstance(item, dict)]
        enrichment = self._as_dict(snapshot.get("context_enrichment"))
        candidates = enrichment.get("candidates", [])
        if isinstance(candidates, list) and candidates:
            return [self._as_dict(item) for item in candidates if isinstance(item, dict)]
        market_scan = self._as_dict(snapshot.get("market_scan"))
        fallback = market_scan.get("selected_candidates", [])
        if isinstance(fallback, list):
            return [self._as_dict(item) for item in fallback if isinstance(item, dict)]
        return []

    def _strategy_eligible_candidates(self, *, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        market_scan = self._as_dict(snapshot.get("market_scan"))
        ranked = [
            self._as_dict(item)
            for item in market_scan.get("ranked_candidates", []) or []
            if isinstance(item, dict)
        ]
        if not ranked:
            return []
        return [item for item in ranked if self._candidate_is_strategy_eligible(item)]

    def _strategy_selected_candidates(self, *, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        market_scan = self._as_dict(snapshot.get("market_scan"))
        selected = [
            self._as_dict(item)
            for item in market_scan.get("selected_candidates", []) or []
            if isinstance(item, dict)
        ]
        return [item for item in selected if self._candidate_is_strategy_eligible(item)]

    def _candidate_is_strategy_eligible(self, candidate: dict[str, Any]) -> bool:
        status = self._candidate_effective_market_data_status(candidate)
        if status in {"account_only", "stale", "missing_bar_timestamp"}:
            return False
        if "market_data_eligible" in candidate:
            return bool(candidate.get("market_data_eligible"))
        return True

    def _candidate_effective_market_data_status(self, candidate: dict[str, Any]) -> str:
        source = str(candidate.get("source", "")).strip()
        status = str(candidate.get("market_data_status", "") or "").strip().lower()
        if status:
            return status
        if source == "trading212_market_data":
            provider = (
                str(getattr(self.config, "trading212_paper_market_data_provider", "disabled") or "disabled")
                .strip()
                .lower()
            )
            if provider in {"positions_api", "trading212_positions"}:
                return "account_only"
        return status

    def _universe_overview(self, *, snapshot: dict[str, Any]) -> dict[str, Any]:
        market_scan = self._as_dict(snapshot.get("market_scan"))
        context_enrichment = self._as_dict(snapshot.get("context_enrichment"))
        slow_queue = self._as_dict(snapshot.get("slow_enrichment_queue"))
        discovered_candidates = [
            self._as_dict(item)
            for item in market_scan.get("discovered_candidates", []) or []
            if isinstance(item, dict)
        ]
        raw_ranked_candidates = [
            self._as_dict(item)
            for item in market_scan.get("ranked_candidates", []) or []
            if isinstance(item, dict)
        ]
        selected_candidates = [
            self._as_dict(item)
            for item in market_scan.get("selected_candidates", []) or []
            if isinstance(item, dict) and self._candidate_is_strategy_eligible(self._as_dict(item))
        ]
        ranked_candidates = [
            item for item in raw_ranked_candidates if self._candidate_is_strategy_eligible(item)
        ]
        enriched_candidates = [
            self._as_dict(item)
            for item in context_enrichment.get("candidates", []) or []
            if isinstance(item, dict)
        ]
        pending_after = int(slow_queue.get("pending_after_estimate", 0) or 0)
        max_pending = int(slow_queue.get("max_pending_items", 0) or 0)
        selected_for_fast = len(selected_candidates)
        deferred_candidates = max(0, len(ranked_candidates) - selected_for_fast)
        skipped_enqueue_reasons = {
            reason: int(count or 0)
            for reason, count in self._as_dict(slow_queue.get("skipped_reasons")).items()
            if int(count or 0) > 0
        }
        market_data_diagnostics = self._market_data_diagnostics(ranked_candidates=ranked_candidates)
        queue_note = ""
        if max_pending > 0 and pending_after >= max_pending:
            queue_note = (
                "advisory slow queue is at its pending cap; new leftovers may not be enqueued "
                "until old pending rows clear"
            )
        if not slow_queue:
            queue_note = "latest tick snapshot did not persist slow-enrichment queue step output"
        elif not context_enrichment:
            queue_note = "latest tick snapshot has no fast context-enrichment payload; fast selection and actual enrichments are different concepts here"
        total_discovered = len(discovered_candidates) if discovered_candidates else len(raw_ranked_candidates)
        fallback_ineligible = sum(
            1 for item in raw_ranked_candidates if not self._candidate_is_strategy_eligible(item)
        )
        stale_or_account_only = sum(
            1 for item in discovered_candidates if not bool(item.get("market_data_eligible", True))
        )
        return {
            "total_candidates_discovered": total_discovered,
            "discovered_candidates": total_discovered,
            "stale_or_account_only_candidates": (
                stale_or_account_only
                if discovered_candidates
                else fallback_ineligible
            ),
            "eligible_for_strategy_evaluation": len(ranked_candidates),
            "selected_for_fast_strategy_evaluation": selected_for_fast,
            "newly_enriched_this_tick": len(enriched_candidates),
            "actual_new_enrichments": len(enriched_candidates),
            "already_enriched_but_reused_candidates": int(context_enrichment.get("reused_candidates", 0) or 0),
            "deferred_candidates_not_in_fast_batch": deferred_candidates,
            "actually_enqueued_slow_jobs": int(slow_queue.get("enqueued", 0) or 0),
            "queue_rows_reused_by_work_key": int(slow_queue.get("refreshed", 0) or 0),
            "skipped_enqueue_reasons": skipped_enqueue_reasons,
            "candidates_with_price_history": sum(
                1 for item in ranked_candidates if item.get("previous_close_price") not in (None, "")
            ),
            "candidates_with_technical_context_ready": sum(
                1 for item in enriched_candidates if bool(item.get("technical_context_ready"))
            ),
            "selection_policy": "score_based_rank_desc_by_discovery_score_then_movement_liquidity",
            "queue_saturated": 1 if max_pending > 0 and pending_after >= max_pending else 0,
            "queue_state_note": queue_note,
            "source_freshness_status": self._as_dict(market_scan.get("result", {}).get("source_freshness_status")),
            "stale_sources_excluded": list(market_scan.get("result", {}).get("stale_sources_excluded", []) or []),
            "candidates_excluded_due_to_stale_source": int(
                max(
                    int(market_scan.get("result", {}).get("candidates_excluded_due_to_stale_source", 0) or 0),
                    fallback_ineligible,
                )
            ),
            "candidates_excluded_due_to_account_only_source": int(
                max(
                    int(
                        market_scan.get("result", {}).get(
                            "candidates_excluded_due_to_account_only_source",
                            0,
                        )
                        or 0
                    ),
                    sum(
                        1
                        for item in raw_ranked_candidates
                        if self._candidate_effective_market_data_status(item) == "account_only"
                    ),
                )
            ),
            "market_data_source_used_for_strategy": self._as_dict(
                market_scan.get("result", {}).get("market_data_source_used_for_strategy")
            ),
            "account_data_source_used_for_positions": self._as_dict(
                market_scan.get("result", {}).get("account_data_source_used_for_positions")
            ),
            **market_data_diagnostics,
        }

    def _asset_class_coverage(self, *, snapshot: dict[str, Any]) -> dict[str, Any]:
        market_scan = self._as_dict(snapshot.get("market_scan"))
        discovered = [
            self._as_dict(item)
            for item in market_scan.get("discovered_candidates", []) or []
            if isinstance(item, dict)
        ]
        ranked = [
            self._as_dict(item)
            for item in market_scan.get("ranked_candidates", []) or []
            if isinstance(item, dict) and self._candidate_is_strategy_eligible(self._as_dict(item))
        ]
        universe = discovered or ranked
        total_equity = sum(1 for item in universe if str(item.get("asset_class", "")).lower() == "equity")
        total_crypto = sum(1 for item in universe if str(item.get("asset_class", "")).lower() == "crypto")
        selected_equity = sum(
            1 for item in ranked
            if bool(item.get("selected")) and str(item.get("asset_class", "")).lower() == "equity"
        )
        selected_crypto = sum(
            1 for item in ranked
            if bool(item.get("selected")) and str(item.get("asset_class", "")).lower() == "crypto"
        )
        note = ""
        if selected_crypto > 0 and selected_equity == 0 and total_equity > 0:
            note = "current fast batch is all crypto because the top-ranked selected set contains no equities"
        return {
            "total_equity_candidates": total_equity,
            "total_crypto_candidates": total_crypto,
            "selected_equity_candidates": selected_equity,
            "selected_crypto_candidates": selected_crypto,
            "queued_equity_candidates": max(0, total_equity - selected_equity),
            "queued_crypto_candidates": max(0, total_crypto - selected_crypto),
            "selection_note": note,
        }

    def _strategy_coverage(
        self,
        *,
        snapshot: dict[str, Any],
        strategy_ids: list[str],
        registry_profiles: dict[str, tuple[Any, Any]],
    ) -> list[dict[str, Any]]:
        ranked = [
            self._as_dict(item)
            for item in self._as_dict(snapshot.get("market_scan")).get("ranked_candidates", []) or []
            if isinstance(item, dict) and self._candidate_is_strategy_eligible(self._as_dict(item))
        ]
        rows: list[dict[str, Any]] = []
        for strategy_id in strategy_ids:
            entry = registry_profiles.get(strategy_id)
            if entry is None:
                rows.append(
                    {
                        "strategy_id": strategy_id,
                        "required_asset_class": "unknown",
                        "available_matching_candidates": 0,
                        "selected_matching_candidates": 0,
                        "skipped_because_no_selected_candidates": True,
                    }
                )
                continue
            _strategy, profile = entry
            available = [
                item for item in ranked
                if str(item.get("asset_class", "")).lower() in profile.asset_classes
            ]
            selected = [item for item in available if bool(item.get("selected"))]
            rows.append(
                {
                    "strategy_id": strategy_id,
                    "required_asset_class": ",".join(profile.asset_classes),
                    "available_matching_candidates": len(available),
                    "selected_matching_candidates": len(selected),
                    "skipped_because_no_selected_candidates": len(selected) == 0,
                }
            )
        return rows

    def _queue_diagnostics(self) -> dict[str, Any]:
        pending_cap = int(
            getattr(self.config, "slow_enrichment_queue_max_pending_items", 500)
        )
        now = datetime.now().astimezone()
        pending = 0
        processing = 0
        oldest_pending_at: datetime | None = None
        expired_pending = 0
        failed = 0
        processed_last_hour = 0
        processed_last_24h = 0
        last_processed_at: datetime | None = None

        if self.usage_ledger.backend == "postgres" and hasattr(self.usage_ledger, "_connect_postgres"):
            with self.usage_ledger._connect_postgres() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT
                            COUNT(*) FILTER (WHERE status = 'pending') AS pending_count,
                            COUNT(*) FILTER (WHERE status = 'processing') AS processing_count,
                            MIN(queued_at) FILTER (WHERE status = 'pending') AS oldest_pending_at,
                            COUNT(*) FILTER (
                                WHERE status = 'pending'
                                  AND expires_at IS NOT NULL
                                  AND expires_at <= NOW()
                            ) AS expired_pending_count,
                            COUNT(*) FILTER (WHERE status = 'failed') AS failed_count
                        FROM slow_enrichment_jobs
                        """
                    )
                    row = cursor.fetchone()
                    if row:
                        pending = int(row[0] or 0)
                        processing = int(row[1] or 0)
                        oldest_pending_at = row[2]
                        expired_pending = int(row[3] or 0)
                        failed = int(row[4] or 0)
                    cursor.execute(
                        """
                        SELECT
                            COUNT(*) FILTER (WHERE processed_at >= NOW() - INTERVAL '1 hour') AS processed_last_hour,
                            COUNT(*) FILTER (WHERE processed_at >= NOW() - INTERVAL '24 hours') AS processed_last_24h,
                            MAX(processed_at) AS last_processed_at
                        FROM slow_enrichment_results
                        """
                    )
                    processed_row = cursor.fetchone()
                    if processed_row:
                        processed_last_hour = int(processed_row[0] or 0)
                        processed_last_24h = int(processed_row[1] or 0)
                        last_processed_at = processed_row[2]
        elif hasattr(self.usage_ledger, "_connect_sqlite"):
            with self.usage_ledger._connect_sqlite() as connection:
                row = connection.execute(
                    """
                    SELECT
                        SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_count,
                        SUM(CASE WHEN status = 'processing' THEN 1 ELSE 0 END) AS processing_count,
                        MIN(CASE WHEN status = 'pending' THEN queued_at END) AS oldest_pending_at,
                        SUM(
                            CASE
                                WHEN status = 'pending'
                                 AND expires_at IS NOT NULL
                                 AND datetime(expires_at) <= datetime(?)
                                THEN 1 ELSE 0
                            END
                        ) AS expired_pending_count,
                        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_count
                    FROM slow_enrichment_jobs
                    """,
                    (now.isoformat(),),
                ).fetchone()
                if row:
                    pending = int(row[0] or 0)
                    processing = int(row[1] or 0)
                    oldest_pending_at = self._as_datetime(row[2])
                    expired_pending = int(row[3] or 0)
                    failed = int(row[4] or 0)
                processed_row = connection.execute(
                    """
                    SELECT
                        SUM(CASE WHEN processed_at >= ? THEN 1 ELSE 0 END) AS processed_last_hour,
                        SUM(CASE WHEN processed_at >= ? THEN 1 ELSE 0 END) AS processed_last_24h,
                        MAX(processed_at) AS last_processed_at
                    FROM slow_enrichment_results
                    """,
                    (
                        (now - timedelta(hours=1)).isoformat(),
                        (now - timedelta(hours=24)).isoformat(),
                    ),
                ).fetchone()
                if processed_row:
                    processed_last_hour = int(processed_row[0] or 0)
                    processed_last_24h = int(processed_row[1] or 0)
                    last_processed_at = self._as_datetime(processed_row[2])

        oldest_age = "-"
        if oldest_pending_at is not None:
            oldest_age = self._format_age(now - oldest_pending_at)
        queue_is_draining = processed_last_hour > 0 or processing > 0
        can_get_stuck = pending >= pending_cap and not queue_is_draining
        terminal_count = failed + expired_pending
        note = ""
        if expired_pending > 0:
            note = (
                "expired pending rows are present and should be repairable; they should no longer count toward enqueue capacity"
            )
        elif pending >= pending_cap:
            note = "slow queue is at its configured cap, so newly deferred candidates may not be enqueued"
        elif terminal_count > 0 and pending == 0:
            note = "terminal slow-queue rows exist historically, but there are no active pending rows to process right now"
        queue_health = "pass"
        if can_get_stuck or expired_pending > 0:
            queue_health = "fail"
        elif pending >= pending_cap or failed > 0 or terminal_count > 0:
            queue_health = "warn"
        return {
            "current_pending_count": pending,
            "current_processing_count": processing,
            "pending_cap": pending_cap,
            "oldest_pending_item_age": oldest_age,
            "expired_pending_count": expired_pending,
            "failed_count": failed,
            "terminal_count": terminal_count,
            "processed_last_hour": processed_last_hour,
            "processed_last_24h": processed_last_24h,
            "last_processed_at": (
                last_processed_at.isoformat()
                if hasattr(last_processed_at, "isoformat")
                else str(last_processed_at or "-")
            ),
            "queue_health": queue_health,
            "pending_rows_are_being_processed": processing > 0,
            "queue_is_draining_over_time": queue_is_draining,
            "candidates_can_get_stuck_permanently": can_get_stuck,
            "note": note,
        }

    def _candidate_diagnostics(self, *, snapshot: dict[str, Any]) -> list[dict[str, Any]]:
        market_scan = self._as_dict(snapshot.get("market_scan"))
        context_enrichment = self._as_dict(snapshot.get("context_enrichment"))
        discovered_candidates = [
            self._as_dict(item)
            for item in market_scan.get("discovered_candidates", []) or []
            if isinstance(item, dict)
        ]
        ranked_candidates = [
            self._as_dict(item)
            for item in market_scan.get("ranked_candidates", []) or []
            if isinstance(item, dict)
        ]
        excluded_by_key = {
            (
                str(item.get("source", "")).strip(),
                str(item.get("symbol", "")).strip().upper(),
            ): self._as_dict(item)
            for item in market_scan.get("excluded_candidates", []) or []
            if isinstance(item, dict)
        }
        previous_by_key = self._previous_bars_for_candidates(ranked_candidates)
        enriched_by_key = {
            (
                str(item.get("source", "")).strip(),
                str(item.get("symbol", "")).strip().upper(),
            ): self._as_dict(item)
            for item in context_enrichment.get("candidates", []) or []
            if isinstance(item, dict)
        }
        last_enriched = self._latest_slow_enrichment_by_symbol()
        history_by_key = self._market_data_history_by_symbol(ranked_candidates)
        eligible_keys_in_order: list[tuple[str, str]] = []
        strategy_batch_by_key: dict[tuple[str, str], int] = {}
        for candidate in discovered_candidates or ranked_candidates:
            source = str(candidate.get("source", "")).strip()
            symbol = str(candidate.get("symbol", "")).strip().upper()
            key = (source, symbol)
            if self._candidate_is_strategy_eligible(candidate):
                eligible_keys_in_order.append(key)
                if bool(candidate.get("selected")):
                    strategy_batch_by_key[key] = len(strategy_batch_by_key) + 1
        eligible_rank_by_key = {
            key: index for index, key in enumerate(eligible_keys_in_order, start=1)
        }
        selected_eligible_count = len(strategy_batch_by_key)
        details: list[dict[str, Any]] = []
        for candidate in discovered_candidates or ranked_candidates:
            eligible_for_strategy = self._candidate_is_strategy_eligible(candidate)
            source = str(candidate.get("source", "")).strip()
            symbol = str(candidate.get("symbol", "")).strip().upper()
            key = (source, symbol)
            enriched = enriched_by_key.get(key, {})
            previous = previous_by_key.get(key, {})
            history = history_by_key.get(key, {})
            rank = int(candidate.get("rank", 0) or 0)
            selected = bool(candidate.get("selected")) and eligible_for_strategy
            eligible_rank = eligible_rank_by_key.get(key, "-")
            strategy_batch_index = strategy_batch_by_key.get(key, "-") if selected else "-"
            queue_position: int | str = "-"
            if eligible_for_strategy and not selected and isinstance(eligible_rank, int):
                queue_position = max(eligible_rank - selected_eligible_count, 1)
            exclusion_reason = "-"
            if not eligible_for_strategy:
                exclusion_reason = str(
                    candidate.get("market_data_rejection_reason")
                    or excluded_by_key.get(key, {}).get("market_data_rejection_reason")
                    or self._candidate_effective_market_data_status(candidate)
                    or "ineligible_for_strategy_evaluation"
                )
            details.append(
                {
                    "symbol": symbol,
                    "source": source,
                    "discovery_rank": rank,
                    "eligible_rank": eligible_rank,
                    "selected": selected,
                    "strategy_batch_index": strategy_batch_index,
                    "queue_position": queue_position,
                    "exclusion_reason": exclusion_reason,
                    "movement_pct": self._fmt_num(candidate.get("movement_pct"), 6),
                    "market_data_status": self._candidate_effective_market_data_status(candidate) or "-",
                    "eligible_for_strategy_evaluation": ("yes" if eligible_for_strategy else "no"),
                    "current_bar_timestamp": self._fmt_optional_dt(candidate.get("bar_timestamp")),
                    "previous_bar_timestamp": self._fmt_optional_dt(previous.get("bar_timestamp")),
                    "previous_close_price": self._fmt_num(candidate.get("previous_close_price"), 6),
                    "close_price": self._fmt_num(candidate.get("close_price"), 6),
                    "number_of_bars_available": int(history.get("total_rows", 0) or 0),
                    "newest_bar_age": history.get("newest_bar_age", "-"),
                    "technical_context_ready": (
                        "yes" if bool(enriched.get("technical_context_ready")) else "no"
                        if key in enriched_by_key else "-"
                    ),
                    "last_enriched_at": last_enriched.get(key, "-"),
                    "market_data_rejection_reason": str(
                        excluded_by_key.get(key, {}).get("market_data_rejection_reason", "") or "-"
                    ),
                }
            )
        return details

    def _latest_slow_enrichment_by_symbol(self) -> dict[tuple[str, str], str]:
        rows: dict[tuple[str, str], str] = {}
        if not hasattr(self.usage_ledger, "backend"):
            return rows
        if self.usage_ledger.backend == "postgres":
            if not hasattr(self.usage_ledger, "_connect_postgres"):
                return rows
            with self.usage_ledger._connect_postgres() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT source, symbol, MAX(processed_at) AS processed_at
                        FROM slow_enrichment_results
                        GROUP BY source, symbol
                        """
                    )
                    for source, symbol, processed_at in cursor.fetchall():
                        rows[(str(source or "").strip(), str(symbol or "").strip().upper())] = (
                            processed_at.isoformat() if hasattr(processed_at, "isoformat") else str(processed_at)
                        )
            return rows

        if not hasattr(self.usage_ledger, "_connect_sqlite"):
            return rows
        with self.usage_ledger._connect_sqlite() as connection:
            result = connection.execute(
                """
                SELECT source, symbol, MAX(processed_at) AS processed_at
                FROM slow_enrichment_results
                GROUP BY source, symbol
                """
            ).fetchall()
        for source, symbol, processed_at in result:
            rows[(str(source or "").strip(), str(symbol or "").strip().upper())] = str(processed_at or "-")
        return rows

    def _previous_bars_for_candidates(
        self,
        candidates: list[dict[str, Any]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        get_previous_bars = getattr(self.usage_ledger, "get_previous_bars", None)
        if not callable(get_previous_bars):
            return {}
        symbol_keys = [
            (str(item.get("source", "")).strip(), str(item.get("symbol", "")).strip().upper())
            for item in candidates
            if str(item.get("source", "")).strip() and str(item.get("symbol", "")).strip()
        ]
        latest_tick = self.usage_ledger.get_latest_tick_run()
        tick_id = str(latest_tick.get("tick_id", "") or "") if isinstance(latest_tick, dict) else ""
        return get_previous_bars(
            tick_id=tick_id,
            symbol_keys=symbol_keys,
            current_rows=candidates,
        )

    def _market_data_history_by_symbol(
        self,
        candidates: list[dict[str, Any]],
    ) -> dict[tuple[str, str], dict[str, Any]]:
        result: dict[tuple[str, str], dict[str, Any]] = {}
        if not candidates:
            return result
        if self.usage_ledger.backend == "postgres" and hasattr(self.usage_ledger, "_connect_postgres"):
            with self.usage_ledger._connect_postgres() as connection:
                with connection.cursor() as cursor:
                    for candidate in candidates:
                        source = str(candidate.get("source", "")).strip()
                        symbol = str(candidate.get("symbol", "")).strip().upper()
                        if not source or not symbol:
                            continue
                        cursor.execute(
                            """
                            SELECT
                                COUNT(*) AS total_rows,
                                COUNT(DISTINCT COALESCE(bar_timestamp, captured_at)) AS distinct_bars,
                                MAX(COALESCE(bar_timestamp, captured_at)) AS newest_point_at
                            FROM market_data_latest_bars
                            WHERE source = %s AND symbol = %s
                            """,
                            (source, symbol),
                        )
                        row = cursor.fetchone()
                        newest_point = row[2] if row else None
                        result[(source, symbol)] = {
                            "total_rows": int(row[0] or 0) if row else 0,
                            "distinct_bars": int(row[1] or 0) if row else 0,
                            "newest_bar_age": self._format_age(datetime.now().astimezone() - newest_point)
                            if newest_point is not None
                            else "-",
                        }
        elif hasattr(self.usage_ledger, "_connect_sqlite"):
            with self.usage_ledger._connect_sqlite() as connection:
                for candidate in candidates:
                    source = str(candidate.get("source", "")).strip()
                    symbol = str(candidate.get("symbol", "")).strip().upper()
                    if not source or not symbol:
                        continue
                    row = connection.execute(
                        """
                        SELECT
                            COUNT(*) AS total_rows,
                            COUNT(DISTINCT COALESCE(bar_timestamp, captured_at)) AS distinct_bars,
                            MAX(COALESCE(bar_timestamp, captured_at)) AS newest_point_at
                        FROM market_data_latest_bars
                        WHERE source = ? AND symbol = ?
                        """,
                        (source, symbol),
                    ).fetchone()
                    newest_point = self._as_datetime(row[2]) if row else None
                    result[(source, symbol)] = {
                        "total_rows": int(row[0] or 0) if row else 0,
                        "distinct_bars": int(row[1] or 0) if row else 0,
                        "newest_bar_age": self._format_age(datetime.now().astimezone() - newest_point)
                        if newest_point is not None
                        else "-",
                    }
        return result

    def _proposal_data_integrity(
        self,
        *,
        snapshot: dict[str, Any],
        candidate_details: list[dict[str, Any]],
        strategies: list[dict[str, Any]],
        queue_diagnostics: dict[str, Any],
    ) -> dict[str, Any]:
        stale_or_account_only_selected: list[str] = []
        stale_or_account_only_with_strategy_batch_index = [
            f"{str(item.get('source', '')).strip()}:{str(item.get('symbol', '')).strip().upper()}"
            for item in candidate_details
            if str(item.get("eligible_for_strategy_evaluation", "yes")).strip().lower() == "no"
            and item.get("strategy_batch_index", "-") != "-"
        ]
        stale_or_account_only_in_strategy_misses = [
            f"{str(item.get('source', '')).strip()}:{str(item.get('symbol', '')).strip().upper()}"
            for item in candidate_details
            if str(item.get("eligible_for_strategy_evaluation", "yes")).strip().lower() == "no"
            and bool(item.get("selected"))
        ]
        excluded_symbols = {
            str(item.get("symbol", "")).strip().upper()
            for item in candidate_details
            if str(item.get("eligible_for_strategy_evaluation", "yes")).strip().lower() == "no"
        }
        stale_or_account_only_in_symbols_scanned: list[str] = []
        stale_or_account_only_in_closest_misses: list[str] = []
        stale_or_account_only_in_eligible_rank: list[str] = []
        for item in candidate_details:
            detail = self._as_dict(item)
            candidate_key = (
                f"{str(detail.get('source', '')).strip()}:"
                f"{str(detail.get('symbol', '')).strip().upper()}"
            )
            if str(detail.get("eligible_for_strategy_evaluation", "yes")).strip().lower() != "no":
                continue
            if bool(detail.get("selected")):
                stale_or_account_only_selected.append(candidate_key)
            if detail.get("eligible_rank", "-") != "-":
                stale_or_account_only_in_eligible_rank.append(candidate_key)

        for strategy in strategies:
            strategy_item = self._as_dict(strategy)
            scanned_symbols = [
                str(symbol).strip().upper()
                for symbol in strategy_item.get("scanned_symbols", []) or []
                if str(symbol).strip()
            ]
            stale_or_account_only_in_symbols_scanned.extend(
                symbol for symbol in scanned_symbols if symbol in excluded_symbols
            )
            for miss in strategy_item.get("closest_misses", []) or []:
                miss_item = self._as_dict(miss)
                miss_symbol = str(miss_item.get("symbol", "")).strip().upper()
                if miss_symbol and miss_symbol in excluded_symbols:
                    stale_or_account_only_in_closest_misses.append(miss_symbol)

        failure_reasons: list[str] = []
        if stale_or_account_only_selected:
            failure_reasons.append("stale_or_account_only_selected")
        if stale_or_account_only_in_eligible_rank:
            failure_reasons.append("stale_or_account_only_with_eligible_rank")
        if stale_or_account_only_with_strategy_batch_index:
            failure_reasons.append("stale_or_account_only_with_strategy_batch_index")
        if stale_or_account_only_in_strategy_misses:
            failure_reasons.append("stale_or_account_only_selected_in_candidate_batch")
        if stale_or_account_only_in_symbols_scanned:
            failure_reasons.append("stale_or_account_only_in_symbols_scanned")
        if stale_or_account_only_in_closest_misses:
            failure_reasons.append("stale_or_account_only_in_closest_misses")

        violations = self._ordered_unique(
            stale_or_account_only_selected
            + stale_or_account_only_in_eligible_rank
            + stale_or_account_only_with_strategy_batch_index
            + stale_or_account_only_in_strategy_misses
            + stale_or_account_only_in_symbols_scanned
            + stale_or_account_only_in_closest_misses
        )
        return {
            "status": "fail" if violations else "pass",
            "failure_reasons": failure_reasons,
            "stale_or_account_only_selected_count": len(stale_or_account_only_selected),
            "stale_or_account_only_with_strategy_batch_index_count": len(
                stale_or_account_only_with_strategy_batch_index
            ),
            "stale_or_account_only_in_strategy_misses_count": len(
                stale_or_account_only_in_closest_misses
            ),
            "stale_or_account_only_in_symbols_scanned_count": len(
                stale_or_account_only_in_symbols_scanned
            ),
            "queue_health_affects_proposal_data_integrity": False,
            "queue_health": queue_diagnostics.get("queue_health", "-"),
            "violations": violations,
        }

    def _market_data_diagnostics(
        self,
        *,
        ranked_candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        previous_by_key = self._previous_bars_for_candidates(ranked_candidates)
        history_by_key = self._market_data_history_by_symbol(ranked_candidates)
        latest_market_data_at: datetime | None = None
        newest_bar_age_by_source: dict[str, str] = {}
        bars_available_by_source: dict[str, int] = defaultdict(int)
        source_latest_point: dict[str, datetime] = {}
        symbols_with_only_one_distinct_bar = 0
        symbols_where_previous_close_equals_close = 0
        for candidate in ranked_candidates:
            source = str(candidate.get("source", "")).strip()
            symbol = str(candidate.get("symbol", "")).strip().upper()
            key = (source, symbol)
            history = history_by_key.get(key, {})
            previous = previous_by_key.get(key, {})
            bars_available_by_source[source] = bars_available_by_source.get(source, 0) + 1
            if int(history.get("distinct_bars", 0) or 0) <= 1:
                symbols_with_only_one_distinct_bar += 1
            previous_close = self._to_float(previous.get("close_price"))
            current_close = self._to_float(candidate.get("close_price"))
            if previous_close is not None and current_close is not None and previous_close == current_close:
                symbols_where_previous_close_equals_close += 1
            newest_point = self._as_datetime(
                candidate.get("bar_timestamp")
                or previous.get("bar_timestamp")
            )
            if newest_point is not None:
                if latest_market_data_at is None or newest_point > latest_market_data_at:
                    latest_market_data_at = newest_point
                existing = source_latest_point.get(source)
                if existing is None or newest_point > existing:
                    source_latest_point[source] = newest_point
        now = datetime.now().astimezone()
        for source, point in source_latest_point.items():
            newest_bar_age_by_source[source] = self._format_age(now - point)
        stale_source_warning = any(
            self._source_looks_stale(source=source, latest_point=point, now=now)
            for source, point in source_latest_point.items()
        ) or symbols_with_only_one_distinct_bar > 0
        return {
            "latest_market_data_at": latest_market_data_at.isoformat() if latest_market_data_at else "-",
            "newest_bar_age_by_source": dict(newest_bar_age_by_source),
            "bars_available_by_source": dict(bars_available_by_source),
            "symbols_with_only_one_distinct_bar": symbols_with_only_one_distinct_bar,
            "symbols_where_previous_close_equals_close": symbols_where_previous_close_equals_close,
            "stale_source_warning": stale_source_warning,
        }

    def _source_looks_stale(
        self,
        *,
        source: str,
        latest_point: datetime,
        now: datetime,
    ) -> bool:
        age_minutes = (now - latest_point).total_seconds() / 60.0
        if source == "alpaca_crypto_data":
            return age_minutes > 10.0
        if source == "alpaca_market_data":
            return age_minutes > 180.0
        if source == "trading212_market_data":
            return age_minutes > 180.0
        return age_minutes > 60.0

    def _ordered_unique(self, values: list[str]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = str(value or "").strip()
            if not normalized or normalized in seen:
                continue
            seen.add(normalized)
            ordered.append(normalized)
        return ordered

    def _as_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _as_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

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

    def _fmt_num(self, value: Any, decimals: int) -> str:
        number = self._to_float(value)
        if number is None:
            return "-"
        return f"{number:.{decimals}f}"

    def _fmt_optional_dt(self, value: Any) -> str:
        parsed = self._as_datetime(value)
        if parsed is None:
            return "-"
        return parsed.isoformat()

    def _format_age(self, value: timedelta) -> str:
        total_seconds = max(0, int(value.total_seconds()))
        hours, remainder = divmod(total_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        if minutes > 0:
            return f"{minutes}m {seconds}s"
        return f"{seconds}s"
