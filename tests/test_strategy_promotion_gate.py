from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest

from app.heartbeat import support
from app.framework.runtime.models import TickContext


class _FakeUsageLedger:
    def __init__(
        self,
        promotion: dict[str, object] | None = None,
        *,
        fitness_summary: dict[str, object] | None = None,
    ) -> None:
        self._promotion = promotion
        self._orders: list[dict[str, object]] = []
        self.recorded_evaluations: list[dict[str, object]] = []
        self.approval_calls: list[dict[str, object]] = []
        self.resolve_calls: list[dict[str, object]] = []
        self._fitness_summary = fitness_summary

    def get_strategy_promotion(self, *, strategy_id: str, profile_id: str) -> dict[str, object] | None:
        if not self._promotion:
            return None
        if (
            self._promotion.get("strategy_id") == strategy_id
            and self._promotion.get("profile_id") == profile_id
        ):
            return self._promotion
        return None

    def list_recent_paper_trade_orders(self, *, limit: int = 250) -> list[dict[str, object]]:
        return list(self._orders[:limit])

    def record_strategy_promotion_evaluation(self, **kwargs: object) -> None:
        self.recorded_evaluations.append(dict(kwargs))

    def approve_strategy_for_paper(self, **kwargs: object) -> None:
        self.approval_calls.append(dict(kwargs))
        self._promotion = {
            "strategy_id": str(kwargs.get("strategy_id", "")),
            "profile_id": str(kwargs.get("profile_id", "")),
            "stage": "paper_approved",
            "paper_approved": 1,
            "live_approved": 0,
            "paper_execution_profile": 1,
            "research_only_profile": 1 if kwargs.get("research_only_profile") else 0,
            "max_paper_notional_usd": float(kwargs.get("max_paper_notional_usd", 0.0) or 0.0),
            "max_open_trades": int(kwargs.get("max_open_trades", 0) or 0),
            "cooldown_minutes": int(kwargs.get("cooldown_minutes", 0) or 0),
            "rejected": 0,
        }

    def resolve_attention_alerts_for_approval_request(self, **kwargs: object) -> None:
        self.resolve_calls.append(dict(kwargs))

    def get_latest_strategy_fitness_summary(self, *, strategy_id: str, profile_id: str):
        _ = (strategy_id, profile_id)
        return self._fitness_summary if self._fitness_summary is not None else {
            "composite_fitness_score": 0.75,
            "avg_realized_return_pct": 0.22,
            "win_rate": 0.63,
            "evaluated_proposals": 12,
            "avg_max_adverse_excursion_pct": -0.08,
            "checkpoint_code": "paper_sim_ok",
            "captured_at": datetime.now().astimezone(),
        }


class StrategyPromotionGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._original_get_execution_adapter = support.get_execution_adapter

        class _FakeAdapter:
            def validate_entry_constraints(self, **_kwargs):
                return None

            def build_entry_order_request(self, **_kwargs):
                return {"symbol": "AAPL", "side": "buy"}

        support.get_execution_adapter = lambda *_args, **_kwargs: _FakeAdapter()

    def tearDown(self) -> None:
        support.get_execution_adapter = self._original_get_execution_adapter

    def test_record_research_evidence_preserves_internal_safe_stage(self) -> None:
        from app.framework.reporting.promotion_gate import PromotionGateReport

        ledger = _FakeUsageLedger()
        reporter = PromotionGateReport(
            config=SimpleNamespace(
                include_backtest_evidence_in_paper_fitness=False,
                include_backtest_evidence_in_live_fitness=False,
                strategy_allocation_min_checkpoints=5,
                strategy_allocation_suppress_threshold=0.1,
            ),
            usage_ledger=ledger,
        )
        reporter.record_research_evidence(
            strategy_id="crypto_pullback.downside_continuation_watch",
            profile_id="downside_continuation_watch",
            recommendation="paper_sim_candidate",
            blocker_reasons=[],
            replay_summary={"classification": "paper_sim_candidate"},
            paper_sim_summary={"sample_size": 0},
            data_integrity={"status": "pass", "failure_reasons": []},
            research_only_profile=True,
        )

        self.assertEqual(ledger.recorded_evaluations[-1]["stage"], "paper_sim_candidate")

    def test_evaluate_marks_paper_removal_candidate_without_auto_unapproving(self) -> None:
        from app.framework.reporting.promotion_gate import PromotionGateReport

        ledger = _FakeUsageLedger(
            {
                "strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "stage": "paper_approved",
                "paper_approved": 1,
                "live_approved": 0,
                "paper_execution_profile": 1,
                "research_only_profile": 0,
                "max_paper_notional_usd": 10.0,
                "max_open_trades": 1,
                "cooldown_minutes": 30,
                "rejected": 0,
            }
        )
        reporter = PromotionGateReport(
            config=SimpleNamespace(
                include_backtest_evidence_in_paper_fitness=False,
                include_backtest_evidence_in_live_fitness=False,
                strategy_allocation_min_checkpoints=5,
                strategy_allocation_suppress_threshold=0.1,
            ),
            usage_ledger=ledger,
        )
        reporter._resolve_profile = lambda **_kwargs: SimpleNamespace(
            strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            parameters={},
        )
        reporter._latest_research_entry = lambda **_kwargs: {
            "classification": "research_only",
            "promotion_recommendation": "research_only",
            "net_performance_pct": 0.0,
            "net_win_rate": 0.0,
            "proposal_count": 3,
            "replay_windows_with_data": 1,
            "replay_windows_required": 4,
        }
        reporter._diagnostic_strategy = lambda **_kwargs: {"paper_execution_allowed": True}

        import app.framework.reporting.research_status as research_status_module
        import app.framework.reporting.proposal_pipeline_diagnostics as diagnostics_module

        original_research = research_status_module.ResearchStatusReport
        original_diag = diagnostics_module.ProposalPipelineDiagnosticsReport
        research_status_module.ResearchStatusReport = lambda **_kwargs: SimpleNamespace(
            build_report=lambda: {}
        )
        diagnostics_module.ProposalPipelineDiagnosticsReport = lambda **_kwargs: SimpleNamespace(
            build_report=lambda: {"proposal_data_integrity": {"status": "pass", "failure_reasons": []}}
        )
        try:
            report = reporter.evaluate(strategy_id="mean_reversion.snapback", profile_id="snapback")
        finally:
            research_status_module.ResearchStatusReport = original_research
            diagnostics_module.ProposalPipelineDiagnosticsReport = original_diag

        self.assertEqual(report["current_stage"], "paper_removal_candidate")
        self.assertEqual(report["recommendation"], "manual_paper_removal_review")
        self.assertIn("manual_paper_removal_required", report["blocker_reasons"])
        self.assertEqual(ledger.recorded_evaluations[-1]["stage"], "paper_removal_candidate")

    def _context(self, ledger: _FakeUsageLedger) -> TickContext:
        return TickContext(
            tick_id="20260606-120000",
            started_at=datetime.now().astimezone(),
            config=SimpleNamespace(
                paper_execution_equity_broker_id="alpaca_paper",
                paper_execution_crypto_broker_id="alpaca_paper",
                paper_execution_equity_only=False,
                paper_execution_require_market_open=False,
                paper_execution_min_projected_gain_pct=0.01,
                paper_execution_crypto_min_projected_gain_pct=0.01,
                paper_execution_limit_buffer_bps=5.0,
                paper_execution_crypto_limit_buffer_bps=25.0,
                paper_execution_default_notional_usd=10.0,
                trading212_paper_execution_default_notional_gbp=5.0,
            ),
            usage_ledger=ledger,
            state={},
        )

    def _proposal(self) -> dict[str, object]:
        return {
            "proposal_id": "p1",
            "strategy_id": "mean_reversion.snapback",
            "strategy_family": "mean_reversion",
            "profile_id": "snapback",
            "source": "alpaca_equity_data",
            "symbol": "AAPL",
            "asset_class": "equity",
            "direction": "long",
            "entry_price": 100.0,
            "stop_loss_price": 99.0,
            "target_price": 102.0,
        }

    def test_requires_manual_paper_promotion(self) -> None:
        approval, rejection = support._build_paper_trade_approval(
            context=self._context(_FakeUsageLedger()),
            proposal=self._proposal(),
            tick_id="20260606-120000",
            config=self._context(_FakeUsageLedger()).config,
            market_gate={},
            position_symbols=set(),
            open_order_symbols=set(),
            broker_id="alpaca_paper",
        )

        self.assertIsNone(approval)
        self.assertEqual(rejection["reason"], "paper_promotion_required")

    def test_respects_manual_cooldown_and_notional_caps(self) -> None:
        ledger = _FakeUsageLedger(
            {
                "strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "stage": "paper_approved",
                "paper_approved": 1,
                "live_approved": 0,
                "paper_execution_profile": 1,
                "research_only_profile": 0,
                "max_paper_notional_usd": 10.0,
                "max_open_trades": 3,
                "cooldown_minutes": 30,
            }
        )
        ledger._orders.append(
            {
                "strategy_id": "mean_reversion.snapback",
                "profile_id": "snapback",
                "broker_id": "alpaca_paper",
                "status": "filled",
                "side": "buy",
                "submitted_at": (datetime.now().astimezone() - timedelta(minutes=5)).isoformat(),
            }
        )
        context = self._context(ledger)
        approval, rejection = support._build_paper_trade_approval(
            context=context,
            proposal=self._proposal(),
            tick_id="20260606-120000",
            config=context.config,
            market_gate={},
            position_symbols=set(),
            open_order_symbols=set(),
            broker_id="alpaca_paper",
        )

        self.assertIsNone(approval)
        self.assertEqual(rejection["reason"], "promotion_cooldown_active")

    def _promotion_reporter(self, ledger: _FakeUsageLedger):
        from app.framework.reporting.promotion_gate import PromotionGateReport

        reporter = PromotionGateReport(
            config=SimpleNamespace(
                include_backtest_evidence_in_paper_fitness=False,
                include_backtest_evidence_in_live_fitness=False,
                strategy_allocation_min_checkpoints=5,
                strategy_allocation_suppress_threshold=0.1,
            ),
            usage_ledger=ledger,
        )
        reporter._resolve_profile = lambda **_kwargs: SimpleNamespace(
            strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            parameters={},
        )
        return reporter

    def test_approve_paper_refuses_research_only(self) -> None:
        reporter = self._promotion_reporter(_FakeUsageLedger())
        reporter.evaluate = lambda **_kwargs: {
            "current_stage": "research_only",
            "recommendation": "hold_research_only",
            "blocker_reasons": [],
        }

        with self.assertRaisesRegex(ValueError, "approval_refused_stage_research_only"):
            reporter.approve_paper(
                strategy_id="mean_reversion.snapback",
                profile_id="snapback",
                max_paper_notional_usd=10.0,
                max_open_trades=1,
                cooldown_minutes=60,
                confirmed=True,
            )

    def test_approve_paper_refuses_rejected(self) -> None:
        reporter = self._promotion_reporter(_FakeUsageLedger())
        reporter.evaluate = lambda **_kwargs: {
            "current_stage": "rejected",
            "recommendation": "manually_rejected",
            "blocker_reasons": ["manually_rejected"],
        }

        with self.assertRaisesRegex(ValueError, "approval_refused_stage_rejected"):
            reporter.approve_paper(
                strategy_id="mean_reversion.snapback",
                profile_id="snapback",
                max_paper_notional_usd=10.0,
                max_open_trades=1,
                cooldown_minutes=60,
                confirmed=True,
            )

    def test_approve_paper_refuses_oversized_notional(self) -> None:
        reporter = self._promotion_reporter(_FakeUsageLedger())
        reporter.evaluate = lambda **_kwargs: {
            "current_stage": "paper_candidate",
            "recommendation": "manual_paper_review",
            "blocker_reasons": [],
        }

        with self.assertRaisesRegex(ValueError, "approval_refused_notional_cap"):
            reporter.approve_paper(
                strategy_id="mean_reversion.snapback",
                profile_id="snapback",
                max_paper_notional_usd=10.01,
                max_open_trades=1,
                cooldown_minutes=60,
                confirmed=True,
            )

    def test_approve_paper_refuses_open_trade_cap_above_one(self) -> None:
        reporter = self._promotion_reporter(_FakeUsageLedger())
        reporter.evaluate = lambda **_kwargs: {
            "current_stage": "paper_candidate",
            "recommendation": "manual_paper_review",
            "blocker_reasons": [],
        }

        with self.assertRaisesRegex(ValueError, "approval_refused_open_trade_cap"):
            reporter.approve_paper(
                strategy_id="mean_reversion.snapback",
                profile_id="snapback",
                max_paper_notional_usd=10.0,
                max_open_trades=2,
                cooldown_minutes=60,
                confirmed=True,
            )

    def test_approve_paper_refuses_cooldown_below_sixty(self) -> None:
        reporter = self._promotion_reporter(_FakeUsageLedger())
        reporter.evaluate = lambda **_kwargs: {
            "current_stage": "paper_candidate",
            "recommendation": "manual_paper_review",
            "blocker_reasons": [],
        }

        with self.assertRaisesRegex(ValueError, "approval_refused_cooldown_too_low"):
            reporter.approve_paper(
                strategy_id="mean_reversion.snapback",
                profile_id="snapback",
                max_paper_notional_usd=10.0,
                max_open_trades=1,
                cooldown_minutes=59,
                confirmed=True,
            )

    def test_approve_paper_accepts_paper_candidate_with_safe_caps(self) -> None:
        ledger = _FakeUsageLedger()
        reporter = self._promotion_reporter(ledger)
        reporter.evaluate = lambda **_kwargs: {
            "current_stage": "paper_candidate",
            "recommendation": "manual_paper_review",
            "blocker_reasons": [],
        }

        record = reporter.approve_paper(
            strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            max_paper_notional_usd=10.0,
            max_open_trades=1,
            cooldown_minutes=60,
            confirmed=True,
        )

        self.assertEqual(record["stage"], "paper_approved")
        self.assertEqual(len(ledger.approval_calls), 1)
        self.assertEqual(ledger.approval_calls[0]["max_paper_notional_usd"], 10.0)
        self.assertEqual(ledger.approval_calls[0]["max_open_trades"], 1)
        self.assertEqual(ledger.approval_calls[0]["cooldown_minutes"], 60)
        self.assertEqual(ledger.resolve_calls[0]["status"], "resolved")

    def test_approve_paper_does_not_affect_live_approval(self) -> None:
        ledger = _FakeUsageLedger()
        reporter = self._promotion_reporter(ledger)
        reporter.evaluate = lambda **_kwargs: {
            "current_stage": "paper_sim_active",
            "recommendation": "continue_paper_sim",
            "blocker_reasons": [],
        }

        record = reporter.approve_paper(
            strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            max_paper_notional_usd=10.0,
            max_open_trades=1,
            cooldown_minutes=60,
            confirmed=True,
        )

        self.assertFalse(bool(record.get("live_approved")))

    def test_replay_qualified_candidate_can_become_paper_candidate_and_remains_manual(self) -> None:
        from app.framework.reporting.promotion_gate import PromotionGateReport
        import app.framework.reporting.research_status as research_status_module
        import app.framework.reporting.proposal_pipeline_diagnostics as diagnostics_module

        ledger = _FakeUsageLedger(
            fitness_summary={
                "composite_fitness_score": 0.0,
                "avg_realized_return_pct": 0.0,
                "win_rate": 0.0,
                "evaluated_proposals": 0,
                "avg_max_adverse_excursion_pct": 0.0,
                "checkpoint_code": "",
                "captured_at": datetime.now().astimezone(),
            }
        )
        reporter = PromotionGateReport(
            config=SimpleNamespace(
                include_backtest_evidence_in_paper_fitness=False,
                include_backtest_evidence_in_live_fitness=False,
                strategy_allocation_min_checkpoints=5,
                strategy_allocation_suppress_threshold=0.1,
            ),
            usage_ledger=ledger,
        )
        reporter._resolve_profile = lambda **_kwargs: SimpleNamespace(
            strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            parameters={},
        )
        reporter._diagnostic_strategy = lambda **_kwargs: {"paper_execution_allowed": True}
        reporter._latest_research_entry = lambda **_kwargs: {
            "classification": "paper_sim_candidate",
            "promotion_recommendation": "paper_sim_candidate",
            "net_performance_pct": 0.22,
            "net_win_rate": 0.63,
            "proposal_count": 55,
            "replay_windows_with_data": 4,
            "replay_windows_required": 4,
            "paper_blocker_reasons": [],
            "paper_policy_notes": ["paper_allocation_excludes_backtest_evidence"],
            "live_blocker_reasons": ["live_allocation_excludes_backtest_evidence"],
            "allocation_includes_backtest_evidence": {"paper": False, "live": False},
        }
        original_research = research_status_module.ResearchStatusReport
        original_diag = diagnostics_module.ProposalPipelineDiagnosticsReport
        research_status_module.ResearchStatusReport = lambda **_kwargs: SimpleNamespace(build_report=lambda: {})
        diagnostics_module.ProposalPipelineDiagnosticsReport = lambda **_kwargs: SimpleNamespace(
            build_report=lambda: {"proposal_data_integrity": {"status": "pass", "failure_reasons": []}}
        )
        try:
            report = reporter.evaluate(strategy_id="mean_reversion.snapback", profile_id="snapback")
        finally:
            research_status_module.ResearchStatusReport = original_research
            diagnostics_module.ProposalPipelineDiagnosticsReport = original_diag

        self.assertEqual(report["current_stage"], "paper_candidate")
        self.assertTrue(report["paper_stage_eligible"])
        self.assertFalse(report["live_stage_eligible"])
        self.assertNotIn("live_allocation_excludes_backtest_evidence", report["paper_blocker_reasons"])
        self.assertIn("paper_allocation_excludes_backtest_evidence", report["paper_policy_notes"])
        self.assertEqual(len(ledger.approval_calls), 0)

    def test_replay_only_candidate_cannot_become_live_candidate(self) -> None:
        from app.framework.reporting.promotion_gate import PromotionGateReport
        import app.framework.reporting.research_status as research_status_module
        import app.framework.reporting.proposal_pipeline_diagnostics as diagnostics_module

        ledger = _FakeUsageLedger(
            fitness_summary={
                "composite_fitness_score": 0.0,
                "avg_realized_return_pct": 0.0,
                "win_rate": 0.0,
                "evaluated_proposals": 0,
                "avg_max_adverse_excursion_pct": 0.0,
                "checkpoint_code": "",
                "captured_at": datetime.now().astimezone(),
            }
        )
        reporter = PromotionGateReport(
            config=SimpleNamespace(
                include_backtest_evidence_in_paper_fitness=True,
                include_backtest_evidence_in_live_fitness=False,
                strategy_allocation_min_checkpoints=5,
                strategy_allocation_suppress_threshold=0.1,
            ),
            usage_ledger=ledger,
        )
        reporter._resolve_profile = lambda **_kwargs: SimpleNamespace(
            strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            parameters={},
        )
        reporter._diagnostic_strategy = lambda **_kwargs: {"paper_execution_allowed": True}
        reporter._latest_research_entry = lambda **_kwargs: {
            "classification": "paper_sim_candidate",
            "promotion_recommendation": "paper_sim_candidate",
            "net_performance_pct": 0.22,
            "net_win_rate": 0.63,
            "proposal_count": 55,
            "replay_windows_with_data": 4,
            "replay_windows_required": 4,
            "paper_blocker_reasons": [],
            "live_blocker_reasons": ["live_allocation_excludes_backtest_evidence"],
            "allocation_includes_backtest_evidence": {"paper": True, "live": False},
        }
        original_research = research_status_module.ResearchStatusReport
        original_diag = diagnostics_module.ProposalPipelineDiagnosticsReport
        research_status_module.ResearchStatusReport = lambda **_kwargs: SimpleNamespace(build_report=lambda: {})
        diagnostics_module.ProposalPipelineDiagnosticsReport = lambda **_kwargs: SimpleNamespace(
            build_report=lambda: {"proposal_data_integrity": {"status": "pass", "failure_reasons": []}}
        )
        try:
            report = reporter.evaluate(strategy_id="mean_reversion.snapback", profile_id="snapback")
        finally:
            research_status_module.ResearchStatusReport = original_research
            diagnostics_module.ProposalPipelineDiagnosticsReport = original_diag

        self.assertEqual(report["current_stage"], "paper_candidate")
        self.assertNotEqual(report["current_stage"], "live_candidate")
        self.assertFalse(report["live_stage_eligible"])

    def test_live_allocation_exclusion_still_blocks_live_candidate(self) -> None:
        from app.framework.reporting.promotion_gate import PromotionGateReport
        import app.framework.reporting.research_status as research_status_module
        import app.framework.reporting.proposal_pipeline_diagnostics as diagnostics_module

        ledger = _FakeUsageLedger(
            fitness_summary={
                "composite_fitness_score": 0.0,
                "avg_realized_return_pct": 0.0,
                "win_rate": 0.0,
                "evaluated_proposals": 0,
                "avg_max_adverse_excursion_pct": 0.0,
                "checkpoint_code": "",
                "captured_at": datetime.now().astimezone(),
            }
        )
        reporter = PromotionGateReport(
            config=SimpleNamespace(
                include_backtest_evidence_in_paper_fitness=True,
                include_backtest_evidence_in_live_fitness=False,
                strategy_allocation_min_checkpoints=5,
                strategy_allocation_suppress_threshold=0.1,
            ),
            usage_ledger=ledger,
        )
        reporter._resolve_profile = lambda **_kwargs: SimpleNamespace(
            strategy_id="mean_reversion.snapback",
            profile_id="snapback",
            parameters={},
        )
        reporter._diagnostic_strategy = lambda **_kwargs: {"paper_execution_allowed": True}
        reporter._latest_research_entry = lambda **_kwargs: {
            "classification": "paper_sim_candidate",
            "promotion_recommendation": "paper_sim_candidate",
            "net_performance_pct": 0.22,
            "net_win_rate": 0.63,
            "proposal_count": 55,
            "replay_windows_with_data": 4,
            "replay_windows_required": 4,
            "paper_blocker_reasons": [],
            "live_blocker_reasons": ["live_allocation_excludes_backtest_evidence"],
            "allocation_includes_backtest_evidence": {"paper": True, "live": False},
        }
        original_research = research_status_module.ResearchStatusReport
        original_diag = diagnostics_module.ProposalPipelineDiagnosticsReport
        research_status_module.ResearchStatusReport = lambda **_kwargs: SimpleNamespace(build_report=lambda: {})
        diagnostics_module.ProposalPipelineDiagnosticsReport = lambda **_kwargs: SimpleNamespace(
            build_report=lambda: {"proposal_data_integrity": {"status": "pass", "failure_reasons": []}}
        )
        try:
            report = reporter.evaluate(strategy_id="mean_reversion.snapback", profile_id="snapback")
        finally:
            research_status_module.ResearchStatusReport = original_research
            diagnostics_module.ProposalPipelineDiagnosticsReport = original_diag

        self.assertIn("live_allocation_excludes_backtest_evidence", report["live_blocker_reasons"])
        self.assertFalse(report["live_stage_eligible"])


if __name__ == "__main__":
    unittest.main()
