from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.framework.engine.replay import _max_checkpoint_window_minutes, _window_code_to_minutes
from app.framework.engine.research_cycle import ResearchCycleRunner
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class HistoricalReplayCoverageReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_report(self) -> dict[str, Any]:
        runner = ResearchCycleRunner(config=self.config, usage_ledger=self.usage_ledger)
        as_of = datetime.now().astimezone()
        diagnostics = runner.build_historical_replay_diagnostics(
            end_at=as_of,
            pre_replay_refresh=runner._run_pre_replay_historical_refresh(as_of=as_of),
        )
        inventory = diagnostics["inventory"]
        historical = dict(inventory.get("historical", {}) or {})
        sources = [str(item.get("source", "") or "") for item in historical.get("rows_by_source", [])]
        timeframes = [str(item.get("timeframe", "") or "") for item in historical.get("rows_by_timeframe", [])]
        symbol_timeframe_rows = self._symbol_timeframe_rows()
        return {
            "backend": inventory.get("backend"),
            "backend_detail": inventory.get("backend_detail"),
            "historical": historical,
            "available_sources": sources,
            "available_timeframes": timeframes,
            "symbol_timeframe_rows": symbol_timeframe_rows,
            "timeframe_existence": {
                "1Min": "1Min" in timeframes,
                "15Min": "15Min" in timeframes,
                "1Hour": "1Hour" in timeframes,
            },
            "pre_replay_refresh": {
                "pre_replay_refresh_enabled": diagnostics.get(
                    "pre_replay_refresh_enabled", "no"
                ),
                "pre_replay_refresh_dry_run": diagnostics.get(
                    "pre_replay_refresh_dry_run", "yes"
                ),
                "pre_replay_refresh_ran": diagnostics.get("pre_replay_refresh_ran", "no"),
                "pre_replay_refresh_mode": diagnostics.get(
                    "pre_replay_refresh_mode",
                    "disabled",
                ),
                "pre_replay_refresh_asset_classes": list(
                    diagnostics.get("pre_replay_refresh_asset_classes", []) or []
                ),
                "pre_replay_refresh_symbols": dict(
                    diagnostics.get("pre_replay_refresh_symbols", {}) or {}
                ),
                "pre_replay_refresh_safety_guard": diagnostics.get(
                    "pre_replay_refresh_safety_guard",
                    "historical_backfill_only_no_orders_no_auto_approvals",
                ),
                "ingestion_ran_this_cycle": diagnostics.get("ingestion_ran_this_cycle", "no"),
                "bars_inserted_this_cycle": int(
                    diagnostics.get("bars_inserted_this_cycle", 0) or 0
                ),
                "bars_updated_this_cycle": int(
                    diagnostics.get("bars_updated_this_cycle", 0) or 0
                ),
                "latest_bar_before_ingestion": diagnostics.get(
                    "latest_bar_before_ingestion"
                ),
                "latest_bar_after_ingestion": diagnostics.get("latest_bar_after_ingestion"),
                "latest_bar_before_refresh": diagnostics.get("latest_bar_before_refresh"),
                "latest_bar_after_refresh": diagnostics.get("latest_bar_after_refresh"),
                "bars_inserted_by_refresh": int(
                    diagnostics.get("bars_inserted_by_refresh", 0) or 0
                ),
                "bars_updated_by_refresh": int(
                    diagnostics.get("bars_updated_by_refresh", 0) or 0
                ),
                "refresh_attempted_symbols": dict(
                    diagnostics.get("refresh_attempted_symbols", {}) or {}
                ),
                "refresh_success_symbols": dict(
                    diagnostics.get("refresh_success_symbols", {}) or {}
                ),
                "refresh_failed_symbols": dict(
                    diagnostics.get("refresh_failed_symbols", {}) or {}
                ),
                "refresh_skipped_symbols": dict(
                    diagnostics.get("refresh_skipped_symbols", {}) or {}
                ),
                "refresh_skip_reasons": dict(
                    diagnostics.get("refresh_skip_reasons", {}) or {}
                ),
                "provider_error_count": int(diagnostics.get("provider_error_count", 0) or 0),
                "provider_errors": list(diagnostics.get("provider_errors", []) or []),
                "replay_windows_selected_from_latest_available_data": diagnostics.get(
                    "replay_windows_selected_from_latest_available_data",
                    "unknown",
                ),
                "rolling_replay_mode_enabled": diagnostics.get("rolling_replay_mode_enabled", "no"),
                "rolling_replay_cursor_enabled": diagnostics.get("rolling_replay_cursor_enabled", "no"),
                "replay_mode": diagnostics.get("replay_mode", "-"),
                "learning_progress_this_cycle": diagnostics.get("learning_progress_this_cycle", "no"),
                "latest_raw_bar_at": diagnostics.get("latest_raw_bar_at"),
                "max_future_outcome_horizon": diagnostics.get(
                    "max_future_outcome_horizon",
                    "-",
                ),
                "latest_replay_eligible_bar_at": diagnostics.get(
                    "latest_replay_eligible_bar_at"
                ),
                "latest_available_bar_per_asset_class": dict(
                    diagnostics.get("latest_available_bar_per_asset_class", {}) or {}
                ),
                "latest_available_bar_per_symbol": dict(
                    diagnostics.get("latest_available_bar_per_symbol", {}) or {}
                ),
                "latest_replay_eligible_bar_per_timeframe": dict(
                    diagnostics.get("latest_replay_eligible_bar_per_timeframe", {}) or {}
                ),
                "latest_replay_eligible_bar_per_asset_class": dict(
                    diagnostics.get("latest_replay_eligible_bar_per_asset_class", {}) or {}
                ),
                "latest_replay_eligible_at_by_bucket": dict(
                    diagnostics.get("latest_replay_eligible_at_by_bucket", {}) or {}
                ),
                "previous_replay_eligible_at_by_bucket": dict(
                    diagnostics.get("previous_replay_eligible_at_by_bucket", {}) or {}
                ),
                "replay_eligible_advance_delta_by_bucket": dict(
                    diagnostics.get("replay_eligible_advance_delta_by_bucket", {}) or {}
                ),
                "last_replayed_until_by_bucket": dict(
                    diagnostics.get("last_replayed_until_by_bucket", {}) or {}
                ),
                "unseen_replay_range_available_by_bucket": dict(
                    diagnostics.get("unseen_replay_range_available_by_bucket", {}) or {}
                ),
                "next_unseen_replay_start_by_bucket": dict(
                    diagnostics.get("next_unseen_replay_start_by_bucket", {}) or {}
                ),
                "next_unseen_replay_end_by_bucket": dict(
                    diagnostics.get("next_unseen_replay_end_by_bucket", {}) or {}
                ),
                "candidate_replay_windows_considered": list(
                    diagnostics.get("candidate_replay_windows_considered", []) or []
                ),
                "candidate_replay_windows_rejected": list(
                    diagnostics.get("candidate_replay_windows_rejected", []) or []
                ),
                "selected_replay_windows": list(
                    diagnostics.get("selected_replay_windows", []) or []
                ),
                "selected_replay_window_reason": diagnostics.get(
                    "selected_replay_window_reason",
                    "-",
                ),
                "max_allowed_replay_window_end": diagnostics.get(
                    "max_allowed_replay_window_end",
                    "",
                ),
                "global_anchor_enabled": diagnostics.get("global_anchor_enabled", "-"),
                "global_anchor_time": diagnostics.get("global_anchor_time", ""),
                "global_anchor_constrained_by_asset_class": diagnostics.get(
                    "global_anchor_constrained_by_asset_class",
                    "",
                ),
                "global_anchor_constrained_by_timeframe": diagnostics.get(
                    "global_anchor_constrained_by_timeframe",
                    "",
                ),
                "global_anchor_constrained_by_symbol": diagnostics.get(
                    "global_anchor_constrained_by_symbol",
                    "",
                ),
                "freshness_lost_to_future_outcome_horizon": diagnostics.get(
                    "freshness_lost_to_future_outcome_horizon",
                    "-",
                ),
                "freshness_lost_to_global_anchor": diagnostics.get(
                    "freshness_lost_to_global_anchor",
                    "-",
                ),
                "selected_replay_window_end_by_timeframe": dict(
                    diagnostics.get("selected_replay_window_end_by_timeframe", {}) or {}
                ),
                "selected_replay_window_end_by_asset_class": dict(
                    diagnostics.get("selected_replay_window_end_by_asset_class", {}) or {}
                ),
                "selected_replay_window_end_by_bucket": dict(
                    diagnostics.get("selected_replay_window_end_by_bucket", {}) or {}
                ),
                "accepted_replay_window_count_by_timeframe": dict(
                    diagnostics.get("accepted_replay_window_count_by_timeframe", {}) or {}
                ),
                "accepted_replay_window_count_by_asset_class": dict(
                    diagnostics.get("accepted_replay_window_count_by_asset_class", {}) or {}
                ),
                "selected_anchor_time_by_bucket": dict(
                    diagnostics.get("selected_anchor_time_by_bucket", {}) or {}
                ),
                "candidate_anchor_time_by_bucket": dict(
                    diagnostics.get("candidate_anchor_time_by_bucket", {}) or {}
                ),
                "rejected_bucket_anchor_time_by_bucket": dict(
                    diagnostics.get("rejected_bucket_anchor_time_by_bucket", {}) or {}
                ),
                "freshness_gain_vs_global_by_bucket": dict(
                    diagnostics.get("freshness_gain_vs_global_by_bucket", {}) or {}
                ),
                "windows_selected_by_bucket": dict(
                    diagnostics.get("windows_selected_by_bucket", {}) or {}
                ),
                "windows_rejected_by_bucket": dict(
                    diagnostics.get("windows_rejected_by_bucket", {}) or {}
                ),
                "bucket_rejection_reasons": dict(
                    diagnostics.get("bucket_rejection_reasons", {}) or {}
                ),
                "replay_selection_mode": diagnostics.get(
                    "replay_selection_mode",
                    "global",
                ),
                "alternative_replay_selection_modes_available": diagnostics.get(
                    "alternative_replay_selection_modes_available",
                    "no",
                ),
                "simulated_asset_class_anchor_time": dict(
                    diagnostics.get("simulated_asset_class_anchor_time", {}) or {}
                ),
                "simulated_asset_class_and_timeframe_anchor_time": dict(
                    diagnostics.get(
                        "simulated_asset_class_and_timeframe_anchor_time",
                        {},
                    )
                    or {}
                ),
                "simulated_freshness_gain_by_asset_class": dict(
                    diagnostics.get("simulated_freshness_gain_by_asset_class", {}) or {}
                ),
                "simulated_freshness_gain_by_asset_class_and_timeframe": dict(
                    diagnostics.get(
                        "simulated_freshness_gain_by_asset_class_and_timeframe",
                        {},
                    )
                    or {}
                ),
                "strategies_helped_by_isolated_replay": list(
                    diagnostics.get("strategies_helped_by_isolated_replay", []) or []
                ),
                "strategies_unaffected_by_isolated_replay": list(
                    diagnostics.get("strategies_unaffected_by_isolated_replay", []) or []
                ),
                "strategies_blocked_by_mixed_global_anchor": list(
                    diagnostics.get("strategies_blocked_by_mixed_global_anchor", []) or []
                ),
                "minimum_required_window_completeness": diagnostics.get(
                    "minimum_required_window_completeness",
                    "-",
                ),
                "lookback_window_policy": diagnostics.get("lookback_window_policy", "-"),
                "warmup_buffer_policy": diagnostics.get("warmup_buffer_policy", "-"),
                "market_hours_policy": diagnostics.get("market_hours_policy", "-"),
                "weekend_policy": diagnostics.get("weekend_policy", "-"),
                "asset_class_window_policy": diagnostics.get(
                    "asset_class_window_policy",
                    "-",
                ),
                "reason_latest_bars_not_used_for_replay": diagnostics.get(
                    "reason_latest_bars_not_used_for_replay",
                    "",
                ),
                "plain_english_replay_anchor_explanation": diagnostics.get(
                    "plain_english_replay_anchor_explanation",
                    "",
                ),
                "reason_if_not": diagnostics.get("reason_if_not", ""),
                "selected_window_ids_current": dict(
                    diagnostics.get("selected_window_ids_current", {}) or {}
                ),
                "selected_window_ids_previous": dict(
                    diagnostics.get("selected_window_ids_previous", {}) or {}
                ),
                "selected_window_set_changed": diagnostics.get("selected_window_set_changed", "-"),
                "new_replay_windows_selected_count": int(
                    diagnostics.get("new_replay_windows_selected_count", 0) or 0
                ),
                "duplicate_replay_windows_skipped_count": int(
                    diagnostics.get("duplicate_replay_windows_skipped_count", 0) or 0
                ),
                "replay_evidence_new_rows_inserted": int(
                    diagnostics.get("replay_evidence_new_rows_inserted", 0) or 0
                ),
                "replay_evidence_duplicate_rows_skipped": int(
                    diagnostics.get("replay_evidence_duplicate_rows_skipped", 0) or 0
                ),
                "reason_replay_window_not_advancing": diagnostics.get(
                    "reason_replay_window_not_advancing",
                    "-",
                ),
                "reason_no_learning_progress": diagnostics.get("reason_no_learning_progress", "-"),
                "asset_class_freshness_status": dict(
                    diagnostics.get("asset_class_freshness_status", {}) or {}
                ),
                "refresh_error_count": int(diagnostics.get("refresh_error_count", 0) or 0),
                "refresh_errors": list(diagnostics.get("refresh_errors", []) or []),
                "refresh_duration_ms": int(
                    diagnostics.get("refresh_duration_ms", 0) or 0
                ),
            },
            "future_outcome_coverage": self._future_outcome_coverage(symbol_timeframe_rows),
            "diagnostics": diagnostics,
        }

    def render(self) -> str:
        report = self.build_report()
        diagnostics = report["diagnostics"]
        lines = [
            "Historical Replay Coverage",
            f"selected_storage_backend={report.get('backend', '-')}",
            f"selected_storage_backend_detail={report.get('backend_detail', '-')}",
            f"available_historical_bar_sources={','.join(report.get('available_sources', []) or ['-'])}",
            "timeframe_exists_1Min=" + ("yes" if report["timeframe_existence"].get("1Min") else "no"),
            "timeframe_exists_15Min=" + ("yes" if report["timeframe_existence"].get("15Min") else "no"),
            "timeframe_exists_1Hour=" + ("yes" if report["timeframe_existence"].get("1Hour") else "no"),
        ]
        for row in report.get("symbol_timeframe_rows", []):
            lines.append(
                "symbol_timeframe="
                f"{row.get('symbol', '-')}"
                f" | asset_class={row.get('asset_class', '-')}"
                f" | timeframe={row.get('timeframe', '-')}"
                f" | earliest={self._fmt_dt(row.get('earliest_timestamp'))}"
                f" | latest={self._fmt_dt(row.get('latest_timestamp'))}"
                f" | bar_count={int(row.get('bar_count', 0) or 0)}"
            )
        coverage = report.get("future_outcome_coverage", {})
        refresh = report.get("pre_replay_refresh", {})
        for key in ("15m", "1h", "1d", "7d"):
            lines.append(
                f"enough_future_data_exists_for_{key}_outcome="
                + ("yes" if coverage.get(key) else "no")
            )
        lines.extend(
            [
                f"latest_available_historical_bar_at={self._fmt_dt(diagnostics.get('latest_available_historical_bar_at'))}",
                f"max_required_future_horizon={self._fmt_delta(diagnostics.get('max_required_future_horizon'))}",
                f"latest_valid_replay_window_end={self._fmt_dt(diagnostics.get('latest_valid_replay_window_end'))}",
                f"window_anchor_mode={diagnostics.get('window_anchor_mode', '-') or '-'}",
            ]
        )
        lines.extend(
            [
                f"ingestion_ran_this_cycle={refresh.get('ingestion_ran_this_cycle', 'unknown')}",
                f"pre_replay_refresh_enabled={refresh.get('pre_replay_refresh_enabled', 'unknown')}",
                f"pre_replay_refresh_dry_run={refresh.get('pre_replay_refresh_dry_run', 'unknown')}",
                f"pre_replay_refresh_ran={refresh.get('pre_replay_refresh_ran', 'unknown')}",
                f"pre_replay_refresh_mode={refresh.get('pre_replay_refresh_mode', 'unknown')}",
                "pre_replay_refresh_asset_classes="
                f"{','.join(refresh.get('pre_replay_refresh_asset_classes', []) or ['-'])}",
                "pre_replay_refresh_symbols="
                f"equity={','.join((refresh.get('pre_replay_refresh_symbols', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((refresh.get('pre_replay_refresh_symbols', {}) or {}).get('crypto', []) or ['-'])}",
                "pre_replay_refresh_safety_guard="
                f"{refresh.get('pre_replay_refresh_safety_guard', '-')}",
                f"bars_inserted_this_cycle={int(refresh.get('bars_inserted_this_cycle', 0) or 0)}",
                f"bars_updated_this_cycle={int(refresh.get('bars_updated_this_cycle', 0) or 0)}",
                f"latest_bar_before_ingestion={self._fmt_dt(refresh.get('latest_bar_before_ingestion'))}",
                f"latest_bar_after_ingestion={self._fmt_dt(refresh.get('latest_bar_after_ingestion'))}",
                f"latest_bar_before_refresh={self._fmt_dt(refresh.get('latest_bar_before_refresh'))}",
                f"latest_bar_after_refresh={self._fmt_dt(refresh.get('latest_bar_after_refresh'))}",
                f"bars_inserted_by_refresh={int(refresh.get('bars_inserted_by_refresh', 0) or 0)}",
                f"bars_updated_by_refresh={int(refresh.get('bars_updated_by_refresh', 0) or 0)}",
                "refresh_attempted_symbols="
                f"equity={','.join((refresh.get('refresh_attempted_symbols', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((refresh.get('refresh_attempted_symbols', {}) or {}).get('crypto', []) or ['-'])}",
                "refresh_success_symbols="
                f"equity={','.join((refresh.get('refresh_success_symbols', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((refresh.get('refresh_success_symbols', {}) or {}).get('crypto', []) or ['-'])}",
                "refresh_failed_symbols="
                f"equity={','.join((refresh.get('refresh_failed_symbols', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((refresh.get('refresh_failed_symbols', {}) or {}).get('crypto', []) or ['-'])}",
                "refresh_skipped_symbols="
                f"equity={','.join((refresh.get('refresh_skipped_symbols', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((refresh.get('refresh_skipped_symbols', {}) or {}).get('crypto', []) or ['-'])}",
                "refresh_skip_reasons="
                f"equity={','.join((refresh.get('refresh_skip_reasons', {}) or {}).get('equity', []) or ['-'])};"
                f"crypto={','.join((refresh.get('refresh_skip_reasons', {}) or {}).get('crypto', []) or ['-'])}",
                f"provider_error_count={int(refresh.get('provider_error_count', 0) or 0)}",
                f"provider_errors={','.join(refresh.get('provider_errors', []) or ['-'])}",
                f"refresh_error_count={int(refresh.get('refresh_error_count', 0) or 0)}",
                f"refresh_errors={','.join(refresh.get('refresh_errors', []) or ['-'])}",
                f"refresh_duration_ms={int(refresh.get('refresh_duration_ms', 0) or 0)}",
                "replay_windows_selected_from_latest_available_data="
                f"{refresh.get('replay_windows_selected_from_latest_available_data', 'unknown')}",
                f"latest_raw_bar_at={self._fmt_dt(refresh.get('latest_raw_bar_at'))}",
                f"rolling_replay_mode_enabled={refresh.get('rolling_replay_mode_enabled', '-')}",
                f"rolling_replay_cursor_enabled={refresh.get('rolling_replay_cursor_enabled', '-')}",
                f"replay_mode={refresh.get('replay_mode', '-')}",
                f"learning_progress_this_cycle={refresh.get('learning_progress_this_cycle', '-')}",
                f"max_future_outcome_horizon={refresh.get('max_future_outcome_horizon', '-')}",
                f"latest_replay_eligible_bar_at={self._fmt_dt(refresh.get('latest_replay_eligible_bar_at'))}",
                "latest_available_bar_per_asset_class="
                f"{self._render_mapping(refresh.get('latest_available_bar_per_asset_class', {}) or {})}",
                "latest_available_bar_per_symbol="
                f"{self._render_mapping(refresh.get('latest_available_bar_per_symbol', {}) or {})}",
                "latest_replay_eligible_bar_per_timeframe="
                f"{self._render_mapping(refresh.get('latest_replay_eligible_bar_per_timeframe', {}) or {})}",
                "latest_replay_eligible_bar_per_asset_class="
                f"{self._render_mapping(refresh.get('latest_replay_eligible_bar_per_asset_class', {}) or {})}",
                "latest_replay_eligible_at_by_bucket="
                f"{self._render_mapping(refresh.get('latest_replay_eligible_at_by_bucket', {}) or {})}",
                "previous_replay_eligible_at_by_bucket="
                f"{self._render_mapping(refresh.get('previous_replay_eligible_at_by_bucket', {}) or {})}",
                "replay_eligible_advance_delta_by_bucket="
                f"{self._render_mapping(refresh.get('replay_eligible_advance_delta_by_bucket', {}) or {})}",
                "last_replayed_until_by_bucket="
                f"{self._render_mapping(refresh.get('last_replayed_until_by_bucket', {}) or {})}",
                "unseen_replay_range_available_by_bucket="
                f"{self._render_mapping(refresh.get('unseen_replay_range_available_by_bucket', {}) or {})}",
                "next_unseen_replay_start_by_bucket="
                f"{self._render_mapping(refresh.get('next_unseen_replay_start_by_bucket', {}) or {})}",
                "next_unseen_replay_end_by_bucket="
                f"{self._render_mapping(refresh.get('next_unseen_replay_end_by_bucket', {}) or {})}",
                "candidate_replay_windows_considered="
                f"{self._render_window_rows(refresh.get('candidate_replay_windows_considered', []) or [])}",
                "candidate_replay_windows_rejected="
                f"{self._render_window_rows(refresh.get('candidate_replay_windows_rejected', []) or [])}",
                "selected_replay_windows="
                f"{self._render_window_rows(refresh.get('selected_replay_windows', []) or [])}",
                "selected_replay_window_reason="
                f"{refresh.get('selected_replay_window_reason', '-')}",
                f"max_allowed_replay_window_end={refresh.get('max_allowed_replay_window_end', '-') or '-'}",
                f"global_anchor_enabled={refresh.get('global_anchor_enabled', '-')}",
                f"global_anchor_time={refresh.get('global_anchor_time', '-') or '-'}",
                "global_anchor_constrained_by_asset_class="
                f"{refresh.get('global_anchor_constrained_by_asset_class', '-') or '-'}",
                "global_anchor_constrained_by_timeframe="
                f"{refresh.get('global_anchor_constrained_by_timeframe', '-') or '-'}",
                "global_anchor_constrained_by_symbol="
                f"{refresh.get('global_anchor_constrained_by_symbol', '-') or '-'}",
                "freshness_lost_to_future_outcome_horizon="
                f"{refresh.get('freshness_lost_to_future_outcome_horizon', '-')}",
                "freshness_lost_to_global_anchor="
                f"{refresh.get('freshness_lost_to_global_anchor', '-')}",
                "selected_replay_window_end_by_timeframe="
                f"{self._render_mapping(refresh.get('selected_replay_window_end_by_timeframe', {}) or {})}",
                "selected_replay_window_end_by_asset_class="
                f"{self._render_mapping(refresh.get('selected_replay_window_end_by_asset_class', {}) or {})}",
                "selected_replay_window_end_by_bucket="
                f"{self._render_mapping(refresh.get('selected_replay_window_end_by_bucket', {}) or {})}",
                "accepted_replay_window_count_by_timeframe="
                f"{self._render_mapping(refresh.get('accepted_replay_window_count_by_timeframe', {}) or {})}",
                "accepted_replay_window_count_by_asset_class="
                f"{self._render_mapping(refresh.get('accepted_replay_window_count_by_asset_class', {}) or {})}",
                "selected_anchor_time_by_bucket="
                f"{self._render_mapping(refresh.get('selected_anchor_time_by_bucket', {}) or {})}",
                "candidate_anchor_time_by_bucket="
                f"{self._render_mapping(refresh.get('candidate_anchor_time_by_bucket', {}) or {})}",
                "rejected_bucket_anchor_time_by_bucket="
                f"{self._render_mapping(refresh.get('rejected_bucket_anchor_time_by_bucket', {}) or {})}",
                "freshness_gain_vs_global_by_bucket="
                f"{self._render_mapping(refresh.get('freshness_gain_vs_global_by_bucket', {}) or {})}",
                "windows_selected_by_bucket="
                f"{self._render_mapping(refresh.get('windows_selected_by_bucket', {}) or {})}",
                "windows_rejected_by_bucket="
                f"{self._render_mapping(refresh.get('windows_rejected_by_bucket', {}) or {})}",
                "bucket_rejection_reasons="
                f"{self._render_mapping(refresh.get('bucket_rejection_reasons', {}) or {})}",
                f"replay_selection_mode={refresh.get('replay_selection_mode', '-')}",
                "alternative_replay_selection_modes_available="
                f"{refresh.get('alternative_replay_selection_modes_available', '-')}",
                "simulated_asset_class_anchor_time="
                f"{self._render_mapping(refresh.get('simulated_asset_class_anchor_time', {}) or {})}",
                "simulated_asset_class_and_timeframe_anchor_time="
                f"{self._render_mapping(refresh.get('simulated_asset_class_and_timeframe_anchor_time', {}) or {})}",
                "simulated_freshness_gain_by_asset_class="
                f"{self._render_mapping(refresh.get('simulated_freshness_gain_by_asset_class', {}) or {})}",
                "simulated_freshness_gain_by_asset_class_and_timeframe="
                f"{self._render_mapping(refresh.get('simulated_freshness_gain_by_asset_class_and_timeframe', {}) or {})}",
                "strategies_helped_by_isolated_replay="
                f"{','.join(refresh.get('strategies_helped_by_isolated_replay', []) or ['-'])}",
                "strategies_unaffected_by_isolated_replay="
                f"{','.join(refresh.get('strategies_unaffected_by_isolated_replay', []) or ['-'])}",
                "strategies_blocked_by_mixed_global_anchor="
                f"{','.join(refresh.get('strategies_blocked_by_mixed_global_anchor', []) or ['-'])}",
                "minimum_required_window_completeness="
                f"{refresh.get('minimum_required_window_completeness', '-')}",
                f"lookback_window_policy={refresh.get('lookback_window_policy', '-')}",
                f"warmup_buffer_policy={refresh.get('warmup_buffer_policy', '-')}",
                f"market_hours_policy={refresh.get('market_hours_policy', '-')}",
                f"weekend_policy={refresh.get('weekend_policy', '-')}",
                f"asset_class_window_policy={refresh.get('asset_class_window_policy', '-')}",
                "reason_latest_bars_not_used_for_replay="
                f"{refresh.get('reason_latest_bars_not_used_for_replay', '-') or '-'}",
                "plain_english_replay_anchor_explanation="
                f"{refresh.get('plain_english_replay_anchor_explanation', '-') or '-'}",
                f"reason_if_not={refresh.get('reason_if_not', '-') or '-'}",
                "selected_window_ids_current="
                f"{self._render_mapping(refresh.get('selected_window_ids_current', {}) or {})}",
                "selected_window_ids_previous="
                f"{self._render_mapping(refresh.get('selected_window_ids_previous', {}) or {})}",
                f"selected_window_set_changed={refresh.get('selected_window_set_changed', '-')}",
                f"new_replay_windows_selected_count={int(refresh.get('new_replay_windows_selected_count', 0) or 0)}",
                f"duplicate_replay_windows_skipped_count={int(refresh.get('duplicate_replay_windows_skipped_count', 0) or 0)}",
                f"replay_evidence_new_rows_inserted={int(refresh.get('replay_evidence_new_rows_inserted', 0) or 0)}",
                f"replay_evidence_duplicate_rows_skipped={int(refresh.get('replay_evidence_duplicate_rows_skipped', 0) or 0)}",
                "reason_replay_window_not_advancing="
                f"{refresh.get('reason_replay_window_not_advancing', '-')}",
                f"reason_no_learning_progress={refresh.get('reason_no_learning_progress', '-')}",
            ]
        )
        freshness_by_asset = dict(refresh.get("asset_class_freshness_status", {}) or {})
        for asset_class in ("equity", "crypto"):
            item = dict(freshness_by_asset.get(asset_class, {}) or {})
            lines.append(
                "asset_class_freshness_status="
                f"asset_class={asset_class}"
                f" | latest={item.get('latest_available_historical_bar_at', '-') or '-'}"
                f" | age={item.get('age', '-') or '-'}"
                f" | threshold_used={item.get('threshold_used', '-') or '-'}"
                f" | fresh={item.get('fresh', '-') or '-'}"
                f" | reason={item.get('reason', '-') or '-'}"
            )
        lines.extend(
            [
                f"replay_window_candidates_found={len(diagnostics.get('replay_window_candidates', []) or [])}",
                f"replay_window_candidates_accepted={int(diagnostics.get('replay_windows_accepted_count', 0) or 0)}",
                f"replay_window_candidates_rejected={int(diagnostics.get('replay_windows_rejected_count', 0) or 0)}",
            ]
        )
        for item in diagnostics.get("replay_window_acceptances", []) or []:
            lines.append(
                "accepted_replay_window="
                f"timeframe={item.get('timeframe', '-')}"
                f" | start_at={item.get('start_at', '-')}"
                f" | end_at={item.get('end_at', '-')}"
                f" | reason={item.get('reason', '-')}"
            )
        for timeframe, item in sorted((diagnostics.get("timeframe_historical_coverage", {}) or {}).items()):
            lines.append(
                "timeframe_historical_coverage="
                f"timeframe={timeframe}"
                f" | earliest={item.get('earliest_available_historical_bar_at', '-') or '-'}"
                f" | latest={item.get('latest_available_historical_bar_at', '-') or '-'}"
                f" | latest_valid_replay_window_end={item.get('latest_valid_replay_window_end', '-') or '-'}"
                f" | max_required_future_horizon={item.get('max_required_future_horizon', '-') or '-'}"
            )
        for item in diagnostics.get("replay_window_rejections", []) or []:
            lines.append(
                "rejected_replay_window="
                f"timeframe={item.get('timeframe', '-')}"
                f" | start_at={item.get('start_at', '-')}"
                f" | end_at={item.get('end_at', '-')}"
                f" | reason={item.get('reason', '-')}"
            )
        return "\n".join(lines)

    def _render_mapping(self, value: dict[str, object]) -> str:
        if not value:
            return "-"
        return ",".join(f"{key}:{value[key]}" for key in sorted(value))

    def _render_window_rows(self, rows: list[dict[str, object]]) -> str:
        if not rows:
            return "-"
        rendered: list[str] = []
        for row in rows:
            rendered.append(
                "|".join(
                    [
                        f"bucket={row.get('bucket', '-')}",
                        f"asset_class={row.get('asset_class', '-')}",
                        f"timeframe={row.get('timeframe', '-')}",
                        f"window_index={row.get('window_index', '-')}",
                        f"start_at={row.get('start_at', '-')}",
                        f"end_at={row.get('end_at', '-')}",
                        f"reason={row.get('reason', '-')}",
                    ]
                )
            )
        return ";".join(rendered)

    def _symbol_timeframe_rows(self) -> list[dict[str, Any]]:
        inventory = self.usage_ledger.summarize_historical_bars(as_of=datetime.now().astimezone())
        historical = dict(inventory.get("historical", {}) or {})
        min_at = historical.get("min_bar_timestamp")
        max_at = historical.get("max_bar_timestamp")
        rows: list[dict[str, Any]] = []
        for timeframe_row in historical.get("rows_by_timeframe", []) or []:
            timeframe = str(timeframe_row.get("timeframe", "") or "")
            if not timeframe:
                continue
            bars = self.usage_ledger.list_historical_bars(
                timeframe=timeframe,
                sources=["alpaca_market_data", "alpaca_crypto_data"],
                start_at=min_at if isinstance(min_at, datetime) else None,
                end_at=max_at if isinstance(max_at, datetime) else None,
            )
            grouped: dict[tuple[str, str], list[datetime]] = defaultdict(list)
            for row in bars:
                symbol = str(row.get("symbol", "") or "")
                asset_class = str(row.get("asset_class", "") or "")
                ts = row.get("bar_timestamp")
                if not symbol or not isinstance(ts, datetime):
                    continue
                grouped[(symbol, asset_class)].append(ts)
            for (symbol, asset_class), timestamps in sorted(grouped.items()):
                ordered = sorted(timestamps)
                rows.append(
                    {
                        "symbol": symbol,
                        "asset_class": asset_class or "unknown",
                        "timeframe": timeframe,
                        "earliest_timestamp": ordered[0],
                        "latest_timestamp": ordered[-1],
                        "bar_count": len(ordered),
                    }
                )
        return rows

    def _future_outcome_coverage(self, rows: list[dict[str, Any]]) -> dict[str, bool]:
        required = {"15m": 15, "1h": 60, "1d": 1440, "7d": 10080}
        observed_by_timeframe: dict[str, int] = defaultdict(int)
        for row in rows:
            timeframe = str(row.get("timeframe", "") or "")
            if not timeframe:
                continue
            try:
                observed_by_timeframe[timeframe] = max(
                    observed_by_timeframe[timeframe],
                    _window_code_to_minutes(self._coverage_window_code(row)),
                )
            except ValueError:
                continue
        supported_windows = tuple(getattr(self.config, "shadow_checkpoint_windows", ("15m", "1h", "1d", "7d")))
        supported_max = _max_checkpoint_window_minutes(supported_windows)
        return {
            key: any(minutes <= span for span in observed_by_timeframe.values()) or supported_max >= minutes
            for key, minutes in required.items()
        }

    def _coverage_window_code(self, row: dict[str, Any]) -> str:
        timeframe = str(row.get("timeframe", "") or "")
        if timeframe.endswith("Min"):
            return timeframe[:-3] + "m"
        if timeframe.endswith("Hour"):
            return timeframe[:-4] + "h"
        if timeframe.endswith("Day"):
            return timeframe[:-3] + "d"
        return "15m"

    def _fmt_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")

    def _fmt_delta(self, value: Any) -> str:
        if isinstance(value, timedelta):
            return str(value)
        return str(value or "-")
