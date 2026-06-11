from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from statistics import mean
import sys
from time import monotonic
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger

ALLOWED_REAL_SOURCES = {"real_heartbeat"}
ALLOWED_REAL_ORIGINS = {"launchd_scheduled", "real_heartbeat", "forced_one_shot"}
VALID_FINAL_STATUSES = {
    "improving",
    "degrading",
    "flat_collecting_evidence",
    "stuck",
    "insufficient_history",
}
STUCK_CYCLE_THRESHOLD = 3


class SelfImprovementStatusReport:
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
            lock_timeout_ms=5_000,
        )

    def build_report(self) -> dict[str, Any]:
        build_started = monotonic()
        self._log_report_phase("build_report", "start")
        all_cycle_candidates = self._research_cycle_candidates(limit=400)
        latest_persisted = all_cycle_candidates[0] if all_cycle_candidates else {}
        cycles = [
            item for item in all_cycle_candidates if bool(item.get("included_in_self_improvement"))
        ]
        promotions = self._promotion_index()
        recent_cycles, previous_cycles = self._split_recent_vs_previous(cycles)

        section_learning = self._build_learning_section(
            cycles=cycles,
            latest_persisted=latest_persisted,
        )
        section_quality = self._build_quality_section(
            recent_cycles=recent_cycles,
            previous_cycles=previous_cycles,
        )
        section_closest = self._build_closest_to_promotion(
            cycles=cycles,
            promotions=promotions,
        )
        section_opportunities = self._build_opportunity_section(
            cycles=cycles,
            promotions=promotions,
        )
        freshness = self._build_freshness_diagnostics(
            cycles=cycles,
            latest_persisted=latest_persisted,
        )
        section_stuck = self._build_stuck_section(cycles=cycles, freshness=freshness)
        final_status, explanation = self._final_verdict(
            cycles=cycles,
            quality=section_quality,
            stuck=section_stuck,
        )
        report = {
            "status": "ok",
            "evidence_filter": {
                "allowed_sources": sorted(ALLOWED_REAL_SOURCES),
                "allowed_cycle_origins": sorted(ALLOWED_REAL_ORIGINS),
                "synthetic_evidence_excluded": True,
            },
            "lookback_cycles": len(cycles),
            "learning": section_learning,
            "evidence_quality": section_quality,
            "closest_to_promotion": section_closest,
            "trade_opportunities": section_opportunities,
            "freshness_diagnostics": freshness,
            "stuck_analysis": section_stuck,
            "strategy_trends": section_stuck.get("strategy_trends", []),
            "self_improvement_status": final_status,
            "explanation": explanation,
        }
        self._log_report_phase(
            "build_report",
            "ok",
            elapsed_ms=int((monotonic() - build_started) * 1000),
        )
        return report

    def render(self) -> str:
        render_started = monotonic()
        self._log_report_phase("render", "start")
        report = self.build_report()
        learning = report["learning"]
        quality = report["evidence_quality"]
        stuck = report["stuck_analysis"]
        strategy_trends = report.get("strategy_trends", []) or []
        opportunities = report["trade_opportunities"]
        freshness = report["freshness_diagnostics"]
        lines = [
            "Self Improvement Status",
            "section=is_centaur_learning",
            f"latest_real_research_cycle_time={learning.get('latest_real_research_cycle_time', '-')}",
            f"real_research_cycles_in_lookback={int(learning.get('real_research_cycles_in_lookback', 0) or 0)}",
            f"historical_windows_selected_per_cycle={learning.get('historical_windows_selected_per_cycle', '-')}",
            f"profiles_with_replay_evidence_per_cycle={learning.get('profiles_with_replay_evidence_per_cycle', '-')}",
            f"evidence_decisions_per_cycle={learning.get('evidence_decisions_per_cycle', '-')}",
            f"paper_safety_status={learning.get('paper_safety_status', '-')}",
            f"live_safety_status={learning.get('live_safety_status', '-')}",
            f"broker_orders_created={int(learning.get('broker_orders_created', 0) or 0)}",
            f"live_orders_created={int(learning.get('live_orders_created', 0) or 0)}",
                f"auto_paper_approved={int(learning.get('auto_paper_approved', 0) or 0)}",
                f"auto_live_approved={int(learning.get('auto_live_approved', 0) or 0)}",
                f"latest_persisted_cycle_id={learning.get('latest_persisted_cycle_id', '-')}",
                f"latest_persisted_cycle_time={learning.get('latest_persisted_cycle_time', '-')}",
                f"latest_persisted_cycle_origin={learning.get('latest_persisted_cycle_origin', '-')}",
                f"latest_persisted_command_source={learning.get('latest_persisted_command_source', '-')}",
                "latest_persisted_cycle_included_in_self_improvement="
                f"{learning.get('latest_persisted_cycle_included_in_self_improvement', '-')}",
                "latest_persisted_cycle_exclusion_reason="
                f"{learning.get('latest_persisted_cycle_exclusion_reason', '-')}",
                "latest_qualifying_self_improvement_cycle_id="
                f"{learning.get('latest_qualifying_self_improvement_cycle_id', '-')}",
                "latest_qualifying_self_improvement_cycle_time="
                f"{learning.get('latest_qualifying_self_improvement_cycle_time', '-')}",
                "section=is_evidence_quality_improving",
            f"recent_avg_net_return_after_costs={quality.get('recent_avg_net_return_after_costs', '-')}",
            f"previous_avg_net_return_after_costs={quality.get('previous_avg_net_return_after_costs', '-')}",
            f"net_return_trend={quality.get('net_return_trend', '-')}",
            f"recent_win_rate={quality.get('recent_win_rate', '-')}",
            f"previous_win_rate={quality.get('previous_win_rate', '-')}",
            f"win_rate_trend={quality.get('win_rate_trend', '-')}",
            f"recent_sample_size={quality.get('recent_sample_size', '-')}",
            f"previous_sample_size={quality.get('previous_sample_size', '-')}",
            f"sample_size_trend={quality.get('sample_size_trend', '-')}",
            f"recent_promotion_eligible_count={quality.get('recent_promotion_eligible_count', '-')}",
            f"previous_promotion_eligible_count={quality.get('previous_promotion_eligible_count', '-')}",
            f"recent_rejected_for_promotion_count={quality.get('recent_rejected_for_promotion_count', '-')}",
            f"previous_rejected_for_promotion_count={quality.get('previous_rejected_for_promotion_count', '-')}",
            f"top_blocker_recent={quality.get('top_blocker_recent', '-')}",
            f"top_blocker_previous={quality.get('top_blocker_previous', '-')}",
            f"top_blocker_trend={quality.get('top_blocker_trend', '-')}",
            f"best_strategy_profile_recent={quality.get('best_strategy_profile_recent', '-')}",
            f"best_strategy_profile_previous={quality.get('best_strategy_profile_previous', '-')}",
            f"best_strategy_profile_trend={quality.get('best_strategy_profile_trend', '-')}",
            f"worst_strategy_profile_recent={quality.get('worst_strategy_profile_recent', '-')}",
            f"worst_strategy_profile_previous={quality.get('worst_strategy_profile_previous', '-')}",
            f"worst_strategy_profile_trend={quality.get('worst_strategy_profile_trend', '-')}",
            f"evidence_quality_status={quality.get('evidence_quality_status', '-')}",
            "section=strategies_closest_to_promotion",
        ]
        for item in report.get("closest_to_promotion", []) or []:
            lines.extend(
                [
                    f"rank={item.get('rank', '-')}",
                    f"strategy_id={item.get('strategy_id', '-')}",
                    f"profile_id={item.get('profile_id', '-')}",
                    f"current_internal_stage={item.get('current_internal_stage', '-')}",
                    f"latest_recommendation={item.get('latest_recommendation', '-')}",
                    f"evidence_score={item.get('evidence_score', '-')}",
                    f"distance_to_paper_candidate={item.get('distance_to_paper_candidate', '-')}",
                    f"failed_gates={item.get('failed_gates', '-')}",
                    f"closest_passing_gate={item.get('closest_passing_gate', '-')}",
                    f"best_checkpoint={item.get('best_checkpoint', '-')}",
                    f"current_net_return={item.get('current_net_return', '-')}",
                    f"required_net_return={item.get('required_net_return', '-')}",
                    f"current_win_rate={item.get('current_win_rate', '-')}",
                    f"required_win_rate={item.get('required_win_rate', '-')}",
                    f"current_sample_size={item.get('current_sample_size', '-')}",
                    f"required_sample_size={item.get('required_sample_size', '-')}",
                    f"required_improvement_to_become_promotion_eligible={item.get('required_improvement_to_become_promotion_eligible', '-')}",
                    f"action={item.get('action', '-')}",
                ]
            )
        lines.extend(
            [
                "section=is_system_producing_better_trade_opportunities",
                f"raw_signals_per_cycle={opportunities.get('raw_signals_per_cycle', '-')}",
                f"shadow_proposals_per_cycle={opportunities.get('shadow_proposals_per_cycle', '-')}",
                f"survived_signals_per_cycle={opportunities.get('survived_signals_per_cycle', '-')}",
                f"suppressed_signals_per_cycle={opportunities.get('suppressed_signals_per_cycle', '-')}",
                f"paper_candidates_created_over_time={opportunities.get('paper_candidates_created_over_time', '-')}",
                f"paper_removal_candidates_created_over_time={opportunities.get('paper_removal_candidates_created_over_time', '-')}",
                f"broker_paper_approvals={opportunities.get('broker_paper_approvals', 0)}",
                f"live_approvals={opportunities.get('live_approvals', 0)}",
                "section=historical_freshness_diagnostics",
                f"newest_historical_bar_timestamp_seen={freshness.get('newest_historical_bar_timestamp_seen', '-')}",
                f"newest_replay_window_end_time={freshness.get('newest_replay_window_end_time', '-')}",
                f"current_system_time={freshness.get('current_system_time', '-')}",
                f"age_of_newest_bar={freshness.get('age_of_newest_bar', '-')}",
                f"age_of_newest_replay_window={freshness.get('age_of_newest_replay_window', '-')}",
                f"freshness_threshold_used={freshness.get('freshness_threshold_used', '-')}",
                f"pre_replay_refresh_enabled={freshness.get('pre_replay_refresh_enabled', '-')}",
                f"pre_replay_refresh_dry_run={freshness.get('pre_replay_refresh_dry_run', '-')}",
                f"pre_replay_refresh_ran={freshness.get('pre_replay_refresh_ran', '-')}",
                f"pre_replay_refresh_mode={freshness.get('pre_replay_refresh_mode', '-')}",
                "pre_replay_refresh_asset_classes="
                f"{','.join(freshness.get('pre_replay_refresh_asset_classes', []) or ['-'])}",
                "pre_replay_refresh_symbols="
                f"equity={','.join((freshness.get('pre_replay_refresh_symbols', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((freshness.get('pre_replay_refresh_symbols', {}) or {}).get('crypto', []) or ['-'])}",
                "pre_replay_refresh_safety_guard="
                f"{freshness.get('pre_replay_refresh_safety_guard', '-')}",
                f"latest_bar_before_refresh={freshness.get('latest_bar_before_refresh', '-')}",
                f"latest_bar_after_refresh={freshness.get('latest_bar_after_refresh', '-')}",
                f"bars_inserted_by_refresh={freshness.get('bars_inserted_by_refresh', '-')}",
                f"bars_updated_by_refresh={freshness.get('bars_updated_by_refresh', '-')}",
                "refresh_attempted_symbols="
                f"equity={','.join((freshness.get('refresh_attempted_symbols', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((freshness.get('refresh_attempted_symbols', {}) or {}).get('crypto', []) or ['-'])}",
                "refresh_success_symbols="
                f"equity={','.join((freshness.get('refresh_success_symbols', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((freshness.get('refresh_success_symbols', {}) or {}).get('crypto', []) or ['-'])}",
                "refresh_failed_symbols="
                f"equity={','.join((freshness.get('refresh_failed_symbols', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((freshness.get('refresh_failed_symbols', {}) or {}).get('crypto', []) or ['-'])}",
                "refresh_skipped_symbols="
                f"equity={','.join((freshness.get('refresh_skipped_symbols', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((freshness.get('refresh_skipped_symbols', {}) or {}).get('crypto', []) or ['-'])}",
                "refresh_skip_reasons="
                f"equity={','.join((freshness.get('refresh_skip_reasons', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((freshness.get('refresh_skip_reasons', {}) or {}).get('crypto', []) or ['-'])}",
                f"provider_error_count={freshness.get('provider_error_count', '-')}",
                f"provider_errors={','.join(freshness.get('provider_errors', []) or ['-'])}",
                f"refresh_error_count={freshness.get('refresh_error_count', '-')}",
                f"refresh_errors={','.join(freshness.get('refresh_errors', []) or ['-'])}",
                f"refresh_duration_ms={freshness.get('refresh_duration_ms', '-')}",
                f"ingestion_ran_this_cycle={freshness.get('ingestion_ran_this_cycle', '-')}",
                f"bars_inserted_this_cycle={freshness.get('bars_inserted_this_cycle', '-')}",
                f"bars_updated_this_cycle={freshness.get('bars_updated_this_cycle', '-')}",
                f"latest_bar_before_ingestion={freshness.get('latest_bar_before_ingestion', '-')}",
                f"latest_bar_after_ingestion={freshness.get('latest_bar_after_ingestion', '-')}",
                "replay_windows_selected_from_latest_available_data="
                f"{freshness.get('replay_windows_selected_from_latest_available_data', '-')}",
                f"latest_raw_bar_at={freshness.get('latest_raw_bar_at', '-')}",
                f"rolling_replay_mode_enabled={freshness.get('rolling_replay_mode_enabled', '-')}",
                f"rolling_replay_cursor_enabled={freshness.get('rolling_replay_cursor_enabled', '-')}",
                f"replay_mode={freshness.get('replay_mode', '-')}",
                f"learning_progress_this_cycle={freshness.get('learning_progress_this_cycle', '-')}",
                f"max_future_outcome_horizon={freshness.get('max_future_outcome_horizon', '-')}",
                f"latest_replay_eligible_bar_at={freshness.get('latest_replay_eligible_bar_at', '-')}",
                "latest_available_bar_per_asset_class="
                f"{freshness.get('latest_available_bar_per_asset_class', '-')}",
                "latest_available_bar_per_symbol="
                f"{freshness.get('latest_available_bar_per_symbol', '-')}",
                "latest_replay_eligible_bar_per_timeframe="
                f"{freshness.get('latest_replay_eligible_bar_per_timeframe', '-')}",
                "latest_replay_eligible_bar_per_asset_class="
                f"{freshness.get('latest_replay_eligible_bar_per_asset_class', '-')}",
                "latest_replay_eligible_at_by_bucket="
                f"{freshness.get('latest_replay_eligible_at_by_bucket', '-')}",
                "previous_replay_eligible_at_by_bucket="
                f"{freshness.get('previous_replay_eligible_at_by_bucket', '-')}",
                "replay_eligible_advance_delta_by_bucket="
                f"{freshness.get('replay_eligible_advance_delta_by_bucket', '-')}",
                "last_replayed_until_by_bucket="
                f"{freshness.get('last_replayed_until_by_bucket', '-')}",
                "unseen_replay_range_available_by_bucket="
                f"{freshness.get('unseen_replay_range_available_by_bucket', '-')}",
                "next_unseen_replay_start_by_bucket="
                f"{freshness.get('next_unseen_replay_start_by_bucket', '-')}",
                "next_unseen_replay_end_by_bucket="
                f"{freshness.get('next_unseen_replay_end_by_bucket', '-')}",
                "candidate_replay_windows_considered="
                f"{freshness.get('candidate_replay_windows_considered', '-')}",
                "candidate_replay_windows_rejected="
                f"{freshness.get('candidate_replay_windows_rejected', '-')}",
                "selected_replay_windows="
                f"{freshness.get('selected_replay_windows', '-')}",
                "selected_replay_window_reason="
                f"{freshness.get('selected_replay_window_reason', '-')}",
                f"max_allowed_replay_window_end={freshness.get('max_allowed_replay_window_end', '-')}",
                f"global_anchor_enabled={freshness.get('global_anchor_enabled', '-')}",
                f"global_anchor_time={freshness.get('global_anchor_time', '-')}",
                "global_anchor_constrained_by_asset_class="
                f"{freshness.get('global_anchor_constrained_by_asset_class', '-')}",
                "global_anchor_constrained_by_timeframe="
                f"{freshness.get('global_anchor_constrained_by_timeframe', '-')}",
                "global_anchor_constrained_by_symbol="
                f"{freshness.get('global_anchor_constrained_by_symbol', '-')}",
                "freshness_lost_to_future_outcome_horizon="
                f"{freshness.get('freshness_lost_to_future_outcome_horizon', '-')}",
                "freshness_lost_to_global_anchor="
                f"{freshness.get('freshness_lost_to_global_anchor', '-')}",
                "selected_replay_window_end_by_timeframe="
                f"{freshness.get('selected_replay_window_end_by_timeframe', '-')}",
                "selected_replay_window_end_by_asset_class="
                f"{freshness.get('selected_replay_window_end_by_asset_class', '-')}",
                "selected_replay_window_end_by_bucket="
                f"{freshness.get('selected_replay_window_end_by_bucket', '-')}",
                "accepted_replay_window_count_by_timeframe="
                f"{freshness.get('accepted_replay_window_count_by_timeframe', '-')}",
                "accepted_replay_window_count_by_asset_class="
                f"{freshness.get('accepted_replay_window_count_by_asset_class', '-')}",
                "selected_anchor_time_by_bucket="
                f"{freshness.get('selected_anchor_time_by_bucket', '-')}",
                "candidate_anchor_time_by_bucket="
                f"{freshness.get('candidate_anchor_time_by_bucket', '-')}",
                "rejected_bucket_anchor_time_by_bucket="
                f"{freshness.get('rejected_bucket_anchor_time_by_bucket', '-')}",
                "freshness_gain_vs_global_by_bucket="
                f"{freshness.get('freshness_gain_vs_global_by_bucket', '-')}",
                "windows_selected_by_bucket="
                f"{freshness.get('windows_selected_by_bucket', '-')}",
                "windows_rejected_by_bucket="
                f"{freshness.get('windows_rejected_by_bucket', '-')}",
                "bucket_rejection_reasons="
                f"{freshness.get('bucket_rejection_reasons', '-')}",
                f"replay_selection_mode={freshness.get('replay_selection_mode', '-')}",
                "alternative_replay_selection_modes_available="
                f"{freshness.get('alternative_replay_selection_modes_available', '-')}",
                "simulated_asset_class_anchor_time="
                f"{freshness.get('simulated_asset_class_anchor_time', '-')}",
                "simulated_asset_class_and_timeframe_anchor_time="
                f"{freshness.get('simulated_asset_class_and_timeframe_anchor_time', '-')}",
                "simulated_freshness_gain_by_asset_class="
                f"{freshness.get('simulated_freshness_gain_by_asset_class', '-')}",
                "simulated_freshness_gain_by_asset_class_and_timeframe="
                f"{freshness.get('simulated_freshness_gain_by_asset_class_and_timeframe', '-')}",
                "strategies_helped_by_isolated_replay="
                f"{freshness.get('strategies_helped_by_isolated_replay', '-')}",
                "strategies_unaffected_by_isolated_replay="
                f"{freshness.get('strategies_unaffected_by_isolated_replay', '-')}",
                "strategies_blocked_by_mixed_global_anchor="
                f"{freshness.get('strategies_blocked_by_mixed_global_anchor', '-')}",
                "minimum_required_window_completeness="
                f"{freshness.get('minimum_required_window_completeness', '-')}",
                f"lookback_window_policy={freshness.get('lookback_window_policy', '-')}",
                f"warmup_buffer_policy={freshness.get('warmup_buffer_policy', '-')}",
                f"market_hours_policy={freshness.get('market_hours_policy', '-')}",
                f"weekend_policy={freshness.get('weekend_policy', '-')}",
                f"asset_class_window_policy={freshness.get('asset_class_window_policy', '-')}",
                "reason_latest_bars_not_used_for_replay="
                f"{freshness.get('reason_latest_bars_not_used_for_replay', '-')}",
                "plain_english_replay_anchor_explanation="
                f"{freshness.get('plain_english_replay_anchor_explanation', '-')}",
                f"reason_if_not={freshness.get('reason_if_not', '-')}",
                "selected_window_ids_current="
                f"{freshness.get('selected_window_ids_current', '-')}",
                "selected_window_ids_previous="
                f"{freshness.get('selected_window_ids_previous', '-')}",
                f"selected_window_set_changed={freshness.get('selected_window_set_changed', '-')}",
                f"new_replay_windows_selected_count={freshness.get('new_replay_windows_selected_count', '-')}",
                f"duplicate_replay_windows_skipped_count={freshness.get('duplicate_replay_windows_skipped_count', '-')}",
                f"replay_evidence_new_rows_inserted={freshness.get('replay_evidence_new_rows_inserted', '-')}",
                f"replay_evidence_duplicate_rows_skipped={freshness.get('replay_evidence_duplicate_rows_skipped', '-')}",
                "reason_replay_window_not_advancing="
                f"{freshness.get('reason_replay_window_not_advancing', '-')}",
                f"reason_no_learning_progress={freshness.get('reason_no_learning_progress', '-')}",
                f"replay_window_set_changed_from_previous_real_cycle={freshness.get('replay_window_set_changed_from_previous_real_cycle', '-')}",
                "section=is_system_stuck",
                f"stuck_detected={'yes' if stuck.get('stuck_detected') else 'no'}",
                f"stuck_reason={stuck.get('stuck_reason', '-')}",
                f"same_top_blocker_cycles={stuck.get('same_top_blocker_cycles', '-')}",
                f"cycles_without_strategy_improvement={stuck.get('cycles_without_strategy_improvement', '-')}",
                f"fresh_historical_bars_detected={stuck.get('fresh_historical_bars_detected', '-')}",
                f"stale_replay_window_set_detected={stuck.get('stale_replay_window_set_detected', '-')}",
                f"sample_size_increasing={stuck.get('sample_size_increasing', '-')}",
                f"replay_window_advancing={stuck.get('replay_window_advancing', '-')}",
                f"strategies_improving_count={stuck.get('strategies_improving_count', '-')}",
                f"strategies_degrading_count={stuck.get('strategies_degrading_count', '-')}",
                f"strategies_flat_count={stuck.get('strategies_flat_count', '-')}",
                f"blocker_counts_recent={stuck.get('blocker_counts_recent', '-')}",
                f"blocker_counts_previous={stuck.get('blocker_counts_previous', '-')}",
                f"dominant_blocker={stuck.get('dominant_blocker', '-')}",
                f"dominant_blocker_cycles={stuck.get('dominant_blocker_cycles', '-')}",
                f"blocker_trend={stuck.get('blocker_trend', '-')}",
                f"system_stuck={'yes' if stuck.get('system_stuck') else 'no'}",
                f"strategy_evidence_stuck={'yes' if stuck.get('strategy_evidence_stuck') else 'no'}",
                f"all_research_only_too_long={'yes' if stuck.get('all_research_only_too_long') else 'no'}",
                "section=strategy_evidence_trends",
                f"self_improvement_status={report.get('self_improvement_status', '-')}",
                f"explanation={report.get('explanation', '-')}",
            ]
        )
        for item in strategy_trends:
            lines.extend(
                [
                    f"strategy_id={item.get('strategy_id', '-')}",
                    f"profile_id={item.get('profile_id', '-')}",
                    f"checkpoint={item.get('checkpoint', '-')}",
                    f"previous_net_return={item.get('previous_net_return', '-')}",
                    f"recent_net_return={item.get('recent_net_return', '-')}",
                    f"net_return_delta={item.get('net_return_delta', '-')}",
                    f"previous_win_rate={item.get('previous_win_rate', '-')}",
                    f"recent_win_rate={item.get('recent_win_rate', '-')}",
                    f"win_rate_delta={item.get('win_rate_delta', '-')}",
                    f"previous_sample_size={item.get('previous_sample_size', '-')}",
                    f"recent_sample_size={item.get('recent_sample_size', '-')}",
                    f"sample_size_delta={item.get('sample_size_delta', '-')}",
                    "distance_to_paper_candidate_previous="
                    f"{item.get('distance_to_paper_candidate_previous', '-')}",
                    "distance_to_paper_candidate_recent="
                    f"{item.get('distance_to_paper_candidate_recent', '-')}",
                    f"distance_delta={item.get('distance_delta', '-')}",
                    f"trend={item.get('trend', '-')}",
                ]
            )
        self._log_report_phase(
            "render",
            "ok",
            elapsed_ms=int((monotonic() - render_started) * 1000),
        )
        return "\n".join(lines)

    def _log_report_phase(
        self,
        phase: str,
        status: str,
        *,
        elapsed_ms: int | None = None,
    ) -> None:
        fields = {
            "phase": phase,
            "status": status,
            "report": "self_improvement_status",
            "backend": str(getattr(self.usage_ledger, "backend", "unknown")),
        }
        if elapsed_ms is not None:
            fields["elapsed_ms"] = str(elapsed_ms)
        print(
            "report_diagnostic " + " ".join(f"{key}={value}" for key, value in fields.items()),
            file=sys.stderr,
            flush=True,
        )

    def _research_cycle_candidates(self, *, limit: int) -> list[dict[str, Any]]:
        cycles: list[dict[str, Any]] = []
        for row in self.usage_ledger.list_recent_tick_runs(limit=limit):
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            if not isinstance(snapshot, dict):
                continue
            run = snapshot.get("run", {})
            state = snapshot.get("research_cycle", {})
            if not isinstance(run, dict) or not isinstance(state, dict):
                continue
            if str(run.get("pipeline", "") or "") != "research_cycle":
                continue
            cycles.append(self._cycle_summary(row=row, run=run, state=state))
        cycles.sort(key=lambda item: item.get("started_at_sort") or datetime.min, reverse=True)
        return cycles

    def _cycle_summary(
        self,
        *,
        row: dict[str, Any],
        run: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        decisions = list(state.get("decisions", []) or [])
        blocker_counts: Counter[str] = Counter()
        profiles: list[dict[str, Any]] = []
        for item in decisions:
            blockers = [str(reason).strip() for reason in list(item.get("blocker_reasons", []) or []) if str(reason).strip()]
            blocker_counts.update(blockers)
            profiles.append(self._profile_summary(item=item))
        top_profile = max(profiles, key=self._profile_rank_key, default=None)
        bottom_profile = min(profiles, key=self._profile_bottom_rank_key, default=None)
        started_at = row.get("started_at")
        return {
            "tick_id": str(row.get("tick_id", "") or ""),
            "started_at": self._fmt_dt(started_at),
            "started_at_sort": started_at if isinstance(started_at, datetime) else datetime.min,
            "source": str(run.get("source", "") or ""),
            "cycle_origin": str(run.get("cycle_origin", "") or ""),
            "command_source": str(run.get("command_source", "") or ""),
            "timeframe": str(run.get("timeframe", "") or ""),
            "historical_windows_selected": int(state.get("historical_windows_selected", 0) or 0),
            "latest_available_historical_bar_at": self._fmt_dt(state.get("latest_available_historical_bar_at")),
            "latest_valid_replay_window_end": self._fmt_dt(state.get("latest_valid_replay_window_end")),
            "selection_anchor_end_at": self._fmt_dt(state.get("selection_anchor_end_at")),
            "pre_replay_refresh_enabled": str(state.get("pre_replay_refresh_enabled", "no") or "no"),
            "pre_replay_refresh_dry_run": str(state.get("pre_replay_refresh_dry_run", "yes") or "yes"),
            "pre_replay_refresh_ran": str(state.get("pre_replay_refresh_ran", "no") or "no"),
            "pre_replay_refresh_mode": str(state.get("pre_replay_refresh_mode", "disabled") or "disabled"),
            "pre_replay_refresh_asset_classes": list(
                state.get("pre_replay_refresh_asset_classes", []) or []
            ),
            "pre_replay_refresh_symbols": dict(state.get("pre_replay_refresh_symbols", {}) or {}),
            "pre_replay_refresh_safety_guard": str(
                state.get(
                    "pre_replay_refresh_safety_guard",
                    "historical_backfill_only_no_orders_no_auto_approvals",
                )
                or "historical_backfill_only_no_orders_no_auto_approvals"
            ),
            "latest_bar_before_refresh": self._fmt_dt(state.get("latest_bar_before_refresh")),
            "latest_bar_after_refresh": self._fmt_dt(state.get("latest_bar_after_refresh")),
            "bars_inserted_by_refresh": int(state.get("bars_inserted_by_refresh", 0) or 0),
            "bars_updated_by_refresh": int(state.get("bars_updated_by_refresh", 0) or 0),
            "refresh_attempted_symbols": dict(state.get("refresh_attempted_symbols", {}) or {}),
            "refresh_success_symbols": dict(state.get("refresh_success_symbols", {}) or {}),
            "refresh_failed_symbols": dict(state.get("refresh_failed_symbols", {}) or {}),
            "refresh_skipped_symbols": dict(state.get("refresh_skipped_symbols", {}) or {}),
            "refresh_skip_reasons": dict(state.get("refresh_skip_reasons", {}) or {}),
            "provider_error_count": int(state.get("provider_error_count", 0) or 0),
            "provider_errors": list(state.get("provider_errors", []) or []),
            "refresh_error_count": int(state.get("refresh_error_count", 0) or 0),
            "refresh_errors": list(state.get("refresh_errors", []) or []),
            "refresh_duration_ms": int(state.get("refresh_duration_ms", 0) or 0),
            "ingestion_ran_this_cycle": str(state.get("ingestion_ran_this_cycle", "no") or "no"),
            "bars_inserted_this_cycle": int(state.get("bars_inserted_this_cycle", 0) or 0),
            "bars_updated_this_cycle": int(state.get("bars_updated_this_cycle", 0) or 0),
            "latest_bar_before_ingestion": self._fmt_dt(state.get("latest_bar_before_ingestion")),
            "latest_bar_after_ingestion": self._fmt_dt(state.get("latest_bar_after_ingestion")),
            "replay_windows_selected_from_latest_available_data": str(
                state.get("replay_windows_selected_from_latest_available_data", "unknown")
                or "unknown"
            ),
            "latest_raw_bar_at": self._fmt_dt(state.get("latest_raw_bar_at")),
            "rolling_replay_mode_enabled": str(
                state.get("rolling_replay_mode_enabled", "no") or "no"
            ),
            "rolling_replay_cursor_enabled": str(
                state.get("rolling_replay_cursor_enabled", "no") or "no"
            ),
            "replay_mode": str(state.get("replay_mode", "") or ""),
            "learning_progress_this_cycle": str(
                state.get("learning_progress_this_cycle", "no") or "no"
            ),
            "max_future_outcome_horizon": str(
                state.get("max_future_outcome_horizon", "") or ""
            ),
            "latest_replay_eligible_bar_at": self._fmt_dt(
                state.get("latest_replay_eligible_bar_at")
            ),
            "latest_available_bar_per_asset_class": dict(
                state.get("latest_available_bar_per_asset_class", {}) or {}
            ),
            "latest_available_bar_per_symbol": dict(
                state.get("latest_available_bar_per_symbol", {}) or {}
            ),
            "latest_replay_eligible_bar_per_timeframe": dict(
                state.get("latest_replay_eligible_bar_per_timeframe", {}) or {}
            ),
            "latest_replay_eligible_bar_per_asset_class": dict(
                state.get("latest_replay_eligible_bar_per_asset_class", {}) or {}
            ),
            "latest_replay_eligible_at_by_bucket": dict(
                state.get("latest_replay_eligible_at_by_bucket", {}) or {}
            ),
            "previous_replay_eligible_at_by_bucket": dict(
                state.get("previous_replay_eligible_at_by_bucket", {}) or {}
            ),
            "replay_eligible_advance_delta_by_bucket": dict(
                state.get("replay_eligible_advance_delta_by_bucket", {}) or {}
            ),
            "last_replayed_until_by_bucket": dict(
                state.get("last_replayed_until_by_bucket", {}) or {}
            ),
            "unseen_replay_range_available_by_bucket": dict(
                state.get("unseen_replay_range_available_by_bucket", {}) or {}
            ),
            "next_unseen_replay_start_by_bucket": dict(
                state.get("next_unseen_replay_start_by_bucket", {}) or {}
            ),
            "next_unseen_replay_end_by_bucket": dict(
                state.get("next_unseen_replay_end_by_bucket", {}) or {}
            ),
            "candidate_replay_windows_considered": list(
                state.get("candidate_replay_windows_considered", []) or []
            ),
            "candidate_replay_windows_rejected": list(
                state.get("candidate_replay_windows_rejected", []) or []
            ),
            "selected_replay_windows": list(state.get("selected_replay_windows", []) or []),
            "selected_replay_window_reason": str(
                state.get("selected_replay_window_reason", "") or ""
            ),
            "max_allowed_replay_window_end": str(
                state.get("max_allowed_replay_window_end", "") or ""
            ),
            "global_anchor_enabled": str(state.get("global_anchor_enabled", "") or ""),
            "global_anchor_time": str(state.get("global_anchor_time", "") or ""),
            "global_anchor_constrained_by_asset_class": str(
                state.get("global_anchor_constrained_by_asset_class", "") or ""
            ),
            "global_anchor_constrained_by_timeframe": str(
                state.get("global_anchor_constrained_by_timeframe", "") or ""
            ),
            "global_anchor_constrained_by_symbol": str(
                state.get("global_anchor_constrained_by_symbol", "") or ""
            ),
            "freshness_lost_to_future_outcome_horizon": str(
                state.get("freshness_lost_to_future_outcome_horizon", "") or ""
            ),
            "freshness_lost_to_global_anchor": str(
                state.get("freshness_lost_to_global_anchor", "") or ""
            ),
            "selected_replay_window_end_by_timeframe": dict(
                state.get("selected_replay_window_end_by_timeframe", {}) or {}
            ),
            "selected_replay_window_end_by_asset_class": dict(
                state.get("selected_replay_window_end_by_asset_class", {}) or {}
            ),
            "selected_replay_window_end_by_bucket": dict(
                state.get("selected_replay_window_end_by_bucket", {}) or {}
            ),
            "accepted_replay_window_count_by_timeframe": dict(
                state.get("accepted_replay_window_count_by_timeframe", {}) or {}
            ),
            "accepted_replay_window_count_by_asset_class": dict(
                state.get("accepted_replay_window_count_by_asset_class", {}) or {}
            ),
            "selected_anchor_time_by_bucket": dict(
                state.get("selected_anchor_time_by_bucket", {}) or {}
            ),
            "candidate_anchor_time_by_bucket": dict(
                state.get("candidate_anchor_time_by_bucket", {}) or {}
            ),
            "rejected_bucket_anchor_time_by_bucket": dict(
                state.get("rejected_bucket_anchor_time_by_bucket", {}) or {}
            ),
            "freshness_gain_vs_global_by_bucket": dict(
                state.get("freshness_gain_vs_global_by_bucket", {}) or {}
            ),
            "windows_selected_by_bucket": dict(
                state.get("windows_selected_by_bucket", {}) or {}
            ),
            "windows_rejected_by_bucket": dict(
                state.get("windows_rejected_by_bucket", {}) or {}
            ),
            "bucket_rejection_reasons": dict(
                state.get("bucket_rejection_reasons", {}) or {}
            ),
            "replay_selection_mode": str(state.get("replay_selection_mode", "") or ""),
            "alternative_replay_selection_modes_available": str(
                state.get("alternative_replay_selection_modes_available", "") or ""
            ),
            "simulated_asset_class_anchor_time": dict(
                state.get("simulated_asset_class_anchor_time", {}) or {}
            ),
            "simulated_asset_class_and_timeframe_anchor_time": dict(
                state.get("simulated_asset_class_and_timeframe_anchor_time", {}) or {}
            ),
            "simulated_freshness_gain_by_asset_class": dict(
                state.get("simulated_freshness_gain_by_asset_class", {}) or {}
            ),
            "simulated_freshness_gain_by_asset_class_and_timeframe": dict(
                state.get(
                    "simulated_freshness_gain_by_asset_class_and_timeframe",
                    {},
                )
                or {}
            ),
            "strategies_helped_by_isolated_replay": list(
                state.get("strategies_helped_by_isolated_replay", []) or []
            ),
            "strategies_unaffected_by_isolated_replay": list(
                state.get("strategies_unaffected_by_isolated_replay", []) or []
            ),
            "strategies_blocked_by_mixed_global_anchor": list(
                state.get("strategies_blocked_by_mixed_global_anchor", []) or []
            ),
            "minimum_required_window_completeness": str(
                state.get("minimum_required_window_completeness", "") or ""
            ),
            "lookback_window_policy": str(state.get("lookback_window_policy", "") or ""),
            "warmup_buffer_policy": str(state.get("warmup_buffer_policy", "") or ""),
            "market_hours_policy": str(state.get("market_hours_policy", "") or ""),
            "weekend_policy": str(state.get("weekend_policy", "") or ""),
            "asset_class_window_policy": str(state.get("asset_class_window_policy", "") or ""),
            "reason_latest_bars_not_used_for_replay": str(
                state.get("reason_latest_bars_not_used_for_replay", "") or ""
            ),
            "plain_english_replay_anchor_explanation": str(
                state.get("plain_english_replay_anchor_explanation", "") or ""
            ),
            "reason_if_not": str(state.get("reason_if_not", "") or ""),
            "selected_window_ids_current": dict(
                state.get("selected_window_ids_current", {}) or {}
            ),
            "selected_window_ids_previous": dict(
                state.get("selected_window_ids_previous", {}) or {}
            ),
            "selected_window_set_changed": str(
                state.get("selected_window_set_changed", "") or ""
            ),
            "new_replay_windows_selected_count": int(
                state.get("new_replay_windows_selected_count", 0) or 0
            ),
            "duplicate_replay_windows_skipped_count": int(
                state.get("duplicate_replay_windows_skipped_count", 0) or 0
            ),
            "replay_evidence_new_rows_inserted": int(
                state.get("replay_evidence_new_rows_inserted", 0) or 0
            ),
            "replay_evidence_duplicate_rows_skipped": int(
                state.get("replay_evidence_duplicate_rows_skipped", 0) or 0
            ),
            "reason_replay_window_not_advancing": str(
                state.get("reason_replay_window_not_advancing", "") or ""
            ),
            "reason_no_learning_progress": str(
                state.get("reason_no_learning_progress", "") or ""
            ),
            "profiles_with_replay_evidence": sum(1 for item in decisions if int(item.get("proposals_created", 0) or 0) > 0),
            "profiles_with_paper_sim_evidence": sum(1 for item in decisions if int(item.get("outcomes_recorded", 0) or 0) > 0),
            "evidence_decisions_count": int(state.get("usable_decisions_count", 0) or 0),
            "promotion_eligible_count": sum(1 for item in decisions if str(item.get("recommendation", "")) == "paper_sim_candidate"),
            "rejected_for_promotion_count": sum(1 for item in decisions if str(item.get("recommendation", "")) != "paper_sim_candidate"),
            "paper_candidates_created": int(state.get("paper_candidates_created", 0) or 0),
            "paper_removal_candidates_created": int(state.get("paper_removal_candidates_created", 0) or 0),
            "decisions": decisions,
            "profiles": profiles,
            "avg_net_return": self._safe_mean(profile["net_return"] for profile in profiles),
            "avg_win_rate": self._safe_mean(profile["win_rate"] for profile in profiles),
            "total_sample_size": sum(profile["sample_size"] for profile in profiles),
            "raw_signals": sum(profile["raw_signals"] for profile in profiles),
            "shadow_proposals": sum(profile["sample_size"] for profile in profiles),
            "survived_signals": sum(profile["sample_size"] for profile in profiles),
            "suppressed_signals": max(0, sum(profile["raw_signals"] for profile in profiles) - sum(profile["sample_size"] for profile in profiles)),
            "top_blocker": blocker_counts.most_common(1)[0][0] if blocker_counts else "none",
            "blocker_counts": blocker_counts,
            "all_research_only": all(str(item.get("recommendation", "")) == "research_only" for item in decisions) if decisions else True,
            "best_profile": top_profile,
            "worst_profile": bottom_profile,
            **self._self_improvement_inclusion_fields(run=run),
        }

    def _self_improvement_inclusion_fields(self, *, run: dict[str, Any]) -> dict[str, Any]:
        source = str(run.get("source", "") or "")
        cycle_origin = str(run.get("cycle_origin", "") or "")
        if source not in ALLOWED_REAL_SOURCES:
            return {
                "included_in_self_improvement": False,
                "exclusion_reason": "source_not_real_heartbeat",
            }
        if cycle_origin not in ALLOWED_REAL_ORIGINS:
            return {
                "included_in_self_improvement": False,
                "exclusion_reason": "cycle_origin_not_allowed_for_self_improvement",
            }
        return {
            "included_in_self_improvement": True,
            "exclusion_reason": "",
        }

    def _profile_summary(self, *, item: dict[str, Any]) -> dict[str, Any]:
        net_summary = item.get("net_return_summary", {}) or item.get("net_return_summary_json", {}) or {}
        win_summary = item.get("win_rate_summary", {}) or item.get("win_rate_summary_json", {}) or {}
        net_return = float(net_summary.get("avg_pct", 0.0) or 0.0)
        win_rate = float(win_summary.get("avg", 0.0) or 0.0)
        sample_size = int(item.get("proposals_created", 0) or 0)
        raw_signals = int(item.get("signals_generated", sample_size) or sample_size)
        failed_gates = [str(reason).strip() for reason in list(item.get("blocker_reasons", []) or item.get("blocker_reasons_json", []) or []) if str(reason).strip()]
        score = self._evidence_score(net_return=net_return, win_rate=win_rate, sample_size=sample_size, failed_gates=failed_gates)
        return {
            "strategy_id": str(item.get("strategy_id", "") or "-"),
            "profile_id": str(item.get("profile_id", "") or "-"),
            "recommendation": str(item.get("recommendation", "research_only") or "research_only"),
            "net_return": net_return,
            "win_rate": win_rate,
            "sample_size": sample_size,
            "has_real_evidence": sample_size > 0 or int(item.get("outcomes_recorded", 0) or 0) > 0,
            "outcomes_recorded": int(item.get("outcomes_recorded", 0) or 0),
            "checkpoint": self._best_checkpoint(item),
            "failed_gates": failed_gates,
            "score": score,
            "raw_signals": raw_signals,
        }

    def _promotion_index(self) -> dict[tuple[str, str], dict[str, Any]]:
        records = {}
        for item in self.usage_ledger.list_strategy_promotions():
            records[(str(item.get("strategy_id", "")), str(item.get("profile_id", "")))] = item
        return records

    def _split_recent_vs_previous(
        self,
        cycles: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        if len(cycles) < 2:
            return cycles[:], []
        split = max(1, len(cycles) // 2)
        return cycles[:split], cycles[split:]

    def _build_learning_section(
        self,
        *,
        cycles: list[dict[str, Any]],
        latest_persisted: dict[str, Any],
    ) -> dict[str, Any]:
        latest = cycles[0] if cycles else {}
        return {
            "latest_real_research_cycle_time": latest.get("started_at", "-"),
            "real_research_cycles_in_lookback": len(cycles),
            "historical_windows_selected_per_cycle": self._series(cycles, "historical_windows_selected"),
            "profiles_with_replay_evidence_per_cycle": self._series(cycles, "profiles_with_replay_evidence"),
            "evidence_decisions_per_cycle": self._series(cycles, "evidence_decisions_count"),
            "paper_safety_status": "unchanged_manual_only",
            "live_safety_status": "unchanged_manual_only",
            "broker_orders_created": 0,
            "live_orders_created": 0,
            "auto_paper_approved": 0,
            "auto_live_approved": 0,
            "latest_persisted_cycle_id": latest_persisted.get("tick_id", "-") or "-",
            "latest_persisted_cycle_time": latest_persisted.get("started_at", "-") or "-",
            "latest_persisted_cycle_origin": latest_persisted.get("cycle_origin", "-") or "-",
            "latest_persisted_command_source": latest_persisted.get("command_source", "-") or "-",
            "latest_persisted_cycle_included_in_self_improvement": (
                "yes"
                if bool(latest_persisted.get("included_in_self_improvement"))
                else ("no" if latest_persisted else "-")
            ),
            "latest_persisted_cycle_exclusion_reason": (
                latest_persisted.get("exclusion_reason", "-") or "-"
            ),
            "latest_qualifying_self_improvement_cycle_id": latest.get("tick_id", "-") or "-",
            "latest_qualifying_self_improvement_cycle_time": latest.get("started_at", "-") or "-",
        }

    def _build_quality_section(
        self,
        *,
        recent_cycles: list[dict[str, Any]],
        previous_cycles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        if not previous_cycles:
            return {
                "recent_avg_net_return_after_costs": self._fmt_pct(self._safe_mean(item["avg_net_return"] for item in recent_cycles)),
                "previous_avg_net_return_after_costs": "-",
                "net_return_trend": "insufficient_history",
                "recent_win_rate": self._fmt_pct(self._safe_mean(item["avg_win_rate"] for item in recent_cycles)),
                "previous_win_rate": "-",
                "win_rate_trend": "insufficient_history",
                "recent_sample_size": int(sum(item["total_sample_size"] for item in recent_cycles)),
                "previous_sample_size": "-",
                "sample_size_trend": "insufficient_history",
                "recent_promotion_eligible_count": int(sum(item["promotion_eligible_count"] for item in recent_cycles)),
                "previous_promotion_eligible_count": "-",
                "recent_rejected_for_promotion_count": int(sum(item["rejected_for_promotion_count"] for item in recent_cycles)),
                "previous_rejected_for_promotion_count": "-",
                "top_blocker_recent": recent_cycles[0]["top_blocker"] if recent_cycles else "-",
                "top_blocker_previous": "-",
                "top_blocker_trend": "insufficient_history",
                "best_strategy_profile_recent": self._profile_label((recent_cycles[0] if recent_cycles else {}).get("best_profile")),
                "best_strategy_profile_previous": "-",
                "best_strategy_profile_trend": "insufficient_history",
                "worst_strategy_profile_recent": self._profile_label((recent_cycles[0] if recent_cycles else {}).get("worst_profile")),
                "worst_strategy_profile_previous": "-",
                "worst_strategy_profile_trend": "insufficient_history",
                "evidence_quality_status": "insufficient_history",
            }
        recent_net = self._safe_mean(item["avg_net_return"] for item in recent_cycles)
        previous_net = self._safe_mean(item["avg_net_return"] for item in previous_cycles)
        recent_win = self._safe_mean(item["avg_win_rate"] for item in recent_cycles)
        previous_win = self._safe_mean(item["avg_win_rate"] for item in previous_cycles)
        recent_sample = sum(item["total_sample_size"] for item in recent_cycles)
        previous_sample = sum(item["total_sample_size"] for item in previous_cycles)
        recent_best = recent_cycles[0].get("best_profile") if recent_cycles else None
        previous_best = previous_cycles[0].get("best_profile") if previous_cycles else None
        recent_worst = recent_cycles[0].get("worst_profile") if recent_cycles else None
        previous_worst = previous_cycles[0].get("worst_profile") if previous_cycles else None
        net_trend = self._metric_trend(recent_net, previous_net)
        win_trend = self._metric_trend(recent_win, previous_win)
        sample_trend = self._sample_trend(recent_sample, previous_sample)
        blocker_trend = self._blocker_trend(
            recent=recent_cycles[0]["top_blocker"] if recent_cycles else "none",
            previous=previous_cycles[0]["top_blocker"] if previous_cycles else "none",
        )
        quality_status = self._evidence_quality_status(
            net_trend=net_trend,
            win_trend=win_trend,
            sample_trend=sample_trend,
        )
        return {
            "recent_avg_net_return_after_costs": self._fmt_pct(recent_net),
            "previous_avg_net_return_after_costs": self._fmt_pct(previous_net),
            "net_return_trend": net_trend,
            "recent_win_rate": self._fmt_pct(recent_win),
            "previous_win_rate": self._fmt_pct(previous_win),
            "win_rate_trend": win_trend,
            "recent_sample_size": int(recent_sample),
            "previous_sample_size": int(previous_sample),
            "sample_size_trend": sample_trend,
            "recent_promotion_eligible_count": int(sum(item["promotion_eligible_count"] for item in recent_cycles)),
            "previous_promotion_eligible_count": int(sum(item["promotion_eligible_count"] for item in previous_cycles)),
            "recent_rejected_for_promotion_count": int(sum(item["rejected_for_promotion_count"] for item in recent_cycles)),
            "previous_rejected_for_promotion_count": int(sum(item["rejected_for_promotion_count"] for item in previous_cycles)),
            "top_blocker_recent": recent_cycles[0]["top_blocker"] if recent_cycles else "-",
            "top_blocker_previous": previous_cycles[0]["top_blocker"] if previous_cycles else "-",
            "top_blocker_trend": blocker_trend,
            "best_strategy_profile_recent": self._profile_label(recent_best),
            "best_strategy_profile_previous": self._profile_label(previous_best),
            "best_strategy_profile_trend": self._profile_trend(recent_best, previous_best),
            "worst_strategy_profile_recent": self._profile_label(recent_worst),
            "worst_strategy_profile_previous": self._profile_label(previous_worst),
            "worst_strategy_profile_trend": self._profile_trend(previous_worst, recent_worst, invert=True),
            "evidence_quality_status": quality_status,
        }

    def _build_closest_to_promotion(
        self,
        *,
        cycles: list[dict[str, Any]],
        promotions: dict[tuple[str, str], dict[str, Any]],
    ) -> list[dict[str, Any]]:
        latest = cycles[0] if cycles else {}
        profiles = list(latest.get("profiles", []) or [])
        ranked = sorted(profiles, key=self._profile_rank_key, reverse=True)[:5]
        rows: list[dict[str, Any]] = []
        for rank, item in enumerate(ranked, start=1):
            key = (item["strategy_id"], item["profile_id"])
            record = promotions.get(key, {})
            failed_gates = list(item["failed_gates"] or [])
            if not item.get("has_real_evidence"):
                failed_gates = ["no_real_evidence_yet", *failed_gates]
            if not failed_gates:
                failed_gates = ["none"]
            closest_gate = "sample_size" if item["sample_size"] >= int(self.config.research_min_proposals) else "net_return"
            rows.append(
                {
                    "rank": rank,
                    "strategy_id": item["strategy_id"],
                    "profile_id": item["profile_id"],
                    "current_internal_stage": str(record.get("stage", item.get("recommendation", "research_only")) or "research_only"),
                    "latest_recommendation": item["recommendation"],
                    "evidence_score": item["score"],
                    "distance_to_paper_candidate": f"{max(0, 100 - item['score'])}%",
                    "failed_gates": ",".join(failed_gates),
                    "closest_passing_gate": closest_gate,
                    "best_checkpoint": item["checkpoint"],
                    "current_net_return": self._fmt_pct(item["net_return"]),
                    "required_net_return": self._fmt_pct(float(self.config.research_min_net_return_pct)),
                    "current_win_rate": self._fmt_pct(item["win_rate"]),
                    "required_win_rate": self._fmt_pct(float(self.config.research_min_net_win_rate)),
                    "current_sample_size": item["sample_size"],
                    "required_sample_size": int(self.config.research_min_proposals),
                    "required_improvement_to_become_promotion_eligible": self._required_improvement(item),
                    "action": "keep_collecting_evidence"
                    if item.get("has_real_evidence")
                    else "collect_real_replay_evidence",
                }
            )
        return rows

    def _build_opportunity_section(
        self,
        *,
        cycles: list[dict[str, Any]],
        promotions: dict[tuple[str, str], dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "raw_signals_per_cycle": self._series(cycles, "raw_signals"),
            "shadow_proposals_per_cycle": self._series(cycles, "shadow_proposals"),
            "survived_signals_per_cycle": self._series(cycles, "survived_signals"),
            "suppressed_signals_per_cycle": self._series(cycles, "suppressed_signals"),
            "paper_candidates_created_over_time": self._series(cycles, "paper_candidates_created"),
            "paper_removal_candidates_created_over_time": self._series(cycles, "paper_removal_candidates_created"),
            "broker_paper_approvals": sum(1 for item in promotions.values() if bool(item.get("paper_approved"))),
            "live_approvals": sum(1 for item in promotions.values() if bool(item.get("live_approved"))),
        }

    def _build_freshness_diagnostics(
        self,
        *,
        cycles: list[dict[str, Any]],
        latest_persisted: dict[str, Any],
    ) -> dict[str, Any]:
        latest = cycles[0] if cycles else {}
        previous = cycles[1] if len(cycles) > 1 else {}
        now = datetime.now().astimezone()
        newest_bar_dt = self._parse_dt(latest.get("latest_available_historical_bar_at"))
        newest_window_dt = self._parse_dt(latest.get("latest_valid_replay_window_end"))
        threshold = self._freshness_threshold_for_cycle(latest)
        return {
            "newest_historical_bar_timestamp_seen": latest.get("latest_available_historical_bar_at", "-"),
            "newest_replay_window_end_time": latest.get("latest_valid_replay_window_end", "-"),
            "current_system_time": now.isoformat(),
            "age_of_newest_bar": self._format_timedelta(now - newest_bar_dt) if newest_bar_dt else "unknown",
            "age_of_newest_replay_window": self._format_timedelta(now - newest_window_dt) if newest_window_dt else "unknown",
            "freshness_threshold_used": self._format_timedelta(threshold),
            "fresh_historical_bars_detected": self._fresh_historical_bars_detected(
                newest_bar_dt=newest_bar_dt,
                newest_window_dt=newest_window_dt,
                now=now,
                threshold=threshold,
            ),
            "pre_replay_refresh_enabled": latest.get("pre_replay_refresh_enabled", "no"),
            "pre_replay_refresh_dry_run": latest.get("pre_replay_refresh_dry_run", "yes"),
            "pre_replay_refresh_ran": latest.get("pre_replay_refresh_ran", "no"),
            "pre_replay_refresh_mode": latest.get("pre_replay_refresh_mode", "disabled"),
            "pre_replay_refresh_asset_classes": list(
                latest.get("pre_replay_refresh_asset_classes", []) or []
            ),
            "pre_replay_refresh_symbols": dict(latest.get("pre_replay_refresh_symbols", {}) or {}),
            "pre_replay_refresh_safety_guard": latest.get(
                "pre_replay_refresh_safety_guard",
                "historical_backfill_only_no_orders_no_auto_approvals",
            ),
            "latest_bar_before_refresh": latest.get("latest_bar_before_refresh", "-"),
            "latest_bar_after_refresh": latest.get("latest_bar_after_refresh", "-"),
            "bars_inserted_by_refresh": int(latest.get("bars_inserted_by_refresh", 0) or 0),
            "bars_updated_by_refresh": int(latest.get("bars_updated_by_refresh", 0) or 0),
            "refresh_attempted_symbols": dict(latest.get("refresh_attempted_symbols", {}) or {}),
            "refresh_success_symbols": dict(latest.get("refresh_success_symbols", {}) or {}),
            "refresh_failed_symbols": dict(latest.get("refresh_failed_symbols", {}) or {}),
            "refresh_skipped_symbols": dict(latest.get("refresh_skipped_symbols", {}) or {}),
            "refresh_skip_reasons": dict(latest.get("refresh_skip_reasons", {}) or {}),
            "provider_error_count": int(latest.get("provider_error_count", 0) or 0),
            "provider_errors": list(latest.get("provider_errors", []) or []),
            "refresh_error_count": int(latest.get("refresh_error_count", 0) or 0),
            "refresh_errors": list(latest.get("refresh_errors", []) or []),
            "refresh_duration_ms": int(latest.get("refresh_duration_ms", 0) or 0),
            "ingestion_ran_this_cycle": latest.get("ingestion_ran_this_cycle", "no"),
            "bars_inserted_this_cycle": int(latest.get("bars_inserted_this_cycle", 0) or 0),
            "bars_updated_this_cycle": int(latest.get("bars_updated_this_cycle", 0) or 0),
            "latest_bar_before_ingestion": latest.get("latest_bar_before_ingestion", "-"),
            "latest_bar_after_ingestion": latest.get("latest_bar_after_ingestion", "-"),
            "replay_windows_selected_from_latest_available_data": latest.get(
                "replay_windows_selected_from_latest_available_data",
                "unknown",
            ),
            "latest_raw_bar_at": latest.get("latest_raw_bar_at", "-"),
            "rolling_replay_mode_enabled": latest.get("rolling_replay_mode_enabled", "no"),
            "rolling_replay_cursor_enabled": latest.get("rolling_replay_cursor_enabled", "no"),
            "replay_mode": latest.get("replay_mode", "-"),
            "learning_progress_this_cycle": latest.get("learning_progress_this_cycle", "no"),
            "max_future_outcome_horizon": latest.get("max_future_outcome_horizon", "-"),
            "latest_replay_eligible_bar_at": latest.get("latest_replay_eligible_bar_at", "-"),
            "latest_available_bar_per_asset_class": self._render_mapping(
                latest.get("latest_available_bar_per_asset_class", {}) or {}
            ),
            "latest_available_bar_per_symbol": self._render_mapping(
                latest.get("latest_available_bar_per_symbol", {}) or {}
            ),
            "latest_replay_eligible_bar_per_timeframe": self._render_mapping(
                latest.get("latest_replay_eligible_bar_per_timeframe", {}) or {}
            ),
            "latest_replay_eligible_bar_per_asset_class": self._render_mapping(
                latest.get("latest_replay_eligible_bar_per_asset_class", {}) or {}
            ),
            "latest_replay_eligible_at_by_bucket": self._render_mapping(
                latest.get("latest_replay_eligible_at_by_bucket", {}) or {}
            ),
            "previous_replay_eligible_at_by_bucket": self._render_mapping(
                latest.get("previous_replay_eligible_at_by_bucket", {}) or {}
            ),
            "replay_eligible_advance_delta_by_bucket": self._render_mapping(
                latest.get("replay_eligible_advance_delta_by_bucket", {}) or {}
            ),
            "last_replayed_until_by_bucket": self._render_mapping(
                latest.get("last_replayed_until_by_bucket", {}) or {}
            ),
            "unseen_replay_range_available_by_bucket": self._render_mapping(
                latest.get("unseen_replay_range_available_by_bucket", {}) or {}
            ),
            "next_unseen_replay_start_by_bucket": self._render_mapping(
                latest.get("next_unseen_replay_start_by_bucket", {}) or {}
            ),
            "next_unseen_replay_end_by_bucket": self._render_mapping(
                latest.get("next_unseen_replay_end_by_bucket", {}) or {}
            ),
            "candidate_replay_windows_considered": self._render_window_rows(
                latest.get("candidate_replay_windows_considered", []) or []
            ),
            "candidate_replay_windows_rejected": self._render_window_rows(
                latest.get("candidate_replay_windows_rejected", []) or []
            ),
            "selected_replay_windows": self._render_window_rows(
                latest.get("selected_replay_windows", []) or []
            ),
            "selected_replay_window_reason": latest.get(
                "selected_replay_window_reason",
                "-",
            ),
            "max_allowed_replay_window_end": latest.get(
                "max_allowed_replay_window_end",
                "-",
            ),
            "global_anchor_enabled": latest.get("global_anchor_enabled", "-"),
            "global_anchor_time": latest.get("global_anchor_time", "-"),
            "global_anchor_constrained_by_asset_class": latest.get(
                "global_anchor_constrained_by_asset_class",
                "-",
            ),
            "global_anchor_constrained_by_timeframe": latest.get(
                "global_anchor_constrained_by_timeframe",
                "-",
            ),
            "global_anchor_constrained_by_symbol": latest.get(
                "global_anchor_constrained_by_symbol",
                "-",
            ),
            "freshness_lost_to_future_outcome_horizon": latest.get(
                "freshness_lost_to_future_outcome_horizon",
                "-",
            ),
            "freshness_lost_to_global_anchor": latest.get(
                "freshness_lost_to_global_anchor",
                "-",
            ),
            "selected_replay_window_end_by_timeframe": self._render_mapping(
                latest.get("selected_replay_window_end_by_timeframe", {}) or {}
            ),
            "selected_replay_window_end_by_asset_class": self._render_mapping(
                latest.get("selected_replay_window_end_by_asset_class", {}) or {}
            ),
            "selected_replay_window_end_by_bucket": self._render_mapping(
                latest.get("selected_replay_window_end_by_bucket", {}) or {}
            ),
            "accepted_replay_window_count_by_timeframe": self._render_mapping(
                latest.get("accepted_replay_window_count_by_timeframe", {}) or {}
            ),
            "accepted_replay_window_count_by_asset_class": self._render_mapping(
                latest.get("accepted_replay_window_count_by_asset_class", {}) or {}
            ),
            "selected_anchor_time_by_bucket": self._render_mapping(
                latest.get("selected_anchor_time_by_bucket", {}) or {}
            ),
            "candidate_anchor_time_by_bucket": self._render_mapping(
                latest.get("candidate_anchor_time_by_bucket", {}) or {}
            ),
            "rejected_bucket_anchor_time_by_bucket": self._render_mapping(
                latest.get("rejected_bucket_anchor_time_by_bucket", {}) or {}
            ),
            "freshness_gain_vs_global_by_bucket": self._render_mapping(
                latest.get("freshness_gain_vs_global_by_bucket", {}) or {}
            ),
            "windows_selected_by_bucket": self._render_mapping(
                latest.get("windows_selected_by_bucket", {}) or {}
            ),
            "windows_rejected_by_bucket": self._render_mapping(
                latest.get("windows_rejected_by_bucket", {}) or {}
            ),
            "bucket_rejection_reasons": self._render_mapping(
                latest.get("bucket_rejection_reasons", {}) or {}
            ),
            "replay_selection_mode": latest.get("replay_selection_mode", "-"),
            "alternative_replay_selection_modes_available": latest.get(
                "alternative_replay_selection_modes_available",
                "-",
            ),
            "simulated_asset_class_anchor_time": self._render_mapping(
                latest.get("simulated_asset_class_anchor_time", {}) or {}
            ),
            "simulated_asset_class_and_timeframe_anchor_time": self._render_mapping(
                latest.get("simulated_asset_class_and_timeframe_anchor_time", {}) or {}
            ),
            "simulated_freshness_gain_by_asset_class": self._render_mapping(
                latest.get("simulated_freshness_gain_by_asset_class", {}) or {}
            ),
            "simulated_freshness_gain_by_asset_class_and_timeframe": self._render_mapping(
                latest.get(
                    "simulated_freshness_gain_by_asset_class_and_timeframe",
                    {},
                )
                or {}
            ),
            "strategies_helped_by_isolated_replay": ",".join(
                latest.get("strategies_helped_by_isolated_replay", []) or []
            )
            or "-",
            "strategies_unaffected_by_isolated_replay": ",".join(
                latest.get("strategies_unaffected_by_isolated_replay", []) or []
            )
            or "-",
            "strategies_blocked_by_mixed_global_anchor": ",".join(
                latest.get("strategies_blocked_by_mixed_global_anchor", []) or []
            )
            or "-",
            "minimum_required_window_completeness": latest.get(
                "minimum_required_window_completeness",
                "-",
            ),
            "lookback_window_policy": latest.get("lookback_window_policy", "-"),
            "warmup_buffer_policy": latest.get("warmup_buffer_policy", "-"),
            "market_hours_policy": latest.get("market_hours_policy", "-"),
            "weekend_policy": latest.get("weekend_policy", "-"),
            "asset_class_window_policy": latest.get("asset_class_window_policy", "-"),
            "reason_latest_bars_not_used_for_replay": latest.get(
                "reason_latest_bars_not_used_for_replay",
                "-",
            ),
            "plain_english_replay_anchor_explanation": latest.get(
                "plain_english_replay_anchor_explanation",
                "-",
            ),
            "reason_if_not": latest.get("reason_if_not", "-") or "-",
            "selected_window_ids_current": self._render_mapping(
                latest.get("selected_window_ids_current", {}) or {}
            ),
            "selected_window_ids_previous": self._render_mapping(
                latest.get("selected_window_ids_previous", {}) or {}
            ),
            "selected_window_set_changed": latest.get("selected_window_set_changed", "-"),
            "new_replay_windows_selected_count": int(
                latest.get("new_replay_windows_selected_count", 0) or 0
            ),
            "duplicate_replay_windows_skipped_count": int(
                latest.get("duplicate_replay_windows_skipped_count", 0) or 0
            ),
            "replay_evidence_new_rows_inserted": int(
                latest.get("replay_evidence_new_rows_inserted", 0) or 0
            ),
            "replay_evidence_duplicate_rows_skipped": int(
                latest.get("replay_evidence_duplicate_rows_skipped", 0) or 0
            ),
            "reason_replay_window_not_advancing": latest.get(
                "reason_replay_window_not_advancing",
                "-",
            ),
            "reason_no_learning_progress": latest.get("reason_no_learning_progress", "-"),
            "replay_window_set_changed_from_previous_real_cycle": self._replay_window_set_changed(
                latest=latest,
                previous=previous,
            ),
            "latest_persisted_cycle_id": latest_persisted.get("tick_id", "-") or "-",
            "latest_persisted_cycle_time": latest_persisted.get("started_at", "-") or "-",
            "latest_persisted_cycle_origin": latest_persisted.get("cycle_origin", "-") or "-",
            "latest_persisted_command_source": latest_persisted.get("command_source", "-") or "-",
            "latest_persisted_cycle_included_in_self_improvement": (
                "yes"
                if bool(latest_persisted.get("included_in_self_improvement"))
                else ("no" if latest_persisted else "-")
            ),
            "latest_persisted_cycle_exclusion_reason": (
                latest_persisted.get("exclusion_reason", "-") or "-"
            ),
            "latest_qualifying_self_improvement_cycle_id": latest.get("tick_id", "-") or "-",
            "latest_qualifying_self_improvement_cycle_time": latest.get("started_at", "-") or "-",
        }

    def _render_mapping(self, value: dict[str, Any]) -> str:
        if not value:
            return "-"
        return ",".join(f"{key}:{value[key]}" for key in sorted(value))

    def _render_window_rows(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "-"
        rendered: list[str] = []
        for row in rows:
            parts = [
                f"bucket={row.get('bucket', '-')}",
                f"asset_class={row.get('asset_class', '-')}",
                f"timeframe={row.get('timeframe', '-')}",
                f"window_index={row.get('window_index', '-')}",
                f"start_at={row.get('start_at', '-')}",
                f"end_at={row.get('end_at', '-')}",
                f"reason={row.get('reason', '-')}",
            ]
            rendered.append("|".join(parts))
        return ";".join(rendered)

    def _build_stuck_section(
        self,
        *,
        cycles: list[dict[str, Any]],
        freshness: dict[str, Any],
    ) -> dict[str, Any]:
        blocker_streak = self._same_top_blocker_cycles(cycles)
        improvement_gap = self._cycles_without_strategy_improvement(cycles)
        sample_size_increasing = self._sample_size_increasing(cycles)
        fresh_bars = str(freshness.get("fresh_historical_bars_detected", "unknown"))
        replay_window_changed = str(
            freshness.get("replay_window_set_changed_from_previous_real_cycle", "unknown")
        )
        replay_window_advancing = (
            "yes" if replay_window_changed == "yes" else
            "no" if replay_window_changed == "no" else
            replay_window_changed
        )
        all_research_only = len(cycles) >= STUCK_CYCLE_THRESHOLD and all(item["all_research_only"] for item in cycles[:STUCK_CYCLE_THRESHOLD])
        no_paper_sim = len(cycles) >= STUCK_CYCLE_THRESHOLD and all(item["profiles_with_paper_sim_evidence"] <= 0 for item in cycles[:STUCK_CYCLE_THRESHOLD])
        blocker_counts_recent = self._aggregate_blocker_counts(cycles[: max(1, len(cycles) // 2)])
        blocker_counts_previous = self._aggregate_blocker_counts(cycles[max(1, len(cycles) // 2) :])
        dominant_blocker = blocker_counts_recent.most_common(1)[0][0] if blocker_counts_recent else "none"
        blocker_trend = self._counter_trend(
            recent=blocker_counts_recent,
            previous=blocker_counts_previous,
            key=dominant_blocker,
        )
        strategy_trends = self._strategy_trends(cycles=cycles)
        strategies_improving_count = sum(1 for item in strategy_trends if item.get("trend") == "improving")
        strategies_degrading_count = sum(1 for item in strategy_trends if item.get("trend") == "degrading")
        strategies_flat_count = sum(1 for item in strategy_trends if item.get("trend") == "flat")
        system_stuck_reasons = []
        strategy_stuck_reasons = []
        if fresh_bars == "no":
            system_stuck_reasons.append("historical_bars_not_fresh")
        if blocker_streak >= STUCK_CYCLE_THRESHOLD:
            strategy_stuck_reasons.append("same_top_blocker_dominates")
        if improvement_gap >= STUCK_CYCLE_THRESHOLD:
            strategy_stuck_reasons.append("no_strategy_improvement")
        if no_paper_sim and blocker_streak >= STUCK_CYCLE_THRESHOLD:
            strategy_stuck_reasons.append("no_paper_sim_evidence")
        if sample_size_increasing == "no" and (
            blocker_streak >= STUCK_CYCLE_THRESHOLD or improvement_gap >= STUCK_CYCLE_THRESHOLD
        ):
            strategy_stuck_reasons.append("sample_size_not_increasing")
        if all_research_only and (
            blocker_streak >= STUCK_CYCLE_THRESHOLD or replay_window_advancing == "no"
        ):
            strategy_stuck_reasons.append("all_strategies_research_only_too_long")
        if replay_window_advancing == "no" and fresh_bars != "no":
            strategy_stuck_reasons.append("stale_replay_window_set")
        if strategies_improving_count > 0 and strategies_degrading_count == 0:
            strategy_stuck_reasons = [
                reason
                for reason in strategy_stuck_reasons
                if reason not in {"no_strategy_improvement", "sample_size_not_increasing"}
            ]
        stuck_reasons = [*system_stuck_reasons, *strategy_stuck_reasons]
        return {
            "stuck_detected": bool(stuck_reasons),
            "stuck_reason": ",".join(stuck_reasons) if stuck_reasons else "none",
            "same_top_blocker_cycles": blocker_streak,
            "cycles_without_strategy_improvement": improvement_gap,
            "fresh_historical_bars_detected": fresh_bars,
            "replay_window_advancing": replay_window_advancing,
            "stale_replay_window_set_detected": "yes"
            if replay_window_advancing == "no"
            else ("no" if replay_window_advancing == "yes" else replay_window_advancing),
            "sample_size_increasing": sample_size_increasing,
            "strategies_improving_count": strategies_improving_count,
            "strategies_degrading_count": strategies_degrading_count,
            "strategies_flat_count": strategies_flat_count,
            "blocker_counts_recent": self._render_counter(blocker_counts_recent),
            "blocker_counts_previous": self._render_counter(blocker_counts_previous),
            "dominant_blocker": dominant_blocker,
            "dominant_blocker_cycles": blocker_streak if dominant_blocker not in {"none", "-"} else 0,
            "blocker_trend": blocker_trend,
            "system_stuck": bool(system_stuck_reasons),
            "strategy_evidence_stuck": bool(strategy_stuck_reasons),
            "all_research_only_too_long": all_research_only,
            "strategy_trends": strategy_trends,
        }

    def _final_verdict(
        self,
        *,
        cycles: list[dict[str, Any]],
        quality: dict[str, Any],
        stuck: dict[str, Any],
    ) -> tuple[str, str]:
        if len(cycles) < 2:
            return (
                "insufficient_history",
                "Centaur has real persisted learning evidence, but there is not enough history yet to judge improvement.",
            )
        if stuck.get("stuck_detected"):
            dominant_blocker = str(stuck.get("dominant_blocker", "unknown") or "unknown")
            if stuck.get("system_stuck") and not stuck.get("strategy_evidence_stuck"):
                return (
                    "stuck",
                    "Centaur is running, but infrastructure freshness is stuck. Historical bars or replay window movement are not healthy enough for reliable evidence rotation.",
                )
            return (
                "stuck",
                "Centaur is operating correctly and collecting fresh replay evidence, but strategy evidence is not improving. "
                f"The dominant blocker is {dominant_blocker}. No paper/live trades are created because no strategy is promotion eligible.",
            )
        quality_status = str(quality.get("evidence_quality_status", "insufficient_history"))
        if quality_status == "improving":
            return (
                "improving",
                "Centaur is learning from real replay data and recent cycles show better evidence quality than earlier cycles, even though promotion gates remain closed.",
            )
        if quality_status == "degrading":
            return (
                "degrading",
                "Centaur is learning from real replay data, but recent net return or win-rate evidence has weakened versus earlier cycles.",
            )
        return (
            "flat_collecting_evidence",
            f"Centaur is learning from real replay data, but has not improved enough to promote any strategy. The dominant blocker is {cycles[0].get('top_blocker', 'unknown')}. Keep collecting evidence.",
        )

    def _evidence_score(
        self,
        *,
        net_return: float,
        win_rate: float,
        sample_size: int,
        failed_gates: list[str],
    ) -> int:
        score = 50
        score += min(20, max(-20, round(net_return * 100)))
        score += min(20, max(-20, round((win_rate - 0.5) * 100)))
        sample_ratio = min(1.0, sample_size / max(1, int(self.config.research_min_proposals)))
        score += round(sample_ratio * 10)
        score -= min(30, len(failed_gates) * 8)
        return max(0, min(100, score))

    def _required_improvement(self, item: dict[str, Any]) -> str:
        parts: list[str] = []
        net_gap = float(self.config.research_min_net_return_pct) - float(item["net_return"])
        win_gap = float(self.config.research_min_net_win_rate) - float(item["win_rate"])
        sample_gap = int(self.config.research_min_proposals) - int(item["sample_size"])
        if net_gap > 0:
            parts.append(f"net_return must improve by {self._fmt_pct(net_gap)}")
        if win_gap > 0:
            parts.append(f"win_rate must improve by {self._fmt_pct(win_gap)}")
        if sample_gap > 0:
            parts.append(f"sample_size must increase by {sample_gap}")
        return " and ".join(parts) if parts else "already_meets_current_replay_thresholds"

    def _same_top_blocker_cycles(self, cycles: list[dict[str, Any]]) -> int:
        if not cycles:
            return 0
        top = cycles[0].get("top_blocker", "none")
        if top in {"", "none", "-"}:
            return 0
        streak = 0
        for item in cycles:
            if item.get("top_blocker", "none") != top:
                break
            streak += 1
        return streak

    def _cycles_without_strategy_improvement(self, cycles: list[dict[str, Any]]) -> int:
        if not cycles:
            return 0
        best_score = None
        streak = 0
        for item in reversed(cycles):
            profile = item.get("best_profile")
            score = profile.get("score", 0) if isinstance(profile, dict) else 0
            if best_score is None or score > best_score:
                best_score = score
                streak = 0
            else:
                streak += 1
        return streak

    def _aggregate_blocker_counts(self, cycles: list[dict[str, Any]]) -> Counter[str]:
        counts: Counter[str] = Counter()
        for item in cycles:
            counts.update(item.get("blocker_counts", Counter()))
        return counts

    def _render_counter(self, value: Counter[str]) -> str:
        if not value:
            return "-"
        return ",".join(f"{key}:{count}" for key, count in value.most_common())

    def _counter_trend(self, *, recent: Counter[str], previous: Counter[str], key: str) -> str:
        if key in {"", "-", "none"}:
            return "unchanged"
        recent_count = int(recent.get(key, 0))
        previous_count = int(previous.get(key, 0))
        if recent_count > previous_count:
            return "worsening"
        if recent_count < previous_count:
            return "reducing"
        return "unchanged"

    def _strategy_trends(self, *, cycles: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if len(cycles) < 2:
            return []
        recent_cycles, previous_cycles = self._split_recent_vs_previous(cycles)
        recent_profiles = self._aggregate_profiles(recent_cycles)
        previous_profiles = self._aggregate_profiles(previous_cycles)
        rows: list[dict[str, Any]] = []
        for key in sorted(set(recent_profiles) | set(previous_profiles)):
            recent = recent_profiles.get(key)
            previous = previous_profiles.get(key)
            if not recent and not previous:
                continue
            recent_score = int((recent or {}).get("avg_score", 0))
            previous_score = int((previous or {}).get("avg_score", 0))
            distance_recent = max(0, 100 - recent_score)
            distance_previous = max(0, 100 - previous_score)
            distance_delta = distance_previous - distance_recent
            trend = "flat"
            if distance_delta > 0:
                trend = "improving"
            elif distance_delta < 0:
                trend = "degrading"
            rows.append(
                {
                    "strategy_id": key[0],
                    "profile_id": key[1],
                    "checkpoint": (recent or previous or {}).get("checkpoint", "-"),
                    "previous_net_return": self._fmt_pct((previous or {}).get("avg_net_return", 0.0)),
                    "recent_net_return": self._fmt_pct((recent or {}).get("avg_net_return", 0.0)),
                    "net_return_delta": self._fmt_pct(
                        float((recent or {}).get("avg_net_return", 0.0))
                        - float((previous or {}).get("avg_net_return", 0.0))
                    ),
                    "previous_win_rate": self._fmt_pct((previous or {}).get("avg_win_rate", 0.0)),
                    "recent_win_rate": self._fmt_pct((recent or {}).get("avg_win_rate", 0.0)),
                    "win_rate_delta": self._fmt_pct(
                        float((recent or {}).get("avg_win_rate", 0.0))
                        - float((previous or {}).get("avg_win_rate", 0.0))
                    ),
                    "previous_sample_size": int((previous or {}).get("sample_size", 0)),
                    "recent_sample_size": int((recent or {}).get("sample_size", 0)),
                    "sample_size_delta": int((recent or {}).get("sample_size", 0))
                    - int((previous or {}).get("sample_size", 0)),
                    "distance_to_paper_candidate_previous": f"{distance_previous}%",
                    "distance_to_paper_candidate_recent": f"{distance_recent}%",
                    "distance_delta": f"{distance_delta:+d}%",
                    "trend": trend,
                }
            )
        rows.sort(key=lambda item: ({"improving": 0, "flat": 1, "degrading": 2}.get(str(item.get("trend")), 3), str(item.get("strategy_id")), str(item.get("profile_id"))))
        return rows

    def _aggregate_profiles(self, cycles: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
        grouped: dict[tuple[str, str], list[dict[str, Any]]] = {}
        for cycle in cycles:
            for profile in list(cycle.get("profiles", []) or []):
                key = (str(profile.get("strategy_id", "-")), str(profile.get("profile_id", "-")))
                grouped.setdefault(key, []).append(profile)
        aggregated: dict[tuple[str, str], dict[str, Any]] = {}
        for key, items in grouped.items():
            aggregated[key] = {
                "checkpoint": items[0].get("checkpoint", "-"),
                "avg_net_return": self._safe_mean(float(item.get("net_return", 0.0) or 0.0) for item in items),
                "avg_win_rate": self._safe_mean(float(item.get("win_rate", 0.0) or 0.0) for item in items),
                "sample_size": sum(int(item.get("sample_size", 0) or 0) for item in items),
                "avg_score": round(self._safe_mean(float(item.get("score", 0) or 0) for item in items)),
            }
        return aggregated

    def _fresh_historical_bars_detected(
        self,
        *,
        newest_bar_dt: datetime | None,
        newest_window_dt: datetime | None,
        now: datetime,
        threshold: timedelta,
    ) -> str:
        candidates = [value for value in (newest_bar_dt, newest_window_dt) if isinstance(value, datetime)]
        if not candidates:
            return "unknown"
        freshest = max(candidates)
        return "yes" if now - freshest <= threshold else "no"

    def _replay_window_set_changed(
        self,
        *,
        latest: dict[str, Any],
        previous: dict[str, Any],
    ) -> str:
        explicit = str(latest.get("selected_window_set_changed", "") or "").strip()
        if explicit in {"yes", "no", "unknown"}:
            return explicit
        latest_value = str(latest.get("latest_valid_replay_window_end", "") or "").strip()
        previous_value = str(previous.get("latest_valid_replay_window_end", "") or "").strip()
        if not latest_value or not previous_value:
            return "unknown"
        return "yes" if latest_value != previous_value else "no"

    def _sample_size_increasing(self, cycles: list[dict[str, Any]]) -> str:
        if len(cycles) < 2:
            return "unknown"
        recent = cycles[0]["total_sample_size"]
        previous = cycles[1]["total_sample_size"]
        if recent > previous:
            return "yes"
        if recent < previous:
            return "no"
        return "unknown"

    def _metric_trend(self, recent: float, previous: float) -> str:
        if recent > previous + 1e-9:
            return "improving"
        if recent < previous - 1e-9:
            return "degrading"
        return "flat"

    def _sample_trend(self, recent: float, previous: float) -> str:
        if recent > previous:
            return "increasing"
        if recent < previous:
            return "decreasing"
        return "flat"

    def _blocker_trend(self, *, recent: str, previous: str) -> str:
        if previous in {"", "-", "none"}:
            return "insufficient_history"
        if recent == previous:
            return "unchanged"
        if recent in {"", "none"}:
            return "reducing"
        return "worsening"

    def _profile_trend(self, recent: dict[str, Any] | None, previous: dict[str, Any] | None, invert: bool = False) -> str:
        if not recent or not previous:
            return "insufficient_history"
        recent_label = self._profile_label(recent)
        previous_label = self._profile_label(previous)
        if recent_label != previous_label:
            return "changed"
        recent_score = float(recent.get("score", 0) or 0)
        previous_score = float(previous.get("score", 0) or 0)
        if invert:
            if recent_score < previous_score:
                return "improving"
            if recent_score > previous_score:
                return "degrading"
        else:
            if recent_score > previous_score:
                return "improving"
            if recent_score < previous_score:
                return "degrading"
        return "unchanged"

    def _evidence_quality_status(self, *, net_trend: str, win_trend: str, sample_trend: str) -> str:
        if "insufficient_history" in {net_trend, win_trend, sample_trend}:
            return "insufficient_history"
        if net_trend == "improving" and win_trend in {"improving", "flat"} and sample_trend == "increasing":
            return "improving"
        if net_trend == "degrading" or win_trend == "degrading":
            return "degrading"
        return "flat"

    def _best_checkpoint(self, item: dict[str, Any]) -> str:
        checkpoint = str(item.get("timeframe", "") or "").strip()
        return checkpoint or str(item.get("checkpoint_code", "") or "-") or "-"

    def _profile_rank_key(self, item: dict[str, Any]) -> tuple[int, int, float, float, float]:
        return (
            1 if item.get("has_real_evidence") else 0,
            int(item.get("sample_size", 0) or 0),
            float(item.get("score", 0) or 0),
            float(item.get("net_return", 0.0) or 0.0),
            float(item.get("win_rate", 0.0) or 0.0),
        )

    def _profile_bottom_rank_key(self, item: dict[str, Any]) -> tuple[int, int, float, float, float]:
        return (
            0 if item.get("has_real_evidence") else 1,
            -int(item.get("sample_size", 0) or 0),
            -float(item.get("score", 0) or 0),
            -float(item.get("net_return", 0.0) or 0.0),
            -float(item.get("win_rate", 0.0) or 0.0),
        )

    def _freshness_threshold_for_cycle(self, cycle: dict[str, Any]) -> timedelta:
        timeframe = str(cycle.get("timeframe", "") or cycle.get("best_checkpoint", "") or "15Min")
        timeframe_delta = self._parse_timeframe_to_timedelta(timeframe) or timedelta(minutes=15)
        return max(timedelta(minutes=30), timeframe_delta * 2)

    def _profile_label(self, item: dict[str, Any] | None) -> str:
        if not item:
            return "-"
        return f"{item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"

    def _series(self, cycles: list[dict[str, Any]], key: str) -> str:
        if not cycles:
            return "-"
        return ",".join(str(item.get(key, 0)) for item in reversed(cycles[:8]))

    def _safe_mean(self, values: Any) -> float:
        materialized = [float(value) for value in values]
        return float(mean(materialized)) if materialized else 0.0

    def _parse_dt(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        text = str(value or "").strip()
        if not text or text == "-":
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            return None

    def _parse_timeframe_to_timedelta(self, value: str) -> timedelta | None:
        text = str(value or "").strip().lower()
        if not text:
            return None
        if text.endswith("min") and text[:-3].isdigit():
            return timedelta(minutes=int(text[:-3]))
        if text.endswith("m") and text[:-1].isdigit():
            return timedelta(minutes=int(text[:-1]))
        if text.endswith("hour") and text[:-4].isdigit():
            return timedelta(hours=int(text[:-4]))
        if text.endswith("h") and text[:-1].isdigit():
            return timedelta(hours=int(text[:-1]))
        if text.endswith("day") and text[:-3].isdigit():
            return timedelta(days=int(text[:-3]))
        if text.endswith("d") and text[:-1].isdigit():
            return timedelta(days=int(text[:-1]))
        return None

    def _format_timedelta(self, value: timedelta) -> str:
        total_seconds = max(0, int(value.total_seconds()))
        days, remainder = divmod(total_seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, seconds = divmod(remainder, 60)
        parts: list[str] = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        if minutes or hours or days:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        return "".join(parts)

    def _fmt_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")

    def _fmt_pct(self, value: float) -> str:
        return f"{value:+.2%}"
