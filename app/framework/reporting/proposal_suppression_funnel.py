from __future__ import annotations

from collections import Counter
from datetime import datetime
from math import inf
import sys
from time import monotonic
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class ProposalSuppressionFunnelReport:
    """Read-only report for why current proposals are fully suppressed."""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(
            config=self.config,
            read_only=True,
            skip_schema_bootstrap=True,
            query_timeout_ms=15_000,
            lock_timeout_ms=5_000,
        )

    def build_report(self) -> dict[str, Any]:
        build_started = monotonic()
        self._log_report_phase("build_report", "start")
        latest_heartbeat_row = self._latest_heartbeat_row()
        latest_real_cycle_row = self._latest_real_cycle_row()
        if latest_heartbeat_row is None and latest_real_cycle_row is None:
            result = {
                "status": "not_found",
                "reason": "No persisted heartbeat or real research cycle snapshot is available yet.",
            }
            self._log_report_phase(
                "build_report",
                "done",
                elapsed_ms=int((monotonic() - build_started) * 1000),
            )
            return result

        heartbeat = self._build_heartbeat_section(row=latest_heartbeat_row)
        research = self._build_research_section(row=latest_real_cycle_row)
        combined_counts = Counter()
        combined_category_counts = Counter()
        reason_category_counts: dict[str, Counter[str]] = {}
        combined_closest: list[dict[str, Any]] = []
        for item in heartbeat.get("suppressed_candidates", []) or []:
            combined_counts.update(item.get("blocker_reasons", []) or [])
            combined_category_counts.update(item.get("blocker_categories", []) or [])
            for reason in item.get("blocker_reasons", []) or []:
                reason_category_counts.setdefault(str(reason), Counter()).update(
                    item.get("blocker_categories", []) or []
                )
            combined_closest.append(item)
        for item in research.get("suppressed_candidates", []) or []:
            combined_counts.update(item.get("blocker_reasons", []) or [])
            combined_category_counts.update(item.get("blocker_categories", []) or [])
            for reason in item.get("blocker_reasons", []) or []:
                reason_category_counts.setdefault(str(reason), Counter()).update(
                    item.get("blocker_categories", []) or []
                )
            combined_closest.append(item)
        biggest_bottleneck = self._top_counter_entry(combined_counts, default="unknown")
        closest = sorted(
            combined_closest,
            key=lambda item: (
                float(item.get("distance_to_survive", inf) or inf),
                str(item.get("source", "")),
                str(item.get("strategy_id", "")),
                str(item.get("profile_id", "")),
                str(item.get("symbol", "")),
            ),
        )[:5]
        promotion = self._build_promotion_section(
            heartbeat=heartbeat,
            research=research,
            combined_category_counts=combined_category_counts,
        )
        result = {
            "status": "ok",
            "backend": self.usage_ledger.backend,
            "heartbeat": heartbeat,
            "research_cycle": research,
            "promotion_path": promotion,
            "top_5_closest_candidates": closest,
            "biggest_bottleneck": biggest_bottleneck,
            "biggest_bottleneck_category": self._biggest_bottleneck_category(
                biggest_bottleneck=biggest_bottleneck,
                reason_category_counts=reason_category_counts,
                combined_category_counts=combined_category_counts,
            ),
            "heartbeat_live_path_verdict": heartbeat.get("verdict", "mixed"),
            "research_replay_path_verdict": research.get("verdict", "mixed"),
            "paper_promotion_path_verdict": promotion.get("paper_verdict", "mixed"),
            "live_promotion_path_verdict": promotion.get("live_verdict", "mixed"),
            "promotion_path_verdict": promotion.get("paper_verdict", "mixed"),
            "verdict": self._overall_verdict(
                heartbeat_verdict=heartbeat.get("verdict", "mixed"),
                research_verdict=research.get("verdict", "mixed"),
                promotion_verdict=promotion.get("paper_verdict", "mixed"),
            ),
        }
        self._log_report_phase(
            "build_report",
            "done",
            elapsed_ms=int((monotonic() - build_started) * 1000),
        )
        return result

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        render_started = monotonic()
        self._log_report_phase("render", "start")
        report = report or self.build_report()
        if report.get("status") != "ok":
            rendered = (
                "Proposal Suppression Funnel\n"
                f"status={report.get('status', 'unknown')}\n"
                f"reason={report.get('reason', '-')}"
            )
            self._log_report_phase(
                "render",
                "done",
                elapsed_ms=int((monotonic() - render_started) * 1000),
            )
            return rendered

        heartbeat = report.get("heartbeat", {}) or {}
        research = report.get("research_cycle", {}) or {}
        lines = [
            "Proposal Suppression Funnel",
            f"backend={report.get('backend', '-')}",
            "",
            "Latest Real Heartbeat",
            (
                f"tick_id={heartbeat.get('tick_id', '-')}"
                f" | started_at={heartbeat.get('started_at', '-')}"
                f" | raw_signals={int(heartbeat.get('raw_signals_count', 0) or 0)}"
                f" | survived={int(heartbeat.get('surviving_signals_count', 0) or 0)}"
                f" | suppressed={int(heartbeat.get('suppressed_signals_count', 0) or 0)}"
                f" | raw_proposals={int(heartbeat.get('raw_proposals_count', 0) or 0)}"
                f" | created_proposals={int(heartbeat.get('created_proposals_count', 0) or 0)}"
                f" | stage={heartbeat.get('primary_stage', '-')}"
            ),
            (
                f"gate_rejections=allocation:{int(heartbeat.get('allocation_rejected_count', 0) or 0)}"
                f" | proposal_build:{int(heartbeat.get('proposal_build_rejected_count', 0) or 0)}"
                f" | cfo:{int(heartbeat.get('cfo_rejected_count', 0) or 0)}"
            ),
            f"heartbeat_blocker_type_counts={self._format_counter(heartbeat.get('blocker_type_counts', {}))}",
            f"biggest_heartbeat_bottleneck={heartbeat.get('biggest_bottleneck', '-')}",
            f"heartbeat_live_path_verdict={heartbeat.get('verdict', 'mixed')}",
        ]
        for item in heartbeat.get("suppressed_candidates", []) or []:
            lines.append(
                "heartbeat_candidate="
                f"{item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                f" | timeframe={item.get('timeframe', '-')}"
                f" | symbol={item.get('symbol', '-')}"
                f" | blocker={item.get('primary_blocker', '-')}"
                f" | blocker_type={','.join(item.get('blocker_categories', []) or ['mixed'])}"
                f" | fitness_actual={self._fmt_float(item.get('fitness_actual'))}"
                f" | fitness_required={self._fmt_float(item.get('fitness_required'))}"
                f" | distance={self._fmt_float(item.get('distance_to_survive'))}"
            )
            lines.append(
                f"  exact_reason={item.get('exact_blocker_reason', '-')}"
            )

        lines.extend(
            [
                "",
                "Latest Real Research Cycle",
                (
                    f"cycle_id={research.get('cycle_id', '-')}"
                    f" | parent_tick_id={research.get('parent_tick_id', '-')}"
                    f" | started_at={research.get('started_at', '-')}"
                    f" | raw_signals={int(research.get('raw_signals_count', 0) or 0)}"
                    f" | raw_proposals={int(research.get('raw_proposals_count', 0) or 0)}"
                    f" | usable_decisions={int(research.get('usable_decisions_count', 0) or 0)}"
                    f" | paper_candidates={int(research.get('paper_candidates_created', 0) or 0)}"
                ),
                (
                    f"gate_rejections=replay_windows:{int(research.get('replay_window_rejected_count', 0) or 0)}"
                    f" | insufficient_windows:{int((research.get('rejected_at_gate', {}) or {}).get('insufficient_replay_windows', 0) or 0)}"
                    f" | insufficient_sample:{int((research.get('rejected_at_gate', {}) or {}).get('insufficient_sample_size', 0) or 0)}"
                    f" | net_return:{int((research.get('rejected_at_gate', {}) or {}).get('net_return_below_threshold', 0) or 0)}"
                    f" | win_rate:{int((research.get('rejected_at_gate', {}) or {}).get('win_rate_below_threshold', 0) or 0)}"
                    f" | allocation_policy:{int((research.get('rejected_at_gate', {}) or {}).get('allocation_policy', 0) or 0)}"
                ),
                f"research_blocker_type_counts={self._format_counter(research.get('blocker_type_counts', {}))}",
                f"biggest_research_bottleneck={research.get('biggest_bottleneck', '-')}",
                f"research_replay_path_verdict={research.get('verdict', 'mixed')}",
            ]
        )
        for item in research.get("suppressed_candidates", []) or []:
            lines.append(
                "research_candidate="
                f"{item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                f" | timeframe={item.get('timeframe', '-')}"
                f" | blocker={item.get('primary_blocker', '-')}"
                f" | blocker_type={','.join(item.get('blocker_categories', []) or ['mixed'])}"
                f" | score_or_fitness={self._fmt_float(item.get('candidate_score'))}"
                f" | distance={self._fmt_float(item.get('distance_to_survive'))}"
            )
            lines.append(
                "  thresholds="
                f"replay_windows {int(item.get('replay_windows_actual', 0) or 0)}/{int(item.get('replay_windows_required', 0) or 0)}"
                f", sample_size {int(item.get('sample_size_actual', 0) or 0)}/{int(item.get('sample_size_required', 0) or 0)}"
                f", net_return {self._fmt_float(item.get('net_return_actual'))}/{self._fmt_float(item.get('net_return_required'))}"
                f", win_rate {self._fmt_float(item.get('win_rate_actual'))}/{self._fmt_float(item.get('win_rate_required'))}"
                f", fitness {self._fmt_float(item.get('fitness_actual'))}/{self._fmt_float(item.get('fitness_required'))}"
            )
            lines.append(
                f"  exact_reason={item.get('exact_blocker_reason', '-')}"
            )

        lines.extend(
            [
                "",
                "Promotion Path",
                f"paper_promotion_blocker_counts={self._format_counter((report.get('promotion_path', {}) or {}).get('paper_blocker_type_counts', {}))}",
                f"live_promotion_blocker_counts={self._format_counter((report.get('promotion_path', {}) or {}).get('live_blocker_type_counts', {}))}",
                f"paper_promotion_primary_blocker={((report.get('promotion_path', {}) or {}).get('paper_primary_blocker', '-'))}",
                f"live_promotion_primary_blocker={((report.get('promotion_path', {}) or {}).get('live_primary_blocker', '-'))}",
                f"paper_promotion_policy_note={((report.get('promotion_path', {}) or {}).get('paper_policy_note', '-'))}",
                "live_promotion_policy_note=replay_backtest_evidence_forbidden_for_live_nomination",
                f"paper_promotion_path_verdict={report.get('paper_promotion_path_verdict', 'mixed')}",
                f"live_promotion_path_verdict={report.get('live_promotion_path_verdict', 'mixed')}",
                "",
                "Top 5 Closest Candidates",
            ]
        )
        for item in report.get("top_5_closest_candidates", []) or []:
            lines.append(
                f"closest={item.get('source', '-')}"
                f" | {item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                f" | timeframe={item.get('timeframe', '-')}"
                f" | symbol={item.get('symbol', '-')}"
                f" | blocker={item.get('primary_blocker', '-')}"
                f" | distance={self._fmt_float(item.get('distance_to_survive'))}"
            )

        lines.extend(
            [
                "",
                f"single_biggest_bottleneck={report.get('biggest_bottleneck', '-')}",
                f"single_biggest_bottleneck_category={report.get('biggest_bottleneck_category', '-')}",
                f"heartbeat_live_path_verdict={report.get('heartbeat_live_path_verdict', 'mixed')}",
                f"research_replay_path_verdict={report.get('research_replay_path_verdict', 'mixed')}",
                f"paper_promotion_path_verdict={report.get('paper_promotion_path_verdict', 'mixed')}",
                f"live_promotion_path_verdict={report.get('live_promotion_path_verdict', 'mixed')}",
                f"promotion_path_verdict={report.get('promotion_path_verdict', 'mixed')}",
                f"verdict={report.get('verdict', 'mixed')}",
            ]
        )
        rendered = "\n".join(lines)
        self._log_report_phase(
            "render",
            "done",
            elapsed_ms=int((monotonic() - render_started) * 1000),
        )
        return rendered

    def _latest_heartbeat_row(self) -> dict[str, Any] | None:
        for row in self._recent_tick_runs_sorted(limit=400):
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            if not isinstance(snapshot, dict):
                continue
            if "heartbeat" not in snapshot:
                continue
            heartbeat = snapshot.get("heartbeat", {})
            if not isinstance(heartbeat, dict) or not heartbeat:
                continue
            run = snapshot.get("run", {})
            if isinstance(run, dict) and str(run.get("pipeline", "") or "") == "research_cycle":
                continue
            return row
        return None

    def _latest_real_cycle_row(self) -> dict[str, Any] | None:
        for row in self._recent_tick_runs_sorted(limit=400):
            snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
            if not isinstance(snapshot, dict):
                continue
            run = snapshot.get("run", {})
            if not isinstance(run, dict):
                continue
            if (
                str(run.get("pipeline", "") or "") == "research_cycle"
                and str(run.get("source", "") or "") == "real_heartbeat"
            ):
                return row
        return None

    def _recent_tick_runs_sorted(self, *, limit: int) -> list[dict[str, Any]]:
        rows = list(self.usage_ledger.list_recent_tick_runs(limit=limit))
        rows.sort(
            key=lambda row: (
                row.get("started_at") if isinstance(row.get("started_at"), datetime) else datetime.min,
                str(row.get("tick_id", "") or ""),
            ),
            reverse=True,
        )
        return rows

    def _build_heartbeat_section(self, *, row: dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {"status": "not_found", "suppressed_candidates": []}
        snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
        strategy_state = self._as_dict(snapshot.get("strategy_signals"))
        allocation = self._as_dict(strategy_state.get("allocation"))
        proposals_state = self._as_dict(snapshot.get("shadow_trade_proposals"))
        blockers = self._as_dict(snapshot.get("tick_blockers"))
        if not blockers:
            blockers = self._build_heartbeat_fallback_blockers(
                allocation=allocation,
                proposals_state=proposals_state,
            )
        raw_preview = list(allocation.get("raw_signals", []) or strategy_state.get("raw_signal_preview", []) or [])
        suppressed_preview = list(
            allocation.get("suppressed_signals", []) or strategy_state.get("suppressed_signal_preview", []) or []
        )
        raw_count = self._coalesce_int(
            allocation.get("signals_in"),
            strategy_state.get("signals_generated"),
            len(raw_preview),
        )
        survived_count = self._coalesce_int(
            allocation.get("signals_out"),
            len(proposals_state.get("proposals", []) or []),
            max(0, raw_count - len(suppressed_preview)),
        )
        suppressed_count = self._coalesce_int(
            allocation.get("suppressed"),
            len(suppressed_preview),
        )
        created_proposals = int(proposals_state.get("proposals_created", 0) or 0)
        raw_proposals_count = survived_count
        candidates = [
            self._heartbeat_candidate(item)
            for item in suppressed_preview
        ]
        blocker_counts = Counter()
        blocker_type_counts = Counter()
        for item in candidates:
            blocker_counts.update(item.get("blocker_reasons", []) or [])
            blocker_type_counts.update(item.get("blocker_categories", []) or [])
        verdict = self._derive_path_verdict(
            category_counts=blocker_type_counts,
            candidates=candidates,
        )
        return {
            "status": "ok",
            "tick_id": str(row.get("tick_id", "") or "-"),
            "started_at": self._fmt_dt(row.get("started_at")),
            "primary_stage": str(blockers.get("primary_stage", "") or "-"),
            "raw_signals_count": raw_count,
            "suppressed_signals_count": suppressed_count,
            "surviving_signals_count": survived_count,
            "raw_proposals_count": raw_proposals_count,
            "created_proposals_count": created_proposals,
            "allocation_rejected_count": suppressed_count,
            "proposal_build_rejected_count": max(0, survived_count - created_proposals),
            "cfo_rejected_count": int(blockers.get("rejected_trades", 0) or 0),
            "suppressed_candidates": candidates,
            "blocker_type_counts": dict(blocker_type_counts),
            "biggest_bottleneck": self._top_counter_entry(
                blocker_counts,
                default=str(blockers.get("primary_stage", "") or "unknown"),
            ),
            "verdict": verdict,
        }

    def _build_heartbeat_fallback_blockers(
        self,
        *,
        allocation: dict[str, Any],
        proposals_state: dict[str, Any],
    ) -> dict[str, Any]:
        raw_signals = int(allocation.get("signals_in", 0) or 0)
        suppressed_signals = int(allocation.get("suppressed", 0) or 0)
        survived_signals = int(allocation.get("signals_out", 0) or 0)
        created_proposals = int(proposals_state.get("proposals_created", 0) or 0)
        if raw_signals <= 0:
            stage = "no_raw_signals"
        elif suppressed_signals >= raw_signals:
            stage = "all_signals_suppressed"
        elif created_proposals <= 0:
            stage = "no_shadow_proposals"
        else:
            stage = "hold"
        return {
            "primary_stage": stage,
            "rejected_trades": 0,
            "surviving_signals": survived_signals,
        }

    def _heartbeat_candidate(self, item: dict[str, Any]) -> dict[str, Any]:
        reason = str(item.get("allocation_note", "") or "suppressed_by_fitness").strip()
        actual = self._as_float(item.get("fitness_composite_score"))
        required = self._as_float(item.get("suppress_threshold_used"))
        distance = inf
        if actual is not None and required is not None:
            distance = max(0.0, required - actual)
        blockers = [reason]
        categories = self._classify_heartbeat_candidate(
            fitness_actual=actual,
            fitness_required=required,
        )
        return {
            "source": "heartbeat",
            "strategy_id": str(item.get("strategy_id", "") or "-"),
            "profile_id": str(item.get("profile_id", "") or "-"),
            "timeframe": str(item.get("holding_window_code", "") or item.get("timeframe", "") or "-"),
            "symbol": str(item.get("symbol", "") or "-"),
            "primary_blocker": "fitness_suppression",
            "exact_blocker_reason": reason,
            "blocker_reasons": blockers,
            "blocker_categories": categories,
            "candidate_score": self._as_float(item.get("signal_score")),
            "fitness_actual": actual,
            "fitness_required": required,
            "distance_to_survive": distance,
        }

    def _build_research_section(self, *, row: dict[str, Any] | None) -> dict[str, Any]:
        if row is None:
            return {"status": "not_found", "suppressed_candidates": [], "rejected_at_gate": {}}
        snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
        state = self._as_dict(snapshot.get("research_cycle"))
        run = self._as_dict(snapshot.get("run"))
        cycle_id = str(run.get("research_cycle_id", "") or row.get("tick_id", "") or "-")
        decisions = self.usage_ledger.list_research_cycle_decisions(cycle_id=cycle_id, limit=500)
        if not decisions:
            decisions = list(state.get("decisions", []) or [])
        suppressed = []
        promotion_candidates = []
        rejected = Counter()
        all_reasons = Counter()
        blocker_type_counts = Counter()
        raw_proposals = 0
        raw_signals = 0
        for item in decisions:
            raw_proposals += int(item.get("proposals_created", 0) or 0)
            raw_signals += int(item.get("signals_generated", item.get("proposals_created", 0)) or 0)
            candidate = self._research_candidate(item)
            promotion_candidates.append(candidate)
            if str(item.get("recommendation", "") or "") in {"paper_sim_candidate", "paper_candidate"}:
                continue
            suppressed.append(candidate)
            blocker_type_counts.update(candidate.get("blocker_categories", []) or [])
            for reason in candidate.get("gate_reason_labels", []) or []:
                if reason == "paper_allocation_excludes_backtest_evidence":
                    rejected["allocation_policy"] += 1
                else:
                    rejected[reason] += 1
            all_reasons.update(candidate.get("blocker_reasons", []) or [])
        return {
            "status": "ok",
            "cycle_id": cycle_id,
            "parent_tick_id": str(run.get("parent_tick_id", "") or "-"),
            "started_at": self._fmt_dt(row.get("started_at")),
            "raw_signals_count": raw_signals,
            "raw_proposals_count": raw_proposals,
            "usable_decisions_count": int(state.get("usable_decisions_count", len(decisions)) or 0),
            "paper_candidates_created": int(state.get("paper_candidates_created", 0) or 0),
            "replay_window_rejected_count": int(state.get("replay_windows_rejected_count", 0) or 0),
            "suppressed_candidates": suppressed,
            "promotion_candidates": promotion_candidates,
            "blocker_type_counts": dict(blocker_type_counts),
            "rejected_at_gate": dict(rejected),
            "biggest_bottleneck": self._top_counter_entry(all_reasons, default="unknown"),
            "verdict": self._derive_path_verdict(
                category_counts=blocker_type_counts,
                candidates=suppressed,
            ),
        }

    def _research_candidate(self, item: dict[str, Any]) -> dict[str, Any]:
        raw = self._as_dict(item.get("raw_json")) or item
        reasons = [
            str(reason).strip()
            for reason in list(item.get("blocker_reasons_json", []) or item.get("blocker_reasons", []) or [])
            if str(reason).strip()
        ]
        paper_reasons = [
            str(reason).strip()
            for reason in list(
                item.get("paper_blocker_reasons_json", []) or item.get("paper_blocker_reasons", []) or reasons
            )
            if str(reason).strip()
            and str(reason).strip() not in {
                "paper_allocation_excludes_backtest_evidence",
                "live_allocation_excludes_backtest_evidence",
            }
        ]
        paper_policy_notes = [
            str(reason).strip()
            for reason in list(
                item.get("paper_policy_notes_json", []) or item.get("paper_policy_notes", []) or []
            )
            if str(reason).strip()
        ]
        if (
            "paper_allocation_excludes_backtest_evidence" in reasons
            and "paper_allocation_excludes_backtest_evidence" not in paper_policy_notes
        ):
            paper_policy_notes.append("paper_allocation_excludes_backtest_evidence")
        live_reasons = [
            str(reason).strip()
            for reason in list(
                item.get("live_blocker_reasons_json", []) or item.get("live_blocker_reasons", []) or reasons
            )
            if str(reason).strip()
        ]
        windows_actual = int(item.get("windows_tested_count", raw.get("windows_tested_count", 0)) or 0)
        windows_required = int(self.config.research_min_windows)
        sample_actual = int(item.get("proposals_created", raw.get("proposals_created", 0)) or 0)
        sample_required = int(self.config.research_min_proposals)
        net_summary = self._as_dict(item.get("net_return_summary_json")) or self._as_dict(raw.get("net_return_summary"))
        win_summary = self._as_dict(item.get("win_rate_summary_json")) or self._as_dict(raw.get("win_rate_summary"))
        net_actual = float(net_summary.get("avg_pct", 0.0) or 0.0)
        win_actual = float(win_summary.get("avg", 0.0) or 0.0)
        net_required = float(self.config.research_min_net_return_pct)
        win_required = float(self.config.research_min_net_win_rate)
        fitness_actual = self._as_float(raw.get("composite_fitness_score"))
        fitness_required = float(self.config.strategy_allocation_suppress_threshold)
        gate_reason_labels = []
        for reason in reasons:
            if reason.startswith("timeframe:"):
                gate_reason_labels.append("insufficient_replay_windows")
            else:
                gate_reason_labels.append(reason)
        marginal_threshold_failure = (
            windows_actual >= windows_required
            and sample_actual >= sample_required
            and net_actual >= (net_required * 0.85)
            and win_actual >= (win_required * 0.95)
        )
        gaps = [
            max(0, windows_required - windows_actual),
            max(0, sample_required - sample_actual) / max(1, sample_required),
            max(0.0, net_required - net_actual) / max(abs(net_required), 1e-9),
            max(0.0, win_required - win_actual) / max(abs(win_required), 1e-9),
        ]
        if fitness_actual is not None:
            gaps.append(max(0.0, fitness_required - fitness_actual))
        distance = sum(gaps)
        categories = self._classify_research_candidate(
            reasons=reasons,
            windows_actual=windows_actual,
            windows_required=windows_required,
            sample_actual=sample_actual,
            sample_required=sample_required,
            net_actual=net_actual,
            net_required=net_required,
            win_actual=win_actual,
            win_required=win_required,
            marginal_threshold_failure=marginal_threshold_failure,
        )
        primary = gate_reason_labels[0] if gate_reason_labels else "no_blocker_reason_recorded"
        return {
            "source": "research_cycle",
            "strategy_id": str(item.get("strategy_id", raw.get("strategy_id", "")) or "-"),
            "profile_id": str(item.get("profile_id", raw.get("profile_id", "")) or "-"),
            "timeframe": str(item.get("timeframe", raw.get("timeframe", "")) or "-"),
            "symbol": ",".join(list(item.get("symbol_universe_json", raw.get("symbol_universe", [])) or [])[:3]) or "-",
            "primary_blocker": primary,
            "exact_blocker_reason": reasons[0] if reasons else "no_blocker_reason_recorded",
            "blocker_reasons": reasons,
            "paper_blocker_reasons": paper_reasons,
            "paper_policy_notes": paper_policy_notes,
            "live_blocker_reasons": live_reasons,
            "gate_reason_labels": gate_reason_labels,
            "blocker_categories": categories,
            "candidate_score": self._evidence_score(
                net_return=net_actual,
                win_rate=win_actual,
                sample_size=sample_actual,
                windows=windows_actual,
            ),
            "replay_windows_actual": windows_actual,
            "replay_windows_required": windows_required,
            "sample_size_actual": sample_actual,
            "sample_size_required": sample_required,
            "net_return_actual": net_actual,
            "net_return_required": net_required,
            "win_rate_actual": win_actual,
            "win_rate_required": win_required,
            "fitness_actual": fitness_actual,
            "fitness_required": fitness_required if fitness_actual is not None else None,
            "distance_to_survive": distance,
            "marginal_threshold_failure": marginal_threshold_failure,
        }

    def _classify_heartbeat_candidate(
        self,
        *,
        fitness_actual: float | None,
        fitness_required: float | None,
    ) -> list[str]:
        if fitness_actual is None or fitness_required is None:
            return ["mixed"]
        gap = fitness_required - fitness_actual
        if gap <= 1.0:
            return ["thresholds_too_strict"]
        return ["strategies_underperforming"]

    def _classify_research_candidate(
        self,
        *,
        reasons: list[str],
        windows_actual: int,
        windows_required: int,
        sample_actual: int,
        sample_required: int,
        net_actual: float,
        net_required: float,
        win_actual: float,
        win_required: float,
        marginal_threshold_failure: bool,
    ) -> list[str]:
        categories: list[str] = []
        normalized_reasons = ",".join(str(reason).strip().lower() for reason in reasons if str(reason).strip())
        for reason in reasons:
            label = str(reason).strip().lower()
            if not label:
                continue
            if any(token in label for token in ("no_historical", "missing_historical", "historical_row", "historical_rows")):
                categories.append("historical_data_gap")
            elif any(token in label for token in ("future_window", "future_outcome", "later_window", "not_enough_elapsed_future_window")):
                categories.append("waiting_for_future_windows")
            elif "allocation_excludes" in label:
                categories.append("allocation_policy_block")
            elif any(token in label for token in ("insufficient_replay_windows", "timeframe:", "no_symbols_with_timeframe_data", "provider_error", "data_unavailable")):
                if windows_actual <= 1 and windows_required > windows_actual:
                    categories.append("waiting_for_future_windows")
                else:
                    categories.append("historical_data_gap")
            elif "allocation_excludes" in label:
                categories.append("allocation_policy_block")
        if sample_actual <= 0:
            categories.append("missing_outcome_samples")
        elif sample_actual < sample_required:
            categories.append("missing_outcome_samples")
        if (
            sample_actual >= sample_required
            and (
                net_actual < 0.0
                or net_actual < (net_required * 0.5)
                or win_actual < (win_required * 0.8)
            )
        ):
            categories.append("strategies_underperforming")
        elif any(token in ",".join(reasons).lower() for token in ("net_return_below_threshold", "win_rate_below_threshold")):
            categories.append("strategies_underperforming")
        if (
            marginal_threshold_failure
            and any(token in normalized_reasons for token in ("net_return_below_threshold", "win_rate_below_threshold"))
            and "allocation_policy_block" not in categories
            and "waiting_for_future_windows" not in categories
            and "historical_data_gap" not in categories
            and "missing_outcome_samples" not in categories
            and "strategies_underperforming" not in categories
        ):
            categories.append("thresholds_too_strict")
        return sorted(set(categories)) or ["mixed"]

    def _derive_path_verdict(
        self,
        *,
        category_counts: Counter[str],
        candidates: list[dict[str, Any]],
    ) -> str:
        if not category_counts:
            return "mixed"
        ranked = [
            "waiting_for_future_windows",
            "missing_outcome_samples",
            "strategies_underperforming",
            "allocation_policy_block",
            "thresholds_too_strict",
            "historical_data_gap",
        ]
        filtered = {key: int(category_counts.get(key, 0) or 0) for key in ranked if int(category_counts.get(key, 0) or 0) > 0}
        if not filtered:
            return "mixed"
        total = sum(filtered.values())
        primary = sorted(filtered.items(), key=lambda item: (-item[1], ranked.index(item[0])))[0][0]
        if primary == "thresholds_too_strict":
            close_count = sum(
                1
                for item in candidates
                if item.get("marginal_threshold_failure")
                or "thresholds_too_strict" in (item.get("blocker_categories", []) or [])
            )
            if close_count <= 0 or total != filtered[primary]:
                return "mixed"
        if filtered[primary] / max(1, total) >= 0.6:
            return primary
        return "mixed"

    def _build_promotion_section(
        self,
        *,
        heartbeat: dict[str, Any],
        research: dict[str, Any],
        combined_category_counts: Counter[str],
    ) -> dict[str, Any]:
        _ = (heartbeat, combined_category_counts)
        paper_counts = Counter()
        live_counts = Counter()
        paper_candidates: list[dict[str, Any]] = []
        live_candidates: list[dict[str, Any]] = []
        for item in list(research.get("promotion_candidates", []) or []):
            paper_categories = self._classify_reasons_to_categories(
                item.get("paper_blocker_reasons", []) or []
            )
            live_categories = self._classify_reasons_to_categories(
                item.get("live_blocker_reasons", []) or []
            )
            paper_counts.update(paper_categories)
            live_counts.update(live_categories)
            if paper_categories:
                paper_candidates.append({**item, "blocker_categories": paper_categories})
            if live_categories:
                live_candidates.append({**item, "blocker_categories": live_categories})
        paper_primary = self._top_counter_entry(paper_counts, default="mixed")
        live_primary = self._top_counter_entry(live_counts, default="mixed")
        paper_policy_note = "replay_backtest_evidence_allowed_for_paper_nomination"
        paper_verdict = self._derive_path_verdict(
            category_counts=paper_counts,
            candidates=paper_candidates,
        )
        live_verdict = self._derive_path_verdict(
            category_counts=live_counts,
            candidates=live_candidates,
        )
        if paper_verdict == "mixed" and int((paper_counts.get("allocation_policy_block", 0) or 0)) > 0:
            paper_verdict = "allocation_policy_block"
        if live_verdict == "mixed" and int((live_counts.get("allocation_policy_block", 0) or 0)) > 0:
            live_verdict = "allocation_policy_block"
        return {
            "blocker_type_counts": dict(paper_counts),
            "primary_blocker": paper_primary,
            "verdict": paper_verdict,
            "paper_blocker_type_counts": dict(paper_counts),
            "live_blocker_type_counts": dict(live_counts),
            "paper_primary_blocker": paper_primary,
            "live_primary_blocker": live_primary,
            "paper_policy_note": paper_policy_note,
            "paper_verdict": paper_verdict,
            "live_verdict": live_verdict,
        }

    def _classify_reasons_to_categories(self, reasons: list[str]) -> list[str]:
        categories: list[str] = []
        for reason in reasons:
            classified = self._classify_reason_text(reason)
            if classified is not None:
                categories.append(classified)
        return categories

    def _overall_verdict(
        self,
        *,
        heartbeat_verdict: str,
        research_verdict: str,
        promotion_verdict: str,
    ) -> str:
        unique = {item for item in (heartbeat_verdict, research_verdict, promotion_verdict) if item and item != "mixed"}
        if len(unique) == 1:
            return next(iter(unique))
        return "mixed"

    def _evidence_score(
        self,
        *,
        net_return: float,
        win_rate: float,
        sample_size: int,
        windows: int,
    ) -> float:
        return round((net_return * 100.0) + (win_rate * 10.0) + (sample_size / 10.0) + windows, 6)

    def _top_counter_entry(self, counts: Counter[str] | dict[str, int], *, default: str) -> str:
        items = counts.items() if isinstance(counts, dict) else counts.items()
        ordered = sorted(items, key=lambda item: (-int(item[1]), str(item[0])))
        return ordered[0][0] if ordered else default

    def _top_category_entry(self, counts: Counter[str] | dict[str, int], *, default: str) -> str:
        priority = [
            "waiting_for_future_windows",
            "missing_outcome_samples",
            "strategies_underperforming",
            "allocation_policy_block",
            "thresholds_too_strict",
            "historical_data_gap",
            "mixed",
        ]
        ordered = sorted(
            (
                (str(key), int(value))
                for key, value in counts.items()
                if int(value) > 0
            ),
            key=lambda item: (
                -item[1],
                priority.index(item[0]) if item[0] in priority else len(priority),
                item[0],
            ),
        )
        return ordered[0][0] if ordered else default

    def _biggest_bottleneck_category(
        self,
        *,
        biggest_bottleneck: str,
        reason_category_counts: dict[str, Counter[str]],
        combined_category_counts: Counter[str],
    ) -> str:
        direct = self._classify_reason_text(biggest_bottleneck)
        if direct is not None:
            return direct
        counts = reason_category_counts.get(str(biggest_bottleneck), Counter())
        if counts:
            return self._top_category_entry(counts, default="mixed")
        return self._top_category_entry(combined_category_counts, default="mixed")

    def _classify_reason_text(self, reason: str) -> str | None:
        label = str(reason or "").strip().lower()
        if not label:
            return None
        if "allocation_excludes" in label:
            return "allocation_policy_block"
        if any(token in label for token in ("future_window", "future_outcome", "later_window", "not_enough_elapsed_future_window")):
            return "waiting_for_future_windows"
        if any(token in label for token in ("insufficient_sample_size",)):
            return "missing_outcome_samples"
        if any(token in label for token in ("net_return_below_threshold", "win_rate_below_threshold", "suppressed by shadow fitness")):
            return "strategies_underperforming"
        if any(token in label for token in ("missing_historical", "historical_row", "historical_rows")):
            return "historical_data_gap"
        return None

    def _fmt_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")

    def _fmt_float(self, value: Any) -> str:
        numeric = self._as_float(value)
        if numeric is None:
            return "-"
        return f"{numeric:.6f}"

    def _format_counter(self, counts: Any) -> str:
        if not isinstance(counts, dict) or not counts:
            return "none"
        ordered = sorted(
            ((str(key), int(value)) for key, value in counts.items() if int(value) > 0),
            key=lambda item: (-item[1], item[0]),
        )
        return ",".join(f"{key}:{value}" for key, value in ordered) or "none"

    def _as_dict(self, value: Any) -> dict[str, Any]:
        return dict(value) if isinstance(value, dict) else {}

    def _as_float(self, value: Any) -> float | None:
        if value in (None, ""):
            return None
        try:
            return float(value)
        except (TypeError, ValueError):
            return None

    def _coalesce_int(self, *values: Any) -> int:
        for value in values:
            if value is None or value == "":
                continue
            try:
                return int(value)
            except (TypeError, ValueError):
                continue
        return 0

    def _log_report_phase(
        self,
        phase: str,
        status: str,
        *,
        elapsed_ms: int | None = None,
    ) -> None:
        fields = {
            "report": "proposal_suppression_funnel",
            "phase": phase,
            "status": status,
        }
        if elapsed_ms is not None:
            fields["elapsed_ms"] = str(elapsed_ms)
        print(
            "report_diagnostic "
            + " ".join(f"{key}={value}" for key, value in fields.items()),
            file=sys.stderr,
            flush=True,
        )
