from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from time import sleep
from typing import Any, Callable

from app.framework.adapters.market_data import get_market_data_adapter
from app.framework.reporting.console import ScreenLogger
from app.framework.runtime.models import StepProfile, TickContext, TickReport
from app.framework.runtime.settings import PROJECT_ROOT, RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger
from app.framework.strategies.registry import build_strategy_registry

from .pipelines import StepDefinition, fx_gbp_reference

CRYPTO_15MIN_MINIMUM_DAYS_REQUIRED = 30
CRYPTO_15MIN_PREFERRED_DAYS = 90


@dataclass(frozen=True, slots=True)
class HistoricalBackfillRequest:
    days: int
    timeframe: str
    equity_symbols: tuple[str, ...]
    crypto_symbols: tuple[str, ...]
    dry_run: bool = False


@dataclass(frozen=True, slots=True)
class MultiTimeframeEquityBackfillRequest:
    years: int
    timeframes: tuple[str, ...]
    equity_symbols: tuple[str, ...]
    dry_run: bool = False
    backfill_from_start: bool = False
    batch_size: int = 20
    retry_limit: int = 3
    base_backoff_seconds: float = 1.0


@dataclass(frozen=True, slots=True)
class Crypto1DayResampleRequest:
    crypto_symbols: tuple[str, ...]
    completeness_threshold: float = 0.80
    native_lookback_days: int = 365


@dataclass(frozen=True, slots=True)
class Crypto15MinBackfillRequest:
    crypto_symbols: tuple[str, ...]
    minimum_days_required: int = CRYPTO_15MIN_MINIMUM_DAYS_REQUIRED
    preferred_days: int = CRYPTO_15MIN_PREFERRED_DAYS
    source_timeframe: str = "15Min"
    resample_from_timeframe: str = "1Min"


@dataclass(frozen=True, slots=True)
class Crypto15MinImportRequest:
    path: str
    crypto_symbols: tuple[str, ...]
    minimum_days_required: int = 30
    timeframe: str = "15Min"
    source: str = "alpaca_crypto_data"


CRYPTO_1DAY_DATASET_ID = "historical_crypto_bars:1Day"
CRYPTO_1DAY_REPORT_TYPE = "historical_crypto_1day_backfill_or_resample"
CRYPTO_15MIN_DATASET_ID = "historical_crypto_bars:15Min"
CRYPTO_15MIN_REPORT_TYPE = "historical_crypto_15min_backfill_or_resample"
CRYPTO_15MIN_IMPORT_REPORT_TYPE = "historical_crypto_15min_bulk_import"


def backfill_equities(context: TickContext) -> dict[str, object]:
    request = _get_request(context)
    if not request.equity_symbols:
        result = {
            "symbols_requested": 0,
            "symbols_with_data": 0,
            "bars_saved": 0,
            "bars_inserted": 0,
            "bars_updated": 0,
            "dry_run": bool(request.dry_run),
            "mode": "disabled",
            "attempted_symbols": [],
            "success_symbols": [],
            "failed_symbols": [],
            "skipped_symbols": [],
            "skip_reasons": ["symbol_universe_empty"],
            "provider_error_count": 0,
            "provider_errors": [],
        }
        context.state["historical_equity_backfill"] = result
        return result

    fx_reference = context.state["fx_gbp_reference"]
    start_at = context.started_at - timedelta(days=request.days)
    market_data = get_market_data_adapter(context, "alpaca")
    bars_by_symbol = market_data.get_historical_equity_bars(
        context,
        symbols=list(request.equity_symbols),
        timeframe=request.timeframe,
        start=start_at,
        end=context.started_at,
        feed=context.config.alpaca_stock_feed,
    )
    plan = _plan_historical_bar_write(
        context=context,
        source="alpaca_market_data",
        asset_class="equity",
        timeframe=request.timeframe,
        bars_by_symbol=bars_by_symbol,
    )
    bars_saved = 0
    if not request.dry_run:
        bars_saved = context.usage_ledger.record_historical_bars(
            batch_id=context.tick_id,
            captured_at=context.started_at,
            source="alpaca_market_data",
            asset_class="equity",
            timeframe=request.timeframe,
            bars_by_symbol=bars_by_symbol,
            quote_currency="USD",
            usd_to_gbp=float(fx_reference["usd_to_gbp"]),
        )
    attempted_symbols = [str(symbol) for symbol in request.equity_symbols]
    success_symbols = sorted(
        symbol for symbol, bars in bars_by_symbol.items() if list(bars or [])
    )
    skipped_symbols = sorted(set(attempted_symbols) - set(success_symbols))
    skip_reasons = _infer_skip_reasons(
        attempted_symbols=attempted_symbols,
        success_symbols=success_symbols,
        bars_inserted=int(plan["bars_inserted"]),
        bars_updated=int(plan["bars_updated"]),
        latest_bar_timestamp=plan["latest_bar_timestamp"],
    )
    result = {
        "symbols_requested": len(request.equity_symbols),
        "symbols_with_data": len(bars_by_symbol),
        "bars_saved": bars_saved,
        "bars_inserted": int(plan["bars_inserted"]),
        "bars_updated": int(plan["bars_updated"]),
        "timeframe": request.timeframe,
        "days": request.days,
        "dry_run": bool(request.dry_run),
        "mode": "historical_bars_dry_run" if request.dry_run else "historical_bars",
        "latest_bar_timestamp": plan["latest_bar_timestamp"],
        "attempted_symbols": attempted_symbols,
        "success_symbols": success_symbols,
        "failed_symbols": [],
        "skipped_symbols": skipped_symbols,
        "skip_reasons": skip_reasons,
        "provider_error_count": 0,
        "provider_errors": [],
    }
    if bars_by_symbol:
        top_symbol, top_count = max(
            ((symbol, len(bars)) for symbol, bars in bars_by_symbol.items()),
            key=lambda item: item[1],
        )
        result["top_symbol"] = top_symbol
        result["top_symbol_bars"] = top_count
    context.state["historical_equity_backfill"] = result
    return result


def backfill_crypto(context: TickContext) -> dict[str, object]:
    request = _get_request(context)
    if not request.crypto_symbols:
        result = {
            "symbols_requested": 0,
            "symbols_with_data": 0,
            "bars_saved": 0,
            "bars_inserted": 0,
            "bars_updated": 0,
            "dry_run": bool(request.dry_run),
            "mode": "disabled",
            "attempted_symbols": [],
            "success_symbols": [],
            "failed_symbols": [],
            "skipped_symbols": [],
            "skip_reasons": ["symbol_universe_empty"],
            "provider_error_count": 0,
            "provider_errors": [],
        }
        context.state["historical_crypto_backfill"] = result
        return result

    fx_reference = context.state["fx_gbp_reference"]
    start_at = context.started_at - timedelta(days=request.days)
    market_data = get_market_data_adapter(context, "alpaca")
    bars_by_symbol = market_data.get_historical_crypto_bars(
        context,
        location=context.config.alpaca_crypto_location,
        symbols=list(request.crypto_symbols),
        timeframe=request.timeframe,
        start=start_at,
        end=context.started_at,
    )
    plan = _plan_historical_bar_write(
        context=context,
        source="alpaca_crypto_data",
        asset_class="crypto",
        timeframe=request.timeframe,
        bars_by_symbol=bars_by_symbol,
    )
    bars_saved = 0
    if not request.dry_run:
        bars_saved = context.usage_ledger.record_historical_bars(
            batch_id=context.tick_id,
            captured_at=context.started_at,
            source="alpaca_crypto_data",
            asset_class="crypto",
            timeframe=request.timeframe,
            bars_by_symbol=bars_by_symbol,
            quote_currency="USD",
            usd_to_gbp=float(fx_reference["usd_to_gbp"]),
        )
    attempted_symbols = [str(symbol) for symbol in request.crypto_symbols]
    success_symbols = sorted(
        symbol for symbol, bars in bars_by_symbol.items() if list(bars or [])
    )
    skipped_symbols = sorted(set(attempted_symbols) - set(success_symbols))
    skip_reasons = _infer_skip_reasons(
        attempted_symbols=attempted_symbols,
        success_symbols=success_symbols,
        bars_inserted=int(plan["bars_inserted"]),
        bars_updated=int(plan["bars_updated"]),
        latest_bar_timestamp=plan["latest_bar_timestamp"],
    )
    result = {
        "symbols_requested": len(request.crypto_symbols),
        "symbols_with_data": len(bars_by_symbol),
        "bars_saved": bars_saved,
        "bars_inserted": int(plan["bars_inserted"]),
        "bars_updated": int(plan["bars_updated"]),
        "timeframe": request.timeframe,
        "days": request.days,
        "dry_run": bool(request.dry_run),
        "mode": "historical_bars_dry_run" if request.dry_run else "historical_bars",
        "latest_bar_timestamp": plan["latest_bar_timestamp"],
        "attempted_symbols": attempted_symbols,
        "success_symbols": success_symbols,
        "failed_symbols": [],
        "skipped_symbols": skipped_symbols,
        "skip_reasons": skip_reasons,
        "provider_error_count": 0,
        "provider_errors": [],
    }
    if bars_by_symbol:
        top_symbol, top_count = max(
            ((symbol, len(bars)) for symbol, bars in bars_by_symbol.items()),
            key=lambda item: item[1],
        )
        result["top_symbol"] = top_symbol
        result["top_symbol_bars"] = top_count
    context.state["historical_crypto_backfill"] = result
    return result


