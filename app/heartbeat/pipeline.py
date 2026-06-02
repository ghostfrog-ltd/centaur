"""Master scheduled heartbeat pipeline.

The ordered step ownership lives here so the folder tree, Mermaid visual, and
LangGraph runtime describe the same heartbeat cron flow.
"""

from __future__ import annotations

from importlib import import_module

from .contracts import HeartbeatStepDefinition

STEP_MODULES: tuple[str, ...] = (
    "app.heartbeat.steps.01_control_heartbeat.pipeline",
    "app.heartbeat.steps.02_alpaca_account.pipeline",
    "app.heartbeat.steps.03_alpaca_clock.pipeline",
    "app.heartbeat.steps.04_alpaca_positions.pipeline",
    "app.heartbeat.steps.05_alpaca_orders.pipeline",
    "app.heartbeat.steps.06_alpaca_live_sync.pipeline",
    "app.heartbeat.steps.07_trading212_paper_sync.pipeline",
    "app.heartbeat.steps.08_risk_daily_protection.pipeline",
    "app.heartbeat.steps.09_risk_live_daily_protection.pipeline",
    "app.heartbeat.steps.10_risk_trailing_drawdown_observer.pipeline",
    "app.heartbeat.steps.11_maintenance_stale_orders.pipeline",
    "app.heartbeat.steps.12_maintenance_live_stale_orders.pipeline",
    "app.heartbeat.steps.13_market_gate.pipeline",
    "app.heartbeat.steps.14_fx_gbp_reference.pipeline",
    "app.heartbeat.steps.15_risk_trading212_paper_daily_protection.pipeline",
    "app.heartbeat.steps.16_market_latest_bars.pipeline",
    "app.heartbeat.steps.17_trading212_latest_bars.pipeline",
    "app.heartbeat.steps.18_crypto_latest_bars.pipeline",
    "app.heartbeat.steps.19_execution_paper_exits.pipeline",
    "app.heartbeat.steps.20_execution_live_exits.pipeline",
    "app.heartbeat.steps.21_shadow_outcomes.pipeline",
    "app.heartbeat.steps.22_strategy_fitness.pipeline",
    "app.heartbeat.steps.23_market_scan.pipeline",
    "app.heartbeat.steps.24_context_enrichment.pipeline",
    "app.heartbeat.steps.25_strategy_signals.pipeline",
    "app.heartbeat.steps.26_analysis_gemini.pipeline",
    "app.heartbeat.steps.27_shadow_proposals.pipeline",
    "app.heartbeat.steps.28_risk_cfo.pipeline",
    "app.heartbeat.steps.29_execution_paper.pipeline",
    "app.heartbeat.steps.30_risk_live_cfo.pipeline",
    "app.heartbeat.steps.31_execution_live.pipeline",
    "app.heartbeat.steps.32_evaluation_post_trade.pipeline",
    "app.heartbeat.steps.33_notifications_slack.pipeline",
)


def build_heartbeat_cron_pipeline() -> list[HeartbeatStepDefinition]:
    """Return the ordered step pipelines executed by the heartbeat cron."""

    steps: list[HeartbeatStepDefinition] = []
    for module_name in STEP_MODULES:
        # Import the folder-owned pipeline lazily so tests/docs can inspect the
        # exact runtime order without importing unrelated step implementations.
        module = import_module(module_name)
        steps.append(module.STEP)
    return steps
