from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import sys
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
from app.framework.reporting.generated_candidate_state_report import (
    GeneratedCandidateStateReport,
)
from app.framework.reporting.historical_bars_status import HistoricalBarsStatusReport
from app.framework.reporting.historical_coverage_report import HistoricalCoverageReport
from app.framework.reporting.historical_replay_coverage import HistoricalReplayCoverageReport
from app.framework.reporting.holding_window_advisor import HoldingWindowAdvisor
from app.framework.reporting.overnight_giveback_report import OvernightGivebackReport
from app.framework.reporting.operator_summary import OperatorSummaryReport
from app.framework.reporting.paper_exit_review import PaperExitReview
from app.framework.reporting.postgres_preflight import PostgresPreflightReport
from app.framework.reporting.promotion_gate import PromotionGateReport
from app.framework.reporting.proposal_pipeline_diagnostics import (
    ProposalPipelineDiagnosticsReport,
)
from app.framework.reporting.proposal_suppression_funnel import (
    ProposalSuppressionFunnelReport,
)
from app.framework.reporting.research_status import ResearchStatusReport
from app.framework.reporting.research_cycle_status import ResearchCycleStatusReport
from app.framework.reporting.research_cycle_last_comparison import (
    ResearchCycleLastComparisonReport,
)
from app.framework.reporting.research_autopilot import ResearchAutopilotRunner
from app.framework.reporting.research_expansion_planner import ResearchExpansionPlannerReport
from app.framework.reporting.real_learning_proof import RealLearningProofReport
from app.framework.reporting.research_proof_vs_real import ResearchProofVsRealReport
from app.framework.reporting.replay_summary import ReplayComparisonReport, ReplaySummaryReport
from app.framework.reporting.self_improvement_status import SelfImprovementStatusReport
from app.framework.reporting.attention_alerts_reconcile import AttentionAlertsReconcileReport
from app.framework.reporting.status import StatusReporter
from app.framework.reporting.strategy_health_report import StrategyHealthReport
from app.framework.reporting.strategy_variant_research import (
    StrategyVariantDiagnosticsReport,
    StrategyVariantResearchReport,
    StrategyVariantResearchService,
)
from app.framework.reporting.strategy_loss_diagnosis import StrategyLossDiagnosisReport
from app.framework.reporting.paper_candidate_audit import PaperCandidateAuditReport
from app.framework.reporting.strategy_portfolio_research_planner import (
    StrategyPortfolioResearchPlannerReport,
)
from app.framework.reporting.strategy_research_planner import StrategyResearchPlannerReport
from app.framework.reporting.symbol_replay_evidence_plan import SymbolReplayEvidencePlanReport
from app.framework.reporting.symbol_subset_stability import SymbolSubsetStabilityReport
from app.framework.reporting.threshold_advisor import ThresholdAdvisor
from app.framework.reporting.trading212_instruments import Trading212InstrumentReport
from app.framework.reporting.evidence_quality_report import EvidenceQualityReport
from app.framework.reporting.outcome_recording_status import OutcomeRecordingStatusReport
from app.framework.reporting.paper_candidate_decision_report import (
    PaperCandidateDecisionReport,
)
from app.framework.reporting.paper_canary import PaperCanaryReport
from app.framework.reporting.replay_dataset_preparation import ReplayDatasetPreparationReport
from app.framework.reporting.specific_replay_cache_precompute import (
    SpecificReplayCachePrecomputeReport,
)
from app.framework.reporting.signal_generation_diagnosis import (
    SignalGenerationDiagnosisReport,
)
from app.framework.reporting.bounded_dip_rebound_precompute import (
    BoundedDipReboundPrecomputeReport,
)
from app.framework.runtime.control import ControlPipelineRunner
from app.framework.runtime.email import SmtpEmailClient
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
        "--backfill-alpaca-equity-bars",
        action="store_true",
        help="Run a dedicated multi-timeframe Alpaca equity historical bars backfill without trading or mutating promotion state.",
    )
    parser.add_argument(
        "--backfill-or-resample-crypto-1day-bars",
        action="store_true",
        help="Research-only: load native crypto 1Day bars when available, otherwise resample stored 1Hour or 15Min crypto bars into auditable 1Day bars.",
    )
    parser.add_argument(
        "--backfill-or-resample-crypto-15min-bars",
        action="store_true",
        help="Research-only: backfill native crypto 15Min bars and persist dataset readiness without changing paper/live state.",
    )
    parser.add_argument(
        "--import-crypto-15min-bars",
        action="store_true",
        help="Research-only: import bulk crypto 15Min CSV/parquet bars, upsert into historical storage, and persist dataset readiness without changing paper/live state.",
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
        "--research-cycle-last-comparison",
        action="store_true",
        help="Compare the last forced real cycle against the last natural scheduled real cycle.",
    )
    parser.add_argument(
        "--research-cycle-last-launchd-comparison",
        action="store_true",
        help="Compare the last forced real cycle against the last actual launchd scheduled cycle.",
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
        "--self-improvement-status",
        action="store_true",
        help="Report whether real persisted learning evidence is improving over time without changing promotion or execution state.",
    )
    parser.add_argument(
        "--operator-summary",
        action="store_true",
        help="Show a compact operator summary covering health, freshness, replay movement, closest-to-promotion, and why no trades are happening.",
    )
    parser.add_argument(
        "--operator-summary-format",
        type=str,
        choices=("text", "slack", "email"),
        default="text",
        help="Output format for --operator-summary.",
    )
    parser.add_argument(
        "--send-operator-summary-email",
        action="store_true",
        help="Send the operator summary via configured SMTP as a professional plain-text email.",
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
        "--attention-alerts-reconcile",
        action="store_true",
        help="Safely reconcile stale or invalid approval-related attention alerts without approving, rejecting, or enabling live execution.",
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
        "--strategy-variant-research-report",
        action="store_true",
        help="Show a read-only persisted strategy variant research report.",
    )
    parser.add_argument(
        "--run-strategy-variant-research",
        action="store_true",
        help="Run research-only strategy variant generation and evaluation for a supported strategy family.",
    )
    parser.add_argument(
        "--strategy-variant-diagnostics",
        action="store_true",
        help="Show a read-only diagnostic report proving whether variant params affect replay decisions and results.",
    )
    parser.add_argument(
        "--strategy-loss-diagnosis",
        action="store_true",
        help="Show a read-only loss diagnosis report for a strategy baseline.",
    )
    parser.add_argument(
        "--symbol-subset-stability-report",
        action="store_true",
        help="Show a read-only stability report for one symbol under one strategy variant.",
    )
    parser.add_argument(
        "--wider-period",
        action="store_true",
        help="Only with --symbol-subset-stability-report: replay the requested symbol across the wider stored historical bar period, research-only.",
    )
    parser.add_argument(
        "--collect-symbol-replay-evidence",
        action="store_true",
        help="Show a research-only WDC-style evidence plan for whether more replay evidence can be collected from existing stored bars.",
    )
    parser.add_argument(
        "--strategy-research-planner",
        action="store_true",
        help="Show a read-only planner that chooses the next research-only strategy experiment from the latest persisted diagnostics.",
    )
    parser.add_argument(
        "--strategy-portfolio-research-planner",
        action="store_true",
        help="Show a read-only planner that ranks portfolio-level strategy research priorities from persisted evidence.",
    )
    parser.add_argument(
        "--paper-candidate-decision-report",
        action="store_true",
        help="Show a read-only decision report for whether any strategy is currently allowed to paper trade.",
    )
    parser.add_argument(
        "--paper-canary-start",
        action="store_true",
        help="Manually activate operator-approved paper canary mode for a single strategy/profile/timeframe.",
    )
    parser.add_argument(
        "--paper-canary-status",
        action="store_true",
        help="Show the current paper canary activation state, limits, and recent activity.",
    )
    parser.add_argument(
        "--paper-candidate-audit",
        action="store_true",
        help="Run a read-only audit for a replay-only paper-candidate strategy variant without approving paper or enabling live.",
    )
    parser.add_argument(
        "--diagnose-next-best-strategy",
        action="store_true",
        help="Run the planner-selected research-only variant replay and linked diagnostics for the current next-best strategy/profile/timeframe.",
    )
    parser.add_argument(
        "--research-autopilot",
        action="store_true",
        help="Run a bounded research-only autopilot that executes only allowlisted next research commands and stops before any paper or live action.",
    )
    parser.add_argument(
        "--research-expansion-planner",
        action="store_true",
        help="Show a research-only planner for the next bounded expansion step when the current strategy set is exhausted or blocked.",
    )
    parser.add_argument(
        "--generate-new-strategy-family-research-only",
        action="store_true",
        help="Alias for --research-expansion-planner that persists one bounded research-only strategy family candidate.",
    )
    parser.add_argument(
        "--generated-candidate-state-report",
        action="store_true",
        help="Show a read-only trace of persisted generated research candidates and whether the portfolio planner currently treats them as actionable.",
    )
    parser.add_argument(
        "--signal-generation-diagnosis",
        action="store_true",
        help="Diagnose research-only signal-generation blockers and propose safe bounded follow-up commands without changing paper/live state.",
    )
    parser.add_argument(
        "--optimise-or-precompute-replay-dataset",
        action="store_true",
        help="Prepare bounded research-only replay dataset coverage and runtime blocker summaries without changing paper/live state.",
    )
    parser.add_argument(
        "--prepare-replay-dataset",
        action="store_true",
        help="Alias for --optimise-or-precompute-replay-dataset.",
    )
    parser.add_argument(
        "--precompute-bounded-dip-rebound-15min-outcomes",
        action="store_true",
        help="Precompute bounded research-only replay outcomes for crypto_research.dip_rebound/dip_rebound/15Min.",
    )
    parser.add_argument(
        "--precompute-specific-replay-cache",
        action="store_true",
        help="Precompute bounded research-only replay outcomes for one exact strategy/profile/timeframe target.",
    )
    parser.add_argument(
        "--execute-next-research-step",
        action="store_true",
        help="Only with --strategy-research-planner: execute the selected next research-only step when a matching safe research command already exists.",
    )
    parser.add_argument(
        "--proposal-pipeline-diagnostics",
        action="store_true",
        help="Run a read-only report explaining where execution-allowed strategies are getting filtered out.",
    )
    parser.add_argument(
        "--proposal-suppression-funnel",
        action="store_true",
        help="Run a read-only report for the latest heartbeat and real research cycle proposal suppression funnel.",
    )
    parser.add_argument(
        "--evidence-quality-report",
        action="store_true",
        help="Run a read-only report explaining why the latest real research cycle produced no replay-qualified paper candidates.",
    )
    parser.add_argument(
        "--outcome-recording-status",
        action="store_true",
        help="Run a read-only report showing how shadow/replay outcomes are recorded, whether matured checkpoints are being missed, and why research sample sizes remain low.",
    )
    parser.add_argument(
        "--historical-coverage-report",
        action="store_true",
        help="Run a read-only report showing historical equity bar coverage by symbol and timeframe for the replay windows used by research.",
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
        "--variant-id",
        type=str,
        default="",
        help="Optional variant id for research-only strategy diagnostics.",
    )
    parser.add_argument(
        "--symbol",
        type=str,
        default="",
        help="Optional symbol for symbol-level read-only research diagnostics.",
    )
    parser.add_argument(
        "--base-strategy",
        type=str,
        default="",
        help="Alias for --strategy-id on strategy-specific read-only reports.",
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
        "--operator-override",
        type=str,
        default="",
        help="Required explicit operator approval note for manual paper canary execution.",
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
        "--timeframes",
        type=str,
        default="",
        help="Comma-separated historical backfill timeframes, for example 15Min,1Hour,1Day.",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=0,
        help="Historical backfill lookback window in years for dedicated multi-timeframe equity backfills.",
    )
    parser.add_argument(
        "--symbols-from-strategies",
        action="store_true",
        help="Use the current equity strategy universe / discovery_equity_symbols for dedicated Alpaca equity backfill.",
    )
    parser.add_argument(
        "--backfill-from-start",
        action="store_true",
        help="For dedicated Alpaca equity backfill, request the full selected lookback window from the start instead of only resuming forward from the latest stored timestamp.",
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
        "--symbols",
        type=str,
        default="",
        help="Optional comma-separated symbol override for symbol-scoped maintenance commands such as crypto historical backfills.",
    )
    parser.add_argument(
        "--path",
        type=str,
        default="",
        help="Filesystem path for bulk CSV/parquet imports.",
    )
    parser.add_argument(
        "--max-replay-timestamps",
        type=int,
        default=0,
        help="Optional cap on historical timestamps processed in --replay mode. Use 0 for all eligible timestamps.",
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=3,
        help="Maximum research autopilot steps. Required to be greater than zero for --research-autopilot.",
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
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Only for supported research-only planning commands: execute the selected safe replay-only follow-up without creating paper or live trades.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Render structured JSON for supported read-only reports.",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show suppressed database diagnostics for operator-facing reports.",
    )
    return parser.parse_args()


