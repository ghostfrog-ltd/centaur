from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
import hashlib
import json
from statistics import mean
from typing import Any

from app.framework.engine.replay import (
    _eligible_replay_timestamps,
    _max_checkpoint_window_minutes,
    _supported_checkpoint_windows,
)
from app.framework.reporting.symbol_subset_stability import SymbolSubsetStabilityReport
from app.framework.reporting.strategy_variant_research import StrategyVariantResearchService
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


ALLOWED_EVIDENCE_ACTION_VERDICTS = {
    "enough_existing_data_to_replay_more",
    "need_more_historical_backfill",
    "need_forward_paper_observation_only",
    "insufficient_symbol_history",
    "no_action_available",
}

SAFETY_STATEMENT = "Research-only symbol replay evidence plan. No paper or live approval has been changed."


class SymbolReplayEvidencePlanReport:
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
        self.symbol_stability_reporter = SymbolSubsetStabilityReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )

    def build_report(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
        variant_id: str,
        symbol: str,
        execute: bool = False,
    ) -> dict[str, Any]:
        clean_symbol = str(symbol or "").strip().upper()
        variant = self._variant_definition(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
        )
        if variant is None or not clean_symbol:
            report = self._empty_report(
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                variant_id=variant_id,
                symbol=clean_symbol,
                why="Variant definition or symbol was not available for a research-only replay evidence plan.",
            )
            report["execution"] = self._execution_not_requested()
            return report

        stored_coverage = self._stored_bar_coverage(symbol=clean_symbol, timeframe=timeframe)
        existing_replay = self._existing_replay_coverage(
            symbol=clean_symbol,
            timeframe=timeframe,
        )
        stability_context = self._stability_context(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant=variant,
            symbol=clean_symbol,
        )
        verdict = self._evidence_action_verdict(
            stored_coverage=stored_coverage,
            existing_replay=existing_replay,
            stability_context=stability_context,
        )
        proposed_action = self._proposed_next_research_action(
            verdict=verdict,
            stored_coverage=stored_coverage,
            existing_replay=existing_replay,
            symbol=clean_symbol,
        )
        proposed_command = self._proposed_next_command(
            verdict=verdict,
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
            symbol=clean_symbol,
        )
        execution_available = verdict == "enough_existing_data_to_replay_more"
        report = {
            "title": "Symbol Replay Evidence Plan",
            "base_strategy_id": base_strategy_id,
            "profile_id": profile_id,
            "timeframe": timeframe,
            "variant_id": variant_id,
            "symbol": clean_symbol,
            "current_symbol_evidence": {
                "earliest_bar_timestamp": stored_coverage.get("earliest_bar_timestamp"),
                "latest_bar_timestamp": stored_coverage.get("latest_bar_timestamp"),
                "number_of_bars": stored_coverage.get("number_of_bars", 0),
                "number_of_eligible_replay_decisions": existing_replay.get("current_eligible_replay_decisions", 0),
                "number_of_months_covered": stored_coverage.get("number_of_months_covered", 0),
                "number_of_weeks_covered": stored_coverage.get("number_of_weeks_covered", 0),
                "existing_stability_sample_size": stability_context.get("existing_stability_sample_size", 0),
            },
            "can_replay_more_from_existing_bars": {
                "unused_bars_outside_current_replay_window": existing_replay.get("unused_bars_outside_current_replay_window", 0),
                "additional_eligible_replay_timestamps": existing_replay.get("additional_eligible_replay_timestamps", 0),
                "additional_checkpoint_windows_available": list(existing_replay.get("additional_checkpoint_windows_available", [])),
                "can_include_earlier_periods_without_fetch": bool(existing_replay.get("can_include_earlier_periods_without_fetch")),
                "can_include_later_periods_without_fetch": bool(existing_replay.get("can_include_later_periods_without_fetch")),
                "can_replay_more_now": bool(existing_replay.get("can_replay_more_now")),
                "why": str(existing_replay.get("why", "") or ""),
            },
            "external_data_needed": verdict != "enough_existing_data_to_replay_more",
            "evidence_action_verdict": verdict,
            "proposed_next_research_action": proposed_action,
            "proposed_next_command": proposed_command,
            "execution_available": execution_available,
            "stability_context": stability_context,
            "execution": self._maybe_execute(
                execute=execute,
                execution_available=execution_available,
                base_strategy_id=base_strategy_id,
                profile_id=profile_id,
                timeframe=timeframe,
                variant_id=variant_id,
                symbol=clean_symbol,
                proposed_command=proposed_command,
            ),
            "safety_statement": SAFETY_STATEMENT,
        }
        report["persistence"] = self._persist_report(
            report=report,
            variant=variant,
        )
        if report["evidence_action_verdict"] not in ALLOWED_EVIDENCE_ACTION_VERDICTS:
            raise ValueError(f"Unsupported evidence action verdict: {report['evidence_action_verdict']}")
        return report

    def render(
        self,
        *,
        base_strategy_id: str = "mean_reversion.snapback",
        profile_id: str = "snapback",
        timeframe: str = "15Min",
        variant_id: str,
        symbol: str,
        execute: bool = False,
    ) -> str:
        report = self.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
            symbol=symbol,
            execute=execute,
        )
        current = dict(report.get("current_symbol_evidence", {}) or {})
        replay = dict(report.get("can_replay_more_from_existing_bars", {}) or {})
        execution = dict(report.get("execution", {}) or {})
        lines = [
            str(report.get("title", "Symbol Replay Evidence Plan")),
            f"base_strategy={report.get('base_strategy_id', '-')}"
            f" | profile={report.get('profile_id', '-')}"
            f" | timeframe={report.get('timeframe', '-')}",
            f"variant_id={report.get('variant_id', '-')}"
            f" | symbol={report.get('symbol', '-')}",
            (
                "current_symbol_evidence="
                f"earliest_bar_timestamp={self._fmt_dt(current.get('earliest_bar_timestamp'))}"
                f" | latest_bar_timestamp={self._fmt_dt(current.get('latest_bar_timestamp'))}"
                f" | number_of_bars={current.get('number_of_bars', 0)}"
                f" | number_of_eligible_replay_decisions={current.get('number_of_eligible_replay_decisions', 0)}"
                f" | number_of_months_covered={current.get('number_of_months_covered', 0)}"
                f" | number_of_weeks_covered={current.get('number_of_weeks_covered', 0)}"
                f" | existing_stability_sample_size={current.get('existing_stability_sample_size', 0)}"
            ),
            (
                "can_replay_more_from_existing_bars="
                f"unused_bars_outside_current_replay_window={replay.get('unused_bars_outside_current_replay_window', 0)}"
                f" | additional_eligible_replay_timestamps={replay.get('additional_eligible_replay_timestamps', 0)}"
                f" | additional_checkpoint_windows_available={','.join(replay.get('additional_checkpoint_windows_available', []) or ['-'])}"
                f" | can_include_earlier_periods_without_fetch={'yes' if replay.get('can_include_earlier_periods_without_fetch') else 'no'}"
                f" | can_include_later_periods_without_fetch={'yes' if replay.get('can_include_later_periods_without_fetch') else 'no'}"
                f" | can_replay_more_now={'yes' if replay.get('can_replay_more_now') else 'no'}"
            ),
            f"external_data_needed={'yes' if report.get('external_data_needed') else 'no'}",
            f"evidence_action_verdict={report.get('evidence_action_verdict', '-')}",
            f"proposed_next_research_action={report.get('proposed_next_research_action', '-')}",
            f"proposed_next_command={report.get('proposed_next_command', '-')}",
            f"execution_available={'yes' if report.get('execution_available') else 'no'}",
            f"execution_status={execution.get('status', '-')}",
            str(report.get("safety_statement", "")),
        ]
        return "\n".join(lines)

    def _variant_definition(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant_id: str,
    ) -> dict[str, Any] | None:
        definitions = self.usage_ledger.list_strategy_variant_definitions(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        direct = next(
            (item for item in definitions if str(item.get("variant_id", "") or "") == str(variant_id or "")),
            None,
        )
        if direct is not None:
            return direct
        requested_alias = self._normalize_variant_alias(variant_id)
        if not requested_alias:
            return None
        for item in definitions:
            if self._normalize_variant_alias(item.get("generation_reason")) == requested_alias:
                return item
            if self._normalize_variant_alias(item.get("variant_id")) == requested_alias:
                return item
        return None

    def _stored_bar_coverage(self, *, symbol: str, timeframe: str) -> dict[str, Any]:
        rows = self.usage_ledger.summarize_historical_bar_coverage(
            asset_class="equity",
            symbols=[symbol],
            timeframes=[timeframe],
        )
        row = dict(rows[0]) if rows else {}
        earliest = row.get("earliest_bar_timestamp")
        latest = row.get("latest_bar_timestamp")
        bar_rows = self.usage_ledger.list_historical_bars(
            timeframe=timeframe,
            sources=["alpaca_market_data"],
            start_at=earliest if isinstance(earliest, datetime) else None,
            end_at=(latest + timedelta(minutes=self._timeframe_minutes(timeframe))) if isinstance(latest, datetime) else None,
            symbols=[symbol],
        ) if row else []
        unique_months = {
            stamp.strftime("%Y-%m")
            for stamp in [item.get("bar_timestamp") for item in bar_rows]
            if isinstance(stamp, datetime)
        }
        unique_weeks = {
            f"{stamp.isocalendar().year}-W{stamp.isocalendar().week:02d}"
            for stamp in [item.get("bar_timestamp") for item in bar_rows]
            if isinstance(stamp, datetime)
        }
        return {
            "earliest_bar_timestamp": earliest,
            "latest_bar_timestamp": latest,
            "number_of_bars": len(bar_rows),
            "number_of_months_covered": len(unique_months),
            "number_of_weeks_covered": len(unique_weeks),
        }

    def _existing_replay_coverage(self, *, symbol: str, timeframe: str) -> dict[str, Any]:
        supported_windows = _supported_checkpoint_windows(
            timeframe=timeframe,
            checkpoint_windows=self.config.shadow_checkpoint_windows,
        )
        lookahead_minutes = _max_checkpoint_window_minutes(supported_windows)
        as_of = datetime.now().astimezone()
        current_start_at = as_of - timedelta(days=max(1, self.config.historical_replay_default_days))
        current_rows = self.usage_ledger.list_historical_bars(
            timeframe=timeframe,
            sources=["alpaca_market_data"],
            start_at=current_start_at,
            end_at=as_of + timedelta(minutes=lookahead_minutes),
            symbols=[symbol],
        )
        full_coverage = self._stored_bar_coverage(symbol=symbol, timeframe=timeframe)
        earliest = full_coverage.get("earliest_bar_timestamp")
        latest = full_coverage.get("latest_bar_timestamp")
        full_rows = self.usage_ledger.list_historical_bars(
            timeframe=timeframe,
            sources=["alpaca_market_data"],
            start_at=earliest if isinstance(earliest, datetime) else None,
            end_at=(latest + timedelta(minutes=lookahead_minutes)) if isinstance(latest, datetime) else None,
            symbols=[symbol],
        ) if isinstance(earliest, datetime) and isinstance(latest, datetime) else list(current_rows)
        current_eligible = self._eligible_count(
            rows=current_rows,
            start_at=current_start_at,
            end_at=as_of,
            supported_windows=supported_windows,
        )
        full_eligible = self._eligible_count(
            rows=full_rows,
            start_at=earliest if isinstance(earliest, datetime) else None,
            end_at=latest if isinstance(latest, datetime) else None,
            supported_windows=supported_windows,
        )
        additional = max(0, full_eligible - current_eligible)
        unused_bars = max(0, len(full_rows) - len(current_rows))
        can_earlier = bool(isinstance(earliest, datetime) and earliest < current_start_at)
        can_later = bool(isinstance(latest, datetime) and latest > as_of)
        can_replay_more = additional > 0 or can_earlier or can_later
        why = "Stored WDC bars already extend beyond the current replay window." if can_replay_more else "Stored WDC bars do not currently expose more replayable timestamps outside the active replay window."
        return {
            "current_eligible_replay_decisions": current_eligible,
            "full_eligible_replay_decisions": full_eligible,
            "unused_bars_outside_current_replay_window": unused_bars,
            "additional_eligible_replay_timestamps": additional,
            "additional_checkpoint_windows_available": list(supported_windows),
            "can_include_earlier_periods_without_fetch": can_earlier,
            "can_include_later_periods_without_fetch": can_later,
            "can_replay_more_now": can_replay_more,
            "why": why,
        }

    def _stability_context(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant: dict[str, Any],
        symbol: str,
    ) -> dict[str, Any]:
        profile = self.service._resolve_profile(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
        )
        collected = self.service.collect_variant_outcomes(
            profile=self.service._profile_from_variant(profile=profile, variant=variant),
            variant=variant,
            timeframe=timeframe,
            replay_id=f"symbol-replay-plan-{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}",
        )
        outcomes = [
            item
            for item in list(collected.get("outcomes", []) or [])
            if str(((item.get("proposal_context", {}) or {}).get("symbol", "")) or "").upper() == symbol
        ]
        months = Counter()
        for item in outcomes:
            evaluated_at = self._to_datetime(item.get("evaluated_at"))
            if evaluated_at is not None:
                months[evaluated_at.strftime("%Y-%m")] += 1
        return {
            "existing_stability_sample_size": len(outcomes),
            "existing_stability_months": sorted(months.keys()),
            "existing_stability_summary": self._outcome_summary(outcomes),
        }

    def _evidence_action_verdict(
        self,
        *,
        stored_coverage: dict[str, Any],
        existing_replay: dict[str, Any],
        stability_context: dict[str, Any],
    ) -> str:
        if int(stored_coverage.get("number_of_bars", 0) or 0) <= 0:
            return "no_action_available"
        if bool(existing_replay.get("can_replay_more_now")):
            return "enough_existing_data_to_replay_more"
        if int(stability_context.get("existing_stability_sample_size", 0) or 0) < 10:
            return "insufficient_symbol_history"
        if int(stored_coverage.get("number_of_months_covered", 0) or 0) < 2:
            return "need_more_historical_backfill"
        if int(stability_context.get("existing_stability_sample_size", 0) or 0) < 30:
            return "need_forward_paper_observation_only"
        return "no_action_available"

    def _proposed_next_research_action(
        self,
        *,
        verdict: str,
        stored_coverage: dict[str, Any],
        existing_replay: dict[str, Any],
        symbol: str,
    ) -> str:
        if verdict == "enough_existing_data_to_replay_more":
            return f"rerun_{symbol}_stability_over_wider_historical_period"
        if verdict == "need_more_historical_backfill":
            return f"request_additional_historical_backfill_for_{symbol}"
        if verdict == "need_forward_paper_observation_only":
            return f"schedule_future_research_observation_for_{symbol}"
        if verdict == "insufficient_symbol_history":
            return f"stop_{symbol}_branch_due_to_insufficient_data"
        return "no_safe_research_action_available"

    def _proposed_next_command(
        self,
        *,
        verdict: str,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant_id: str,
        symbol: str,
    ) -> str:
        if verdict == "enough_existing_data_to_replay_more":
            return (
                ".venv-mac/bin/python main.py --symbol-subset-stability-report "
                f"--base-strategy {base_strategy_id} --profile-id {profile_id} "
                f"--variant-id {variant_id} --symbol {symbol} --wider-period"
            )
        if verdict == "need_more_historical_backfill":
            return (
                ".venv-mac/bin/python main.py --backfill-alpaca-equity-bars "
                f"--years 2 --timeframes {timeframe} --equity-symbols {symbol}"
            )
        if verdict == "need_forward_paper_observation_only":
            return (
                ".venv-mac/bin/python main.py --collect-symbol-replay-evidence "
                f"--base-strategy {base_strategy_id} --profile-id {profile_id} "
                f"--variant-id {variant_id} --symbol {symbol}"
            )
        return (
            ".venv-mac/bin/python main.py --symbol-subset-stability-report "
            f"--base-strategy {base_strategy_id} --profile-id {profile_id} "
            f"--variant-id {variant_id} --symbol {symbol}"
        )

    def _maybe_execute(
        self,
        *,
        execute: bool,
        execution_available: bool,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant_id: str,
        symbol: str,
        proposed_command: str,
    ) -> dict[str, Any]:
        if not execute:
            return self._execution_not_requested()
        if not execution_available:
            return {
                "status": "refused_unsupported",
                "executed_command": None,
                "message": "No additional read-only replay action is available from existing bars, so execution stops safely.",
            }
        built = self.symbol_stability_reporter.build_report(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
            symbol=symbol,
            wider_period=True,
        )
        rendered = self.symbol_stability_reporter.render(
            base_strategy_id=base_strategy_id,
            profile_id=profile_id,
            timeframe=timeframe,
            variant_id=variant_id,
            symbol=symbol,
            wider_period=True,
        )
        return {
            "status": "executed_research_only",
            "executed_command": proposed_command,
            "output_preview": rendered,
            "stability_report": built,
        }

    def _execution_not_requested(self) -> dict[str, Any]:
        return {"status": "not_requested", "executed_command": None}

    def _normalize_variant_alias(self, value: Any) -> str:
        text = str(value or "").strip().lower()
        if not text:
            return ""
        normalized = []
        last_was_sep = False
        for char in text:
            if char.isalnum():
                normalized.append(char)
                last_was_sep = False
                continue
            if not last_was_sep:
                normalized.append("_")
                last_was_sep = True
        return "".join(normalized).strip("_")

    def _persist_report(
        self,
        *,
        report: dict[str, Any],
        variant: dict[str, Any],
    ) -> dict[str, Any]:
        execution = dict(report.get("execution", {}) or {})
        stability_report = dict(execution.get("stability_report", {}) or {})
        raw = {
            "report_type": "symbol_replay_evidence_plan",
            "symbol": report.get("symbol", ""),
            "evidence_action_verdict": report.get("evidence_action_verdict", ""),
            "proposed_next_research_action": report.get("proposed_next_research_action", ""),
            "proposed_next_command": report.get("proposed_next_command", ""),
            "execution_available": bool(report.get("execution_available")),
            "execution_status": execution.get("status", ""),
            "current_symbol_evidence": report.get("current_symbol_evidence", {}),
            "can_replay_more_from_existing_bars": report.get("can_replay_more_from_existing_bars", {}),
            "stability_context": report.get("stability_context", {}),
            "executed_wider_stability_verdict": stability_report.get("stability_verdict", ""),
            "executed_wider_symbol_summary": stability_report.get("selected_symbol_summary", {}),
            "executed_wider_cohort_comparison": stability_report.get("cohort_comparison", {}),
            "executed_wider_comparison": stability_report.get("narrow_vs_wide_comparison", {}),
            "safety_statement": report.get("safety_statement", ""),
        }
        digest = hashlib.sha1(json.dumps(raw, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
        return self.usage_ledger.record_strategy_variant_evaluation(
            evaluation_id=f"{variant['variant_id']}:symbol-replay-evidence:{digest}",
            variant_id=variant["variant_id"],
            base_strategy_id=variant["base_strategy_id"],
            profile_id=variant["profile_id"],
            timeframe=variant["timeframe"],
            replay_id=f"symbol-replay-evidence-{str(report.get('symbol', '')).upper()}-{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}",
            dataset_id=f"historical_equity_bars:{variant['timeframe']}:symbol_replay_evidence",
            asset_class="equity",
            symbols_tested=[str(report.get("symbol", ""))],
            sample_size=int(((raw.get("executed_wider_symbol_summary", {}) or {}).get("sample_size", 0) or 0)),
            gross_return=float(((raw.get("executed_wider_symbol_summary", {}) or {}).get("gross_return_before_costs", 0.0) or 0.0)),
            net_return_after_costs=float(((raw.get("executed_wider_symbol_summary", {}) or {}).get("net_return_after_costs", 0.0) or 0.0)),
            fees_cost=0.0,
            spread_cost=0.0,
            slippage_cost=0.0,
            win_rate=float(((raw.get("executed_wider_symbol_summary", {}) or {}).get("win_rate", 0.0) or 0.0)),
            drawdown=((raw.get("executed_wider_symbol_summary", {}) or {}).get("drawdown")),
            baseline_variant_id="",
            baseline_strategy_key=f"{variant['base_strategy_id']}/{variant['profile_id']}/{variant['timeframe']}",
            baseline_net_return_after_costs=float(((raw.get("executed_wider_comparison", {}) or {}).get("narrow_net_return", 0.0) or 0.0),
            ),
            baseline_win_rate=float(((raw.get("executed_wider_comparison", {}) or {}).get("narrow_win_rate", 0.0) or 0.0)),
            beats_baseline=bool(((raw.get("executed_wider_comparison", {}) or {}).get("signal_survives_wider_period"))),
            beats_thresholds=False,
            recommended_status="evaluated",
            evaluated_at=datetime.now().astimezone(),
            notes=SAFETY_STATEMENT,
            raw=raw,
        )

    def _eligible_count(
        self,
        *,
        rows: list[dict[str, Any]],
        start_at: datetime | None,
        end_at: datetime | None,
        supported_windows: list[str],
    ) -> int:
        ordered = sorted(
            {
                row["bar_timestamp"]
                for row in rows
                if isinstance(row.get("bar_timestamp"), datetime)
            }
        )
        replay_timestamps = [
            timestamp
            for timestamp in ordered
            if (start_at is None or start_at <= timestamp) and (end_at is None or timestamp < end_at)
        ]
        return len(
            _eligible_replay_timestamps(
                timestamps=ordered,
                replay_timestamps=replay_timestamps,
                supported_windows=supported_windows,
                max_timestamps=0,
            )
        )

    def _outcome_summary(self, outcomes: list[dict[str, Any]]) -> dict[str, Any]:
        realized = [float(item.get("realized_return_pct", 0.0) or 0.0) for item in outcomes]
        return {
            "sample_size": len(outcomes),
            "net_return_after_costs": round(mean(realized), 6) if realized else 0.0,
        }

    def _empty_report(
        self,
        *,
        base_strategy_id: str,
        profile_id: str,
        timeframe: str,
        variant_id: str,
        symbol: str,
        why: str,
    ) -> dict[str, Any]:
        return {
            "title": "Symbol Replay Evidence Plan",
            "base_strategy_id": base_strategy_id,
            "profile_id": profile_id,
            "timeframe": timeframe,
            "variant_id": variant_id,
            "symbol": symbol,
            "current_symbol_evidence": {
                "earliest_bar_timestamp": None,
                "latest_bar_timestamp": None,
                "number_of_bars": 0,
                "number_of_eligible_replay_decisions": 0,
                "number_of_months_covered": 0,
                "number_of_weeks_covered": 0,
                "existing_stability_sample_size": 0,
            },
            "can_replay_more_from_existing_bars": {
                "unused_bars_outside_current_replay_window": 0,
                "additional_eligible_replay_timestamps": 0,
                "additional_checkpoint_windows_available": [],
                "can_include_earlier_periods_without_fetch": False,
                "can_include_later_periods_without_fetch": False,
                "can_replay_more_now": False,
                "why": why,
            },
            "external_data_needed": False,
            "evidence_action_verdict": "no_action_available",
            "proposed_next_research_action": "no_safe_research_action_available",
            "proposed_next_command": ".venv-mac/bin/python main.py --research-status",
            "execution_available": False,
            "stability_context": {
                "existing_stability_sample_size": 0,
                "existing_stability_months": [],
                "existing_stability_summary": {"sample_size": 0, "net_return_after_costs": 0.0},
            },
            "safety_statement": SAFETY_STATEMENT,
        }

    def _to_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None

    def _timeframe_minutes(self, timeframe: str) -> int:
        text = str(timeframe or "").strip().lower()
        return {
            "1min": 1,
            "5min": 5,
            "15min": 15,
            "1hour": 60,
            "1day": 60 * 24,
        }.get(text, 15)

    def _fmt_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")
