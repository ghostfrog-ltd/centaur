from __future__ import annotations

from bisect import bisect_left
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter
from typing import Any

from .console import ScreenLogger
from .config import RuntimeConfig, load_runtime_config
from .discovery import rank_candidates
from .fitness import enrich_strategy_fitness_rows
from .models import StepProfile, TickContext, TickReport
from .pipelines import StepDefinition
from .shadow import build_shadow_proposals, evaluate_shadow_checkpoint
from .strategies import evaluate_strategies
from .technicals import compute_volatility_breakout_context
from .usage import UsageLedger


@dataclass(frozen=True, slots=True)
class HistoricalReplayRequest:
    days: int
    timeframe: str
    equity_symbols: tuple[str, ...]
    crypto_symbols: tuple[str, ...]
    max_timestamps: int
    start_at: datetime | None = None
    end_at: datetime | None = None


def load_replay_history(context: TickContext) -> dict[str, object]:
    request = _get_request(context)
    end_at = request.end_at or context.started_at
    start_at = request.start_at or (end_at - timedelta(days=request.days))
    supported_windows = _supported_checkpoint_windows(
        timeframe=request.timeframe,
        checkpoint_windows=context.config.shadow_checkpoint_windows,
    )
    lookahead_minutes = _max_checkpoint_window_minutes(supported_windows)
    data_end_at = end_at + timedelta(minutes=lookahead_minutes)
    symbol_filters = list(request.equity_symbols) + list(request.crypto_symbols)
    rows = context.usage_ledger.list_historical_bars(
        timeframe=request.timeframe,
        sources=["alpaca_market_data", "alpaca_crypto_data"],
        start_at=start_at,
        end_at=data_end_at,
        symbols=symbol_filters,
    )
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
        if timestamp >= start_at and timestamp < end_at
    ]
    eligible_timestamps = _eligible_replay_timestamps(
        timestamps=ordered_timestamps,
        replay_timestamps=replay_timestamps,
        supported_windows=supported_windows,
        max_timestamps=request.max_timestamps,
    )

    context.metadata["historical_replay"] = {
        "rows": rows,
        "grouped_by_timestamp": grouped_by_timestamp,
        "bars_by_symbol": bars_by_symbol,
        "timestamps_by_symbol": timestamps_by_symbol,
        "ordered_timestamps": ordered_timestamps,
        "replay_timestamps": replay_timestamps,
        "eligible_timestamps": eligible_timestamps,
        "supported_windows": supported_windows,
        "timeframe_minutes": _timeframe_to_minutes(request.timeframe),
        "range_start": start_at,
        "range_end": end_at,
        "data_range_end": data_end_at,
    }
    result = {
        "bars_loaded": len(rows),
        "timestamps_loaded": len(replay_timestamps),
        "eligible_timestamps": len(eligible_timestamps),
        "timeframe": request.timeframe,
        "days": request.days,
        "range_start": start_at.isoformat(),
        "range_end": end_at.isoformat(),
        "data_range_end": data_end_at.isoformat(),
        "equity_symbols": len(request.equity_symbols),
        "crypto_symbols": len(request.crypto_symbols),
        "mode": "historical_store",
    }
    context.state["historical_replay_load"] = result
    return result