def _print_operator_report(*, reporter_factory, args: argparse.Namespace) -> None:
    stderr_buffer = io.StringIO()
    stderr_target = sys.stderr if args.verbose else stderr_buffer
    with contextlib.redirect_stderr(stderr_target):
        reporter = reporter_factory()
        if args.json:
            print(
                json.dumps(
                    reporter.build_report(),
                    default=str,
                    indent=2,
                ),
                flush=True,
            )
        else:
            print(reporter.render(), flush=True)
    if not args.verbose and not args.json:
        diagnostics = [line for line in stderr_buffer.getvalue().splitlines() if str(line or "").strip()]
        if diagnostics:
            print(
                f"diagnostics_suppressed={len(diagnostics)} (rerun with --verbose for DB details)",
                flush=True,
            )


def main() -> None:
    args = parse_args()
    if args.base_strategy:
        args.strategy_id = args.base_strategy
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
        try:
            record = reporter.approve_paper(
                strategy_id=args.strategy_id,
                profile_id=args.profile_id,
                max_paper_notional_usd=args.max_paper_notional,
                max_open_trades=args.max_open_trades,
                cooldown_minutes=args.cooldown_minutes,
                confirmed=bool(args.confirm_promotion_approval),
            )
        except ValueError as exc:
            print(f"Strategy Promotion Approval Refused\nreason={str(exc)}", flush=True)
            return
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

    if args.run_strategy_variant_research:
        service = StrategyVariantResearchService()
        profile_id = args.profile_id or "snapback"
        result = service.run_research(
            base_strategy_id=args.strategy_id,
            profile_id=profile_id,
            timeframe=args.timeframe or "15Min",
        )
        if args.json:
            print(json.dumps(result, default=str, indent=2), flush=True)
        else:
            print(
                "Strategy Variant Research Run\n"
                f"candidate_id={result.get('candidate_id', '') or '-'}"
                f" | lifecycle_status={result.get('lifecycle_status', '') or '-'}\n"
                f"base_strategy={result.get('base_strategy_id', '-')}"
                f" | profile={result.get('profile_id', '-')}"
                f" | timeframe={result.get('timeframe', '-')}\n"
                f"baseline_variant_id={result.get('baseline_variant_id', '-')}"
                f" | variants_generated={int(result.get('variants_generated', 0) or 0)}"
                f" | variants_total_including_baseline={int(result.get('variants_total_including_baseline', 0) or 0)}\n"
                f"evaluations_persisted={len(list(result.get('evaluations', []) or []))}"
                f" | variants_evaluated={int(result.get('variants_evaluated', 0) or 0)}\n"
                f"symbols_processed={int(result.get('symbols_processed', 0) or 0)}"
                f" | bars_read={int(result.get('bars_read', 0) or 0)}"
                f" | baseline_sample_size={int(result.get('baseline_sample_size', 0) or 0)}\n"
                f"coverage_symbols_seen={int(result.get('coverage_symbols_seen', 0) or 0)}"
                f" | eligible_symbols_after_filters={int(result.get('eligible_symbols_after_filters', 0) or 0)}"
                f" | symbols_processed_for_strategy={int(result.get('symbols_processed_for_strategy', 0) or 0)}\n"
                f"zero_sample_reason={result.get('zero_sample_reason', '') or '-'}"
                f" | history_coverage_reason={result.get('history_coverage_reason', '') or '-'}\n"
                f"best_variant_id={result.get('best_variant_id', '-')}"
                f" | best_variant_sample_size={int(result.get('best_variant_sample_size', 0) or 0)}"
                f" | best_variant_net_return_after_costs={float(result.get('best_variant_net_return_after_costs', 0.0) or 0.0)}"
                f" | best_variant_win_rate={float(result.get('best_variant_win_rate', 0.0) or 0.0)}"
                f" | best_variant_drawdown={result.get('best_variant_drawdown', '') if result.get('best_variant_drawdown') is not None else '-'}\n"
                f"runtime_status={result.get('runtime_status', 'completed')}"
                f" | runtime_blocker={result.get('runtime_blocker', '') or '-'}\n"
                f"next_required_action={result.get('next_required_action', '') or '-'}\n"
                f"next_recommended_command={result.get('next_recommended_command', '') or '.venv-mac/bin/python main.py --strategy-portfolio-research-planner'}\n"
                "Research-only. No paper or live approval has been changed.",
                flush=True,
            )
        return

    if args.strategy_variant_research_report:
        reporter = StrategyVariantResearchReport()
        profile_id = args.profile_id or "snapback"
        if args.json:
            print(
                json.dumps(
                    reporter.build_report(
                        base_strategy_id=args.strategy_id,
                        profile_id=profile_id,
                        timeframe=args.timeframe or "15Min",
                    ),
                    default=str,
                    indent=2,
                ),
                flush=True,
            )
        else:
            print(
                reporter.render(
                    base_strategy_id=args.strategy_id,
                    profile_id=profile_id,
                    timeframe=args.timeframe or "15Min",
                ),
                flush=True,
            )
        return

    if args.strategy_variant_diagnostics:
        reporter = StrategyVariantDiagnosticsReport()
        profile_id = args.profile_id or "snapback"
        if args.json:
            print(
                json.dumps(
                    reporter.build_report(
                        base_strategy_id=args.strategy_id,
                        profile_id=profile_id,
                        timeframe=args.timeframe or "15Min",
                    ),
                    default=str,
                    indent=2,
                ),
                flush=True,
            )
        else:
            print(
                reporter.render(
                    base_strategy_id=args.strategy_id,
                    profile_id=profile_id,
                    timeframe=args.timeframe or "15Min",
                ),
                flush=True,
            )
        return

    if args.strategy_loss_diagnosis:
        reporter = StrategyLossDiagnosisReport()
        profile_id = args.profile_id or "snapback"
        if args.json:
            print(
                json.dumps(
                    reporter.build_report(
                        base_strategy_id=args.strategy_id,
                        profile_id=profile_id,
                        timeframe=args.timeframe or "15Min",
                        variant_id=args.variant_id or None,
                    ),
                    default=str,
                    indent=2,
                ),
                flush=True,
            )
        else:
            print(
                reporter.render(
                    base_strategy_id=args.strategy_id,
                    profile_id=profile_id,
                    timeframe=args.timeframe or "15Min",
                    variant_id=args.variant_id or None,
                ),
                flush=True,
            )
        return

    if args.paper_candidate_audit:
        reporter = PaperCandidateAuditReport()
        profile_id = args.profile_id or "snapback"
        if args.json:
            print(
                json.dumps(
                    reporter.build_report(
                        base_strategy_id=args.strategy_id,
                        profile_id=profile_id,
                        timeframe=args.timeframe or "15Min",
                        variant_id=args.variant_id or None,
                    ),
                    default=str,
                    indent=2,
                ),
                flush=True,
            )
        else:
            print(
                reporter.render(
                    base_strategy_id=args.strategy_id,
                    profile_id=profile_id,
                    timeframe=args.timeframe or "15Min",
                    variant_id=args.variant_id or None,
                ),
                flush=True,
            )
        return

    if args.paper_candidate_decision_report:
        _print_operator_report(
            reporter_factory=PaperCandidateDecisionReport,
            args=args,
        )
        return

    if args.paper_canary_start:
        reporter = PaperCanaryReport()
        state = reporter.start(
            strategy_id=args.strategy_id,
            profile_id=args.profile_id or "snapback",
            timeframe=args.timeframe or "1Hour",
            operator_override=args.operator_override,
        )
        if args.json:
            print(json.dumps(state, default=str, indent=2), flush=True)
        else:
            print(reporter.render(report=reporter.build_report()), flush=True)
        return

    if args.paper_canary_status:
        reporter = PaperCanaryReport()
        if args.json:
            print(json.dumps(reporter.build_report(), default=str, indent=2), flush=True)
        else:
            print(reporter.render(), flush=True)
        return

    if args.symbol_subset_stability_report:
        reporter = SymbolSubsetStabilityReport()
        profile_id = args.profile_id or "snapback"
        if args.json:
            print(
                json.dumps(
                    reporter.build_report(
                        base_strategy_id=args.strategy_id,
                        profile_id=profile_id,
                        timeframe=args.timeframe or "15Min",
                        variant_id=args.variant_id,
                        symbol=args.symbol,
                        wider_period=bool(args.wider_period),
                    ),
                    default=str,
                    indent=2,
                ),
                flush=True,
            )
        else:
            print(
                reporter.render(
                    base_strategy_id=args.strategy_id,
                    profile_id=profile_id,
                    timeframe=args.timeframe or "15Min",
                    variant_id=args.variant_id,
                    symbol=args.symbol,
                    wider_period=bool(args.wider_period),
                ),
                flush=True,
            )
        return

    if args.collect_symbol_replay_evidence:
        reporter = SymbolReplayEvidencePlanReport()
        profile_id = args.profile_id or "snapback"
        auto_execute = True if not args.dry_run else False
        if args.json:
            print(
                json.dumps(
                    reporter.build_report(
                        base_strategy_id=args.strategy_id,
                        profile_id=profile_id,
                        timeframe=args.timeframe or "15Min",
                        variant_id=args.variant_id,
                        symbol=args.symbol,
                        execute=bool(args.execute) or auto_execute,
                    ),
                    default=str,
                    indent=2,
                ),
                flush=True,
            )
        else:
            print(
                reporter.render(
                    base_strategy_id=args.strategy_id,
                    profile_id=profile_id,
                    timeframe=args.timeframe or "15Min",
                    variant_id=args.variant_id,
                    symbol=args.symbol,
                    execute=bool(args.execute) or auto_execute,
                ),
                flush=True,
            )
        return

    if args.strategy_research_planner:
        reporter = StrategyResearchPlannerReport()
        profile_id = args.profile_id or "snapback"
        if args.json:
            print(
                json.dumps(
                    reporter.build_report(
                        base_strategy_id=args.strategy_id,
                        profile_id=profile_id,
                        timeframe=args.timeframe or "15Min",
                        execute_next_research_step=bool(args.execute_next_research_step),
                    ),
                    default=str,
                    indent=2,
                ),
                flush=True,
            )
        else:
            print(
                reporter.render(
                    base_strategy_id=args.strategy_id,
                    profile_id=profile_id,
                    timeframe=args.timeframe or "15Min",
                    execute_next_research_step=bool(args.execute_next_research_step),
                ),
                flush=True,
            )
        return

    if args.diagnose_next_best_strategy:
        reporter = StrategyPortfolioResearchPlannerReport()
        result = reporter.run_selected_strategy_diagnostics(
            base_strategy_id=args.strategy_id,
            profile_id=args.profile_id,
            timeframe=args.timeframe,
        )
        if args.json:
            print(json.dumps(result, default=str, indent=2), flush=True)
        else:
            before = dict(result.get("before", {}) or {})
            after = dict(result.get("after", {}) or {})
            selected = dict(result.get("selected_next_strategy", {}) or {})
            planner_after = dict(result.get("planner_after", {}) or {})
            summary = dict(result.get("diagnosis_summary", {}) or {})
            print(
                "Selected Strategy Diagnostics\n"
                f"base_strategy={selected.get('base_strategy_id', '-')}"
                f" | profile={selected.get('profile_id', '-')}"
                f" | timeframe={selected.get('timeframe', '-')}\n"
                f"before_sample_size={before.get('sample_size', 0)}"
                f" | after_sample_size={after.get('sample_size', 0)}"
                f" | before_net_return_after_costs={before.get('net_return_after_costs', 0.0)}"
                f" | after_net_return_after_costs={after.get('net_return_after_costs', 0.0)}\n"
                f"before_recommendation={before.get('strategy_planner_recommendation', '-')}"
                f" | after_recommendation={after.get('strategy_planner_recommendation', '-')}\n"
                f"sample_size={summary.get('sample_size', after.get('sample_size', 0))}"
                f" | net_return_after_costs={summary.get('net_return_after_costs', after.get('net_return_after_costs', 0.0))}"
                f" | win_rate={summary.get('win_rate', after.get('win_rate', 0.0))}"
                f" | drawdown={summary.get('drawdown', after.get('drawdown', '-'))}\n"
                f"diagnosis_verdict={summary.get('diagnosis_verdict', '-')}"
                f" | planner_recommendation={summary.get('planner_recommendation', '-')}"
                f" | next_required_action={summary.get('next_required_action', '-')}\n"
                f"next_recommended_command={summary.get('next_recommended_command', '-')}\n"
                f"paper_candidate_path={summary.get('paper_candidate_path', '-')}"
                f" | can_become_paper_candidate={summary.get('can_become_paper_candidate', '-')}\n"
                f"planner_next_portfolio_action={planner_after.get('next_portfolio_action', '-')}"
                f" | planner_selected_next_experiment_type={planner_after.get('selected_next_experiment_type', '-')}\n"
                "Research-only. No paper or live approval has been changed.",
                flush=True,
            )
        return

    if args.research_autopilot:
        runner = ResearchAutopilotRunner()
        report = runner.run(max_steps=args.max_steps)
        if args.json:
            print(json.dumps(report, default=str, indent=2), flush=True)
        else:
            print(runner.render(report=report), flush=True)
        return

    if args.research_expansion_planner or args.generate_new_strategy_family_research_only:
        _print_operator_report(
            reporter_factory=ResearchExpansionPlannerReport,
            args=args,
        )
        return

    if args.generated_candidate_state_report:
        _print_operator_report(
            reporter_factory=GeneratedCandidateStateReport,
            args=args,
        )
        return

    if args.signal_generation_diagnosis:
        _print_operator_report(
            reporter_factory=SignalGenerationDiagnosisReport,
            args=args,
        )
        return

    if args.optimise_or_precompute_replay_dataset or args.prepare_replay_dataset:
        _print_operator_report(
            reporter_factory=ReplayDatasetPreparationReport,
            args=args,
        )
        return

    if args.precompute_bounded_dip_rebound_15min_outcomes:
        _print_operator_report(
            reporter_factory=BoundedDipReboundPrecomputeReport,
            args=args,
        )
        return

    if args.precompute_specific_replay_cache:
        reporter = SpecificReplayCachePrecomputeReport(
            base_strategy_id=args.strategy_id or "mean_reversion.snapback",
            profile_id=args.profile_id or "snapback",
            timeframe=args.timeframe or "15Min",
        )
        if args.json:
            print(json.dumps(reporter.build_report(), default=str, indent=2), flush=True)
        else:
            print(reporter.render(), flush=True)
        return

    if args.strategy_portfolio_research_planner:
        _print_operator_report(
            reporter_factory=StrategyPortfolioResearchPlannerReport,
            args=args,
        )
        return

    if args.proposal_pipeline_diagnostics:
        reporter = ProposalPipelineDiagnosticsReport()
        print(reporter.render(), flush=True)
        return

    if args.proposal_suppression_funnel:
        reporter = ProposalSuppressionFunnelReport()
        if args.json:
            print(json.dumps(reporter.build_report(), sort_keys=True, default=str), flush=True)
            return
        print(reporter.render(), flush=True)
        return

    if args.evidence_quality_report:
        reporter = EvidenceQualityReport()
        if args.json:
            print(json.dumps(reporter.build_report(lookback_hours=24), sort_keys=True, default=str), flush=True)
            return
        print(reporter.render(report=reporter.build_report(lookback_hours=24)), flush=True)
        return

    if args.outcome_recording_status:
        reporter = OutcomeRecordingStatusReport()
        if args.json:
            print(json.dumps(reporter.build_report(lookback_hours=24), sort_keys=True, default=str), flush=True)
            return
        print(reporter.render(report=reporter.build_report(lookback_hours=24)), flush=True)
        return

    if args.historical_coverage_report:
        reporter = HistoricalCoverageReport()
        if args.json:
            print(json.dumps(reporter.build_report(), sort_keys=True, default=str), flush=True)
            return
        print(reporter.render(report=reporter.build_report()), flush=True)
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

    if args.backfill_alpaca_equity_bars:
        runner = HistoricalBackfillRunner()
        runner.run_equity_timeframe_backfill(
            years=args.years if args.years > 0 else 1,
            timeframes=_parse_csv_argument(args.timeframes) or (args.timeframe or "15Min",),
            symbols_from_strategies=bool(args.symbols_from_strategies),
            dry_run=bool(args.dry_run),
            backfill_from_start=bool(args.backfill_from_start),
        )
        return

    if args.backfill_or_resample_crypto_1day_bars:
        runner = HistoricalBackfillRunner()
        runner.run_crypto_1day_backfill_or_resample()
        return

    if args.backfill_or_resample_crypto_15min_bars:
        runner = HistoricalBackfillRunner()
        crypto_symbols = _parse_csv_argument(args.crypto_symbols or args.symbols)
        runner.run_crypto_15min_backfill_or_resample(
            days=args.days if args.days > 0 else None,
            crypto_symbols=crypto_symbols,
        )
        return

    if args.import_crypto_15min_bars:
        if not args.path.strip():
            raise ValueError("--import-crypto-15min-bars requires --path")
        runner = HistoricalBackfillRunner()
        runner.run_crypto_15min_bulk_import(path=args.path)
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

    if args.research_cycle_last_comparison:
        print(ResearchCycleLastComparisonReport().render(), flush=True)
        return

    if args.research_cycle_last_launchd_comparison:
        print(ResearchCycleLastComparisonReport(launchd_only=True).render(), flush=True)
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

    if args.self_improvement_status:
        reporter = SelfImprovementStatusReport()
        if args.json:
            print(json.dumps(reporter.build_report(), sort_keys=True, default=str), flush=True)
            return
        print(reporter.render(), flush=True)
        return

    if args.attention_alerts_reconcile:
        reporter = AttentionAlertsReconcileReport()
        if args.json:
            print(json.dumps(reporter.reconcile(), sort_keys=True, default=str), flush=True)
            return
        print(reporter.render(), flush=True)
        return

    if args.operator_summary:
        reporter = OperatorSummaryReport()
        if args.json:
            print(json.dumps(reporter.build_report(), sort_keys=True, default=str), flush=True)
            return
        if args.operator_summary_format == "slack":
            print(reporter.render_slack(), flush=True)
            return
        if args.operator_summary_format == "email":
            print(reporter.render_email(), flush=True)
            return
        print(reporter.render(), flush=True)
        return

    if args.send_operator_summary_email:
        config = load_runtime_config()
        reporter = OperatorSummaryReport(config=config)
        client = SmtpEmailClient(
            host=config.smtp_host,
            port=config.smtp_port,
            username=config.smtp_user,
            password=config.smtp_pass,
            use_ssl=config.smtp_use_ssl,
            timeout_seconds=config.smtp_timeout_seconds,
        )
        client.send_message(
            subject=reporter.email_subject(),
            body=reporter.render_email(),
            from_address=config.smtp_from,
            to_addresses=config.smtp_to,
        )
        print(
            "operator_summary_email_sent="
            f"{','.join(config.smtp_to) if config.smtp_to else '-'}",
            flush=True,
        )
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
    if args.heartbeat_service:
        runner = ControlPipelineRunner(
            config=config,
            process_mode="heartbeat_service",
            command_source="main.py --heartbeat-service",
        )
        max_ticks = None if args.max_ticks <= 0 else args.max_ticks
        runner.run_heartbeat_service_loop(
            interval_seconds=max(1, args.interval_seconds),
            max_ticks=max_ticks,
        )
        return

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


def _run_heartbeat_autonomous_learning_once(*, force_research_cycle: bool = False) -> str:
    config = load_runtime_config()
    ledger = UsageLedger(config=config)
    runner = ControlPipelineRunner(
        config=config,
        usage_ledger=ledger,
        process_mode="control_heartbeat_once",
        command_source="main.py --heartbeat-autonomous-learning-once",
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
