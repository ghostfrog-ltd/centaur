from __future__ import annotations

import argparse
import json
from datetime import datetime

from app.framework.engine.backfill import HistoricalBackfillRunner
from app.framework.engine.replay import HistoricalReplayRunner
from app.framework.engine.research_cycle import ResearchCycleRunner
from app.framework.engine.slow_enrichment_queue import (
    process_slow_enrichment_queue_until_idle,
    repair_slow_enrichment_queue,
)
from app.framework.engine.trading212_seed import Trading212PriceSeeder
from app.framework.reporting.adapter_inventory import AdapterInventoryReport
from app.framework.reporting.attention_status import AttentionStatusReport
from app.framework.reporting.autopilot_proof import AutopilotProofRunner
from app.framework.reporting.crypto_health_report import CryptoHealthReport
from app.framework.reporting.evidence_report import EvidenceReport
from app.framework.reporting.historical_bars_status import HistoricalBarsStatusReport
from app.framework.reporting.historical_replay_coverage import HistoricalReplayCoverageReport
from app.framework.reporting.holding_window_advisor import HoldingWindowAdvisor
from app.framework.reporting.overnight_giveback_report import OvernightGivebackReport
from app.framework.reporting.paper_exit_review import PaperExitReview
from app.framework.reporting.postgres_preflight import PostgresPreflightReport
from app.framework.reporting.promotion_gate import PromotionGateReport
from app.framework.reporting.proposal_pipeline_diagnostics import (
    ProposalPipelineDiagnosticsReport,
)
from app.framework.reporting.research_status import ResearchStatusReport
from app.framework.reporting.research_cycle_status import ResearchCycleStatusReport
from app.framework.reporting.real_learning_proof import RealLearningProofReport
from app.framework.reporting.research_proof_vs_real import ResearchProofVsRealReport
from app.framework.reporting.replay_summary import ReplayComparisonReport, ReplaySummaryReport
from app.framework.reporting.status import StatusReporter
from app.framework.reporting.strategy_health_report import StrategyHealthReport
from app.framework.reporting.threshold_advisor import ThresholdAdvisor
from app.framework.reporting.trading212_instruments import Trading212InstrumentReport
from app.framework.runtime.control import ControlPipelineRunner
from app.framework.runtime.settings import load_runtime_config
from app.framework.storage.usage import UsageLedger


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the Project Centaur control pipeline."
    )
    parser.add_argument(
        "--loop",
        action="store_true",
        help="Run a local development heartbeat loop.",
    )
    parser.add_argument(
        "--heartbeat-service",
        action="store_true",
        help="Run the supervised production heartbeat loop for launchd.",
    )
    parser.add_argument(
        "--interval-seconds",
        type=int,
        default=60,
        help="Seconds between ticks in --loop mode.",
    )
    parser.add_argument(
        "--max-ticks",
        type=int,
        default=0,
        help="Optional safety limit for --loop mode. Use 0 for unlimited.",
    )
    parser.add_argument(
        "--backfill",
        action="store_true",
        help="Run a one-shot historical bars backfill instead of the live control tick.",
    )
    parser.add_argument(
        "--replay",
        action="store_true",
        help="Run a one-shot historical replay over stored bars to generate shadow training outcomes.",
    )
    parser.add_argument(
        "--replay-summary",
        action="store_true",
        help="Show a read-only summary for one persisted replay run.",
    )
    parser.add_argument(
        "--replay-comparison",
        action="store_true",
        help="Show a read-only comparison across multiple persisted historical replay runs.",
    )
    parser.add_argument(
        "--research-cycle",
        action="store_true",
        help="Run a bounded research-only autonomous replay cycle without affecting paper/live execution.",
    )
    parser.add_argument(
        "--research-status",
        action="store_true",
        help="Show the latest persisted research-cycle decision report.",
    )
    parser.add_argument(
        "--research-cycle-status",
        action="store_true",
        help="Show the latest real heartbeat research-cycle summary.",
    )
    parser.add_argument(
        "--autopilot-proof",
        action="store_true",
        help="Run a safe dry-run proof that autonomy stays in learning lanes and manual approval gates risky lanes.",
    )
    parser.add_argument(
        "--research-proof-vs-real",
        action="store_true",
        help="Compare the synthetic autopilot proof harness against the latest persisted real-heartbeat research cycle.",
    )
    parser.add_argument(
        "--historical-replay-coverage",
        action="store_true",
        help="Show the real historical replay coverage and replay-window rejection reasons used by the heartbeat.",
    )
    parser.add_argument(
        "--real-learning-proof",
        action="store_true",
        help="Verify that persisted real-heartbeat research used stored historical evidence while keeping safety gates closed.",
    )
    parser.add_argument(
        "--run-fresh",
        action="store_true",
        help="Run a fresh forced real-heartbeat research cycle before the selected diagnostic report.",
    )
    parser.add_argument(
        "--heartbeat-autonomous-learning-once",
        action="store_true",
        help="Run the real control-heartbeat autonomous learning path once and record source=real_heartbeat.",
    )
    parser.add_argument(
        "--force-research-cycle",
        action="store_true",
        help="Diagnostic-only: bypass the research-cycle interval gate for the real heartbeat path without relaxing broker/live safety.",
    )
    parser.add_argument(
        "--historical-bars-status",
        action="store_true",
        help="Show a read-only summary of the historical bars store and replay readiness.",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="Show a one-shot Centaur status summary without running a control tick.",
    )
    parser.add_argument(
        "--threshold-advice",
        action="store_true",
        help="Run the recommendation-only GA adviser for the strategy suppress threshold.",
    )
    parser.add_argument(
        "--holding-window-advice",
        action="store_true",
        help="Run the recommendation-only adviser for strategy holding-window fitness.",
    )
    parser.add_argument(
        "--promotion-status",
        action="store_true",
        help="Show persisted strategy promotion stages and manual paper approvals.",
    )
    parser.add_argument(
        "--promotion-evaluate",
        action="store_true",
        help="Evaluate replay and paper-sim evidence for one strategy/profile without auto-approving broker paper execution.",
    )
    parser.add_argument(
        "--promotion-approve-paper",
        action="store_true",
        help="Manually approve one strategy/profile for broker paper execution.",
    )
    parser.add_argument(
        "--promotion-reject",
        action="store_true",
        help="Reject one strategy/profile from promotion with an auditable reason.",
    )
    parser.add_argument(
        "--alert-ack",
        action="store_true",
        help="Acknowledge an open attention alert and stop repeat Slack reminders.",
    )
    parser.add_argument(
        "--alert-resolve",
        action="store_true",
        help="Resolve an attention alert manually with a reason.",
    )
    parser.add_argument(
        "--attention-status",
        action="store_true",
        help="List open attention alerts and how to acknowledge or resolve them.",
    )
    parser.add_argument(
        "--paper-exit-review",
        action="store_true",
        help="Run a read-only post-mortem that compares paper exits to stored shadow checkpoints.",
    )
    parser.add_argument(
        "--strategy-health",
        action="store_true",
        help="Run a read-only strategy health report that bundles paper P/L, exits, proposals, and signal flow.",
    )
    parser.add_argument(
        "--proposal-pipeline-diagnostics",
        action="store_true",
        help="Run a read-only report explaining where execution-allowed strategies are getting filtered out.",
    )
    parser.add_argument(
        "--slow-enrichment-queue-process",
        action="store_true",
        help="Run the advisory slow enrichment queue worker once until idle.",
    )
    parser.add_argument(
        "--slow-enrichment-queue-repair",
        action="store_true",
        help="Repair expired or stale advisory slow enrichment queue rows so deferred coverage can resume.",
    )
    parser.add_argument(
        "--crypto-health",
        action="store_true",
        help="Run a read-only crypto health report focused on overnight crypto scan activity and signal visibility.",
    )
    parser.add_argument(
        "--overnight-giveback",
        action="store_true",
        help="Run a read-only report for 01:00-to-09:00 Alpaca Paper mark-to-market giveback.",
    )
    parser.add_argument(
        "--evidence-report",
        action="store_true",
        help="Run a read-only registry report for shadow/counterfactual evidence streams before deciding actions.",
    )
    parser.add_argument(
        "--storage-separation-report",
        action="store_true",
        help="Run a read-only paper/live provenance and storage-separation report.",
    )
    parser.add_argument(
        "--adapter-inventory",
        action="store_true",
        help="Run a read-only inventory of market-data, execution, and broker/account adapters.",
    )
    parser.add_argument(
        "--postgres-preflight",
        action="store_true",
        help="Run a read-only PostgreSQL runtime diagnostics report without printing secrets.",
    )
    parser.add_argument(
        "--trading212-instruments",
        action="store_true",
        help="Fetch Trading 212 instrument metadata and report UK symbol/ticker readiness.",
    )
    parser.add_argument(
        "--trading212-seed-prices",
        action="store_true",
        help="Create tiny Trading 212 paper holdings for positions_api price discovery.",
    )
    parser.add_argument(
        "--confirm-trading212-paper-seed",
        action="store_true",
        help="Actually submit Trading 212 paper seed market orders. Without this, --trading212-seed-prices is a dry run.",
    )
    parser.add_argument(
        "--trading212-seed-quantity",
        type=str,
        default="0.01",
        help="Tiny per-symbol Trading 212 seed quantity. Capped at 0.01 for capital preservation.",
    )
    parser.add_argument(
        "--profile-id",
        type=str,
        default="",
        help="Profile id for promotion and strategy-specific commands.",
    )
    parser.add_argument(
        "--strategy-id",
        type=str,
        default="mean_reversion.snapback",
        help="Strategy id for advisory commands such as --holding-window-advice.",
    )
    parser.add_argument(
        "--max-paper-notional",
        type=float,
        default=0.0,
        help="Manual paper promotion cap for max per-trade notional in USD.",
    )
    parser.add_argument(
        "--max-open-trades",
        type=int,
        default=0,
        help="Manual paper promotion cap for concurrent open trades.",
    )
    parser.add_argument(
        "--cooldown-minutes",
        type=int,
        default=0,
        help="Manual paper promotion cooldown between entry submissions for the same strategy/profile.",
    )
    parser.add_argument(
        "--confirm-promotion-approval",
        action="store_true",
        help="Required confirmation flag for --promotion-approve-paper.",
    )
    parser.add_argument(
        "--reason",
        type=str,
        default="",
        help="Reason for auditable rejection or manual promotion notes.",
    )
    parser.add_argument(
        "--event-id",
        type=str,
        default="",
        help="Attention alert event id for ack/resolve commands.",
    )
    parser.add_argument(
        "--dashboard",
        action="store_true",
        help="Launch the local Centaur web dashboard server.",
    )
    parser.add_argument(
        "--dashboard-desktop",
        action="store_true",
        help="Launch the legacy local Centaur desktop monitor window.",
    )
    parser.add_argument(
        "--host",
        type=str,
        default="127.0.0.1",
        help="Host for the web dashboard server.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8788,
        help="Port for the web dashboard server.",
    )
    parser.add_argument(
        "--backfill-api-costs",
        action="store_true",
        help="Reprice stored API usage events from current provider pricing and rebuild cost rollups.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=0,
        help="Historical backfill lookback window in days. Uses config default when omitted.",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="",
        help="Historical backfill timeframe, for example 1Min or 1Hour.",
    )
    parser.add_argument(
        "--equity-symbols",
        type=str,
        default="",
        help="Optional comma-separated equity symbols for backfill.",
    )
    parser.add_argument(
        "--crypto-symbols",
        type=str,
        default="",
        help="Optional comma-separated crypto symbols for backfill.",
    )
    parser.add_argument(
        "--max-replay-timestamps",
        type=int,
        default=0,
        help="Optional cap on historical timestamps processed in --replay mode. Use 0 for all eligible timestamps.",
    )
    parser.add_argument(
        "--replay-start-at",
        type=str,
        default="",
        help="Optional ISO datetime/date start for --replay mode.",
    )
    parser.add_argument(
        "--replay-end-at",
        type=str,
        default="",
        help="Optional ISO datetime/date end for --replay mode.",
    )
    parser.add_argument(
        "--replay-run-id",
        type=str,
        default="",
        help="Replay run id for --replay-summary.",
    )
    parser.add_argument(
        "--replay-limit",
        type=int,
        default=12,
        help="Maximum persisted replay runs to include in --replay-comparison.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Process the selected one-shot command without persisting replay evidence.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.status:
        StatusReporter().print()
        return

    if args.threshold_advice:
        print(ThresholdAdvisor().render(), flush=True)
        return

    if args.holding_window_advice:
        advisor = HoldingWindowAdvisor()
        print(advisor.render(advice=advisor.build_advice(strategy_id=args.strategy_id)), flush=True)
        return

    if args.promotion_status:
        reporter = PromotionGateReport()
        print(reporter.render_status(), flush=True)
        return

    if args.promotion_evaluate:
        reporter = PromotionGateReport()
        print(
            reporter.render_evaluation(
                report=reporter.evaluate(
                    strategy_id=args.strategy_id,
                    profile_id=args.profile_id,
                )
            ),
            flush=True,
        )
        return

    if args.promotion_approve_paper:
        reporter = PromotionGateReport()
        record = reporter.approve_paper(
            strategy_id=args.strategy_id,
            profile_id=args.profile_id,
            max_paper_notional_usd=args.max_paper_notional,
            max_open_trades=args.max_open_trades,
            cooldown_minutes=args.cooldown_minutes,
            confirmed=bool(args.confirm_promotion_approval),
        )
        print(reporter.render_status(report={"status": "ok", "records": [record]}), flush=True)
        return

    if args.promotion_reject:
        reporter = PromotionGateReport()
        record = reporter.reject(
            strategy_id=args.strategy_id,
            profile_id=args.profile_id,
            reason=args.reason,
        )
        print(reporter.render_status(report={"status": "ok", "records": [record]}), flush=True)
        return

    if args.alert_ack:
        ledger = UsageLedger(config=load_runtime_config())
        ledger.resolve_attention_alert(
            event_id=args.event_id,
            status="acknowledged",
            reason=args.reason or "manually_acknowledged",
        )
        print(f"Attention alert acknowledged: {args.event_id}", flush=True)
        return

    if args.alert_resolve:
        ledger = UsageLedger(config=load_runtime_config())
        ledger.resolve_attention_alert(
            event_id=args.event_id,
            status="resolved",
            reason=args.reason or "manually_resolved",
        )
        print(f"Attention alert resolved: {args.event_id}", flush=True)
        return

    if args.attention_status:
        print(AttentionStatusReport().render(), flush=True)
        return

    if args.paper_exit_review:
        reviewer = PaperExitReview()
        print(
            reviewer.render(
                review=reviewer.build_review(strategy_id=args.strategy_id)
            ),
            flush=True,
        )
        return

    if args.strategy_health:
        reporter = StrategyHealthReport()
        print(
            reporter.render(
                report=reporter.build_report(strategy_id=args.strategy_id)
            ),
            flush=True,
        )
        return

    if args.proposal_pipeline_diagnostics:
        reporter = ProposalPipelineDiagnosticsReport()
        print(reporter.render(), flush=True)
        return

    if args.slow_enrichment_queue_process:
        print(
            json.dumps(
                {"status": "ok", **process_slow_enrichment_queue_until_idle()},
                sort_keys=True,
                default=str,
            ),
            flush=True,
        )
        return

    if args.slow_enrichment_queue_repair:
        print(
            json.dumps(
                {"status": "ok", **repair_slow_enrichment_queue()},
                sort_keys=True,
                default=str,
            ),
            flush=True,
        )
        return

    if args.crypto_health:
        reporter = CryptoHealthReport()
        lookback_hours = max(1, args.days * 24) if args.days > 0 else 36
        print(
            reporter.render(
                report=reporter.build_report(lookback_hours=lookback_hours)
            ),
            flush=True,
        )
        return

    if args.overnight_giveback:
        reporter = OvernightGivebackReport()
        print(
            reporter.render(
                report=reporter.build_report(days=args.days if args.days > 0 else 7)
            ),
            flush=True,
        )
        return

    if args.evidence_report:
        reporter = EvidenceReport()
        print(
            reporter.render(
                report=reporter.build_report(tick_limit=max(1, args.days * 48) if args.days > 0 else 120)
            ),
            flush=True,
        )
        return

    if args.storage_separation_report:
        reporter = EvidenceReport()
        print(reporter.render_storage_separation_report(), flush=True)
        return

    if args.adapter_inventory:
        print(AdapterInventoryReport().render(), flush=True)
        return

    if args.postgres_preflight:
        reporter = PostgresPreflightReport()
        print(reporter.render(reporter.build_report()), flush=True)
        return

    if args.trading212_instruments:
        print(Trading212InstrumentReport().render(), flush=True)
        return

    if args.trading212_seed_prices:
        seeder = Trading212PriceSeeder()
        print(
            seeder.render(
                result=seeder.run(
                    confirm=bool(args.confirm_trading212_paper_seed),
                    quantity=args.trading212_seed_quantity,
                    symbols=_parse_csv_argument(args.equity_symbols),
                )
            ),
            flush=True,
        )
        return

    if args.dashboard:
        from app.framework.reporting.web_dashboard import run_web_dashboard

        run_web_dashboard(
            host=args.host,
            port=args.port,
            config=load_runtime_config(),
        )
        return

    if args.dashboard_desktop:
        from app.framework.reporting.dashboard import run_dashboard

        run_dashboard()
        return

    if args.backfill_api_costs:
        ledger = UsageLedger(config=load_runtime_config())
        summary = ledger.backfill_api_costs()
        print("Centaur API cost backfill complete", flush=True)
        print(
            (
                f"Backend: {summary['backend']} | repriced_at={summary['repriced_at']} | "
                f"events_scanned={summary['events_scanned']} | "
                f"events_cost_changed={summary['events_cost_changed']} | "
                f"zero_cost_events={summary['zero_cost_events']}"
            ),
            flush=True,
        )
        print(
            (
                f"Gemini: events_scanned={summary['gemini_events_scanned']} | "
                f"with_tokens={summary['gemini_events_with_tokens']} | "
                f"nonzero_cost={summary['gemini_events_nonzero_cost']}"
            ),
            flush=True,
        )
        print(
            (
                f"Rollups: daily_rows_rebuilt={summary['daily_rows_rebuilt']} | "
                f"tick_runs_updated={summary['tick_runs_updated']} | "
                f"total_estimated_cost_usd=${float(summary['total_estimated_cost_usd']):.6f}"
            ),
            flush=True,
        )
        return

    if args.backfill:
        runner = HistoricalBackfillRunner()
        runner.run(
            days=args.days if args.days > 0 else None,
            timeframe=args.timeframe or None,
            equity_symbols=_parse_csv_argument(args.equity_symbols),
            crypto_symbols=_parse_csv_argument(args.crypto_symbols),
        )
        return

    if args.replay:
        runner = HistoricalReplayRunner()
        runner.run(
            days=args.days if args.days > 0 else None,
            timeframe=args.timeframe or None,
            equity_symbols=_parse_csv_argument(args.equity_symbols),
            crypto_symbols=_parse_csv_argument(args.crypto_symbols),
            max_timestamps=args.max_replay_timestamps
            if args.max_replay_timestamps > 0
            else None,
            start_at=_parse_datetime_argument(args.replay_start_at),
            end_at=_parse_datetime_argument(args.replay_end_at),
            dry_run=args.dry_run,
        )
        return

    if args.replay_summary:
        report = ReplaySummaryReport()
        print(report.render(replay_run_id=args.replay_run_id.strip()), flush=True)
        return

    if args.replay_comparison:
        report = ReplayComparisonReport()
        print(report.render(replay_limit=max(1, args.replay_limit)), flush=True)
        return

    if args.research_cycle:
        ResearchCycleRunner().run()
        print(
            ResearchStatusReport().render(),
            flush=True,
        )
        return

    if args.research_status:
        print(ResearchStatusReport().render(), flush=True)
        return

    if args.research_cycle_status:
        print(ResearchCycleStatusReport().render(), flush=True)
        return

    if args.autopilot_proof:
        reporter = AutopilotProofRunner()
        print(reporter.render(reporter.run()), flush=True)
        return

    if args.research_proof_vs_real:
        print(ResearchProofVsRealReport().render(), flush=True)
        return

    if args.historical_replay_coverage:
        print(HistoricalReplayCoverageReport().render(), flush=True)
        return

    if args.real_learning_proof:
        if args.run_fresh:
            print(
                _run_heartbeat_autonomous_learning_once(force_research_cycle=True),
                flush=True,
            )
            print("", flush=True)
        print(RealLearningProofReport().render(), flush=True)
        return

    if args.heartbeat_autonomous_learning_once:
        print(
            _run_heartbeat_autonomous_learning_once(
                force_research_cycle=bool(args.force_research_cycle)
            ),
            flush=True,
        )
        return

    if args.historical_bars_status:
        report = HistoricalBarsStatusReport()
        print(
            report.render(
                days=args.days if args.days > 0 else None,
                timeframe=args.timeframe or None,
                start_at=_parse_datetime_argument(args.replay_start_at),
                end_at=_parse_datetime_argument(args.replay_end_at),
                equity_symbols=_parse_csv_argument(args.equity_symbols),
                crypto_symbols=_parse_csv_argument(args.crypto_symbols),
            ),
            flush=True,
        )
        return

    config = load_runtime_config()
    runner = ControlPipelineRunner(config=config)

    if args.heartbeat_service:
        max_ticks = None if args.max_ticks <= 0 else args.max_ticks
        runner.run_heartbeat_service_loop(
            interval_seconds=max(1, args.interval_seconds),
            max_ticks=max_ticks,
        )
        return

    if args.loop:
        max_ticks = None if args.max_ticks <= 0 else args.max_ticks
        runner.run_development_loop(
            interval_seconds=max(1, args.interval_seconds),
            max_ticks=max_ticks,
        )
        return

    runner.run_tick()


def _parse_csv_argument(value: str) -> tuple[str, ...] | None:
    items = [item.strip() for item in value.split(",") if item.strip()]
    if not items:
        return None
    return tuple(items)


def _parse_datetime_argument(value: str) -> datetime | None:
    raw = value.strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalized)
    if parsed.tzinfo is None:
        local_tz = datetime.now().astimezone().tzinfo
        return parsed.replace(tzinfo=local_tz)
    return parsed


def _run_heartbeat_autonomous_learning_once(*, force_research_cycle: bool = False) -> str:
    config = load_runtime_config()
    ledger = UsageLedger(config=config)
    runner = ControlPipelineRunner(
        config=config,
        usage_ledger=ledger,
    )
    report = runner.run_control_heartbeat_once(
        initial_state={
            "diagnostics": {
                "force_research_cycle": bool(force_research_cycle),
            }
        }
    )
    autonomous_state = dict(report.state_snapshot.get("autonomous_learning", {}) or {})
    return "\n".join(
        [
            "Heartbeat Autonomous Learning Once",
            f"tick_id={report.tick_id}",
            f"status={str(autonomous_state.get('status', 'unknown'))}",
            f"forced_research_cycle={'yes' if force_research_cycle else 'no'}",
            f"research_cycle_id={str(autonomous_state.get('research_cycle_id', '') or '-')}",
            f"research_cycle_source={str(autonomous_state.get('research_cycle_source', '') or '-')}",
            f"persisted_tick_run={'yes' if report.persisted_tick_run else 'no'}",
            f"persistence_error={report.persistence_error or '-'}",
        ]
    )


if __name__ == "__main__":
    main()