def replay_shadow_training(context: TickContext) -> dict[str, object]:
    replay_state = context.metadata.get("historical_replay", {})
    grouped_by_timestamp = replay_state.get("grouped_by_timestamp", {})
    bars_by_symbol = replay_state.get("bars_by_symbol", {})
    timestamps_by_symbol = replay_state.get("timestamps_by_symbol", {})
    eligible_timestamps = replay_state.get("eligible_timestamps", [])
    supported_windows = tuple(replay_state.get("supported_windows", ()))
    timeframe_minutes = int(replay_state.get("timeframe_minutes", 0) or 0)
    range_start = replay_state.get("range_start")
    range_end = replay_state.get("range_end")

    if not eligible_timestamps or not supported_windows:
        result = {
            "timestamps_replayed": 0,
            "proposals_created": 0,
            "outcomes_evaluated": 0,
            "strategies_triggered": 0,
            "mode": "no_eligible_history",
        }
        context.state["historical_replay_training"] = {**result, "strategy_counts": {}}
        return result

    proposals: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    strategy_counts: dict[str, int] = defaultdict(int)
    previous_by_symbol: dict[tuple[str, str], dict[str, Any]] = {}
    recent_proposal_times: dict[tuple[str, str, str], datetime] = {}
    existing_events = []
    if isinstance(range_start, datetime) and isinstance(range_end, datetime):
        existing_events = context.usage_ledger.list_shadow_proposal_events(
            start_at=range_start
            - timedelta(minutes=context.config.shadow_proposal_cooldown_minutes),
            end_at=range_end,
        )
    event_index = 0

    for replay_timestamp in eligible_timestamps:
        while event_index < len(existing_events):
            event = existing_events[event_index]
            proposed_at = event.get("proposed_at")
            if not isinstance(proposed_at, datetime) or proposed_at >= replay_timestamp:
                break
            recent_proposal_times[
                (
                    str(event.get("strategy_id", "")),
                    str(event.get("source", "")),
                    str(event.get("symbol", "")),
                )
            ] = proposed_at
            event_index += 1

        current_rows = list(grouped_by_timestamp.get(replay_timestamp, []))
        if not current_rows:
            continue

        ranked = rank_candidates(
            current_rows=current_rows,
            previous_by_symbol=previous_by_symbol,
            target_count=context.config.discovery_target_count,
        )
        candidate_dicts = [item.as_dict() for item in ranked]
        for row in current_rows:
            previous_by_symbol[(str(row["source"]), str(row["symbol"]))] = row

        if not candidate_dicts:
            continue

        enriched_candidates = _enrich_replay_candidates_with_technicals(
            candidates=candidate_dicts,
            bars_by_symbol=bars_by_symbol,
            timestamps_by_symbol=timestamps_by_symbol,
            replay_timestamp=replay_timestamp,
            lookback_periods=20,
        )

        replay_tick_id = _replay_tick_id(
            timeframe=_safe_slug(_get_request(context).timeframe),
            replay_timestamp=replay_timestamp,
        )
        batch = evaluate_strategies(
            tick_id=replay_tick_id,
            candidates=enriched_candidates,
            config=context.config,
            market_context={
                "market_gate": {"can_scan": True, "reason": "historical_replay"},
                "account_equity": 100000.0,
                "replay_timeframe": _get_request(context).timeframe,
            },
        )
        signal_dicts = [
            item.as_dict(tick_id=replay_tick_id)
            for item in batch.signals
            if int(item.holding_window_minutes) >= timeframe_minutes
        ]
        if not signal_dicts:
            continue

        recent_keys = _recent_strategy_keys(
            recent_proposal_times=recent_proposal_times,
            as_of=replay_timestamp,
            cooldown_minutes=context.config.shadow_proposal_cooldown_minutes,
        )
        replay_proposals = build_shadow_proposals(
            tick_id=replay_tick_id,
            proposed_at=replay_timestamp,
            strategy_signals=signal_dicts,
            recent_strategy_keys=recent_keys,
            proposal_limit=context.config.shadow_proposal_limit,
            min_signal_score=context.config.shadow_min_opportunity_score,
            checkpoint_windows=supported_windows,
        )
        if not replay_proposals:
            continue

        for proposal in replay_proposals:
            strategy_counts[str(proposal.get("strategy_id", ""))] += 1
            proposal["note"] = (
                f"historical_replay:{_get_request(context).timeframe.lower()}:{proposal.get('note', '')}"
            )
            recent_proposal_times[
                (
                    str(proposal.get("strategy_id", "")),
                    str(proposal.get("source", "")),
                    str(proposal.get("symbol", "")),
                )
            ] = replay_timestamp

            symbol_key = (str(proposal["source"]), str(proposal["symbol"]))
            symbol_history = list(bars_by_symbol.get(symbol_key, []))
            symbol_timestamps = list(timestamps_by_symbol.get(symbol_key, []))
            if not symbol_history or not symbol_timestamps:
                continue

            future_index = bisect_left(symbol_timestamps, replay_timestamp)
            future_bars = symbol_history[future_index:]
            if not future_bars:
                continue

            for checkpoint in proposal.get("checkpoint_windows", []):
                due_at = _to_datetime(checkpoint.get("due_at"))
                if due_at is None:
                    continue
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
                        "risk_pct": proposal.get("risk_pct", 0),
                        "holding_window_code": proposal["holding_window_code"],
                        "holding_window_minutes": proposal["holding_window_minutes"],
                        "break_even_trigger_price": proposal.get("break_even_trigger_price"),
                        "trailing_stop_mode": proposal.get("trailing_stop_mode"),
                        "raw_json": proposal,
                    },
                    bars=future_bars,
                    as_of=due_at + timedelta(minutes=timeframe_minutes),
                    execution_spread_bps=context.config.shadow_execution_spread_bps,
                    entry_slippage_bps=context.config.shadow_entry_slippage_bps,
                    exit_slippage_bps=context.config.shadow_exit_slippage_bps,
                    fixed_round_trip_cost_usd=context.config.shadow_fixed_round_trip_cost_usd,
                    reference_notional_usd=context.config.paper_execution_default_notional_usd,
                    profit_target_ladder_pct=context.config.shadow_profit_target_ladder_pct,
                )
                if outcome is not None:
                    outcomes.append(outcome)

        proposals.extend(replay_proposals)

    proposals_created = 0
    outcomes_evaluated = 0
    if proposals:
        context.usage_ledger.record_shadow_trade_proposals(proposals=proposals)
        proposals_created = len(proposals)
    if outcomes:
        outcomes_evaluated = context.usage_ledger.record_shadow_trade_outcomes(
            outcomes=outcomes,
        )

    result = {
        "timestamps_replayed": len(eligible_timestamps),
        "proposals_created": proposals_created,
        "outcomes_evaluated": outcomes_evaluated,
        "strategies_triggered": len(strategy_counts),
        "mode": "historical_shadow_replay",
    }
    if strategy_counts:
        top_strategy = max(strategy_counts.items(), key=lambda item: item[1])
        result["top_strategy"] = top_strategy[0]
        result["top_strategy_proposals"] = top_strategy[1]
    context.state["historical_replay_training"] = {
        **result,
        "strategy_counts": dict(sorted(strategy_counts.items())),
    }
    return result


