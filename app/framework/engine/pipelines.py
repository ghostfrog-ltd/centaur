"""Compatibility facade for heartbeat step runners.

The scheduled heartbeat implementation now lives in `app.heartbeat.steps` so
the code ownership follows the folder flow. This module remains for older
imports used by backfill/replay facades, reports, and tests while new
orchestration work should import the owning heartbeat step directly.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any, Callable

from app.framework.runtime.models import TickContext

PipelineResult = dict[str, Any]
PipelineRunner = Callable[[TickContext], PipelineResult]


@dataclass(frozen=True, slots=True)
class StepDefinition:
    name: str
    runner: PipelineRunner

_PATCHABLE_SUPPORT_NAMES = (
    "BrokerAdapterError",
    "ExecutionAdapterError",
    "ExecutionRouter",
    "MarketDataAdapterError",
    "SlackWebhookClient",
    "get_broker_adapter",
    "get_execution_adapter",
    "get_market_data_adapter",
)


def _sync_support_patchables() -> None:
    import app.heartbeat.support as support

    for name in _PATCHABLE_SUPPORT_NAMES:
        if name in globals():
            setattr(support, name, globals()[name])

def _step_runner(step_folder: str) -> PipelineRunner:
    def run(context: TickContext) -> PipelineResult:
        _sync_support_patchables()
        import app.heartbeat.support as support

        module = import_module(f"app.heartbeat.steps.{step_folder}.implementation.main")
        for name in _PATCHABLE_SUPPORT_NAMES:
            if hasattr(support, name):
                setattr(module, name, getattr(support, name))
        return module.run_implementation(context)

    return run


control_heartbeat = _step_runner("01_control_heartbeat")
alpaca_account = _step_runner("02_alpaca_account")
alpaca_clock = _step_runner("03_alpaca_clock")
alpaca_positions = _step_runner("04_alpaca_positions")
alpaca_orders = _step_runner("05_alpaca_orders")
alpaca_live_sync = _step_runner("06_alpaca_live_sync")
trading212_paper_sync = _step_runner("07_trading212_paper_sync")
daily_protection = _step_runner("08_risk_daily_protection")
live_daily_protection = _step_runner("09_risk_live_daily_protection")
trailing_drawdown_observer = _step_runner("10_risk_trailing_drawdown_observer")
stale_order_reaper = _step_runner("11_maintenance_stale_orders")
live_stale_order_reaper = _step_runner("12_maintenance_live_stale_orders")
market_gate = _step_runner("13_market_gate")
fx_gbp_reference = _step_runner("14_fx_gbp_reference")
trading212_paper_daily_protection = _step_runner("15_risk_trading212_paper_daily_protection")
market_latest_bars = _step_runner("16_market_latest_bars")
trading212_latest_bars = _step_runner("17_trading212_latest_bars")
crypto_latest_bars = _step_runner("18_crypto_latest_bars")
paper_exit_management = _step_runner("19_execution_paper_exits")
live_exit_management = _step_runner("20_execution_live_exits")
shadow_trade_outcomes = _step_runner("21_shadow_outcomes")
strategy_fitness = _step_runner("22_strategy_fitness")
market_scan = _step_runner("23_market_scan")
slow_enrichment_queue = _step_runner("24_slow_enrichment_queue")
context_enrichment = _step_runner("25_context_enrichment")
strategy_signals = _step_runner("26_strategy_signals")
gemini_analysis = _step_runner("27_analysis_gemini")
shadow_trade_proposals = _step_runner("28_shadow_proposals")
risk_cfo_gate = _step_runner("29_risk_cfo")
execution_paper = _step_runner("30_execution_paper")
live_risk_cfo_gate = _step_runner("31_risk_live_cfo")
execution_live = _step_runner("32_execution_live")
post_trade_evaluation = _step_runner("33_evaluation_post_trade")
slack_notifications = _step_runner("34_notifications_slack")

def build_default_pipeline():
    from app.heartbeat.pipeline import build_heartbeat_cron_pipeline

    return build_heartbeat_cron_pipeline()


from app.heartbeat.support import *  # noqa: F403,E402

def _build_paper_trade_approval(*args: Any, **kwargs: Any):
    _sync_support_patchables()
    import app.heartbeat.support as support

    return support._build_paper_trade_approval(*args, **kwargs)


def _build_live_trade_approval(*args: Any, **kwargs: Any):
    _sync_support_patchables()
    import app.heartbeat.support as support

    return support._build_live_trade_approval(*args, **kwargs)
