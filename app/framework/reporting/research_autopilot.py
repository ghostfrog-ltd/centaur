from __future__ import annotations

import json
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime
from hashlib import sha1
from typing import Any, Callable

from app.framework.reporting.paper_candidate_decision_report import PaperCandidateDecisionReport
from app.framework.reporting.strategy_portfolio_research_planner import (
    StrategyPortfolioResearchPlannerReport,
)
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


SAFETY_STATEMENT = (
    "Bounded research-only autopilot. No paper trades, approvals, live settings, thresholds, "
    "or promotion policy were changed."
)

ALLOWED_PRIMARY_FLAGS = {
    "--diagnose-next-best-strategy",
    "--signal-generation-diagnosis",
    "--strategy-variant-research-report",
    "--strategy-research-planner",
    "--run-strategy-variant-research",
    "--symbol-subset-stability-report",
    "--collect-symbol-replay-evidence",
    "--strategy-portfolio-research-planner",
    "--research-expansion-planner",
    "--strategy-loss-diagnosis",
    "--generate-new-strategy-family-research-only",
    "--optimise-or-precompute-replay-dataset",
    "--precompute-bounded-dip-rebound-15min-outcomes",
    "--precompute-specific-replay-cache",
}
FORBIDDEN_FLAGS = {
    "--promotion-approve-paper",
    "--promotion-reject",
    "--trading212-seed-prices",
    "--confirm-trading212-paper-seed",
    "--loop",
    "--heartbeat-service",
    "--backfill",
    "--execute-next-research-step",
}
STOP_REASONS_REQUIRING_MANUAL_REVIEW = {
    "approved_for_manual_review",
    "requires_manual_review",
}
STOP_NEXT_ACTIONS = {
    "audit_paper_candidate",
    "no_actionable_candidate",
}
STOP_DATA_RUNTIME_ACTIONS = {
    "optimise_or_precompute_replay_dataset",
    "optimise_or_precompute_crypto_replay_dataset",
    "backfill_or_resample_data",
    "precompute_bounded_dip_rebound_15Min_outcomes",
    "precompute_specific_replay_cache",
    "optimise_specific_crypto_15Min_replay_cache",
}
CLASSIFICATION_STOP_VALUES = {
    "deprioritise_until_new_data",
    "parked_until_new_data",
    "stopped_until_new_data",
}
PAPER_AUDIT_READY_REASONS = {
    "audit_paper_candidate",
    "approved_for_manual_review",
    "requires_manual_review",
}


@dataclass(frozen=True)
class AllowedCommand:
    command_text: str
    argv: list[str]
    primary_flag: str
    candidate_key: str


@dataclass(frozen=True)
class ActionIdentity:
    base_strategy_id: str
    profile_id: str
    timeframe: str
    variant_id: str
    action_type: str
    command_type: str