def replay_strategy_fitness(context: TickContext) -> dict[str, object]:
    raw_rows = context.usage_ledger.list_strategy_fitness_rows(
        as_of=context.started_at,
        lookback_days=context.config.strategy_fitness_lookback_days,
    )
    summaries = enrich_strategy_fitness_rows(
        rows=raw_rows,
        min_checkpoints=context.config.strategy_fitness_min_checkpoints,
    )
    saved_count = context.usage_ledger.record_strategy_fitness_snapshots(
        tick_id=context.tick_id,
        captured_at=context.started_at,
        summaries=summaries,
        environment=context.config.centaur_environment,
        mode="shadow",
        source_environment="backtest",
        broker_id="simulator",
        data_provider="historical_store",
        execution_provider="simulator",
    )
    result = {
        "strategy_summaries": len(summaries),
        "summaries_saved": saved_count,
        "lookback_days": context.config.strategy_fitness_lookback_days,
        "mode": "scorecard" if summaries else "insufficient_data",
    }
    if summaries:
        result["top_strategy"] = summaries[0]["strategy_id"]
        result["top_checkpoint"] = summaries[0]["checkpoint_code"]
        result["top_composite_score"] = summaries[0]["composite_fitness_score"]
    context.state["historical_replay_fitness"] = {**result, "summaries": summaries}
    return result


def build_historical_replay_pipeline() -> list[StepDefinition]:
    return [
        StepDefinition(name="replay.load_history", runner=load_replay_history),
        StepDefinition(name="replay.shadow_training", runner=replay_shadow_training),
        StepDefinition(name="replay.strategy_fitness", runner=replay_strategy_fitness),
    ]


