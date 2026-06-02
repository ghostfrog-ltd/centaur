from __future__ import annotations

import argparse
from datetime import datetime

from app.framework.engine.backfill import HistoricalBackfillRunner
from app.framework.engine.replay import HistoricalReplayRunner
from app.framework.engine.trading212_seed import Trading212PriceSeeder
from app.framework.reporting.adapter_inventory import AdapterInventoryReport
from app.framework.reporting.crypto_health_report import CryptoHealthReport
from app.framework.reporting.evidence_report import EvidenceReport
from app.framework.reporting.holding_window_advisor import HoldingWindowAdvisor
from app.framework.reporting.paper_exit_review import PaperExitReview
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
        help="Run a local development heartbeat loop. Production should use an external scheduler.",
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
        "--crypto-health",
        action="store_true",
        help="Run a read-only crypto health report focused on overnight crypto scan activity and signal visibility.",
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
        "--strategy-id",
        type=str,
        default="mean_reversion.snapback",
        help="Strategy id for advisory commands such as --holding-window-advice.",
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
        )
        return

    config = load_runtime_config()
    runner = ControlPipelineRunner(config=config)

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


if __name__ == "__main__":
    main()
