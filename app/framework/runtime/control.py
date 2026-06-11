from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import signal
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
        process_mode: str = "one_shot",
        command_source: str = "main.py",
    ) -> None:
        self.config = config or load_runtime_config()
        self.steps = steps or build_default_pipeline()
        self.logger = logger or ScreenLogger()
        self.process_mode = str(process_mode or "one_shot")
        self.command_source = str(command_source or "main.py")
        os.environ["CENTAUR_COMMAND_SOURCE"] = self.command_source
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)
        self._stop_requested = False

    def run_tick(self) -> TickReport:
        return self._run_tick_with_state()

    def _run_tick_with_state(
        self,
        *,
        initial_state: dict[str, object] | None = None,
    ) -> TickReport:
        started_at = datetime.now().astimezone()
        started_perf = perf_counter()
        tick_id = started_at.strftime("%Y%m%d-%H%M%S")
        context = TickContext(
            tick_id=tick_id,
            started_at=started_at,
            config=self.config,
            usage_ledger=self.usage_ledger,
            state=dict(initial_state or {}),
            metadata={
                "process_mode": self.process_mode,
                "command_source": self.command_source,
            },
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

    def run_control_heartbeat_once(
        self,
        *,
        initial_state: dict[str, object] | None = None,
    ) -> TickReport:
        control_step = next(
            (step for step in self.steps if str(getattr(step, "name", "")) == "control.heartbeat"),
            None,
        )
        if control_step is None:
            raise RuntimeError("control.heartbeat step is not present in the pipeline")
        one_step_runner = ControlPipelineRunner(
            steps=[control_step],
            logger=self.logger,
            config=self.config,
            usage_ledger=self.usage_ledger,
            process_mode="control_heartbeat_once",
            command_source=self.command_source,
        )
        return one_step_runner._run_tick_with_state(initial_state=initial_state)

    def run_development_loop(
        self,
        *,
        interval_seconds: int = 60,
        max_ticks: int | None = None,
    ) -> None:
        self.run_heartbeat_loop(
            interval_seconds=interval_seconds,
            max_ticks=max_ticks,
            reload_runtime_each_tick=False,
            label="Development loop",
        )

    def run_heartbeat_service_loop(
        self,
        *,
        interval_seconds: int = 10,
        max_ticks: int | None = None,
    ) -> None:
        lock_state = self._acquire_heartbeat_service_singleton()
        if lock_state.get("skip_run"):
            self.logger.line(
                "Heartbeat service singleton already owned by another process; skipping duplicate startup."
            )
            return
        try:
            self.run_heartbeat_loop(
                interval_seconds=interval_seconds,
                max_ticks=max_ticks,
                reload_runtime_each_tick=True,
                label="Heartbeat service",
            )
        finally:
            self._release_heartbeat_service_singleton(lock_state)

    def run_heartbeat_loop(
        self,
        *,
        interval_seconds: int,
        max_ticks: int | None,
        reload_runtime_each_tick: bool,
        label: str,
    ) -> None:
        interval_seconds = max(1, int(interval_seconds))
        tick_count = 0
        previous_handlers = self._install_stop_handlers()
        self.logger.line(
            (
                f"{label} enabled | interval={interval_seconds}s | "
                f"reload_runtime_each_tick={reload_runtime_each_tick}"
            )
        )

        try:
            while not self._stop_requested and (
                max_ticks is None or tick_count < max_ticks
            ):
                loop_started_perf = perf_counter()
                if reload_runtime_each_tick:
                    self.config = load_runtime_config()
                    self.process_mode = "heartbeat_service"
                    self.command_source = "main.py --heartbeat-service"
                    os.environ["CENTAUR_COMMAND_SOURCE"] = self.command_source
                    self.usage_ledger = UsageLedger(config=self.config)
                    self.steps = build_default_pipeline()
                self.run_tick()
                tick_count += 1

                if max_ticks is not None and tick_count >= max_ticks:
                    self.logger.line(f"{label} complete.")
                    return

                sleep_for = max(
                    0.0,
                    interval_seconds - (perf_counter() - loop_started_perf),
                )
                self.logger.line(
                    f"Sleeping {sleep_for:.2f}s before next heartbeat tick."
                )
                self._sleep_until_next_tick(sleep_for)
        finally:
            self._restore_stop_handlers(previous_handlers)
            if self._stop_requested:
                self.logger.line(f"{label} stop requested; exiting after current tick.")

    def _install_stop_handlers(self) -> dict[int, object]:
        previous: dict[int, object] = {}
        for signum in (signal.SIGINT, signal.SIGTERM):
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, self._request_stop)
        return previous

    def _restore_stop_handlers(self, previous_handlers: dict[int, object]) -> None:
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)

    def _request_stop(self, signum: int, _frame: object) -> None:
        self._stop_requested = True
        self.logger.line(
            f"Heartbeat stop signal received | signal={signum} | stop_after_current_tick=yes"
        )

    def _heartbeat_service_singleton_dir(self) -> Path:
        return Path("/tmp/ghostfrog-centaur-heartbeat-service.lock")

    def _acquire_heartbeat_service_singleton(self) -> dict[str, object]:
        lock_dir = self._heartbeat_service_singleton_dir()
        pid_file = lock_dir / "pid"
        state: dict[str, object] = {
            "lock_dir": lock_dir,
            "pid_file": pid_file,
            "owned": False,
            "skip_run": False,
        }
        existing_detected = "no"
        try:
            lock_dir.mkdir()
        except FileExistsError:
            existing_pid = pid_file.read_text(encoding="utf-8").strip() if pid_file.exists() else ""
            if existing_pid and self._pid_is_running(existing_pid):
                existing_detected = "yes"
                state["skip_run"] = True
            else:
                self.logger.line(
                    f"Heartbeat service singleton removing stale lock at {lock_dir}."
                )
                pid_file.unlink(missing_ok=True)
                lock_dir.rmdir()
                lock_dir.mkdir()
        if not state["skip_run"]:
            pid_file.write_text(str(os.getpid()), encoding="utf-8")
            state["owned"] = True
        os.environ["CENTAUR_EXISTING_HEARTBEAT_PROCESS_DETECTED"] = existing_detected
        os.environ["CENTAUR_HEARTBEAT_COMMAND_SOURCE"] = self.command_source
        self.logger.line(
            "Heartbeat service singleton "
            f"existing_heartbeat_process_detected={existing_detected} "
            f"process_id={os.getpid()} "
            f"existing_research_cycle_process_detected=unknown"
        )
        return state

    def _release_heartbeat_service_singleton(self, state: dict[str, object]) -> None:
        if not state.get("owned"):
            return
        pid_file = state.get("pid_file")
        lock_dir = state.get("lock_dir")
        if isinstance(pid_file, Path):
            pid_file.unlink(missing_ok=True)
        if isinstance(lock_dir, Path):
            try:
                lock_dir.rmdir()
            except OSError:
                pass

    def _pid_is_running(self, pid_text: str) -> bool:
        try:
            os.kill(int(pid_text), 0)
        except (OSError, ValueError):
            return False
        return True

    def _sleep_until_next_tick(self, sleep_for: float) -> None:
        deadline = perf_counter() + max(0.0, sleep_for)
        while not self._stop_requested:
            remaining = deadline - perf_counter()
            if remaining <= 0:
                return
            sleep(min(1.0, remaining))


def run_tick() -> TickReport:
    return ControlPipelineRunner().run_tick()