def build_historical_backfill_pipeline() -> list[StepDefinition]:
    return [
        StepDefinition(name="fx.gbp_reference", runner=fx_gbp_reference),
        StepDefinition(name="backfill.equities", runner=backfill_equities),
        StepDefinition(name="backfill.crypto", runner=backfill_crypto),
    ]


class HistoricalBackfillRunner:
    def __init__(
        self,
        *,
        steps: list[StepDefinition] | None = None,
        logger: ScreenLogger | None = None,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
        sleep_fn: Callable[[float], None] | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.steps = steps or build_historical_backfill_pipeline()
        self.logger = logger or ScreenLogger()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)
        self.sleep_fn = sleep_fn or sleep

    def run(
        self,
        *,
        days: int | None = None,
        timeframe: str | None = None,
        equity_symbols: tuple[str, ...] | None = None,
        crypto_symbols: tuple[str, ...] | None = None,
        dry_run: bool = False,
    ) -> TickReport:
        request = HistoricalBackfillRequest(
            days=max(1, days or self.config.historical_backfill_default_days),
            timeframe=(timeframe or self.config.historical_backfill_default_timeframe).strip()
            or self.config.historical_backfill_default_timeframe,
            equity_symbols=equity_symbols or self.config.discovery_equity_symbols,
            crypto_symbols=crypto_symbols or self.config.discovery_crypto_symbols,
            dry_run=bool(dry_run),
        )
        started_at = datetime.now().astimezone()
        started_perf = perf_counter()
        tick_id = f"backfill-{started_at.strftime('%Y%m%d-%H%M%S')}"
        context = TickContext(
            tick_id=tick_id,
            started_at=started_at,
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        context.metadata["historical_backfill_request"] = request
        context.state["run"] = {
            "pipeline": "historical_backfill",
            "days": request.days,
            "timeframe": request.timeframe,
            "equity_symbols": list(request.equity_symbols),
            "crypto_symbols": list(request.crypto_symbols),
        }

        self.logger.tick_start(
            tick_id=tick_id,
            started_at=started_at,
            stage_count=len(self.steps),
            pipeline_name="historical_backfill",
        )
        self.logger.runtime_summary(config=self.config, started_at=started_at)
        self.logger.line(
            (
                "Backfill: "
                f"days={request.days} | "
                f"timeframe={request.timeframe} | "
                f"equities={len(request.equity_symbols)} | "
                f"crypto={len(request.crypto_symbols)} | "
                f"dry_run={'yes' if request.dry_run else 'no'}"
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

    def run_equity_timeframe_backfill(
        self,
        *,
        years: int,
        timeframes: tuple[str, ...],
        symbols_from_strategies: bool = False,
        dry_run: bool = False,
        backfill_from_start: bool = False,
        batch_size: int = 20,
        retry_limit: int = 3,
        base_backoff_seconds: float = 1.0,
    ) -> TickReport:
        request = MultiTimeframeEquityBackfillRequest(
            years=max(1, int(years)),
            timeframes=self._normalize_timeframes(timeframes),
            equity_symbols=self._resolve_equity_symbols(
                symbols_from_strategies=symbols_from_strategies
            ),
            dry_run=bool(dry_run),
            backfill_from_start=bool(backfill_from_start),
            batch_size=max(1, int(batch_size)),
            retry_limit=max(1, int(retry_limit)),
            base_backoff_seconds=max(0.0, float(base_backoff_seconds)),
        )
        started_at = datetime.now().astimezone()
        started_perf = perf_counter()
        tick_id = f"backfill-equity-{started_at.strftime('%Y%m%d-%H%M%S')}"
        context = TickContext(
            tick_id=tick_id,
            started_at=started_at,
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        context.state["run"] = {
            "pipeline": "historical_equity_backfill",
            "years": request.years,
            "timeframes": list(request.timeframes),
            "equity_symbols": list(request.equity_symbols),
            "symbols_from_strategies": bool(symbols_from_strategies),
            "dry_run": bool(request.dry_run),
            "backfill_from_start": bool(request.backfill_from_start),
            "safety_guard": "historical_backfill_only_no_orders_no_auto_approvals",
        }
        context.state["promotion_mutation_count"] = 0
        context.state["live_execution_enabled"] = bool(
            getattr(self.config, "live_execution_enabled", False)
        )

        self.logger.tick_start(
            tick_id=tick_id,
            started_at=started_at,
            stage_count=max(1, len(request.timeframes)),
            pipeline_name="historical_equity_backfill",
        )
        self.logger.runtime_summary(config=self.config, started_at=started_at)
        self.logger.line(
            (
                "Equity Backfill: "
                f"years={request.years} | "
                f"timeframes={','.join(request.timeframes)} | "
                f"equities={len(request.equity_symbols)} | "
                f"symbols_from_strategies={'yes' if symbols_from_strategies else 'no'} | "
                f"backfill_from_start={'yes' if request.backfill_from_start else 'no'} | "
                f"dry_run={'yes' if request.dry_run else 'no'}"
            ),
            timestamp=started_at,
        )

        fx_reference = fx_gbp_reference(context)
        details = self._run_equity_backfill_batches(
            context=context,
            request=request,
            fx_reference=fx_reference,
        )
        step_profiles = [
            StepProfile(
                name="backfill.equity_timeframes",
                status="ok",
                started_at=started_at,
                ended_at=datetime.now().astimezone(),
                duration_seconds=max(0.0, perf_counter() - started_perf),
                details=details,
            )
        ]
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
            status="ok",
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

    def run_crypto_1day_backfill_or_resample(self) -> TickReport:
        request = Crypto1DayResampleRequest(
            crypto_symbols=tuple(self.config.discovery_crypto_symbols or ()),
        )
        started_at = datetime.now().astimezone()
        started_perf = perf_counter()
        tick_id = f"backfill-crypto-1day-{started_at.strftime('%Y%m%d-%H%M%S')}"
        context = TickContext(
            tick_id=tick_id,
            started_at=started_at,
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        context.state["run"] = {
            "pipeline": "historical_crypto_1day_backfill_or_resample",
            "crypto_symbols": list(request.crypto_symbols),
            "safety_guard": "historical_backfill_only_no_orders_no_auto_approvals",
        }
        context.state["promotion_mutation_count"] = 0
        context.state["live_execution_enabled"] = bool(
            getattr(self.config, "live_execution_enabled", False)
        )

        self.logger.tick_start(
            tick_id=tick_id,
            started_at=started_at,
            stage_count=1,
            pipeline_name="historical_crypto_1day_backfill_or_resample",
        )
        self.logger.runtime_summary(config=self.config, started_at=started_at)
        self.logger.line(
            (
                "Crypto 1Day Backfill/Resample: "
                f"symbols={len(request.crypto_symbols)} | "
                f"completeness_threshold={request.completeness_threshold:.2f}"
            ),
            timestamp=started_at,
        )

        fx_reference = fx_gbp_reference(context)
        details = self._run_crypto_1day_backfill_or_resample(
            context=context,
            request=request,
            fx_reference=fx_reference,
        )
        context.state["historical_crypto_1day_backfill_or_resample"] = details
        step_profiles = [
            StepProfile(
                name="backfill.crypto_1day_resample",
                status="ok",
                started_at=started_at,
                ended_at=datetime.now().astimezone(),
                duration_seconds=max(0.0, perf_counter() - started_perf),
                details=details,
            )
        ]
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
            status="ok",
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

    def run_crypto_15min_backfill_or_resample(
        self,
        *,
        days: int | None = None,
        crypto_symbols: tuple[str, ...] | None = None,
    ) -> TickReport:
        resolved_days = max(1, int(days)) if days is not None else None
        request = Crypto15MinBackfillRequest(
            crypto_symbols=tuple(
                crypto_symbols or self.config.discovery_crypto_symbols or ()
            ),
            minimum_days_required=resolved_days
            if resolved_days is not None
            else CRYPTO_15MIN_MINIMUM_DAYS_REQUIRED,
            preferred_days=resolved_days
            if resolved_days is not None
            else CRYPTO_15MIN_PREFERRED_DAYS,
        )
        started_at = datetime.now().astimezone()
        started_perf = perf_counter()
        tick_id = f"backfill-crypto-15min-{started_at.strftime('%Y%m%d-%H%M%S')}"
        context = TickContext(
            tick_id=tick_id,
            started_at=started_at,
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        context.state["run"] = {
            "pipeline": "historical_crypto_15min_backfill_or_resample",
            "crypto_symbols": list(request.crypto_symbols),
            "minimum_days_required": request.minimum_days_required,
            "preferred_days": request.preferred_days,
            "safety_guard": "historical_backfill_only_no_orders_no_auto_approvals",
        }
        context.state["promotion_mutation_count"] = 0
        context.state["live_execution_enabled"] = bool(
            getattr(self.config, "live_execution_enabled", False)
        )

        self.logger.tick_start(
            tick_id=tick_id,
            started_at=started_at,
            stage_count=1,
            pipeline_name="historical_crypto_15min_backfill_or_resample",
        )
        self.logger.runtime_summary(config=self.config, started_at=started_at)
        self.logger.line(
            (
                "Crypto 15Min Backfill/Resample: "
                f"symbols={len(request.crypto_symbols)} | "
                f"minimum_days_required={request.minimum_days_required} | "
                f"preferred_days={request.preferred_days}"
            ),
            timestamp=started_at,
        )

        fx_reference = fx_gbp_reference(context)
        details = self._run_crypto_15min_backfill_or_resample(
            context=context,
            request=request,
            fx_reference=fx_reference,
        )
        context.state["historical_crypto_15min_backfill_or_resample"] = details
        step_profiles = [
            StepProfile(
                name="backfill.crypto_15min_resample",
                status="ok",
                started_at=started_at,
                ended_at=datetime.now().astimezone(),
                duration_seconds=max(0.0, perf_counter() - started_perf),
                details=details,
            )
        ]
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
            status="ok",
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

    def run_crypto_15min_bulk_import(self, *, path: str) -> TickReport:
        request = Crypto15MinImportRequest(
            path=str(path).strip(),
            crypto_symbols=tuple(
                str(symbol).strip()
                for symbol in self.config.discovery_crypto_symbols
                if str(symbol).strip()
            ),
        )
        started_at = datetime.now().astimezone()
        started_perf = perf_counter()
        tick_id = f"import-crypto-15min-{started_at.strftime('%Y%m%d-%H%M%S')}"
        context = TickContext(
            tick_id=tick_id,
            started_at=started_at,
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        context.state["run"] = {
            "pipeline": "historical_crypto_15min_bulk_import",
            "path": request.path,
            "crypto_symbols": list(request.crypto_symbols),
            "timeframe": request.timeframe,
        }

        self.logger.tick_start(
            tick_id=tick_id,
            started_at=started_at,
            stage_count=1,
            pipeline_name="historical_crypto_15min_bulk_import",
        )
        self.logger.runtime_summary(config=self.config, started_at=started_at)
        self.logger.line(
            (
                "Crypto 15Min Bulk Import: "
                f"path={request.path} | "
                f"configured_symbols={len(request.crypto_symbols)} | "
                f"timeframe={request.timeframe}"
            ),
            timestamp=started_at,
        )

        details = self._run_crypto_15min_bulk_import(
            context=context,
            request=request,
            fx_reference={"usd_to_gbp": 1.0},
        )
        context.state["historical_crypto_15min_bulk_import"] = details
        step_profiles = [
            StepProfile(
                name="historical_crypto_15min_bulk_import",
                status="ok",
                started_at=started_at,
                ended_at=datetime.now().astimezone(),
                duration_seconds=max(0.0, perf_counter() - started_perf),
                details=details,
            )
        ]

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
            status="ok",
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

    def _run_crypto_1day_backfill_or_resample(
        self,
        *,
        context: TickContext,
        request: Crypto1DayResampleRequest,
        fx_reference: dict[str, Any],
    ) -> dict[str, Any]:
        symbols = [str(symbol) for symbol in request.crypto_symbols]
        if not symbols:
            result = {
                "source_used": "none",
                "source_timeframe": "",
                "symbols_processed": 0,
                "symbols_covered": 0,
                "days_processed": 0,
                "days_covered": 0,
                "bars_generated": 0,
                "skipped_incomplete_days": 0,
                "data_gap_resolved": "no",
                "readiness_status": "no_symbols_configured",
                "symbols_requested": [],
                "symbols_with_generated_bars": [],
                "symbols_missing_after_run": [],
                "paper_trades_created": "no",
                "live_changed": "no",
                "thresholds_changed": "no",
                "promotion_policy_changed": "no",
            }
            self._record_crypto_1day_readiness(context=context, result=result)
            return result

        candidates = [
            self._load_native_crypto_1day_candidate(
                context=context,
                symbols=symbols,
                lookback_days=request.native_lookback_days,
            ),
            self._resample_crypto_1day_candidate(
                context=context,
                symbols=symbols,
                source_timeframe="1Hour",
                completeness_threshold=request.completeness_threshold,
            ),
            self._resample_crypto_1day_candidate(
                context=context,
                symbols=symbols,
                source_timeframe="15Min",
                completeness_threshold=request.completeness_threshold,
            ),
        ]
        chosen = max(candidates, key=self._candidate_sort_key)
        bars_saved = 0
        if chosen["bars_by_symbol"]:
            bars_saved = self.usage_ledger.record_historical_bars(
                batch_id=context.tick_id,
                captured_at=context.started_at,
                source="alpaca_crypto_data",
                asset_class="crypto",
                timeframe="1Day",
                bars_by_symbol=chosen["bars_by_symbol"],
                quote_currency="USD",
                usd_to_gbp=float(fx_reference["usd_to_gbp"]),
            )
        result = {
            "source_used": chosen["source_used"],
            "source_timeframe": chosen["source_timeframe"],
            "symbols_processed": len(symbols),
            "symbols_covered": int(chosen["symbols_covered"]),
            "days_processed": int(chosen["days_processed"]),
            "days_covered": int(chosen["days_covered"]),
            "bars_generated": int(chosen["bars_generated"]),
            "bars_saved": int(bars_saved),
            "skipped_incomplete_days": int(chosen["skipped_incomplete_days"]),
            "data_gap_resolved": "yes" if int(chosen["bars_generated"]) > 0 else "no",
            "readiness_status": "ready" if int(chosen["bars_generated"]) > 0 else "remaining_data_gap",
            "provider_error": str(chosen.get("provider_error", "") or ""),
            "symbols_requested": symbols,
            "symbols_with_generated_bars": list(chosen["symbols_with_generated_bars"]),
            "symbols_missing_after_run": list(chosen["symbols_missing_after_run"]),
            "paper_trades_created": "no",
            "live_changed": "no",
            "thresholds_changed": "no",
            "promotion_policy_changed": "no",
        }
        self._record_crypto_1day_readiness(context=context, result=result)
        return result

    def _load_native_crypto_1day_candidate(
        self,
        *,
        context: TickContext,
        symbols: list[str],
        lookback_days: int,
    ) -> dict[str, Any]:
        market_data = get_market_data_adapter(context, "alpaca")
        provider_error = ""
        bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
        try:
            fetched = market_data.get_historical_crypto_bars(
                context,
                location=context.config.alpaca_crypto_location,
                symbols=symbols,
                timeframe="1Day",
                start=context.started_at - timedelta(days=max(1, lookback_days)),
                end=context.started_at,
            )
            for symbol, bars in (fetched or {}).items():
                normalized: list[dict[str, Any]] = []
                for bar in list(bars or []):
                    bar_start = self._to_datetime(bar.get("t"))
                    normalized.append(
                        {
                            **dict(bar),
                            "source_timeframe": "1Day",
                            "source_bar_count": 1,
                            "completeness_ratio": 1.0,
                            "provenance": "native_1Day_backfill",
                            "start_at": bar_start,
                            "end_at": bar_start + timedelta(days=1) if bar_start is not None else None,
                        }
                    )
                if normalized:
                    bars_by_symbol[str(symbol).upper()] = normalized
        except Exception as exc:
            provider_error = f"{type(exc).__name__}: {exc}"
        return self._candidate_summary(
            source_used="native_1Day",
            source_timeframe="1Day",
            bars_by_symbol=bars_by_symbol,
            requested_symbols=symbols,
            skipped_incomplete_days=0,
            provider_error=provider_error,
        )

    def _resample_crypto_1day_candidate(
        self,
        *,
        context: TickContext,
        symbols: list[str],
        source_timeframe: str,
        completeness_threshold: float,
    ) -> dict[str, Any]:
        rows = self.usage_ledger.list_historical_bars(
            timeframe=source_timeframe,
            sources=["alpaca_crypto_data"],
            symbols=symbols,
            start_at=None,
            end_at=None,
        )
        rows_by_symbol_day: dict[tuple[str, date], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            bar_dt = self._to_datetime(row.get("bar_timestamp"))
            if bar_dt is None:
                continue
            rows_by_symbol_day[(str(row.get("symbol", "")).upper(), bar_dt.astimezone(UTC).date())].append(row)

        expected_count = 24 if source_timeframe == "1Hour" else 96
        bars_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
        skipped_incomplete_days = 0
        for (symbol, day_key), items in rows_by_symbol_day.items():
            ordered = sorted(
                items,
                key=lambda item: self._to_datetime(item.get("bar_timestamp")) or context.started_at,
            )
            count = len(ordered)
            completeness_ratio = count / expected_count if expected_count else 0.0
            if completeness_ratio < completeness_threshold:
                skipped_incomplete_days += 1
                continue
            open_price = self._to_float(ordered[0].get("open_price"))
            high_values = [
                self._to_float(item.get("high_price")) for item in ordered if self._to_float(item.get("high_price")) is not None
            ]
            low_values = [
                self._to_float(item.get("low_price")) for item in ordered if self._to_float(item.get("low_price")) is not None
            ]
            close_price = self._to_float(ordered[-1].get("close_price"))
            if open_price is None or close_price is None or not high_values or not low_values:
                skipped_incomplete_days += 1
                continue
            volume_values = [
                self._to_float(item.get("volume")) for item in ordered if item.get("volume") is not None
            ]
            trade_count_values = [
                int(item.get("trade_count") or 0) for item in ordered if item.get("trade_count") is not None
            ]
            day_start = datetime.combine(day_key, datetime.min.time(), tzinfo=UTC)
            bars_by_symbol[symbol].append(
                {
                    "t": day_start,
                    "o": open_price,
                    "h": max(high_values),
                    "l": min(low_values),
                    "c": close_price,
                    "v": sum(volume_values) if volume_values else None,
                    "n": sum(trade_count_values) if trade_count_values else None,
                    "source_timeframe": source_timeframe,
                    "source_bar_count": count,
                    "completeness_ratio": round(completeness_ratio, 4),
                    "provenance": f"resampled_from_{source_timeframe}",
                    "start_at": day_start,
                    "end_at": day_start + timedelta(days=1),
                }
            )
        return self._candidate_summary(
            source_used=source_timeframe,
            source_timeframe=source_timeframe,
            bars_by_symbol={key: value for key, value in bars_by_symbol.items()},
            requested_symbols=symbols,
            skipped_incomplete_days=skipped_incomplete_days,
            provider_error="",
        )

    def _candidate_summary(
        self,
        *,
        source_used: str,
        source_timeframe: str,
        bars_by_symbol: dict[str, list[dict[str, Any]]],
        requested_symbols: list[str],
        skipped_incomplete_days: int,
        provider_error: str,
    ) -> dict[str, Any]:
        symbols_with_generated_bars = sorted(
            symbol for symbol, bars in bars_by_symbol.items() if list(bars or [])
        )
        bars_generated = sum(len(list(bars or [])) for bars in bars_by_symbol.values())
        missing = sorted(
            str(symbol).upper()
            for symbol in requested_symbols
            if str(symbol).upper() not in set(symbols_with_generated_bars)
        )
        return {
            "source_used": source_used,
            "source_timeframe": source_timeframe,
            "bars_by_symbol": bars_by_symbol,
            "symbols_covered": len(symbols_with_generated_bars),
            "symbols_with_generated_bars": symbols_with_generated_bars,
            "symbols_missing_after_run": missing,
            "bars_generated": bars_generated,
            "days_covered": bars_generated,
            "days_processed": bars_generated + int(skipped_incomplete_days),
            "skipped_incomplete_days": skipped_incomplete_days,
            "provider_error": provider_error,
        }

    def _candidate_sort_key(self, candidate: dict[str, Any]) -> tuple[int, int, int, int]:
        priority = {"native_1Day": 3, "1Hour": 2, "15Min": 1}.get(
            str(candidate.get("source_used", "") or ""),
            0,
        )
        if int(candidate.get("bars_generated", 0) or 0) <= 0:
            priority = 0
        return (
            int(candidate.get("symbols_covered", 0) or 0),
            int(candidate.get("days_processed", 0) or 0),
            int(candidate.get("days_covered", 0) or 0),
            int(candidate.get("bars_generated", 0) or 0),
            priority,
        )

    def _record_crypto_1day_readiness(
        self,
        *,
        context: TickContext,
        result: dict[str, Any],
    ) -> None:
        self.usage_ledger.record_strategy_variant_evaluation(
            evaluation_id=f"{CRYPTO_1DAY_REPORT_TYPE}:{context.tick_id}",
            variant_id="historical-data-readiness",
            base_strategy_id="crypto_pullback",
            profile_id="downside_reversal_watch",
            timeframe="1Day",
            replay_id=context.tick_id,
            dataset_id=CRYPTO_1DAY_DATASET_ID,
            asset_class="crypto",
            symbols_tested=list(result.get("symbols_with_generated_bars", []) or []),
            sample_size=int(result.get("bars_generated", 0) or 0),
            gross_return=0.0,
            net_return_after_costs=0.0,
            fees_cost=0.0,
            spread_cost=0.0,
            slippage_cost=0.0,
            win_rate=0.0,
            drawdown=None,
            baseline_variant_id="",
            baseline_strategy_key="crypto_pullback/downside_reversal_watch/1Day",
            baseline_net_return_after_costs=0.0,
            baseline_win_rate=0.0,
            beats_baseline=False,
            beats_thresholds=False,
            recommended_status="evaluated",
            evaluated_at=context.started_at,
            notes="Research-only crypto 1Day historical data preparation. No paper/live state changed.",
            raw={
                "report_type": CRYPTO_1DAY_REPORT_TYPE,
                "dataset_id": CRYPTO_1DAY_DATASET_ID,
                "symbols_covered": int(result.get("symbols_covered", 0) or 0),
                "days_covered": int(result.get("days_covered", 0) or 0),
                "bars_generated": int(result.get("bars_generated", 0) or 0),
                "source_timeframe": str(result.get("source_timeframe", "") or ""),
                "readiness_status": str(result.get("readiness_status", "") or ""),
                "data_gap_resolved": str(result.get("data_gap_resolved", "no") or "no"),
                "skipped_incomplete_days": int(result.get("skipped_incomplete_days", 0) or 0),
                "symbols_missing_after_run": list(result.get("symbols_missing_after_run", []) or []),
            },
        )

    def _run_crypto_15min_backfill_or_resample(
        self,
        *,
        context: TickContext,
        request: Crypto15MinBackfillRequest,
        fx_reference: dict[str, Any],
    ) -> dict[str, Any]:
        provider_symbols = [
            str(symbol).strip()
            for symbol in request.crypto_symbols
            if str(symbol).strip()
        ]
        symbols = [self._normalize_symbol(symbol) for symbol in provider_symbols]
        symbol_map = {
            self._normalize_symbol(symbol): str(symbol).strip()
            for symbol in provider_symbols
            if str(symbol).strip()
        }
        if not provider_symbols:
            result = {
                "report_type": CRYPTO_15MIN_REPORT_TYPE,
                "dataset_id": CRYPTO_15MIN_DATASET_ID,
                "timeframe": "15Min",
                "symbols_covered": 0,
                "symbols_covered_list": [],
                "days_covered": 0.0,
                "bars_available": 0,
                "minimum_days_required": request.minimum_days_required,
                "preferred_days": request.preferred_days,
                "readiness_status": "no_symbols_configured",
                "data_gap_resolved": "no",
                "symbol_results": [],
                "paper_trades_created": "no",
                "live_changed": "no",
                "thresholds_changed": "no",
                "promotion_policy_changed": "no",
                "backfill_source": "none",
            }
            self._record_crypto_15min_readiness(context=context, result=result)
            return result

        before_coverage = self._historical_coverage_index(
            asset_class="crypto",
            symbols=symbols,
            timeframe="15Min",
        )
        symbols_needing_backfill: list[str] = []
        for symbol in symbols:
            before = before_coverage.get(symbol, {})
            if float(before.get("days_before", 0.0) or 0.0) < request.preferred_days:
                symbols_needing_backfill.append(symbol)

        bars_saved = 0
        bars_added = 0
        source_used = "existing_15Min_history"
        provider_error = ""
        if symbols_needing_backfill:
            source_used = "native_15Min_backfill"
            market_data = get_market_data_adapter(context, "alpaca")
            try:
                fetched = market_data.get_historical_crypto_bars(
                    context,
                    location=context.config.alpaca_crypto_location,
                    symbols=[
                        symbol_map.get(symbol, symbol)
                        for symbol in symbols_needing_backfill
                    ],
                    timeframe=request.source_timeframe,
                    start=context.started_at - timedelta(days=max(1, request.preferred_days)),
                    end=context.started_at,
                )
            except Exception as exc:
                fetched = {}
                provider_error = f"{type(exc).__name__}: {exc}"
            normalized = {
                self._normalize_symbol(symbol): list(bars or [])
                for symbol, bars in (fetched or {}).items()
                if list(bars or [])
            }
            if not normalized and not provider_error and request.resample_from_timeframe:
                normalized, resampled_added = self._resample_crypto_intraday_candidate(
                    context=context,
                    symbols=symbols_needing_backfill,
                    target_timeframe="15Min",
                    source_timeframe=request.resample_from_timeframe,
                )
                if normalized:
                    source_used = f"resampled_from_{request.resample_from_timeframe}"
                    bars_added = resampled_added
            else:
                bars_added = sum(len(list(bars or [])) for bars in normalized.values())
            if normalized:
                bars_saved = self.usage_ledger.record_historical_bars(
                    batch_id=context.tick_id,
                    captured_at=context.started_at,
                    source="alpaca_crypto_data",
                    asset_class="crypto",
                    timeframe="15Min",
                    bars_by_symbol=normalized,
                    quote_currency="USD",
                    usd_to_gbp=float(fx_reference["usd_to_gbp"]),
                )

        after_coverage = self._historical_coverage_index(
            asset_class="crypto",
            symbols=symbols,
            timeframe="15Min",
        )
        symbol_results = []
        ready_symbols: list[str] = []
        total_bars_after = 0
        max_days_after = 0.0
        data_gap_resolved = "yes"
        for symbol in symbols:
            before = before_coverage.get(symbol, self._empty_coverage_row(symbol=symbol, timeframe="15Min"))
            after = after_coverage.get(symbol, before)
            bars_before = int(before.get("bars_before", 0) or 0)
            bars_after = int(after.get("bars_after", 0) or 0)
            days_before = float(before.get("days_before", 0.0) or 0.0)
            days_after = float(after.get("days_after", 0.0) or 0.0)
            if days_after >= request.minimum_days_required:
                coverage_status = "ready"
                ready_symbols.append(symbol)
            elif bars_after > bars_before:
                coverage_status = "partial_gap_remaining"
            else:
                coverage_status = "insufficient_history"
            resolved = "yes" if days_after >= request.minimum_days_required else "no"
            if resolved != "yes":
                data_gap_resolved = "no"
            symbol_results.append(
                {
                    "symbol": symbol,
                    "timeframe": "15Min",
                    "bars_before": bars_before,
                    "bars_after": bars_after,
                    "days_before": round(days_before, 4),
                    "days_after": round(days_after, 4),
                    "backfill_source": source_used,
                    "bars_added": max(0, bars_after - bars_before),
                    "coverage_status": coverage_status,
                    "data_gap_resolved": resolved,
                }
            )
            total_bars_after += bars_after
            max_days_after = max(max_days_after, days_after)

        readiness_status = "ready" if data_gap_resolved == "yes" and ready_symbols else "remaining_data_gap"
        result = {
            "report_type": CRYPTO_15MIN_REPORT_TYPE,
            "dataset_id": CRYPTO_15MIN_DATASET_ID,
            "timeframe": "15Min",
            "backfill_source": source_used,
            "provider_error": provider_error,
            "symbols_requested": symbols,
            "symbols_covered": len(ready_symbols),
            "symbols_covered_list": ready_symbols,
            "days_covered": round(max_days_after, 4),
            "bars_available": total_bars_after,
            "minimum_days_required": request.minimum_days_required,
            "preferred_days": request.preferred_days,
            "readiness_status": readiness_status,
            "data_gap_resolved": data_gap_resolved,
            "bars_saved": int(bars_saved),
            "bars_added": int(sum(item["bars_added"] for item in symbol_results)),
            "symbol_results": symbol_results,
            "paper_trades_created": "no",
            "live_changed": "no",
            "thresholds_changed": "no",
            "promotion_policy_changed": "no",
        }
        self._record_crypto_15min_readiness(context=context, result=result)
        return result

    def _record_crypto_15min_readiness(
        self,
        *,
        context: TickContext,
        result: dict[str, Any],
    ) -> None:
        self.usage_ledger.record_strategy_variant_evaluation(
            evaluation_id=f"{CRYPTO_15MIN_REPORT_TYPE}:{context.tick_id}",
            variant_id="historical-data-readiness",
            base_strategy_id="crypto_research.liquidation_wick_reclaim",
            profile_id="liquidation_wick_reclaim_confirmed",
            timeframe="15Min",
            replay_id=context.tick_id,
            dataset_id=CRYPTO_15MIN_DATASET_ID,
            asset_class="crypto",
            symbols_tested=list(result.get("symbols_covered_list", []) or []),
            sample_size=int(result.get("bars_available", 0) or 0),
            gross_return=0.0,
            net_return_after_costs=0.0,
            fees_cost=0.0,
            spread_cost=0.0,
            slippage_cost=0.0,
            win_rate=0.0,
            drawdown=None,
            baseline_variant_id="",
            baseline_strategy_key="crypto_research.liquidation_wick_reclaim/liquidation_wick_reclaim_confirmed/15Min",
            baseline_net_return_after_costs=0.0,
            baseline_win_rate=0.0,
            beats_baseline=False,
            beats_thresholds=False,
            recommended_status="evaluated",
            evaluated_at=context.started_at,
            notes="Research-only crypto 15Min historical data preparation. No paper/live state changed.",
            raw={
                "report_type": CRYPTO_15MIN_REPORT_TYPE,
                "dataset_id": CRYPTO_15MIN_DATASET_ID,
                "symbols_covered": int(result.get("symbols_covered", 0) or 0),
                "symbols_covered_list": list(result.get("symbols_covered_list", []) or []),
                "days_covered": float(result.get("days_covered", 0.0) or 0.0),
                "bars_available": int(result.get("bars_available", 0) or 0),
                "minimum_days_required": int(result.get("minimum_days_required", 0) or 0),
                "preferred_days": int(result.get("preferred_days", 0) or 0),
                "readiness_status": str(result.get("readiness_status", "") or ""),
                "data_gap_resolved": str(result.get("data_gap_resolved", "no") or "no"),
                "backfill_source": str(result.get("backfill_source", "") or ""),
                "bars_added": int(result.get("bars_added", 0) or 0),
                "symbol_results": list(result.get("symbol_results", []) or []),
            },
        )

    def _run_crypto_15min_bulk_import(
        self,
        *,
        context: TickContext,
        request: Crypto15MinImportRequest,
        fx_reference: dict[str, Any],
    ) -> dict[str, Any]:
        configured_symbols = [self._normalize_symbol(item) for item in request.crypto_symbols if self._normalize_symbol(item)]
        if not configured_symbols:
            result = {
                "report_type": CRYPTO_15MIN_IMPORT_REPORT_TYPE,
                "dataset_id": CRYPTO_15MIN_DATASET_ID,
                "timeframe": request.timeframe,
                "readiness_status": "no_symbols_configured",
                "data_gap_resolved": "no",
                "path": request.path,
                "formats_supported": ["csv", "parquet"],
                "source_files": [],
                "symbols_requested": [],
                "symbols_imported": [],
                "symbols_covered": 0,
                "symbols_covered_list": [],
                "days_covered": 0.0,
                "bars_available": 0,
                "rows_inserted": 0,
                "rows_updated": 0,
                "rows_skipped": 0,
                "bars_saved": 0,
                "symbol_results": [],
                "paper_trades_created": "no",
                "live_changed": "no",
                "thresholds_changed": "no",
                "promotion_policy_changed": "no",
                "backfill_source": "bulk_file_import",
            }
            self._record_crypto_15min_readiness(context=context, result=result)
            return result

        import_path = Path(request.path).expanduser()
        source_files = self._resolve_bulk_import_files(import_path)
        before_coverage = self._historical_coverage_index(
            asset_class="crypto",
            symbols=configured_symbols,
            timeframe=request.timeframe,
        )
        bars_by_symbol, ingest_counts = self._load_crypto_15min_bulk_bars(
            files=source_files,
            configured_symbols=configured_symbols,
            timeframe=request.timeframe,
            as_of=context.started_at,
        )
        write_plan = _plan_historical_bar_write(
            context=context,
            source=request.source,
            asset_class="crypto",
            timeframe=request.timeframe,
            bars_by_symbol=bars_by_symbol,
        )
        bars_saved = 0
        if bars_by_symbol:
            bars_saved = context.usage_ledger.record_historical_bars(
                batch_id=context.tick_id,
                captured_at=context.started_at,
                source=request.source,
                asset_class="crypto",
                timeframe=request.timeframe,
                bars_by_symbol=bars_by_symbol,
                quote_currency="USD",
                usd_to_gbp=float(fx_reference.get("usd_to_gbp", 1.0) or 1.0),
            )
        after_coverage = self._historical_coverage_index(
            asset_class="crypto",
            symbols=configured_symbols,
            timeframe=request.timeframe,
        )

        symbol_results: list[dict[str, Any]] = []
        ready_symbols: list[str] = []
        imported_symbols: list[str] = []
        total_bars_after = 0
        max_days_after = 0.0
        data_gap_resolved = "yes"
        per_symbol_counts = ingest_counts["per_symbol"]
        for symbol in configured_symbols:
            before = before_coverage.get(symbol, self._empty_coverage_row(symbol=symbol, timeframe=request.timeframe))
            after = after_coverage.get(symbol, before)
            symbol_input = dict(per_symbol_counts.get(symbol, {}) or {})
            inserted = int(symbol_input.get("inserted", 0) or 0)
            updated = int(symbol_input.get("updated", 0) or 0)
            skipped = int(symbol_input.get("skipped", 0) or 0)
            bars_after = int(after.get("bars_after", 0) or 0)
            days_after = float(after.get("days_after", 0.0) or 0.0)
            earliest = after.get("earliest_bar_timestamp")
            latest = after.get("latest_bar_timestamp")
            if bars_after > 0:
                imported_symbols.append(symbol)
            if days_after >= request.minimum_days_required:
                coverage_status = "ready"
                ready_symbols.append(symbol)
            elif inserted > 0 or updated > 0:
                coverage_status = "partial_gap_remaining"
            else:
                coverage_status = "insufficient_history"
            if coverage_status != "ready":
                data_gap_resolved = "no"
            symbol_results.append(
                {
                    "symbol": symbol,
                    "timeframe": request.timeframe,
                    "rows_inserted": inserted,
                    "rows_updated": updated,
                    "rows_skipped": skipped,
                    "bars_before": int(before.get("bars_before", 0) or 0),
                    "bars_after": bars_after,
                    "days_before": round(float(before.get("days_before", 0.0) or 0.0), 4),
                    "days_after": round(days_after, 4),
                    "earliest_bar_timestamp": earliest.isoformat() if isinstance(earliest, datetime) else "",
                    "latest_bar_timestamp": latest.isoformat() if isinstance(latest, datetime) else "",
                    "coverage_status": coverage_status,
                    "data_gap_resolved": "yes" if coverage_status == "ready" else "no",
                }
            )
            total_bars_after += bars_after
            max_days_after = max(max_days_after, days_after)

        result = {
            "report_type": CRYPTO_15MIN_IMPORT_REPORT_TYPE,
            "dataset_id": CRYPTO_15MIN_DATASET_ID,
            "timeframe": request.timeframe,
            "path": str(import_path),
            "formats_supported": ["csv", "parquet"],
            "source_files": [str(item) for item in source_files],
            "symbols_requested": configured_symbols,
            "symbols_imported": imported_symbols,
            "symbols_covered": len(ready_symbols),
            "symbols_covered_list": ready_symbols,
            "days_covered": round(max_days_after, 4),
            "bars_available": total_bars_after,
            "readiness_status": "ready" if data_gap_resolved == "yes" and ready_symbols else "remaining_data_gap",
            "data_gap_resolved": data_gap_resolved,
            "rows_inserted": int(write_plan.get("bars_inserted", 0) or 0),
            "rows_updated": int(write_plan.get("bars_updated", 0) or 0),
            "rows_skipped": int(ingest_counts.get("rows_skipped", 0) or 0),
            "rows_seen": int(ingest_counts.get("rows_seen", 0) or 0),
            "bars_saved": int(bars_saved or 0),
            "backfill_source": "bulk_file_import",
            "paper_trades_created": "no",
            "live_changed": "no",
            "thresholds_changed": "no",
            "promotion_policy_changed": "no",
            "symbol_results": symbol_results,
        }
        self._record_crypto_15min_readiness(context=context, result=result)
        return result

    def _resolve_bulk_import_files(self, path: Path) -> list[Path]:
        root = PROJECT_ROOT.resolve()
        candidate = (path if path.is_absolute() else (root / path)).resolve()
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError(
                "Bulk import path must be inside the current project workspace. "
                "Stage the data under this repo first, for example "
                "`data/crypto_15min_2025_2026`."
            ) from exc
        if not candidate.exists():
            raise FileNotFoundError(
                f"Bulk import path does not exist inside project workspace: {candidate}"
            )
        if candidate.is_file():
            if candidate.suffix.lower() not in {".csv", ".parquet"}:
                raise ValueError(f"Unsupported bulk import file type: {candidate.suffix}")
            return [candidate]
        files = sorted(
            item
            for item in candidate.iterdir()
            if item.is_file() and item.suffix.lower() in {".csv", ".parquet"}
        )
        if not files:
            raise ValueError(f"No CSV or parquet files found at: {candidate}")
        return files

    def _load_crypto_15min_bulk_bars(
        self,
        *,
        files: list[Path],
        configured_symbols: list[str],
        timeframe: str,
        as_of: datetime,
    ) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
        configured = set(configured_symbols)
        deduped: dict[tuple[str, datetime], dict[str, Any]] = {}
        stats: dict[str, Any] = {
            "rows_seen": 0,
            "rows_skipped": 0,
            "per_symbol": defaultdict(lambda: {"seen": 0, "skipped": 0}),
        }
        for file_path in files:
            if file_path.suffix.lower() == ".csv":
                rows = self._iter_csv_rows(file_path)
            else:
                rows = self._iter_parquet_rows(file_path)
            for row in rows:
                stats["rows_seen"] += 1
                parsed = self._parse_crypto_15min_import_row(
                    row=row,
                    fallback_symbol=file_path.stem,
                    configured_symbols=configured,
                    timeframe=timeframe,
                    as_of=as_of,
                )
                symbol = parsed.get("symbol", "")
                if symbol:
                    stats["per_symbol"][symbol]["seen"] += 1
                if parsed.get("skip_reason"):
                    stats["rows_skipped"] += 1
                    if symbol:
                        stats["per_symbol"][symbol]["skipped"] += 1
                    continue
                key = (str(parsed["symbol"]), parsed["t"])
                if key in deduped:
                    stats["rows_skipped"] += 1
                    stats["per_symbol"][parsed["symbol"]]["skipped"] += 1
                deduped[key] = parsed
        existing_rows: dict[tuple[str, datetime], bool] = {}
        if deduped:
            existing = self.usage_ledger.list_historical_bars(
                timeframe=timeframe,
                sources=["alpaca_crypto_data"],
                symbols=sorted({symbol for symbol, _ in deduped.keys()}),
            )
            for row in existing:
                timestamp = self._to_datetime(row.get("bar_timestamp"))
                if timestamp is None:
                    continue
                existing_rows[(self._normalize_symbol(row.get("symbol", "")), timestamp)] = True
        bars_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (symbol, _timestamp), bar in sorted(deduped.items(), key=lambda item: (item[0][0], item[0][1])):
            bars_by_symbol[symbol].append(bar)
            if existing_rows.get((symbol, bar["t"])):
                stats["per_symbol"][symbol]["updated"] = int(stats["per_symbol"][symbol].get("updated", 0) or 0) + 1
            else:
                stats["per_symbol"][symbol]["inserted"] = int(stats["per_symbol"][symbol].get("inserted", 0) or 0) + 1
        return dict(bars_by_symbol), stats

    def _iter_csv_rows(self, path: Path) -> list[dict[str, Any]]:
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            return [dict(row) for row in reader]

    def _iter_parquet_rows(self, path: Path) -> list[dict[str, Any]]:
        try:
            import pyarrow.parquet as pq  # type: ignore

            table = pq.read_table(path)
            return [dict(row) for row in table.to_pylist()]
        except ImportError:
            raise RuntimeError(
                "Parquet import requires pyarrow in the active runtime; CSV import is available without extra dependencies."
            ) from None

    def _parse_crypto_15min_import_row(
        self,
        *,
        row: dict[str, Any],
        fallback_symbol: str,
        configured_symbols: set[str],
        timeframe: str,
        as_of: datetime,
    ) -> dict[str, Any]:
        normalized = {
            str(key or "").strip().lower(): value
            for key, value in dict(row or {}).items()
        }
        symbol = self._normalize_symbol(
            normalized.get("symbol")
            or normalized.get("pair")
            or normalized.get("ticker")
            or normalized.get("instrument")
            or fallback_symbol
        )
        if symbol not in configured_symbols:
            return {"symbol": symbol, "skip_reason": "symbol_not_configured"}
        row_timeframe = str(
            normalized.get("timeframe")
            or normalized.get("interval")
            or normalized.get("granularity")
            or timeframe
        ).strip()
        if row_timeframe and row_timeframe not in {timeframe, "15m", "15min", "15minute", "15minutes"}:
            return {"symbol": symbol, "skip_reason": "timeframe_mismatch"}
        timestamp = self._parse_import_timestamp(
            normalized.get("timestamp")
            or normalized.get("bar_timestamp")
            or normalized.get("time")
            or normalized.get("datetime")
            or normalized.get("date")
            or normalized.get("t")
        )
        open_price = self._to_float(normalized.get("open") or normalized.get("o"))
        high_price = self._to_float(normalized.get("high") or normalized.get("h"))
        low_price = self._to_float(normalized.get("low") or normalized.get("l"))
        close_price = self._to_float(normalized.get("close") or normalized.get("c"))
        if timestamp is None or open_price is None or high_price is None or low_price is None or close_price is None:
            return {"symbol": symbol, "skip_reason": "missing_required_fields"}
        if timestamp > as_of:
            return {"symbol": symbol, "skip_reason": "future_timestamp"}
        return {
            "symbol": symbol,
            "t": timestamp,
            "o": open_price,
            "h": high_price,
            "l": low_price,
            "c": close_price,
            "v": self._to_float(normalized.get("volume") or normalized.get("v")) or 0.0,
            "n": int(float(normalized.get("trade_count") or normalized.get("n") or 0) or 0),
            "vw": self._to_float(normalized.get("vwap") or normalized.get("vw")),
            "import_source": "bulk_file_import",
        }

    def _parse_import_timestamp(self, value: Any) -> datetime | None:
        if isinstance(value, (int, float)) and value > 0:
            number = float(value)
            if number > 10_000_000_000:
                number /= 1000.0
            return datetime.fromtimestamp(number, tz=UTC)
        if isinstance(value, str):
            stripped = value.strip()
            if not stripped:
                return None
            if stripped.isdigit():
                return self._parse_import_timestamp(int(stripped))
            cleaned = stripped.replace("Z", "+00:00")
            for candidate in (cleaned, cleaned.replace(" ", "T")):
                try:
                    parsed = datetime.fromisoformat(candidate)
                    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
                except ValueError:
                    continue
        return self._to_datetime(value)

    def _historical_coverage_index(
        self,
        *,
        asset_class: str,
        symbols: list[str],
        timeframe: str,
    ) -> dict[str, dict[str, Any]]:
        rows = self.usage_ledger.summarize_historical_bar_coverage(
            asset_class=asset_class,
            symbols=symbols,
            timeframes=[timeframe],
        )
        coverage: dict[str, dict[str, Any]] = {}
        for row in rows:
            symbol = self._normalize_symbol(row.get("symbol", ""))
            coverage[symbol] = {
                "symbol": symbol,
                "timeframe": timeframe,
                "bars_before": int(row.get("row_count", 0) or 0),
                "bars_after": int(row.get("row_count", 0) or 0),
                "days_before": float(row.get("distinct_bar_days", 0) or 0),
                "days_after": float(row.get("distinct_bar_days", 0) or 0),
            }
        for symbol in symbols:
            coverage.setdefault(symbol, self._empty_coverage_row(symbol=symbol, timeframe=timeframe))
        return coverage

    def _empty_coverage_row(self, *, symbol: str, timeframe: str) -> dict[str, Any]:
        return {
            "symbol": symbol,
            "timeframe": timeframe,
            "bars_before": 0,
            "bars_after": 0,
            "days_before": 0.0,
            "days_after": 0.0,
        }

    def _resample_crypto_intraday_candidate(
        self,
        *,
        context: TickContext,
        symbols: list[str],
        target_timeframe: str,
        source_timeframe: str,
    ) -> tuple[dict[str, list[dict[str, Any]]], int]:
        rows = self.usage_ledger.list_historical_bars(
            timeframe=source_timeframe,
            sources=["alpaca_crypto_data"],
            symbols=symbols,
            start_at=context.started_at - timedelta(days=90),
            end_at=context.started_at,
        )
        if target_timeframe != "15Min" or source_timeframe != "1Min":
            return {}, 0
        grouped: dict[tuple[str, datetime], list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            bar_dt = self._to_datetime(row.get("bar_timestamp"))
            if bar_dt is None:
                continue
            start_bucket = bar_dt.replace(minute=(bar_dt.minute // 15) * 15, second=0, microsecond=0)
            grouped[(self._normalize_symbol(row.get("symbol", "")), start_bucket)].append(row)
        bars_by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for (symbol, bucket_start), items in grouped.items():
            ordered = sorted(items, key=lambda item: self._to_datetime(item.get("bar_timestamp")) or bucket_start)
            if len(ordered) < 15:
                continue
            open_price = self._to_float(ordered[0].get("open_price"))
            close_price = self._to_float(ordered[-1].get("close_price"))
            highs = [self._to_float(item.get("high_price")) for item in ordered if self._to_float(item.get("high_price")) is not None]
            lows = [self._to_float(item.get("low_price")) for item in ordered if self._to_float(item.get("low_price")) is not None]
            if open_price is None or close_price is None or not highs or not lows:
                continue
            bars_by_symbol[symbol].append(
                {
                    "t": bucket_start,
                    "o": open_price,
                    "h": max(highs),
                    "l": min(lows),
                    "c": close_price,
                    "v": sum(self._to_float(item.get("volume")) or 0.0 for item in ordered),
                    "n": sum(int(item.get("trade_count") or 0) for item in ordered),
                    "source_timeframe": source_timeframe,
                    "source_bar_count": len(ordered),
                    "provenance": f"resampled_from_{source_timeframe}",
                    "start_at": bucket_start,
                    "end_at": bucket_start + timedelta(minutes=15),
                }
            )
        count = sum(len(list(bars or [])) for bars in bars_by_symbol.values())
        return dict(bars_by_symbol), count

    def _normalize_symbol(self, value: Any) -> str:
        return str(value or "").replace("/", "").upper().strip()

    def _to_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if isinstance(value, str) and value:
            try:
                parsed = datetime.fromisoformat(value)
            except ValueError:
                return None
            return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
        return None

    def _to_float(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _resolve_equity_symbols(self, *, symbols_from_strategies: bool) -> tuple[str, ...]:
        configured = tuple(
            str(symbol).strip()
            for symbol in getattr(self.config, "discovery_equity_symbols", tuple()) or tuple()
            if str(symbol).strip()
        )
        if not symbols_from_strategies:
            return configured
        strategy_profiles = []
        for strategy in build_strategy_registry():
            for profile in strategy.build_profiles(self.config):
                if "equity" in tuple(str(item) for item in profile.asset_classes):
                    strategy_profiles.append(profile)
        if not strategy_profiles:
            return configured
        return tuple(sorted(dict.fromkeys(configured)))

    def _normalize_timeframes(self, timeframes: tuple[str, ...]) -> tuple[str, ...]:
        normalized: list[str] = []
        for raw in timeframes:
            value = str(raw or "").strip()
            if not value:
                continue
            if value not in {"1Min", "15Min", "1Hour", "1Day"}:
                raise ValueError(f"Unsupported timeframe for Alpaca equity backfill: {value}")
            normalized.append(value)
        if not normalized:
            raise ValueError("At least one timeframe is required for Alpaca equity backfill.")
        return tuple(dict.fromkeys(normalized))

    def _timeframe_delta(self, timeframe: str) -> timedelta:
        normalized = str(timeframe or "").strip().lower()
        if normalized.endswith("min"):
            return timedelta(minutes=max(1, int(normalized[:-3] or "1")))
        if normalized.endswith("hour"):
            return timedelta(hours=max(1, int(normalized[:-4] or "1")))
        if normalized.endswith("day"):
            return timedelta(days=max(1, int(normalized[:-3] or "1")))
        return timedelta(minutes=15)

    def _run_equity_backfill_batches(
        self,
        *,
        context: TickContext,
        request: MultiTimeframeEquityBackfillRequest,
        fx_reference: dict[str, object],
    ) -> dict[str, object]:
        end_at = context.started_at
        global_start = end_at - timedelta(days=365 * request.years)
        coverage = self.usage_ledger.summarize_historical_bar_coverage(
            asset_class="equity",
            symbols=list(request.equity_symbols),
            timeframes=list(request.timeframes),
        )
        latest_by_symbol_timeframe = {
            (str(row.get("symbol", "")), str(row.get("timeframe", ""))): row.get("latest_bar_timestamp")
            for row in coverage
        }
        market_data = get_market_data_adapter(context, "alpaca")
        summary: dict[str, object] = {
            "mode": "historical_bars_dry_run" if request.dry_run else "historical_bars",
            "years": request.years,
            "timeframes": list(request.timeframes),
            "equity_symbols": list(request.equity_symbols),
            "symbols_from_strategies": bool(
                (context.state.get("run", {}) or {}).get("symbols_from_strategies")
            ),
            "backfill_from_start": bool(request.backfill_from_start),
            "safety_guard": "historical_backfill_only_no_orders_no_auto_approvals",
            "promotion_mutation_count": 0,
            "live_execution_touched": False,
            "timeframe_results": [],
        }
        for timeframe in request.timeframes:
            timeframe_delta = self._timeframe_delta(timeframe)
            resume_groups: dict[str, list[str]] = {}
            skipped_up_to_date: list[str] = []
            for symbol in request.equity_symbols:
                if request.backfill_from_start:
                    resume_start = global_start
                else:
                    latest = latest_by_symbol_timeframe.get((symbol, timeframe))
                    if isinstance(latest, datetime):
                        resume_start = max(global_start, latest + timeframe_delta)
                    else:
                        resume_start = global_start
                if resume_start >= end_at:
                    skipped_up_to_date.append(symbol)
                    continue
                resume_groups.setdefault(resume_start.isoformat(), []).append(symbol)
            timeframe_result = {
                "timeframe": timeframe,
                "requested_start_at": global_start.isoformat(),
                "requested_end_at": end_at.isoformat(),
                "batches_total": 0,
                "batches_completed": 0,
                "symbols_skipped_up_to_date": skipped_up_to_date,
                "bars_fetched": 0,
                "bars_saved": 0,
                "bars_inserted": 0,
                "bars_updated": 0,
                "latest_timestamp_stored": "",
                "batch_progress": [],
            }
            batched_groups: list[tuple[datetime, list[str]]] = []
            for resume_start_text, symbols in sorted(resume_groups.items()):
                resume_start_dt = datetime.fromisoformat(resume_start_text)
                ordered = sorted(symbols)
                for index in range(0, len(ordered), request.batch_size):
                    batched_groups.append(
                        (resume_start_dt, ordered[index : index + request.batch_size])
                    )
            timeframe_result["batches_total"] = len(batched_groups)
            for batch_number, (resume_start_dt, symbols) in enumerate(batched_groups, start=1):
                bars_by_symbol = self._fetch_equity_batch_with_retry(
                    context=context,
                    market_data=market_data,
                    symbols=symbols,
                    timeframe=timeframe,
                    start_at=resume_start_dt,
                    end_at=end_at,
                    retry_limit=request.retry_limit,
                    base_backoff_seconds=request.base_backoff_seconds,
                )
                fetched = sum(len(list(bars or [])) for bars in bars_by_symbol.values())
                bars_inserted = fetched
                bars_updated = 0
                bars_saved = 0
                if not request.dry_run and bars_by_symbol:
                    bars_saved = context.usage_ledger.record_historical_bars(
                        batch_id=context.tick_id,
                        captured_at=context.started_at,
                        source="alpaca_market_data",
                        asset_class="equity",
                        timeframe=timeframe,
                        bars_by_symbol=bars_by_symbol,
                        quote_currency="USD",
                        usd_to_gbp=float(fx_reference["usd_to_gbp"]),
                    )
                latest_timestamp_stored = self._latest_timestamp_stored_for_batch(
                    latest_by_symbol_timeframe=latest_by_symbol_timeframe,
                    symbols=symbols,
                    timeframe=timeframe,
                    bars_by_symbol=bars_by_symbol,
                    wrote_bars=not request.dry_run,
                )
                timeframe_result["batches_completed"] = batch_number
                timeframe_result["bars_fetched"] += fetched
                timeframe_result["bars_saved"] += int(bars_saved or 0)
                timeframe_result["bars_inserted"] += int(bars_inserted)
                timeframe_result["bars_updated"] += int(bars_updated)
                timeframe_result["latest_timestamp_stored"] = latest_timestamp_stored or str(
                    timeframe_result["latest_timestamp_stored"] or ""
                )
                batch_progress = {
                    "timeframe": timeframe,
                    "batch_number": batch_number,
                    "batch_total": len(batched_groups),
                    "symbols": list(symbols),
                    "requested_start_at": resume_start_dt.isoformat(),
                    "requested_end_at": end_at.isoformat(),
                    "bars_fetched": fetched,
                    "bars_saved": int(bars_saved or 0),
                    "latest_timestamp_stored": latest_timestamp_stored,
                }
                timeframe_result["batch_progress"].append(batch_progress)
                self.logger.line(
                    (
                        f"Equity backfill progress: timeframe={timeframe} "
                        f"| batch={batch_number}/{len(batched_groups)} "
                        f"| symbols={','.join(symbols)} "
                        f"| requested_start={resume_start_dt.isoformat()} "
                        f"| requested_end={end_at.isoformat()} "
                        f"| bars_fetched={fetched} "
                        f"| bars_saved={int(bars_saved or 0)} "
                        f"| latest_timestamp_stored={batch_progress['latest_timestamp_stored'] or '-'}"
                    ),
                    timestamp=datetime.now().astimezone(),
                )
            summary["timeframe_results"].append(timeframe_result)
        context.state["historical_equity_backfill_multi"] = summary
        return summary

    def _fetch_equity_batch_with_retry(
        self,
        *,
        context: TickContext,
        market_data,
        symbols: list[str],
        timeframe: str,
        start_at: datetime,
        end_at: datetime,
        retry_limit: int,
        base_backoff_seconds: float,
    ) -> dict[str, list[dict[str, object]]]:
        last_error: Exception | None = None
        for attempt in range(1, retry_limit + 1):
            try:
                return market_data.get_historical_equity_bars(
                    context,
                    symbols=list(symbols),
                    timeframe=timeframe,
                    start=start_at,
                    end=end_at,
                    feed=self.config.alpaca_stock_feed,
                )
            except Exception as exc:
                last_error = exc
                if attempt >= retry_limit:
                    raise
                delay = base_backoff_seconds * attempt
                self.logger.line(
                    (
                        f"Equity backfill retry: timeframe={timeframe} "
                        f"| attempt={attempt}/{retry_limit} "
                        f"| symbols={','.join(symbols)} "
                        f"| delay_seconds={delay:.1f} "
                        f"| error={type(exc).__name__}: {exc}"
                    ),
                    timestamp=datetime.now().astimezone(),
                )
                if delay > 0:
                    self.sleep_fn(delay)
        if last_error is not None:
            raise last_error
        return {}

    def _latest_timestamp_stored_for_batch(
        self,
        *,
        latest_by_symbol_timeframe: dict[tuple[str, str], object],
        symbols: list[str],
        timeframe: str,
        bars_by_symbol: dict[str, list[dict[str, object]]],
        wrote_bars: bool,
    ) -> str:
        latest_batch_timestamp: datetime | None = None
        for symbol in symbols:
            current_latest = latest_by_symbol_timeframe.get((symbol, timeframe))
            if isinstance(current_latest, datetime):
                candidate_latest = current_latest
            else:
                candidate_latest = None
            if wrote_bars:
                fetched_latest = max(
                    (
                        bar.get("t")
                        for bar in list(bars_by_symbol.get(symbol, []) or [])
                        if isinstance(bar.get("t"), datetime)
                    ),
                    default=None,
                )
                if isinstance(fetched_latest, datetime):
                    if candidate_latest is None or fetched_latest > candidate_latest:
                        candidate_latest = fetched_latest
                    latest_by_symbol_timeframe[(symbol, timeframe)] = fetched_latest
            if isinstance(candidate_latest, datetime) and (
                latest_batch_timestamp is None or candidate_latest > latest_batch_timestamp
            ):
                latest_batch_timestamp = candidate_latest
        if isinstance(latest_batch_timestamp, datetime):
            return latest_batch_timestamp.isoformat()
        return ""


def _get_request(context: TickContext) -> HistoricalBackfillRequest:
    request = context.metadata.get("historical_backfill_request")
    if not isinstance(request, HistoricalBackfillRequest):
        raise RuntimeError("Historical backfill request is not configured.")
    return request


def _plan_historical_bar_write(
    *,
    context: TickContext,
    source: str,
    asset_class: str,
    timeframe: str,
    bars_by_symbol: dict[str, list[dict[str, object]]],
) -> dict[str, object]:
    symbols = [str(symbol) for symbol in bars_by_symbol.keys() if str(symbol).strip()]
    existing_rows = context.usage_ledger.list_historical_bars(
        timeframe=timeframe,
        sources=[source],
        symbols=symbols,
    )
    existing_keys = {
        (
            str(row.get("source", "")),
            str(row.get("symbol", "")),
            str(row.get("timeframe", "")),
            row.get("bar_timestamp"),
        )
        for row in existing_rows
    }
    inserted = 0
    updated = 0
    latest_bar_timestamp = None
    for symbol, bars in bars_by_symbol.items():
        for bar in bars:
            timestamp = bar.get("t")
            key = (source, str(symbol), timeframe, timestamp)
            if key in existing_keys:
                updated += 1
            else:
                inserted += 1
            if latest_bar_timestamp is None or (
                timestamp is not None and timestamp > latest_bar_timestamp
            ):
                latest_bar_timestamp = timestamp
    return {
        "asset_class": asset_class,
        "bars_inserted": inserted,
        "bars_updated": updated,
        "latest_bar_timestamp": (
            latest_bar_timestamp.isoformat()
            if isinstance(latest_bar_timestamp, datetime)
            else ""
        ),
    }


def _infer_skip_reasons(
    *,
    attempted_symbols: list[str],
    success_symbols: list[str],
    bars_inserted: int,
    bars_updated: int,
    latest_bar_timestamp: str,
) -> list[str]:
    if not attempted_symbols:
        return ["symbol_universe_empty"]
    if success_symbols:
        if bars_inserted <= 0 and bars_updated > 0:
            return ["backfill_already_up_to_date"]
        if bars_inserted > 0 or bars_updated > 0 or str(latest_bar_timestamp).strip():
            return []
    return ["provider_returned_no_bars"]
