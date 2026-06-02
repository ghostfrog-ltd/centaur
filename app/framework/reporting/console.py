from __future__ import annotations

from datetime import datetime
from typing import Any

from app.framework.runtime.models import ApiUsageSummary, StepProfile, TickReport
from app.framework.runtime.settings import RuntimeConfig


class ScreenLogger:
    def line(self, message: str, *, timestamp: datetime | None = None) -> None:
        current_time = timestamp or datetime.now().astimezone()
        print(f"[{self._format_timestamp(current_time)}] {message}", flush=True)

    def tick_start(
        self,
        *,
        tick_id: str,
        started_at: datetime,
        stage_count: int,
        pipeline_name: str = "control",
    ) -> None:
        self.line(f"**** Start {self._format_elapsed_clock(0.0)} ****", timestamp=started_at)
        self.line(f"Tick ID: {tick_id}", timestamp=started_at)
        self.line(
            f"Pipeline: {pipeline_name} | stages={stage_count}",
            timestamp=started_at,
        )

    def runtime_summary(self, *, config: RuntimeConfig, started_at: datetime) -> None:
        if not config.gemini_analysis_enabled:
            gemini_state = "disabled"
        elif config.gemini_api_configured:
            gemini_state = "configured"
        else:
            gemini_state = "pending"
        self.line(
            (
                "Runtime: "
                f"env={config.env_name} | "
                f"backend_pref={config.operations_db_backend_preference} | "
                f"sqlite_dev_store={config.usage_ledger_db_path} | "
                f"profiling={'on' if config.control_enable_profiling else 'off'}"
            ),
            timestamp=started_at,
        )
        self.line(
            (
                "Providers: "
                f"gemini={gemini_state} | "
                f"alpaca={'configured' if config.alpaca_api_configured else 'pending'} | "
                f"ig={'configured' if config.ig_api_configured else 'pending'} | "
                f"postgres={'configured' if config.postgres_configured else 'pending'}"
            ),
            timestamp=started_at,
        )
        self.line(
            (
                "Budget: "
                f"daily_warning=${config.api_daily_cost_warning_usd:.2f} | "
                f"daily_limit=${config.api_daily_cost_limit_usd:.2f}"
            ),
            timestamp=started_at,
        )

    def step_start(
        self,
        *,
        step_name: str,
        index: int,
        total: int,
        started_at: datetime,
    ) -> None:
        self.line(f"[{index}/{total}] -> {step_name}", timestamp=started_at)

    def step_end(
        self,
        *,
        profile: StepProfile,
        index: int,
        total: int,
    ) -> None:
        details = self._format_details(profile.details)
        suffix = f" | {details}" if details else ""
        self.line(
            f"[{index}/{total}] <- {profile.name} | {profile.status.upper()} | {profile.duration_seconds:.3f}s{suffix}",
            timestamp=profile.ended_at,
        )

    def profiling_summary(self, report: TickReport) -> None:
        self.line("---- Profiling ----", timestamp=report.ended_at)

        for profile in report.step_profiles:
            share = 0.0
            if report.duration_seconds > 0:
                share = (profile.duration_seconds / report.duration_seconds) * 100

            self.line(
                f"{profile.name:<22} {profile.duration_seconds:>7.3f}s | {share:>5.1f}% | {profile.status.upper()}",
                timestamp=report.ended_at,
            )

        self.line(
            f"Total duration: {report.duration_seconds:.3f}s",
            timestamp=report.ended_at,
        )

    def api_usage_summary(self, report: TickReport) -> None:
        self.line("---- API Usage ----", timestamp=report.ended_at)
        self.line(
            (
                f"Tick requests: {report.tick_api_request_count} | "
                f"tick_estimated_cost=${report.tick_estimated_cost_usd:.6f}"
            ),
            timestamp=report.ended_at,
        )
        self.line(
            (
                f"Daily requests: {report.daily_api_request_count} | "
                f"daily_estimated_cost=${report.daily_estimated_cost_usd:.6f} | "
                f"budget_status={report.budget_status}"
            ),
            timestamp=report.ended_at,
        )
        self.line(
            (
                f"Thresholds: warning=${report.daily_warning_threshold_usd:.2f} | "
                f"limit=${report.daily_limit_threshold_usd:.2f}"
            ),
            timestamp=report.ended_at,
        )
        self.line(
            (
                f"Operations store: {report.operations_backend} | "
                f"detail={report.operations_backend_detail}"
            ),
            timestamp=report.ended_at,
        )
        if report.persistence_error:
            self.line(
                f"Persistence error: {report.persistence_error}",
                timestamp=report.ended_at,
            )
        else:
            self.line(
                f"Tick run persisted: {'yes' if report.persisted_tick_run else 'no'}",
                timestamp=report.ended_at,
            )

        if report.daily_api_usage:
            for summary in report.daily_api_usage:
                self.line(
                    self._format_usage_summary(summary),
                    timestamp=report.ended_at,
                )
        else:
            self.line("No API usage recorded yet.", timestamp=report.ended_at)

    def tick_end(self, report: TickReport) -> None:
        self.line(
            f"Tick status: {report.status.upper()}",
            timestamp=report.ended_at,
        )
        self.line(
            f"**** End {self._format_elapsed_clock(report.duration_seconds)} ****",
            timestamp=report.ended_at,
        )

    def _format_details(self, details: dict[str, Any]) -> str:
        if not details:
            return ""

        compact_parts: list[str] = []
        for key, value in details.items():
            compact_parts.append(f"{key}={self._format_value(value)}")
        return ", ".join(compact_parts)

    def _format_value(self, value: Any) -> str:
        if isinstance(value, float):
            return f"{value:.3f}"
        if isinstance(value, list):
            return str(len(value))
        return str(value)

    def _format_usage_summary(self, summary: ApiUsageSummary) -> str:
        return (
            f"{summary.source:<22} "
            f"requests={summary.request_count:<4} | "
            f"errors={summary.error_count:<3} | "
            f"cost=${summary.estimated_cost_usd:.6f}"
        )

    def _format_elapsed_clock(self, seconds: float) -> str:
        rounded = max(0, int(round(seconds)))
        minutes, remaining_seconds = divmod(rounded, 60)
        return f"{minutes:02d}:{remaining_seconds:02d}"

    def _format_timestamp(self, value: datetime) -> str:
        return value.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