class ResearchAutopilotRunner:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
        planner: StrategyPortfolioResearchPlannerReport | None = None,
        paper_reporter: PaperCandidateDecisionReport | None = None,
        command_executor: Callable[[list[str]], dict[str, Any]] | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(
            config=self.config,
            read_only=False,
            skip_schema_bootstrap=True,
            query_timeout_ms=15_000,
            lock_timeout_ms=5_000,
        )
        self.planner = planner or StrategyPortfolioResearchPlannerReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
            operator_mode=True,
        )
        self.paper_reporter = paper_reporter or PaperCandidateDecisionReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )
        self.command_executor = command_executor or self._execute_subprocess_command

    def run(self, *, max_steps: int) -> dict[str, Any]:
        if max_steps <= 0:
            raise ValueError("research autopilot requires --max-steps > 0")
        steps: list[dict[str, Any]] = []
        seen_commands: dict[str, str] = {}
        seen_candidates: set[str] = set()
        parked_candidates_this_run: list[str] = []
        current_planner: dict[str, Any] | None = None
        current_paper: dict[str, Any] | None = None
        last_command = ""
        last_result_status = "not_run"
        for step_number in range(1, max_steps + 1):
            planner_before = current_planner if current_planner is not None else self._build_planner_report(
                parked_candidates_this_run=parked_candidates_this_run
            )
            paper_before = current_paper if current_paper is not None else self.paper_reporter.build_report()
            current_planner = None
            current_paper = None
            stop = self._preflight_stop(planner=planner_before, paper=paper_before)
            if stop:
                return self._final_summary(
                    status="stopped_without_execution" if not steps else "stopped",
                    stop_reason=stop,
                    steps=steps,
                    planner=planner_before,
                    paper=paper_before,
                    parked_candidates_this_run=parked_candidates_this_run,
                    last_result_status=last_result_status,
                    last_command=last_command,
                )
            candidate_key = self._candidate_key(planner_before)
            command_text = str(planner_before.get("next_actionable_research_command", "") or "").strip()
            if not command_text:
                return self._final_summary(
                    status="stopped_without_execution" if not steps else "stopped",
                    stop_reason="no_alternative_candidate",
                    steps=steps,
                    planner=planner_before,
                    paper=paper_before,
                    parked_candidates_this_run=parked_candidates_this_run,
                    last_result_status=last_result_status,
                    last_command=last_command,
                )
            try:
                allowed = self.validate_command(
                    command_text=command_text,
                    planner_report=planner_before,
                )
            except ValueError:
                return self._final_summary(
                    status="refused",
                    stop_reason="command_not_allowlisted",
                    steps=steps,
                    planner=planner_before,
                    paper=paper_before,
                    parked_candidates_this_run=parked_candidates_this_run,
                    last_result_status="refused",
                    last_command=command_text,
                )
            evidence_stamp = self._evidence_stamp(planner_before)
            if seen_commands.get(allowed.command_text) == evidence_stamp:
                return self._final_summary(
                    status="stopped",
                    stop_reason="loop_detected",
                    steps=steps,
                    planner=planner_before,
                    paper=paper_before,
                    parked_candidates_this_run=parked_candidates_this_run,
                    last_result_status=last_result_status,
                    last_command=allowed.command_text,
                )
            if candidate_key and candidate_key in seen_candidates:
                return self._final_summary(
                    status="stopped",
                    stop_reason="loop_detected",
                    steps=steps,
                    planner=planner_before,
                    paper=paper_before,
                    parked_candidates_this_run=parked_candidates_this_run,
                    last_result_status=last_result_status,
                    last_command=allowed.command_text,
                )
            execution = self.command_executor(list(allowed.argv))
            planner_after = self._build_planner_report(parked_candidates_this_run=parked_candidates_this_run)
            paper_after = self.paper_reporter.build_report()
            current_planner = planner_after
            current_paper = paper_after
            result_status = self._result_status(
                execution=execution,
                planner_before=planner_before,
                planner_after=planner_after,
                paper_after=paper_after,
            )
            step = self._build_step_summary(
                step_number=step_number,
                allowed=allowed,
                planner_before=planner_before,
                planner_after=planner_after,
                paper_after=paper_after,
                execution=execution,
                result_status=result_status,
            )
            self._persist_step(step)
            steps.append(step)
            seen_commands[allowed.command_text] = evidence_stamp
            if candidate_key:
                seen_candidates.add(candidate_key)
            last_command = allowed.command_text
            last_result_status = result_status
            if result_status not in {"command_failed", "runtime_blocked"} and str(step.get("step_advanced", "") or "") == "no":
                if str(step.get("classification_applied", "") or "") in CLASSIFICATION_STOP_VALUES:
                    if step["candidate"] and step["candidate"] not in parked_candidates_this_run:
                        parked_candidates_this_run.append(step["candidate"])
                    replanned = self._build_planner_report(parked_candidates_this_run=parked_candidates_this_run)
                    repaper = self.paper_reporter.build_report()
                    current_planner = replanned
                    current_paper = repaper
                    replan_outcome = self._parked_candidate_replan_outcome(
                        planner_before=planner_after,
                        planner_after=replanned,
                    )
                    if replan_outcome == "continue" and step_number < max_steps:
                        continue
                    if replan_outcome == "continue":
                        return self._final_summary(
                            status="stopped",
                            stop_reason="no_progress_but_alternatives_remain",
                            steps=steps,
                            planner=replanned,
                            paper=repaper,
                            parked_candidates_this_run=parked_candidates_this_run,
                            last_result_status=result_status,
                            last_command=allowed.command_text,
                            no_advance_reason=str(step.get("no_advance_reason", "") or "planner_state_unchanged_after_execution"),
                        )
                    if (
                        replan_outcome == "no_alternative_candidate"
                        and str(replanned.get("research_universe_status", "") or "") == "exhausted_current_strategy_set"
                    ):
                        return self._final_summary(
                            status="stopped",
                            stop_reason="stopped_because_strategy_universe_exhausted",
                            steps=steps,
                            planner=replanned,
                            paper=repaper,
                            parked_candidates_this_run=parked_candidates_this_run,
                            last_result_status=result_status,
                            last_command=allowed.command_text,
                            no_advance_reason=str(step.get("no_advance_reason", "") or "planner_state_unchanged_after_execution"),
                        )
                    return self._final_summary(
                        status="stopped",
                        stop_reason=replan_outcome,
                        steps=steps,
                        planner=replanned,
                        paper=repaper,
                        parked_candidates_this_run=parked_candidates_this_run,
                        last_result_status=result_status,
                        last_command=allowed.command_text,
                        no_advance_reason=str(step.get("no_advance_reason", "") or "planner_state_unchanged_after_execution"),
                    )
                return self._final_summary(
                    status="stopped",
                    stop_reason="stopped_because_no_progress",
                    steps=steps,
                    planner=planner_after,
                    paper=paper_after,
                    parked_candidates_this_run=parked_candidates_this_run,
                    last_result_status=result_status,
                    last_command=allowed.command_text,
                    no_advance_reason=str(step.get("no_advance_reason", "") or "planner_state_unchanged_after_execution"),
                )
            stop_after = self._post_execution_stop(
                planner=planner_after,
                paper=paper_after,
                execution=execution,
                result_status=result_status,
            )
            if stop_after:
                return self._final_summary(
                    status="stopped",
                    stop_reason=stop_after,
                    steps=steps,
                    planner=planner_after,
                    paper=paper_after,
                    parked_candidates_this_run=parked_candidates_this_run,
                    last_result_status=result_status,
                    last_command=allowed.command_text,
                )
        planner_final = self._build_planner_report(parked_candidates_this_run=parked_candidates_this_run)
        paper_final = self.paper_reporter.build_report()
        return self._final_summary(
            status="stopped",
            stop_reason="stopped_because_max_steps",
            steps=steps,
            planner=planner_final,
            paper=paper_final,
            parked_candidates_this_run=parked_candidates_this_run,
            last_result_status=last_result_status,
            last_command=last_command,
        )

    def render(self, *, report: dict[str, Any]) -> str:
        lines = [
            "Research Autopilot",
            f"research_autopilot_status={report.get('research_autopilot_status', '')}",
            f"steps_run={report.get('steps_run', 0)}",
            f"stop_reason={report.get('stop_reason', '')}",
            f"last_candidate={report.get('last_candidate', '')}",
            f"last_command={report.get('last_command', '')}",
            f"last_result_status={report.get('last_result_status', '')}",
            f"current_known_best_candidate={report.get('current_known_best_candidate', '')}",
            f"current_paper_candidate={report.get('current_paper_candidate', '')}",
            f"paper_candidate_status={report.get('paper_candidate_status', '')}",
            f"paper_trading_allowed={report.get('paper_trading_allowed', '')}",
            f"candidate_ready_for_manual_paper_audit={report.get('candidate_ready_for_manual_paper_audit', '')}",
            f"portfolio_research_status={report.get('portfolio_research_status', '')}",
            f"research_universe_status={report.get('research_universe_status', '')}",
            f"next_actionable_research_candidate={report.get('next_actionable_research_candidate', '')}",
            f"next_actionable_research_command={report.get('next_actionable_research_command', '')}",
            f"next_required_operator_action={report.get('next_required_operator_action', '')}",
            f"parked_candidates_this_run={','.join(report.get('parked_candidates_this_run', []) or [])}",
            f"run_scoped_parked_candidates_received={','.join(report.get('run_scoped_parked_candidates_received', []) or [])}",
            f"planner_candidate_before_parking={report.get('planner_candidate_before_parking', '')}",
            f"planner_candidate_after_parking={report.get('planner_candidate_after_parking', '')}",
            f"parked_candidate_returned={report.get('parked_candidate_returned', '')}",
            f"parked_candidate_return_reason={report.get('parked_candidate_return_reason', '')}",
            f"data_runtime_action_detected={report.get('data_runtime_action_detected', '')}",
            f"data_runtime_stop_selection_reason={report.get('data_runtime_stop_selection_reason', '')}",
            f"terminal_research_state={report.get('terminal_research_state', '')}",
            f"next_safe_operator_action={report.get('next_safe_operator_action', '')}",
            f"next_safe_operator_command={report.get('next_safe_operator_command', '')}",
            f"precompute_mapping_attempted={report.get('precompute_mapping_attempted', '')}",
            f"mapped_precompute_command={report.get('mapped_precompute_command', '')}",
            f"precompute_already_completed={report.get('precompute_already_completed', '')}",
            f"why_next_safe_operator_command_blank={report.get('why_next_safe_operator_command_blank', '')}",
            f"next_check_command={report.get('next_check_command', '')}",
            f"step_log_count={len(report.get('step_log', []) or [])}",
            SAFETY_STATEMENT,
        ]
        for step in list(report.get("step_log", []) or []):
            lines.append(
                "step="
                f"{step.get('step_number', 0)}"
                f" before_candidate={step.get('before_candidate', '')}"
                f" before_command={step.get('before_command', '')}"
                f" before_action={step.get('before_action', '')}"
                f" after_candidate={step.get('after_candidate', '')}"
                f" after_command={step.get('after_command', '')}"
                f" after_action={step.get('after_action', '')}"
                f" result_status={step.get('result_status', '')}"
                f" classification_applied={step.get('classification_applied', '')}"
                f" classification_reason={step.get('classification_reason', '')}"
                f" sample_size_before={step.get('sample_size_before', 0)}"
                f" sample_size_after={step.get('sample_size_after', 0)}"
                f" net_return_after_costs_before={step.get('net_return_after_costs_before', 0.0)}"
                f" net_return_after_costs_after={step.get('net_return_after_costs_after', 0.0)}"
                f" win_rate_before={step.get('win_rate_before', 0.0)}"
                f" win_rate_after={step.get('win_rate_after', 0.0)}"
                f" blocker_reason={step.get('blocker_reason', '')}"
                f" next_recommendation={step.get('next_recommendation', '')}"
                f" evidence_changed={step.get('evidence_changed', '')}"
                f" candidate_status_changed={step.get('candidate_status_changed', '')}"
                f" step_advanced={step.get('step_advanced', '')}"
                f" planner_candidate_before_parking={step.get('planner_candidate_before_parking', '')}"
                f" planner_candidate_after_parking={step.get('planner_candidate_after_parking', '')}"
                f" data_runtime_action_detected={step.get('data_runtime_action_detected', '')}"
                f" data_runtime_stop_selection_reason={step.get('data_runtime_stop_selection_reason', '')}"
                f" exit_code={step.get('exit_code', '')}"
            )
        return "\n".join(lines)

    def validate_command(self, *, command_text: str, planner_report: dict[str, Any]) -> AllowedCommand:
        stripped = str(command_text or "").strip()
        if not stripped:
            raise ValueError("missing command")
        if any(token in stripped for token in ("&&", "||", ";", "|", "$(", "`", ">", "<")):
            raise ValueError("unsafe shell chaining")
        argv = shlex.split(stripped)
        if len(argv) < 3:
            raise ValueError("command too short")
        if argv[0] not in {".venv-mac/bin/python", "./.venv-mac/bin/python"}:
            raise ValueError("unexpected interpreter")
        if argv[1] != "main.py":
            raise ValueError("unexpected entrypoint")
        present_primary = [flag for flag in ALLOWED_PRIMARY_FLAGS if flag in argv]
        if len(present_primary) != 1:
            raise ValueError("exactly one allowlisted primary flag is required")
        if any(flag in argv for flag in FORBIDDEN_FLAGS):
            raise ValueError("forbidden flag present")
        if "--execute" in argv and present_primary[0] != "--collect-symbol-replay-evidence":
            raise ValueError("execute flag not allowed for this command")
        if "--json" in argv:
            raise ValueError("json output is not supported for autopilot execution")
        candidate_key = self._candidate_key(planner_report)
        expected = dict(planner_report.get("next_actionable_research_candidate") or {})
        if expected:
            self._require_flag_value(argv, "--base-strategy", str(expected.get("base_strategy_id", "") or ""))
            self._require_flag_value(argv, "--profile-id", str(expected.get("profile_id", "") or ""))
            self._require_flag_value(argv, "--timeframe", str(expected.get("timeframe", "") or ""))
        return AllowedCommand(
            command_text=stripped,
            argv=argv,
            primary_flag=present_primary[0],
            candidate_key=candidate_key,
        )

    def _require_flag_value(self, argv: list[str], flag: str, expected: str) -> None:
        if not expected:
            return
        if flag not in argv:
            raise ValueError(f"missing {flag}")
        index = argv.index(flag)
        if index + 1 >= len(argv) or argv[index + 1] != expected:
            raise ValueError(f"unexpected {flag} value")

    def _execute_subprocess_command(self, argv: list[str]) -> dict[str, Any]:
        completed = subprocess.run(argv, capture_output=True, text=True, check=False)
        return {
            "exit_code": int(completed.returncode),
            "stdout": str(completed.stdout or ""),
            "stderr": str(completed.stderr or ""),
        }

    def _build_planner_report(self, *, parked_candidates_this_run: list[str]) -> dict[str, Any]:
        return self.planner.build_report(
            parked_candidate_keys_this_run=list(parked_candidates_this_run),
        )

    def _preflight_stop(self, *, planner: dict[str, Any], paper: dict[str, Any]) -> str:
        paper_status = str(paper.get("paper_candidate_status", "") or "")
        if paper_status in STOP_REASONS_REQUIRING_MANUAL_REVIEW:
            return "candidate_ready_for_manual_paper_audit"
        if str(paper.get("paper_trading_allowed", "") or "") == "yes":
            return "stopped_because_manual_review_required"
        next_action = str(planner.get("next_portfolio_action", "") or "")
        if next_action in STOP_NEXT_ACTIONS:
            if str(planner.get("research_universe_status", "") or "") == "exhausted_current_strategy_set":
                return "stopped_because_strategy_universe_exhausted"
            return (
                "no_alternative_candidate"
                if next_action == "no_actionable_candidate"
                else "candidate_ready_for_manual_paper_audit"
            )
        if self._generic_replay_prep_did_not_unlock_candidate(planner):
            return "stopped_because_replay_prep_did_not_unlock_candidate"
        if self._should_stop_for_data_runtime_action(planner):
            return "manual_runtime_action_required"
        return ""

    def _post_execution_stop(
        self,
        *,
        planner: dict[str, Any],
        paper: dict[str, Any],
        execution: dict[str, Any],
        result_status: str,
    ) -> str:
        if int(execution.get("exit_code", 0) or 0) != 0:
            return "stopped_because_command_failure"
        if result_status == "runtime_blocked":
            return "stopped_because_data_runtime_action_required"
        return self._preflight_stop(planner=planner, paper=paper)

    def _build_step_summary(
        self,
        *,
        step_number: int,
        allowed: AllowedCommand,
        planner_before: dict[str, Any],
        planner_after: dict[str, Any],
        paper_after: dict[str, Any],
        execution: dict[str, Any],
        result_status: str,
    ) -> dict[str, Any]:
        before_candidate = self._candidate_key(planner_before)
        before_command = str(planner_before.get("next_actionable_research_command", "") or "")
        before_action = str(planner_before.get("next_portfolio_action", "") or "")
        after_candidate = self._candidate_key(planner_after)
        after_command = str(planner_after.get("next_actionable_research_command", "") or "")
        after_action = str(planner_after.get("next_portfolio_action", "") or "")
        before_action_identity = self._action_identity_dict(planner_before)
        after_action_identity = self._action_identity_dict(planner_after)
        before_metrics = self._candidate_metrics(planner_before)
        after_metrics = self._candidate_metrics(planner_after)
        evidence_changed = self._evidence_stamp(planner_before) != self._evidence_stamp(planner_after)
        candidate_status_changed = self._candidate_status(planner_before) != self._candidate_status(planner_after)
        classification_applied, classification_reason = self._classification_applied(
            planner_before=planner_before,
            planner_after=planner_after,
            paper_after=paper_after,
            before_action_identity=before_action_identity,
            after_action_identity=after_action_identity,
        )
        step_advanced = self._step_advanced_value(
            before_candidate=before_candidate,
            after_candidate=after_candidate,
            before_command=before_command,
            after_command=after_command,
            before_action=before_action,
            after_action=after_action,
            evidence_changed=evidence_changed,
            candidate_status_changed=candidate_status_changed,
            classification_applied=classification_applied,
            result_status=result_status,
        )
        data_runtime_diagnostics = self._data_runtime_stop_diagnostics(planner_after)
        return {
            "step_number": step_number,
            "candidate": allowed.candidate_key,
            "command": allowed.command_text,
            "primary_flag": allowed.primary_flag,
            "result_status": result_status,
            "exit_code": int(execution.get("exit_code", 0) or 0),
            "stdout_preview": str(execution.get("stdout", "") or "").strip()[:400],
            "stderr_preview": str(execution.get("stderr", "") or "").strip()[:400],
            "planner_before_action": str(planner_before.get("next_portfolio_action", "") or ""),
            "planner_after_action": str(planner_after.get("next_portfolio_action", "") or ""),
            "before_candidate": before_candidate,
            "before_command": before_command,
            "before_action": before_action,
            "before_action_identity": before_action_identity,
            "after_candidate": after_candidate,
            "after_command": after_command,
            "after_action": after_action,
            "after_action_identity": after_action_identity,
            "sample_size_before": before_metrics["sample_size"],
            "sample_size_after": after_metrics["sample_size"],
            "net_return_after_costs_before": before_metrics["net_return_after_costs"],
            "net_return_after_costs_after": after_metrics["net_return_after_costs"],
            "win_rate_before": before_metrics["win_rate"],
            "win_rate_after": after_metrics["win_rate"],
            "blocker_reason": classification_reason or str(planner_after.get("no_actionable_reason", "") or ""),
            "next_recommendation": after_command or str(planner_after.get("next_safe_operator_action", "") or ""),
            "evidence_changed": "yes" if evidence_changed else "no",
            "candidate_status_changed": "yes" if candidate_status_changed else "no",
            "step_advanced": step_advanced,
            "classification_applied": classification_applied,
            "classification_reason": classification_reason,
            "planner_candidate_before_parking": before_candidate if classification_applied in CLASSIFICATION_STOP_VALUES else "",
            "planner_candidate_after_parking": (
                after_candidate
                if classification_applied in CLASSIFICATION_STOP_VALUES and step_advanced == "no"
                else ""
            ),
            "data_runtime_action_detected": "yes" if data_runtime_diagnostics["detected"] else "no",
            "data_runtime_stop_selection_reason": data_runtime_diagnostics["reason"],
            "no_advance_reason": self._no_advance_reason(
                step_advanced=step_advanced,
                result_status=result_status,
            ),
            "paper_candidate_status_after": str(paper_after.get("paper_candidate_status", "") or ""),
            "paper_trading_allowed_after": str(paper_after.get("paper_trading_allowed", "") or ""),
            "recorded_at": datetime.now().astimezone().isoformat(),
        }

    def _persist_step(self, step: dict[str, Any]) -> None:
        candidate = str(step.get("candidate", "") or "portfolio/unknown/unknown")
        base_strategy_id, profile_id, timeframe = (candidate.split("/", 2) + ["", ""])[:3]
        digest = sha1(json.dumps(step, sort_keys=True, default=str).encode("utf-8")).hexdigest()[:12]
        self.usage_ledger.record_strategy_variant_evaluation(
            evaluation_id=f"research-autopilot:{step['step_number']}:{digest}",
            variant_id="research-autopilot",
            base_strategy_id=base_strategy_id or "portfolio",
            profile_id=profile_id or "autopilot",
            timeframe=timeframe or "research",
            replay_id=f"research-autopilot-{datetime.now().astimezone().strftime('%Y%m%d-%H%M%S')}",
            dataset_id="research_autopilot_step_summary",
            asset_class="mixed",
            symbols_tested=[],
            sample_size=0,
            gross_return=0.0,
            net_return_after_costs=0.0,
            fees_cost=0.0,
            spread_cost=0.0,
            slippage_cost=0.0,
            win_rate=0.0,
            drawdown=None,
            baseline_variant_id="",
            baseline_strategy_key=candidate,
            baseline_net_return_after_costs=0.0,
            baseline_win_rate=0.0,
            beats_baseline=False,
            beats_thresholds=False,
            recommended_status="evaluated",
            evaluated_at=datetime.now().astimezone(),
            notes=SAFETY_STATEMENT,
            raw={"report_type": "research_autopilot_step_summary", **step, "safety_statement": SAFETY_STATEMENT},
        )

    def _final_summary(
        self,
        *,
        status: str,
        stop_reason: str,
        steps: list[dict[str, Any]],
        planner: dict[str, Any],
        paper: dict[str, Any],
        parked_candidates_this_run: list[str],
        last_result_status: str,
        last_command: str,
        no_advance_reason: str = "",
    ) -> dict[str, Any]:
        data_runtime_diagnostics = self._data_runtime_stop_diagnostics(planner)
        parking_step = next(
            (
                step for step in reversed(steps)
                if str(step.get("classification_applied", "") or "") in CLASSIFICATION_STOP_VALUES
            ),
            {},
        )
        return {
            "research_autopilot_status": status,
            "steps_run": len(steps),
            "stop_reason": stop_reason,
            "no_advance_reason": no_advance_reason,
            "last_candidate": steps[-1]["candidate"] if steps else self._candidate_key(planner),
            "last_command": last_command,
            "last_result_status": last_result_status,
            "current_known_best_candidate": self._summary_key(paper.get("current_known_best_candidate")),
            "current_paper_candidate": self._summary_key(paper.get("current_paper_candidate")),
            "paper_candidate_status": str(paper.get("paper_candidate_status", "") or ""),
            "paper_trading_allowed": str(paper.get("paper_trading_allowed", "") or ""),
            "candidate_ready_for_manual_paper_audit": (
                "yes"
                if stop_reason == "candidate_ready_for_manual_paper_audit"
                or str(planner.get("next_portfolio_action", "") or "") in PAPER_AUDIT_READY_REASONS
                or str(paper.get("paper_candidate_status", "") or "") in PAPER_AUDIT_READY_REASONS
                else "no"
            ),
            "portfolio_research_status": str(planner.get("portfolio_research_status", "") or ""),
            "research_universe_status": str(planner.get("research_universe_status", "") or ""),
            "next_actionable_research_candidate": self._candidate_key(planner),
            "next_actionable_research_command": str(planner.get("next_actionable_research_command", "") or ""),
            "parked_candidates_this_run": list(parked_candidates_this_run),
            "run_scoped_parked_candidates_received": list(
                (planner.get("run_scoped_parked_candidates_received", []) or [])
            ),
            "planner_candidate_before_parking": str(parking_step.get("planner_candidate_before_parking", "") or ""),
            "planner_candidate_after_parking": self._candidate_key(planner) if parking_step else "",
            "parked_candidate_returned": "yes" if bool(
                ((planner.get("next_actionable_research_candidate_diagnostics", {}) or {}).get("parked_candidate_returned"))
            ) else "no",
            "parked_candidate_return_reason": str(
                ((planner.get("next_actionable_research_candidate_diagnostics", {}) or {}).get(
                    "returned_parked_candidate_reason", ""
                ))
                or ""
            ),
            "ranked_alternatives_considered": list(
                ((planner.get("next_actionable_research_candidate_diagnostics", {}) or {}).get(
                    "ranked_alternatives_considered", []
                ))
                or []
            ),
            "data_runtime_action_detected": "yes" if data_runtime_diagnostics["detected"] else "no",
            "data_runtime_stop_selection_reason": data_runtime_diagnostics["reason"],
            "next_required_operator_action": str(
                planner.get("next_required_operator_action", "")
                or ((planner.get("next_data_runtime_action", {}) or {}).get("data_or_runtime_action", ""))
                or ((planner.get("next_data_runtime_action", {}) or {}).get("action", ""))
                or planner.get("next_portfolio_action", "")
                or paper.get("next_required_action", "")
                or ""
            ),
            "terminal_research_state": str(planner.get("terminal_research_state", "") or ""),
            "no_actionable_reason": str(planner.get("no_actionable_reason", "") or ""),
            "next_safe_operator_action": str(
                planner.get("next_safe_operator_action", "")
                or planner.get("next_required_operator_action", "")
                or ((planner.get("next_data_runtime_action", {}) or {}).get("data_or_runtime_action", ""))
                or ((planner.get("next_data_runtime_action", {}) or {}).get("action", ""))
                or planner.get("next_portfolio_action", "")
                or ""
            ),
            "next_safe_operator_command": str(
                planner.get("next_safe_operator_command", "")
                or planner.get("mapped_precompute_command", "")
                or planner.get("next_actionable_research_command", "")
                or ""
            ),
            "precompute_mapping_attempted": str(planner.get("precompute_mapping_attempted", "") or ""),
            "mapped_precompute_command": str(planner.get("mapped_precompute_command", "") or ""),
            "precompute_already_completed": str(planner.get("precompute_already_completed", "") or ""),
            "why_next_safe_operator_command_blank": str(
                planner.get("why_next_safe_operator_command_blank", "") or ""
            ),
            "next_check_command": str(planner.get("next_check_command", "") or ""),
            "step_log": steps,
            "safety_statement": SAFETY_STATEMENT,
        }

    def _candidate_metrics(self, planner_report: dict[str, Any]) -> dict[str, float | int]:
        candidate = self._candidate_from_report(planner_report)
        return {
            "sample_size": int(candidate.get("latest_sample_size", candidate.get("sample_size", 0)) or 0),
            "net_return_after_costs": float(
                candidate.get(
                    "latest_net_return_after_costs",
                    candidate.get("net_return_after_costs", 0.0),
                )
                or 0.0
            ),
            "win_rate": float(candidate.get("win_rate", 0.0) or 0.0),
        }

    def _generic_replay_prep_did_not_unlock_candidate(self, planner: dict[str, Any]) -> bool:
        next_action = str(planner.get("next_portfolio_action", "") or "")
        next_data_action = str(((planner.get("next_data_runtime_action", {}) or {}).get("action", "")) or "")
        if next_action != "optimise_or_precompute_replay_dataset" and next_data_action != "optimise_or_precompute_replay_dataset":
            return False
        for item in list(planner.get("ranked_strategies", []) or []):
            latest_prep = dict(item.get("latest_replay_preparation") or {})
            if not latest_prep:
                continue
            if str(latest_prep.get("prep_status", "") or "") not in {
                "replay_prepared_but_still_slow",
                "missing_timeframe_bars",
                "replay_prepared_but_no_signals",
                "needs_backfill_or_resample",
                "no_actionable_candidate",
                "prep_failed",
            }:
                continue
            if str(item.get("research_status", "") or "") in {"runtime_blocked", "data_gap", "insufficient_data"}:
                return True
        return False

    def _candidate_key(self, planner_report: dict[str, Any]) -> str:
        candidate = dict(planner_report.get("next_actionable_research_candidate") or {})
        if not candidate:
            return ""
        return (
            f"{str(candidate.get('base_strategy_id', '') or '')}/"
            f"{str(candidate.get('profile_id', '') or '')}/"
            f"{str(candidate.get('timeframe', '') or '')}"
        )

    def _summary_key(self, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            if not value:
                return ""
            return (
                f"{str(value.get('base_strategy_id', '') or '')}/"
                f"{str(value.get('profile_id', '') or '')}/"
                f"{str(value.get('timeframe', '') or '')}"
            )
        return str(value or "")

    def _evidence_stamp(self, planner_report: dict[str, Any]) -> str:
        candidate = dict(planner_report.get("next_actionable_research_candidate") or {})
        return json.dumps(candidate, sort_keys=True, default=str)

    def _candidate_status(self, planner_report: dict[str, Any]) -> str:
        candidate = dict(planner_report.get("next_actionable_research_candidate") or {})
        return str(candidate.get("research_status", "") or "")

    def _no_advance_reason(
        self,
        *,
        step_advanced: str,
        result_status: str,
    ) -> str:
        if step_advanced != "no":
            return ""
        if result_status == "command_failed":
            return "command_failed_before_planner_could_update"
        if result_status == "runtime_blocked":
            return "runtime_blocked_before_planner_could_update"
        return "diagnosis_result_not_consumed_or_candidate_still_requires_same_action"

    def _result_status(
        self,
        *,
        execution: dict[str, Any],
        planner_before: dict[str, Any],
        planner_after: dict[str, Any],
        paper_after: dict[str, Any],
    ) -> str:
        if int(execution.get("exit_code", 0) or 0) != 0:
            return "command_failed"
        stdout = str(execution.get("stdout", "") or "")
        classification_applied, _classification_reason = self._classification_applied(
            planner_before=planner_before,
            planner_after=planner_after,
            paper_after=paper_after,
            before_action_identity=self._action_identity_dict(planner_before),
            after_action_identity=self._action_identity_dict(planner_after),
        )
        if classification_applied in CLASSIFICATION_STOP_VALUES:
            return "executed_research_only"
        if "runtime_blocked" in stdout and not self._safe_runtime_prep_command_available(planner_after):
            return "runtime_blocked"
        if self._should_stop_for_data_runtime_action(planner_after):
            return "runtime_blocked"
        return "executed_research_only"

    def _should_stop_for_data_runtime_action(self, planner: dict[str, Any]) -> bool:
        if self._safe_runtime_prep_command_available(planner):
            return False
        return bool(self._data_runtime_stop_diagnostics(planner).get("should_stop"))

    def _safe_runtime_prep_command_available(self, planner: dict[str, Any]) -> bool:
        command_text = str(planner.get("next_actionable_research_command", "") or "").strip()
        if not command_text:
            return False
        try:
            allowed = self.validate_command(
                command_text=command_text,
                planner_report=planner,
            )
        except ValueError:
            return False
        return allowed.primary_flag in {
            "--optimise-or-precompute-replay-dataset",
            "--precompute-bounded-dip-rebound-15min-outcomes",
            "--precompute-specific-replay-cache",
        }

    def _data_runtime_stop_diagnostics(self, planner: dict[str, Any]) -> dict[str, Any]:
        runtime_action = dict(planner.get("next_data_runtime_action", {}) or {})
        selected_candidate = dict(planner.get("next_actionable_research_candidate") or {})
        action = str(runtime_action.get("action", "") or "")
        follow_up = str(runtime_action.get("data_or_runtime_action", "") or "")
        data_sources_needed = list(planner.get("data_sources_needed", []) or [])
        minimum_new_data_required = str(planner.get("minimum_new_data_required", "") or "")
        detected = bool(
            action
            or follow_up
            or data_sources_needed
            or minimum_new_data_required
        )
        if not detected:
            return {
                "detected": False,
                "should_stop": False,
                "reason": "",
            }
        if selected_candidate and action == "adjust_signal_generation_research_only" and follow_up == "deprioritise_until_new_data":
            return {
                "detected": True,
                "should_stop": False,
                "reason": "planner_retained_same_candidate_after_deprioritise_until_new_data_without_real_data_runtime_action",
            }
        if selected_candidate and action not in STOP_DATA_RUNTIME_ACTIONS and follow_up not in STOP_DATA_RUNTIME_ACTIONS:
            return {
                "detected": True,
                "should_stop": False,
                "reason": "planner_retained_actionable_candidate_without_explicit_data_runtime_block",
            }
        if action in STOP_DATA_RUNTIME_ACTIONS or follow_up in STOP_DATA_RUNTIME_ACTIONS:
            return {
                "detected": True,
                "should_stop": True,
                "reason": "planner_reported_explicit_data_runtime_action",
            }
        if data_sources_needed or minimum_new_data_required:
            return {
                "detected": True,
                "should_stop": True,
                "reason": "planner_reported_explicit_new_data_requirements",
            }
        return {
            "detected": True,
            "should_stop": False,
            "reason": "data_runtime_metadata_present_but_not_actionable",
        }

    def _classification_applied(
        self,
        *,
        planner_before: dict[str, Any],
        planner_after: dict[str, Any],
        paper_after: dict[str, Any],
        before_action_identity: dict[str, Any],
        after_action_identity: dict[str, Any],
    ) -> tuple[str, str]:
        before_candidate = self._candidate_key(planner_before)
        after_candidate = self._candidate_key(planner_after)
        paper_status = str(paper_after.get("paper_candidate_status", "") or "")
        if (
            before_candidate == after_candidate
            and before_action_identity == after_action_identity
            and paper_status == "blocked"
        ):
            generated_lifecycle = str(
                ((planner_after.get("next_actionable_research_candidate") or {}).get("lifecycle_status", "")) or ""
            )
            explicit_reason = self._post_precompute_negative_reason(
                planner_before=planner_before,
                planner_after=planner_after,
            )
            if explicit_reason:
                return ("deprioritise_until_new_data", explicit_reason)
            runtime_reason = self._generated_candidate_no_progress_reason(
                planner_before=planner_before,
                planner_after=planner_after,
            )
            if runtime_reason:
                return ("deprioritise_until_new_data", runtime_reason)
            if generated_lifecycle == "insufficient_data":
                return ("deprioritise_until_new_data", "generated_candidate_had_no_usable_samples")
            if generated_lifecycle in {
                "deprioritise_until_new_data",
                "no_viable_signal",
                "no_viable_signal_after_variant_research",
                "insufficient_history_after_variant_research",
            }:
                return ("deprioritise_until_new_data", "generated_candidate_was_classified_deprioritised")
            if str(before_action_identity.get("command_type", "") or "") == "run-strategy-variant-research":
                return (
                    "deprioritise_until_new_data",
                    "variant_research_completed_but_same_generated_candidate_remains_next_action",
                )
            return (
                "deprioritise_until_new_data",
                "no_progress_after_research_step_with_negative_replay_edge",
            )
        return "", ""

    def _generated_candidate_no_progress_reason(
        self,
        *,
        planner_before: dict[str, Any],
        planner_after: dict[str, Any],
    ) -> str:
        candidate = self._candidate_from_report(planner_after) or self._candidate_from_report(planner_before)
        if not candidate:
            return ""
        classification = str(candidate.get("no_progress_classification", "") or "")
        if not classification:
            return ""
        reason = str(candidate.get("no_progress_reason", "") or "").strip()
        if classification == "missing_required_features":
            missing_required_fields = list(candidate.get("missing_required_fields", []) or [])
            fields_suffix = (
                f": {', '.join(str(item) for item in missing_required_fields if str(item or '').strip())}"
                if missing_required_fields
                else ""
            )
            return f"generated_candidate_missing_required_features{fields_suffix}"
        if classification == "insufficient_history":
            return "generated_candidate_insufficient_history_for_variant_research"
        if classification == "signal_rules_too_strict":
            return "generated_candidate_signal_rules_too_strict_for_variant_research"
        if classification == "variant_research_not_consumed":
            return "generated_candidate_variant_research_needs_diagnosis"
        if classification == "runtime_blocked":
            return "generated_candidate_variant_research_runtime_blocked"
        if reason:
            return reason
        return ""

    def _post_precompute_negative_reason(
        self,
        *,
        planner_before: dict[str, Any],
        planner_after: dict[str, Any],
    ) -> str:
        candidate = self._candidate_from_report(planner_before) or self._candidate_from_report(planner_after)
        if not candidate:
            return ""
        latest_prep = dict(candidate.get("latest_replay_preparation") or {})
        if str(latest_prep.get("cache_status", "") or "").lower() != "fresh":
            return ""
        if str(latest_prep.get("runtime_status", "") or "") != "precomputed":
            return ""
        sample_size = int(candidate.get("latest_sample_size", 0) or 0)
        latest_net = float(candidate.get("latest_net_return_after_costs", 0.0) or 0.0)
        win_rate = float(candidate.get("win_rate", 0.0) or 0.0)
        if sample_size <= 0:
            return "insufficient_data_after_precompute"
        if sample_size <= 3 and latest_net < 0.0 and win_rate <= 0.5:
            return f"precompute_completed_but_only_{sample_size}_negative_samples"
        if sample_size < 30 and latest_net < 0.0 and win_rate <= 0.5:
            return "no_viable_signal_after_precompute"
        return ""

    def _candidate_from_report(self, planner_report: dict[str, Any]) -> dict[str, Any]:
        candidate_summary = dict(planner_report.get("next_actionable_research_candidate") or {})
        if not candidate_summary:
            return {}
        for item in list(planner_report.get("ranked_strategies", []) or []):
            if (
                str(item.get("base_strategy_id", "") or "") == str(candidate_summary.get("base_strategy_id", "") or "")
                and str(item.get("profile_id", "") or "") == str(candidate_summary.get("profile_id", "") or "")
                and str(item.get("timeframe", "") or "") == str(candidate_summary.get("timeframe", "") or "")
            ):
                return dict(item)
        return candidate_summary

    def _planner_rotated_after_exclusion(
        self,
        *,
        planner_before: dict[str, Any],
        planner_after: dict[str, Any],
    ) -> bool:
        return self._action_identity_dict(planner_before) != self._action_identity_dict(planner_after)

    def _parked_candidate_replan_outcome(
        self,
        *,
        planner_before: dict[str, Any],
        planner_after: dict[str, Any],
    ) -> str:
        if self._planner_rotated_after_exclusion(
            planner_before=planner_before,
            planner_after=planner_after,
        ):
            return "continue"
        next_action = str(planner_after.get("next_portfolio_action", "") or "")
        next_command = str(planner_after.get("next_actionable_research_command", "") or "").strip()
        if not next_command or next_action == "no_actionable_candidate":
            return "no_alternative_candidate"
        if (
            self._action_identity_dict(planner_before) == self._action_identity_dict(planner_after)
            and self._evidence_stamp(planner_before) == self._evidence_stamp(planner_after)
        ):
            return "loop_detected"
        return "no_alternative_candidate"

    def _step_advanced_value(
        self,
        *,
        before_candidate: str,
        after_candidate: str,
        before_command: str,
        after_command: str,
        before_action: str,
        after_action: str,
        evidence_changed: bool,
        candidate_status_changed: bool,
        classification_applied: str,
        result_status: str,
    ) -> str:
        if result_status in {"command_failed", "runtime_blocked"}:
            return "no"
        rotated_candidate = before_candidate != after_candidate
        rotated_command = before_command != after_command
        rotated_action = before_action != after_action
        classified_and_rotated = (
            classification_applied in CLASSIFICATION_STOP_VALUES and rotated_candidate
        )
        if any((candidate_status_changed, evidence_changed, classified_and_rotated)):
            return "yes"
        if any((rotated_candidate, rotated_command, rotated_action)):
            return "partial"
        return "no"

    def _action_identity_dict(self, planner_report: dict[str, Any]) -> dict[str, str]:
        return {
            "base_strategy_id": str((planner_report.get("next_actionable_research_candidate") or {}).get("base_strategy_id", "") or ""),
            "profile_id": str((planner_report.get("next_actionable_research_candidate") or {}).get("profile_id", "") or ""),
            "timeframe": str((planner_report.get("next_actionable_research_candidate") or {}).get("timeframe", "") or ""),
            "variant_id": self._command_flag_value(str(planner_report.get("next_actionable_research_command", "") or ""), "--variant-id"),
            "action_type": str(planner_report.get("next_portfolio_action", "") or ""),
            "command_type": self._command_type(str(planner_report.get("next_actionable_research_command", "") or "")),
        }

    def _command_type(self, command_text: str) -> str:
        stripped = str(command_text or "").strip()
        if not stripped:
            return ""
        try:
            argv = shlex.split(stripped)
        except ValueError:
            return ""
        for token in argv:
            if token.startswith("--") and token in ALLOWED_PRIMARY_FLAGS:
                return token.removeprefix("--")
        return ""

    def _command_flag_value(self, command_text: str, flag: str) -> str:
        stripped = str(command_text or "").strip()
        if not stripped:
            return ""
        try:
            argv = shlex.split(stripped)
        except ValueError:
            return ""
        if flag not in argv:
            return ""
        index = argv.index(flag)
        if index + 1 >= len(argv):
            return ""
        return str(argv[index + 1] or "")