class HistoricalReplayRunner:
    def __init__(
        self,
        *,
        steps: list[StepDefinition] | None = None,
        logger: ScreenLogger | None = None,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.steps = steps or build_historical_replay_pipeline()
        self.logger = logger or ScreenLogger()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def run(
        self,
        *,
        days: int | None = None,
        timeframe: str | None = None,
        equity_symbols: tuple[str, ...] | None = None,
        crypto_symbols: tuple[str, ...] | None = None,
        max_timestamps: int | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
    ) -> TickReport:
        request = HistoricalReplayRequest(
            days=max(1, days or self.config.historical_replay_default_days),
            timeframe=(timeframe or self.config.historical_replay_default_timeframe).strip()
            or self.config.historical_replay_default_timeframe,
            equity_symbols=equity_symbols or self.config.discovery_equity_symbols,
            crypto_symbols=crypto_symbols or self.config.discovery_crypto_symbols,
            max_timestamps=max(0, max_timestamps or self.config.historical_replay_max_timestamps),
            start_at=start_at,
            end_at=end_at,
        )
        started_at = datetime.now().astimezone()
        started_perf = perf_counter()
        tick_id = f"replayrun-{started_at.strftime('%Y%m%d-%H%M%S-%f')}"
        context = TickContext(
            tick_id=tick_id,
            started_at=started_at,
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        context.metadata["historical_replay_request"] = request
        context.state["run"] = {
            "pipeline": "historical_replay",
            "days": request.days,
            "timeframe": request.timeframe,
            "equity_symbols": list(request.equity_symbols),
            "crypto_symbols": list(request.crypto_symbols),
            "max_timestamps": request.max_timestamps,
            "range_start": (request.start_at.isoformat() if request.start_at else None),
            "range_end": (request.end_at.isoformat() if request.end_at else None),
        }

        self.logger.tick_start(
            tick_id=tick_id,
            started_at=started_at,
            stage_count=len(self.steps),
            pipeline_name="historical_replay",
        )
        self.logger.runtime_summary(config=self.config, started_at=started_at)
        self.logger.line(
            (
                "Replay: "
                f"days={request.days} | "
                f"timeframe={request.timeframe} | "
                f"equities={len(request.equity_symbols)} | "
                f"crypto={len(request.crypto_symbols)} | "
                f"max_timestamps={request.max_timestamps or 'all'} | "
                f"range_start={(request.start_at or (started_at - timedelta(days=request.days))).isoformat()} | "
                f"range_end={(request.end_at or started_at).isoformat()}"
            ),
            timestamp=started_at,
        )

        step_profiles: list[StepProfile] = []
        status = "ok"
        for index, step in enumerate(self.steps, start=1):
            profile = self._run_step(
                context=context,
                step=step,
                index=index,
                total=len(self.steps),
            )
            step_profiles.append(profile)
            if profile.status != "ok":
                status = "error"
                break

        ended_at = datetime.now().astimezone()
        duration_seconds = perf_counter() - started_perf
        tick_api_usage = self.usage_ledger.list_tick_usage(
            tick_id=tick_id,
            usage_date=started_at.date(),
        )
        daily_api_usage = self.usage_ledger.list_daily_usage(
            usage_date=started_at.date(),
        )
        daily_estimated_cost_usd = self.usage_ledger.total_estimated_cost_usd(
            daily_api_usage
        )
        report = TickReport(
            tick_id=tick_id,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            step_profiles=step_profiles,
            state_snapshot=dict(context.state),
            tick_api_usage=tick_api_usage,
            daily_api_usage=daily_api_usage,
            tick_api_request_count=self.usage_ledger.total_requests(tick_api_usage),
            tick_estimated_cost_usd=self.usage_ledger.total_estimated_cost_usd(
                tick_api_usage
            ),
            daily_api_request_count=self.usage_ledger.total_requests(daily_api_usage),
            daily_estimated_cost_usd=daily_estimated_cost_usd,
            daily_warning_threshold_usd=self.config.api_daily_cost_warning_usd,
            daily_limit_threshold_usd=self.config.api_daily_cost_limit_usd,
            budget_status=self.usage_ledger.budget_status(
                daily_estimated_cost_usd=daily_estimated_cost_usd
            ),
            operations_backend=self.usage_ledger.backend,
            operations_backend_detail=self.usage_ledger.backend_detail,
        )
        try:
            report.persisted_tick_run = self.usage_ledger.record_tick_run(report)
        except Exception as exc:
            report.persistence_error = f"{type(exc).__name__}: {exc}"

        self.logger.profiling_summary(report)
        self.logger.api_usage_summary(report)
        self.logger.tick_end(report)
        return report

    def _run_step(
        self,
        *,
        context: TickContext,
        step: StepDefinition,
        index: int,
        total: int,
    ) -> StepProfile:
        started_at = datetime.now().astimezone()
        started_perf = perf_counter()
        self.logger.step_start(
            step_name=step.name,
            index=index,
            total=total,
            started_at=started_at,
        )
        details: dict[str, object]
        status = "ok"
        error: str | None = None
        try:
            details = step.runner(context) or {}
        except Exception as exc:
            details = {"error_type": type(exc).__name__}
            error = str(exc)
            status = "error"
            context.state["last_error"] = {
                "step": step.name,
                "message": error,
            }

        ended_at = datetime.now().astimezone()
        duration_seconds = perf_counter() - started_perf
        profile = StepProfile(
            name=step.name,
            status=status,
            started_at=started_at,
            ended_at=ended_at,
            duration_seconds=duration_seconds,
            details=details,
            error=error,
        )
        self.logger.step_end(profile=profile, index=index, total=total)
        return profile


def _get_request(context: TickContext) -> HistoricalReplayRequest:
    request = context.metadata.get("historical_replay_request")
    if not isinstance(request, HistoricalReplayRequest):
        raise RuntimeError("Historical replay request is not configured.")
    return request


def _eligible_replay_timestamps(
    *,
    timestamps: list[datetime],
    replay_timestamps: list[datetime],
    supported_windows: tuple[str, ...],
    max_timestamps: int,
) -> list[datetime]:
    if not timestamps or not replay_timestamps:
        return []
    if not supported_windows:
        return []
    max_window = _max_checkpoint_window_minutes(supported_windows)
    cutoff = timestamps[-1] - timedelta(minutes=max_window)
    eligible = [timestamp for timestamp in replay_timestamps if timestamp <= cutoff]
    if max_timestamps > 0:
        eligible = eligible[-max_timestamps:]
    return eligible


def _supported_checkpoint_windows(
    *,
    timeframe: str,
    checkpoint_windows: tuple[str, ...],
) -> tuple[str, ...]:
    timeframe_minutes = _timeframe_to_minutes(timeframe)
    supported = [
        code
        for code in checkpoint_windows
        if _window_code_to_minutes(code) >= timeframe_minutes
    ]
    if not supported:
        fallback_minutes = timeframe_minutes
        if fallback_minutes >= 1440:
            return ("1d",)
        if fallback_minutes >= 60:
            return ("1h", "1d")
        return checkpoint_windows
    return tuple(supported)


def _recent_strategy_keys(
    *,
    recent_proposal_times: dict[tuple[str, str, str], datetime],
    as_of: datetime,
    cooldown_minutes: int,
) -> set[tuple[str, str, str]]:
    threshold = as_of - timedelta(minutes=max(0, cooldown_minutes))
    return {
        key
        for key, proposed_at in recent_proposal_times.items()
        if proposed_at >= threshold
    }


def _replay_tick_id(*, timeframe: str, replay_timestamp: datetime) -> str:
    return f"replay-{timeframe}-{replay_timestamp.astimezone().strftime('%Y%m%d-%H%M%S')}"


def _enrich_replay_candidates_with_technicals(
    *,
    candidates: list[dict[str, Any]],
    bars_by_symbol: dict[tuple[str, str], list[dict[str, Any]]],
    timestamps_by_symbol: dict[tuple[str, str], list[datetime]],
    replay_timestamp: datetime,
    lookback_periods: int,
) -> list[dict[str, Any]]:
    enriched: list[dict[str, Any]] = []
    minimum_bars = lookback_periods + 1

    for candidate in candidates:
        source = str(candidate.get("source", "")).strip()
        symbol = str(candidate.get("symbol", "")).upper()
        symbol_key = (source, symbol)
        symbol_history = list(bars_by_symbol.get(symbol_key, []))
        symbol_timestamps = list(timestamps_by_symbol.get(symbol_key, []))
        if not symbol_history or not symbol_timestamps:
            enriched.append(dict(candidate))
            continue

        cutoff = bisect_left(symbol_timestamps, replay_timestamp)
        if cutoff < len(symbol_timestamps) and symbol_timestamps[cutoff] == replay_timestamp:
            cutoff += 1
        history_slice = symbol_history[max(0, cutoff - minimum_bars) : cutoff]
        technical_context = compute_volatility_breakout_context(
            bars=history_slice,
            lookback_periods=lookback_periods,
        )
        enriched.append(
            {
                **candidate,
                **technical_context,
            }
        )

    return enriched


def _window_code_to_minutes(code: str) -> int:
    normalized = code.strip().lower()
    if len(normalized) < 2:
        raise ValueError(f"Unsupported replay window: {code}")
    suffix = normalized[-1]
    value = int(normalized[:-1])
    if suffix == "m":
        return value
    if suffix == "h":
        return value * 60
    if suffix == "d":
        return value * 60 * 24
    if suffix == "w":
        return value * 60 * 24 * 7
    raise ValueError(f"Unsupported replay window: {code}")


def _max_checkpoint_window_minutes(checkpoint_windows: tuple[str, ...]) -> int:
    if not checkpoint_windows:
        return 0
    return max(_window_code_to_minutes(code) for code in checkpoint_windows)


def _timeframe_to_minutes(timeframe: str) -> int:
    normalized = timeframe.strip().lower()
    if normalized.endswith("min"):
        return int(normalized[:-3])
    if normalized.endswith("hour"):
        return int(normalized[:-4]) * 60
    if normalized.endswith("day"):
        return int(normalized[:-3]) * 60 * 24
    raise ValueError(f"Unsupported replay timeframe: {timeframe}")


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    return datetime.fromisoformat(str(value))


def _safe_slug(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace("/", "_")
        .replace(" ", "_")
    )
