from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from time import perf_counter

from app.adapters.market_data import get_market_data_adapter
from app.reporting.console import ScreenLogger
from app.runtime.models import StepProfile, TickContext, TickReport
from app.runtime.settings import RuntimeConfig, load_runtime_config
from app.storage.usage import UsageLedger

from .pipelines import StepDefinition, fx_gbp_reference


@dataclass(frozen=True, slots=True)
class HistoricalBackfillRequest:
    days: int
    timeframe: str
    equity_symbols: tuple[str, ...]
    crypto_symbols: tuple[str, ...]


def backfill_equities(context: TickContext) -> dict[str, object]:
    request = _get_request(context)
    if not request.equity_symbols:
        result = {
            "symbols_requested": 0,
            "symbols_with_data": 0,
            "bars_saved": 0,
            "mode": "disabled",
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
    result = {
        "symbols_requested": len(request.equity_symbols),
        "symbols_with_data": len(bars_by_symbol),
        "bars_saved": bars_saved,
        "timeframe": request.timeframe,
        "days": request.days,
        "mode": "historical_bars",
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
            "mode": "disabled",
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
    result = {
        "symbols_requested": len(request.crypto_symbols),
        "symbols_with_data": len(bars_by_symbol),
        "bars_saved": bars_saved,
        "timeframe": request.timeframe,
        "days": request.days,
        "mode": "historical_bars",
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
    ) -> None:
        self.config = config or load_runtime_config()
        self.steps = steps or build_historical_backfill_pipeline()
        self.logger = logger or ScreenLogger()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def run(
        self,
        *,
        days: int | None = None,
        timeframe: str | None = None,
        equity_symbols: tuple[str, ...] | None = None,
        crypto_symbols: tuple[str, ...] | None = None,
    ) -> TickReport:
        request = HistoricalBackfillRequest(
            days=max(1, days or self.config.historical_backfill_default_days),
            timeframe=(timeframe or self.config.historical_backfill_default_timeframe).strip()
            or self.config.historical_backfill_default_timeframe,
            equity_symbols=equity_symbols or self.config.discovery_equity_symbols,
            crypto_symbols=crypto_symbols or self.config.discovery_crypto_symbols,
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
                f"crypto={len(request.crypto_symbols)}"
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


def _get_request(context: TickContext) -> HistoricalBackfillRequest:
    request = context.metadata.get("historical_backfill_request")
    if not isinstance(request, HistoricalBackfillRequest):
        raise RuntimeError("Historical backfill request is not configured.")
    return request
