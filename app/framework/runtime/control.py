from __future__ import annotations

from datetime import datetime
from time import perf_counter, sleep

from app.framework.engine.pipelines import build_default_pipeline
from app.framework.reporting.console import ScreenLogger
from app.heartbeat.contracts import HeartbeatStepDefinition
from app.heartbeat.graph import run_heartbeat_cron_graph
from app.framework.storage.usage import UsageLedger

from .models import TickContext, TickReport
from .settings import RuntimeConfig, load_runtime_config


class ControlPipelineRunner:
    def __init__(
        self,
        *,
        steps: list[HeartbeatStepDefinition] | None = None,
        logger: ScreenLogger | None = None,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.steps = steps or build_default_pipeline()
        self.logger = logger or ScreenLogger()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def run_tick(self) -> TickReport:
        started_at = datetime.now().astimezone()
        started_perf = perf_counter()
        tick_id = started_at.strftime("%Y%m%d-%H%M%S")
        context = TickContext(
            tick_id=tick_id,
            started_at=started_at,
            config=self.config,
            usage_ledger=self.usage_ledger,
        )

        self.logger.tick_start(
            tick_id=tick_id,
            started_at=started_at,
            stage_count=len(self.steps),
        )
        self.logger.runtime_summary(config=self.config, started_at=started_at)

        graph_state = run_heartbeat_cron_graph(
            context,
            steps=self.steps,
            logger=self.logger,
        )
        step_profiles = graph_state.step_profiles
        status = "error" if graph_state.halted else "ok"

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

    def run_development_loop(
        self,
        *,
        interval_seconds: int = 60,
        max_ticks: int | None = None,
    ) -> None:
        tick_count = 0
        self.logger.line(
            f"Development loop enabled | interval={interval_seconds}s | production_recommendation=external_scheduler"
        )

        while max_ticks is None or tick_count < max_ticks:
            loop_started_perf = perf_counter()
            self.run_tick()
            tick_count += 1

            if max_ticks is not None and tick_count >= max_ticks:
                self.logger.line("Development loop complete.")
                return

            sleep_for = max(0.0, interval_seconds - (perf_counter() - loop_started_perf))
            self.logger.line(f"Sleeping {sleep_for:.2f}s before next local tick.")
            sleep(sleep_for)


def run_tick() -> TickReport:
    return ControlPipelineRunner().run_tick()
