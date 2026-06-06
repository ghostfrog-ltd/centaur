from __future__ import annotations

from collections import Counter, defaultdict
from statistics import mean
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class ReplaySummaryReport:
    PULLBACK_REVERSAL_STRATEGY_ID = "crypto_pullback.downside_reversal_watch"
    PULLBACK_CONTINUATION_STRATEGY_ID = "crypto_pullback.downside_continuation_watch"
    PULLBACK_EXTREME_REVERSAL_STRATEGY_ID = "crypto_pullback.extreme_drop_reversal_watch"
    MINIMUM_REGIME_SAMPLE_PROPOSALS = 50

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_report(self, *, replay_run_id: str) -> dict[str, Any]:
        replay_run_id = str(replay_run_id or "").strip()
        if not replay_run_id:
            return {"status": "missing_replay_run_id", "reason": "Pass --replay-run-id."}
        tick_run = self.usage_ledger.get_tick_run(tick_id=replay_run_id)
        if tick_run is None:
            return {"status": "not_found", "reason": f"No replay run found for {replay_run_id}."}
        note_prefix = f"historical_replay:{replay_run_id}:"
        proposals = self.usage_ledger.list_shadow_trade_proposals_by_note_prefix(note_prefix=note_prefix)
        outcomes = self.usage_ledger.list_shadow_trade_outcomes_by_note_prefix(note_prefix=note_prefix)
        snapshot = tick_run.get("state_snapshot_json", {}) if isinstance(tick_run, dict) else {}
        training = snapshot.get("historical_replay_training", {}) if isinstance(snapshot, dict) else {}
        proposals_by_id = {
            str(item.get("proposal_id", "") or ""): item for item in proposals
        }

        by_checkpoint: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in outcomes:
            by_checkpoint[str(row.get("checkpoint_code", "")).lower()].append(row)

        checkpoint_summaries = []
        for checkpoint_code, rows in sorted(by_checkpoint.items()):
            checkpoint_summaries.append(
                self._build_checkpoint_summary(
                    checkpoint_code=checkpoint_code,
                    rows=rows,
                )
            )

        blocker_counts: Counter[str] = Counter()
        rejection_summary = (((snapshot.get("last_error") or {}) if isinstance(snapshot, dict) else {}) or {})
        for item in training.get("top_blockers_by_strategy", []) or []:
            blocker_counts[str(item.get("blocker", "-") or "-")] += int(item.get("count", 0) or 0)

        pullback_strategy_id = self.PULLBACK_REVERSAL_STRATEGY_ID
        pullback_proposals = [
            item
            for item in proposals
            if str(item.get("strategy_id", "") or "") == pullback_strategy_id
        ]
        pullback_outcomes = [
            item
            for item in outcomes
            if str(item.get("strategy_id", "") or "") == pullback_strategy_id
        ]
        pullback_analysis = self._build_strategy_analysis(
            strategy_id=pullback_strategy_id,
            proposals=pullback_proposals,
            outcomes=pullback_outcomes,
            proposals_by_id=proposals_by_id,
        )
        moderate_pullback_proposals = self._filter_pullback_rows_by_bucket(
            proposals=pullback_proposals,
            proposals_by_id=proposals_by_id,
            allowed_buckets={
                "-0.15% to -0.30%",
                "-0.30% to -0.50%",
                "-0.50% to -1.00%",
            },
        )
        moderate_proposal_ids = {
            str(item.get("proposal_id", "") or "") for item in moderate_pullback_proposals
        }
        moderate_pullback_outcomes = [
            item
            for item in pullback_outcomes
            if str(item.get("proposal_id", "") or "") in moderate_proposal_ids
        ]
        extreme_pullback_proposals = self._filter_pullback_rows_by_bucket(
            proposals=pullback_proposals,
            proposals_by_id=proposals_by_id,
            allowed_buckets={"worse than -1.00%"},
        )
        extreme_proposal_ids = {
            str(item.get("proposal_id", "") or "") for item in extreme_pullback_proposals
        }
        extreme_pullback_outcomes = [
            item
            for item in pullback_outcomes
            if str(item.get("proposal_id", "") or "") in extreme_proposal_ids
        ]
        continuation_analysis = self._build_continuation_interpretation(
            strategy_id=self.PULLBACK_CONTINUATION_STRATEGY_ID,
            source_strategy_id=pullback_strategy_id,
            proposals=moderate_pullback_proposals,
            outcomes=moderate_pullback_outcomes,
            proposals_by_id=proposals_by_id,
        )
        extreme_reversal_analysis = self._build_strategy_analysis(
            strategy_id=self.PULLBACK_EXTREME_REVERSAL_STRATEGY_ID,
            proposals=extreme_pullback_proposals,
            outcomes=extreme_pullback_outcomes,
            proposals_by_id=proposals_by_id,
        )
        regime_comparison = [
            self._build_regime_comparison_entry(
                strategy_id=self.PULLBACK_CONTINUATION_STRATEGY_ID,
                regime_label="Normal Pullback / Downside Continuation",
                movement_label="-0.15% to -1.00%",
                proposals=moderate_pullback_proposals,
                outcomes=moderate_pullback_outcomes,
                proposals_by_id=proposals_by_id,
                interpretation="inverse_continuation_only",
            ),
            self._build_regime_comparison_entry(
                strategy_id=self.PULLBACK_EXTREME_REVERSAL_STRATEGY_ID,
                regime_label="Extreme Drop Reversal",
                movement_label="worse than -1.00%",
                proposals=extreme_pullback_proposals,
                outcomes=extreme_pullback_outcomes,
                proposals_by_id=proposals_by_id,
                interpretation="long_reversal_only",
            ),
        ]

        return {
            "status": "ok",
            "replay_run_id": replay_run_id,
            "replay_started_at": training.get("replay_started_at") or snapshot.get("run", {}).get("replay_started_at"),
            "replay_config_hash": training.get("replay_config_hash") or snapshot.get("run", {}).get("replay_config_hash"),
            "timestamps_processed": int(training.get("replay_timestamps_processed", 0) or 0),
            "candidates_evaluated": int(training.get("candidates_evaluated", 0) or 0),
            "signals_generated": int(training.get("signals_generated", 0) or 0),
            "paper_execution_signals_generated": int(training.get("paper_execution_signals_generated", 0) or 0),
            "research_signals_generated": int(training.get("paper_research_signals_generated", 0) or 0),
            "outcomes_recorded": int(training.get("outcomes_recorded", 0) or 0),
            "outcome_checkpoints_skipped_not_enough_future_data": int(
                training.get("outcome_checkpoints_skipped_not_enough_future_data", 0) or 0
            ),
            "proposal_count": len(proposals),
            "outcome_count": len(outcomes),
            "checkpoint_summaries": checkpoint_summaries,
            "regime_comparison": regime_comparison,
            "strategy_analyses": {
                pullback_strategy_id: pullback_analysis,
                self.PULLBACK_CONTINUATION_STRATEGY_ID: continuation_analysis,
                self.PULLBACK_EXTREME_REVERSAL_STRATEGY_ID: extreme_reversal_analysis,
            },
            "top_blockers_by_strategy": blocker_counts.most_common(10),
            "dry_run": bool(training.get("dry_run")),
            "last_error": rejection_summary,
        }

    def render(self, *, replay_run_id: str) -> str:
        report = self.build_report(replay_run_id=replay_run_id)
        if report.get("status") != "ok":
            return (
                "Replay Summary\n"
                f"Status: {report.get('status', 'unknown')}\n"
                f"Reason: {report.get('reason', '-')}"
            )
        lines = [
            "Replay Summary",
            (
                f"replay_run_id={report.get('replay_run_id', '-')}"
                f" | replay_started_at={report.get('replay_started_at', '-')}"
                f" | replay_config_hash={report.get('replay_config_hash', '-')}"
                f" | dry_run={'yes' if report.get('dry_run') else 'no'}"
            ),
            (
                f"timestamps_processed={report.get('timestamps_processed', 0)}"
                f" | candidates_evaluated={report.get('candidates_evaluated', 0)}"
                f" | signals_generated={report.get('signals_generated', 0)}"
                f" | research_signals_generated={report.get('research_signals_generated', 0)}"
                f" | outcomes_recorded={report.get('outcomes_recorded', 0)}"
                f" | skipped_not_enough_future_data={report.get('outcome_checkpoints_skipped_not_enough_future_data', 0)}"
            ),
            "Checkpoint Windows",
        ]
        summaries = report.get("checkpoint_summaries", []) or []
        if summaries:
            for row in summaries:
                lines.append(
                    f"- {row.get('checkpoint_code', '-')}"
                    f" | outcomes={row.get('outcomes', 0)}"
                    f" | win_rate={row.get('win_rate', 0)}"
                    f" | avg_return_pct={row.get('avg_realized_return_pct', 0)}"
                    f" | avg_mfe_pct={row.get('avg_max_favorable_excursion_pct', 0)}"
                    f" | avg_mae_pct={row.get('avg_max_adverse_excursion_pct', 0)}"
                )
        else:
            lines.append("- none")
        lines.extend(self._render_regime_comparison(report.get("regime_comparison", []) or []))
        strategy_analyses = report.get("strategy_analyses", {}) or {}
        pullback = strategy_analyses.get(self.PULLBACK_REVERSAL_STRATEGY_ID)
        if isinstance(pullback, dict) and pullback.get("proposal_count", 0):
            lines.extend(self._render_strategy_analysis(pullback))
        continuation = strategy_analyses.get(self.PULLBACK_CONTINUATION_STRATEGY_ID)
        if isinstance(continuation, dict) and continuation.get("proposal_count", 0):
            lines.extend(self._render_continuation_analysis(continuation))
        extreme_reversal = strategy_analyses.get(self.PULLBACK_EXTREME_REVERSAL_STRATEGY_ID)
        if isinstance(extreme_reversal, dict) and extreme_reversal.get("proposal_count", 0):
            lines.extend(self._render_strategy_analysis(extreme_reversal))
        lines.append("Top Blockers")
        blockers = report.get("top_blockers_by_strategy", []) or []
        if blockers:
            for blocker, count in blockers:
                lines.append(f"- {blocker}: {count}")
        else:
            lines.append("- none")
        return "\n".join(lines)

    def _build_strategy_analysis(
        self,
        *,
        strategy_id: str,
        proposals: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
        proposals_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        proposal_context_by_id = {
            proposal_id: self._proposal_context(proposal)
            for proposal_id, proposal in proposals_by_id.items()
        }
        symbol_counts: Counter[str] = Counter(
            str(item.get("symbol", "") or "-") for item in proposals
        )
        symbol_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        movement_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        discovery_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        trade_count_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        volume_presence_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        volume_threshold_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        checkpoint_inverse: dict[str, list[float]] = defaultdict(list)
        checkpoint_inverse_wins: dict[str, list[float]] = defaultdict(list)
        checkpoint_inverse_mfe: dict[str, list[float]] = defaultdict(list)
        checkpoint_inverse_mae: dict[str, list[float]] = defaultdict(list)

        for row in outcomes:
            proposal_id = str(row.get("proposal_id", "") or "")
            proposal = proposals_by_id.get(proposal_id, {})
            context = proposal_context_by_id.get(proposal_id, {})
            symbol = str(row.get("symbol", proposal.get("symbol", "")) or "-")
            symbol_groups[symbol].append(row)
            movement_groups[self._movement_bucket(context.get("movement_pct"))].append(row)
            discovery_groups[self._discovery_bucket(context.get("discovery_score"))].append(row)
            trade_count_groups[self._trade_count_bucket(context.get("trade_count"))].append(row)
            volume_presence_groups[self._volume_presence_bucket(context.get("volume_gbp"))].append(row)
            volume_threshold_groups[self._volume_threshold_bucket(context.get("volume_gbp"))].append(row)
            realized = self._to_float(row.get("realized_return_pct"))
            mfe = self._to_float(row.get("max_favorable_excursion_pct"))
            mae = self._to_float(row.get("max_adverse_excursion_pct"))
            checkpoint_code = str(row.get("checkpoint_code", "") or "").lower()
            if realized is not None and checkpoint_code:
                inverse_return = -realized
                checkpoint_inverse[checkpoint_code].append(inverse_return)
                checkpoint_inverse_wins[checkpoint_code].append(inverse_return)
            if mfe is not None and checkpoint_code:
                checkpoint_inverse_mae[checkpoint_code].append(-mfe)
            if mae is not None and checkpoint_code:
                checkpoint_inverse_mfe[checkpoint_code].append(-mae)

        return {
            "strategy_id": strategy_id,
            "proposal_count": len(proposals),
            "outcome_count": len(outcomes),
            "by_symbol": [
                {
                    "symbol": symbol,
                    "proposals": int(symbol_counts.get(symbol, 0)),
                    "checkpoint_summaries": self._summaries_for_group(rows),
                }
                for symbol, rows in sorted(
                    symbol_groups.items(),
                    key=lambda item: (-int(symbol_counts.get(item[0], 0)), item[0]),
                )
            ],
            "by_movement_bucket": self._bucket_group_rows(movement_groups),
            "by_discovery_bucket": self._bucket_group_rows(discovery_groups),
            "trade_count_comparison": self._bucket_group_rows(
                trade_count_groups,
                preferred_order=["trade_count>=2", "trade_count<2", "trade_count_unknown"],
            ),
            "volume_presence_comparison": self._bucket_group_rows(
                volume_presence_groups,
                preferred_order=["volume_gbp>0", "volume_gbp<=0_or_missing"],
            ),
            "volume_threshold_comparison": self._bucket_group_rows(
                volume_threshold_groups,
                preferred_order=["volume_gbp>=50000", "volume_gbp<50000_or_missing"],
            ),
            "short_side_interpretation": [
                {
                    "checkpoint_code": checkpoint_code,
                    "inverse_win_rate": round(
                        (
                            sum(1 for value in checkpoint_inverse_wins.get(checkpoint_code, []) if value > 0)
                            / len(checkpoint_inverse_wins.get(checkpoint_code, []))
                        ),
                        6,
                    )
                    if checkpoint_inverse_wins.get(checkpoint_code)
                    else 0.0,
                    "avg_inverse_return_pct": round(mean(values), 6) if values else 0.0,
                    "avg_inverse_max_favorable_excursion_pct": round(
                        mean(checkpoint_inverse_mfe.get(checkpoint_code, [])),
                        6,
                    )
                    if checkpoint_inverse_mfe.get(checkpoint_code)
                    else 0.0,
                    "avg_inverse_max_adverse_excursion_pct": round(
                        mean(checkpoint_inverse_mae.get(checkpoint_code, [])),
                        6,
                    )
                    if checkpoint_inverse_mae.get(checkpoint_code)
                    else 0.0,
                    "positive_average_return": bool(values and mean(values) > 0),
                }
                for checkpoint_code, values in sorted(checkpoint_inverse.items())
            ],
        }

    def _build_continuation_interpretation(
        self,
        *,
        strategy_id: str,
        source_strategy_id: str,
        proposals: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
        proposals_by_id: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        by_symbol: dict[str, list[float]] = defaultdict(list)
        by_checkpoint: dict[str, list[float]] = defaultdict(list)
        by_checkpoint_mfe: dict[str, list[float]] = defaultdict(list)
        by_checkpoint_mae: dict[str, list[float]] = defaultdict(list)
        proposal_context_by_id = {
            proposal_id: self._proposal_context(proposal)
            for proposal_id, proposal in proposals_by_id.items()
        }
        movement_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        discovery_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        trade_count_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        volume_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
        signal_score_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

        for row in outcomes:
            proposal_id = str(row.get("proposal_id", "") or "")
            proposal = proposals_by_id.get(proposal_id, {})
            context = proposal_context_by_id.get(proposal_id, {})
            symbol = str(row.get("symbol", proposal.get("symbol", "")) or "-")
            checkpoint_code = str(row.get("checkpoint_code", "") or "").lower()
            realized = self._to_float(row.get("realized_return_pct"))
            mfe = self._to_float(row.get("max_favorable_excursion_pct"))
            mae = self._to_float(row.get("max_adverse_excursion_pct"))
            if realized is not None:
                inverse_return = -realized
                by_symbol[symbol].append(inverse_return)
                if checkpoint_code:
                    by_checkpoint[checkpoint_code].append(inverse_return)
            if mae is not None and checkpoint_code:
                by_checkpoint_mfe[checkpoint_code].append(-mae)
            if mfe is not None and checkpoint_code:
                by_checkpoint_mae[checkpoint_code].append(-mfe)
            movement_groups[self._movement_bucket(context.get("movement_pct"))].append(row)
            discovery_groups[self._discovery_bucket(context.get("discovery_score"))].append(row)
            trade_count_groups[self._trade_count_bucket(context.get("trade_count"))].append(row)
            volume_groups[self._volume_threshold_bucket(context.get("volume_gbp"))].append(row)
            signal_score_groups[self._signal_score_bucket(context.get("signal_score"))].append(row)

        ranked_symbols = [
            {
                "symbol": symbol,
                "outcomes": len(values),
                "avg_inverse_return_pct": round(mean(values), 6) if values else 0.0,
            }
            for symbol, values in by_symbol.items()
        ]
        ranked_symbols.sort(
            key=lambda item: (-float(item["avg_inverse_return_pct"]), item["symbol"])
        )

        checkpoint_summaries = []
        for checkpoint_code, values in sorted(by_checkpoint.items()):
            inverse_wins = sum(1 for value in values if value > 0)
            checkpoint_summaries.append(
                {
                    "checkpoint_code": checkpoint_code,
                    "outcomes": len(values),
                    "inverse_win_rate": round(inverse_wins / len(values), 6) if values else 0.0,
                    "avg_inverse_return_pct": round(mean(values), 6) if values else 0.0,
                    "avg_inverse_max_favorable_excursion_pct": round(
                        mean(by_checkpoint_mfe.get(checkpoint_code, [])),
                        6,
                    )
                    if by_checkpoint_mfe.get(checkpoint_code)
                    else 0.0,
                    "avg_inverse_max_adverse_excursion_pct": round(
                        mean(by_checkpoint_mae.get(checkpoint_code, [])),
                        6,
                    )
                    if by_checkpoint_mae.get(checkpoint_code)
                    else 0.0,
                }
            )

        return {
            "strategy_id": strategy_id,
            "source_strategy_id": source_strategy_id,
            "proposal_count": len(proposals),
            "outcome_count": len(outcomes),
            "paper_execution_allowed": False,
            "paper_research_allowed": True,
            "live_execution_allowed": False,
            "research_only": True,
            "minimum_sample_warning": self._minimum_sample_warning(len(proposals)),
            "checkpoint_summaries": checkpoint_summaries,
            "by_movement_bucket": self._bucket_group_rows(movement_groups),
            "by_discovery_bucket": self._bucket_group_rows(discovery_groups),
            "trade_count_comparison": self._bucket_group_rows(
                trade_count_groups,
                preferred_order=["trade_count>=2", "trade_count<2", "trade_count_unknown"],
            ),
            "volume_threshold_comparison": self._bucket_group_rows(
                volume_groups,
                preferred_order=["volume_gbp>=50000", "volume_gbp<50000_or_missing"],
            ),
            "signal_score_comparison": self._bucket_group_rows(
                signal_score_groups,
                preferred_order=["signal_score>=80", "signal_score>=70", "signal_score<70", "signal_score_unknown"],
            ),
            "top_symbols_by_inverse_return": ranked_symbols[:5],
            "worst_symbols_by_inverse_return": sorted(
                ranked_symbols,
                key=lambda item: (float(item["avg_inverse_return_pct"]), item["symbol"]),
            )[:5],
        }

    def _build_regime_comparison_entry(
        self,
        *,
        strategy_id: str,
        regime_label: str,
        movement_label: str,
        proposals: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
        proposals_by_id: dict[str, dict[str, Any]],
        interpretation: str,
    ) -> dict[str, Any]:
        by_symbol: dict[str, list[float]] = defaultdict(list)
        by_checkpoint: dict[str, list[float]] = defaultdict(list)
        checkpoint_wins: Counter[str] = Counter()

        for row in outcomes:
            proposal_id = str(row.get("proposal_id", "") or "")
            proposal = proposals_by_id.get(proposal_id, {})
            symbol = str(row.get("symbol", proposal.get("symbol", "")) or "-")
            checkpoint_code = str(row.get("checkpoint_code", "") or "").lower()
            realized = self._to_float(row.get("realized_return_pct"))
            if realized is None or not checkpoint_code:
                continue
            metric_value = -realized if interpretation == "inverse_continuation_only" else realized
            by_symbol[symbol].append(metric_value)
            by_checkpoint[checkpoint_code].append(metric_value)
            if metric_value > 0:
                checkpoint_wins[checkpoint_code] += 1

        checkpoint_metrics = [
            {
                "checkpoint_code": checkpoint_code,
                "outcomes": len(values),
                "win_rate": round(checkpoint_wins[checkpoint_code] / len(values), 6) if values else 0.0,
                "avg_return_pct": round(mean(values), 6) if values else 0.0,
            }
            for checkpoint_code, values in sorted(by_checkpoint.items())
        ]
        ranked_symbols = [
            {
                "symbol": symbol,
                "outcomes": len(values),
                "avg_return_pct": round(mean(values), 6) if values else 0.0,
            }
            for symbol, values in by_symbol.items()
        ]
        ranked_symbols.sort(key=lambda item: (-float(item["avg_return_pct"]), item["symbol"]))

        return {
            "strategy_id": strategy_id,
            "regime_label": regime_label,
            "movement_label": movement_label,
            "interpretation": interpretation,
            "proposal_count": len(proposals),
            "outcome_count": len(outcomes),
            "research_only": True,
            "paper_execution_allowed": False,
            "live_execution_allowed": False,
            "minimum_sample_warning": self._minimum_sample_warning(len(proposals)),
            "checkpoint_metrics": checkpoint_metrics,
            "checkpoint_recommendation": self._checkpoint_recommendation(checkpoint_metrics),
            "best_symbols": ranked_symbols[:5],
            "worst_symbols": sorted(
                ranked_symbols,
                key=lambda item: (float(item["avg_return_pct"]), item["symbol"]),
            )[:5],
        }

    def _filter_pullback_rows_by_bucket(
        self,
        *,
        proposals: list[dict[str, Any]],
        proposals_by_id: dict[str, dict[str, Any]],
        allowed_buckets: set[str],
    ) -> list[dict[str, Any]]:
        filtered: list[dict[str, Any]] = []
        for proposal in proposals:
            proposal_id = str(proposal.get("proposal_id", "") or "")
            proposal_row = proposals_by_id.get(proposal_id, proposal)
            context = self._proposal_context(proposal_row)
            if self._movement_bucket(context.get("movement_pct")) in allowed_buckets:
                filtered.append(proposal)
        return filtered

    def _bucket_group_rows(
        self,
        groups: dict[str, list[dict[str, Any]]],
        *,
        preferred_order: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        order_index = {
            label: index for index, label in enumerate(preferred_order or [])
        }
        ordered_items = sorted(
            groups.items(),
            key=lambda item: (order_index.get(item[0], 999), item[0]),
        )
        return [
            {
                "bucket": bucket,
                "outcomes": len(rows),
                "checkpoint_summaries": self._summaries_for_group(rows),
            }
            for bucket, rows in ordered_items
        ]

    def _summaries_for_group(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in rows:
            grouped[str(row.get("checkpoint_code", "") or "").lower()].append(row)
        return [
            self._build_checkpoint_summary(
                checkpoint_code=checkpoint_code,
                rows=checkpoint_rows,
            )
            for checkpoint_code, checkpoint_rows in sorted(grouped.items())
        ]

    def _build_checkpoint_summary(
        self,
        *,
        checkpoint_code: str,
        rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        realized = [
            value
            for value in (self._to_float(item.get("realized_return_pct")) for item in rows)
            if value is not None
        ]
        mfe = [
            value
            for value in (
                self._to_float(item.get("max_favorable_excursion_pct")) for item in rows
            )
            if value is not None
        ]
        mae = [
            value
            for value in (
                self._to_float(item.get("max_adverse_excursion_pct")) for item in rows
            )
            if value is not None
        ]
        wins = sum(1 for value in realized if value > 0)
        return {
            "checkpoint_code": checkpoint_code,
            "outcomes": len(rows),
            "win_rate": round(wins / len(realized), 6) if realized else 0.0,
            "avg_realized_return_pct": round(mean(realized), 6) if realized else 0.0,
            "avg_max_favorable_excursion_pct": round(mean(mfe), 6) if mfe else 0.0,
            "avg_max_adverse_excursion_pct": round(mean(mae), 6) if mae else 0.0,
        }

    def _proposal_context(self, proposal: dict[str, Any]) -> dict[str, Any]:
        raw = proposal.get("raw_json", {})
        if not isinstance(raw, dict):
            raw = {}
        return {
            "movement_pct": self._to_float(raw.get("movement_pct", proposal.get("movement_pct"))),
            "discovery_score": self._to_float(
                raw.get("discovery_score", proposal.get("discovery_score"))
            ),
            "liquidity_score": self._to_float(raw.get("liquidity_score", proposal.get("liquidity_score"))),
            "trade_count": self._to_int(raw.get("trade_count", proposal.get("trade_count"))),
            "volume": self._to_int(raw.get("volume", proposal.get("volume"))),
            "volume_gbp": self._to_float(raw.get("volume_gbp", proposal.get("volume_gbp"))),
            "signal_score": self._to_float(raw.get("signal_score", proposal.get("signal_score"))),
            "symbol": str(raw.get("symbol", proposal.get("symbol", "")) or ""),
            "strategy_id": str(raw.get("strategy_id", proposal.get("strategy_id", "")) or ""),
            "profile_id": str(raw.get("profile_id", proposal.get("profile_id", "")) or ""),
            "replay_run_id": str(raw.get("replay_run_id", proposal.get("replay_run_id", "")) or ""),
        }

    def _movement_bucket(self, value: float | None) -> str:
        if value is None:
            return "movement_unknown"
        if value >= -0.30:
            return "-0.15% to -0.30%"
        if value >= -0.50:
            return "-0.30% to -0.50%"
        if value >= -1.00:
            return "-0.50% to -1.00%"
        return "worse than -1.00%"

    def _discovery_bucket(self, value: float | None) -> str:
        if value is None:
            return "discovery_unknown"
        if value < 3.0:
            return "2.5-3.0"
        if value < 4.0:
            return "3.0-4.0"
        return "4.0+"

    def _trade_count_bucket(self, value: int | None) -> str:
        if value is None:
            return "trade_count_unknown"
        return "trade_count>=2" if value >= 2 else "trade_count<2"

    def _volume_presence_bucket(self, value: float | None) -> str:
        if value is not None and value > 0:
            return "volume_gbp>0"
        return "volume_gbp<=0_or_missing"

    def _volume_threshold_bucket(self, value: float | None) -> str:
        if value is not None and value >= 50_000.0:
            return "volume_gbp>=50000"
        return "volume_gbp<50000_or_missing"

    def _signal_score_bucket(self, value: float | None) -> str:
        if value is None:
            return "signal_score_unknown"
        if value >= 80.0:
            return "signal_score>=80"
        if value >= 70.0:
            return "signal_score>=70"
        return "signal_score<70"

    def _render_strategy_analysis(self, analysis: dict[str, Any]) -> list[str]:
        lines = [
            f"Strategy Deep Dive: {analysis.get('strategy_id', '-')}",
            (
                f"proposals={analysis.get('proposal_count', 0)}"
                f" | outcomes={analysis.get('outcome_count', 0)}"
                f" | paper_execution_allowed=no | research_only=yes"
            ),
            "By Symbol",
        ]
        by_symbol = analysis.get("by_symbol", []) or []
        if by_symbol:
            for item in by_symbol:
                lines.append(
                    f"- {item.get('symbol', '-')}"
                    f" | proposals={item.get('proposals', 0)}"
                    f" | {self._format_checkpoint_summary_inline(item.get('checkpoint_summaries', []))}"
                )
        else:
            lines.append("- none")
        lines.append("By Movement Bucket")
        lines.extend(self._render_bucket_rows(analysis.get("by_movement_bucket", []) or []))
        lines.append("By Discovery Score Bucket")
        lines.extend(self._render_bucket_rows(analysis.get("by_discovery_bucket", []) or []))
        lines.append("Trade Count Comparison")
        lines.extend(self._render_bucket_rows(analysis.get("trade_count_comparison", []) or []))
        lines.append("Volume GBP Presence Comparison")
        lines.extend(
            self._render_bucket_rows(analysis.get("volume_presence_comparison", []) or [])
        )
        lines.append("Volume GBP Threshold Comparison")
        lines.extend(
            self._render_bucket_rows(analysis.get("volume_threshold_comparison", []) or [])
        )
        lines.append("Short-Side Continuation Interpretation")
        short_side = analysis.get("short_side_interpretation", []) or []
        if short_side:
            for item in short_side:
                lines.append(
                    f"- {item.get('checkpoint_code', '-')}"
                    f" | inverse_win_rate={item.get('inverse_win_rate', 0)}"
                    f" | avg_inverse_return_pct={item.get('avg_inverse_return_pct', 0)}"
                    f" | avg_inverse_mfe_pct={item.get('avg_inverse_max_favorable_excursion_pct', 0)}"
                    f" | avg_inverse_mae_pct={item.get('avg_inverse_max_adverse_excursion_pct', 0)}"
                    f" | positive_average_return={'yes' if item.get('positive_average_return') else 'no'}"
                    f" | research_only=yes"
                )
        else:
            lines.append("- none")
        return lines

    def _render_continuation_analysis(self, analysis: dict[str, Any]) -> list[str]:
        lines = [
            f"Strategy Deep Dive: {analysis.get('strategy_id', '-')}",
            (
                f"source_strategy_id={analysis.get('source_strategy_id', '-')}"
                f" | proposals={analysis.get('proposal_count', 0)}"
                f" | outcomes={analysis.get('outcome_count', 0)}"
                f" | paper_execution_allowed=no | paper_research_allowed=yes | live_execution_allowed=no | research_only=yes"
            ),
        ]
        warning = analysis.get("minimum_sample_warning")
        if warning:
            lines.append(f"Sample Warning: {warning}")
        lines.append("Continuation Checkpoints")
        summaries = analysis.get("checkpoint_summaries", []) or []
        if summaries:
            for item in summaries:
                lines.append(
                    f"- {item.get('checkpoint_code', '-')}"
                    f" | inverse_win_rate={item.get('inverse_win_rate', 0)}"
                    f" | avg_inverse_return_pct={item.get('avg_inverse_return_pct', 0)}"
                    f" | avg_inverse_mfe_pct={item.get('avg_inverse_max_favorable_excursion_pct', 0)}"
                    f" | avg_inverse_mae_pct={item.get('avg_inverse_max_adverse_excursion_pct', 0)}"
                )
        else:
            lines.append("- none")
        lines.append("Top Symbols By Inverse Return")
        lines.extend(self._render_ranked_inverse_symbols(analysis.get("top_symbols_by_inverse_return", []) or []))
        lines.append("Worst Symbols By Inverse Return")
        lines.extend(self._render_ranked_inverse_symbols(analysis.get("worst_symbols_by_inverse_return", []) or []))
        lines.append("By Movement Bucket")
        lines.extend(self._render_bucket_rows(analysis.get("by_movement_bucket", []) or []))
        lines.append("By Discovery Score Bucket")
        lines.extend(self._render_bucket_rows(analysis.get("by_discovery_bucket", []) or []))
        lines.append("Trade Count Comparison")
        lines.extend(self._render_bucket_rows(analysis.get("trade_count_comparison", []) or []))
        lines.append("Volume GBP Threshold Comparison")
        lines.extend(self._render_bucket_rows(analysis.get("volume_threshold_comparison", []) or []))
        lines.append("Signal Score Comparison")
        lines.extend(self._render_bucket_rows(analysis.get("signal_score_comparison", []) or []))
        return lines

    def _render_regime_comparison(self, rows: list[dict[str, Any]]) -> list[str]:
        lines = ["Replay Regime Comparison"]
        if not rows:
            lines.append("- none")
            return lines
        for item in rows:
            lines.append(
                f"- {item.get('strategy_id', '-')}"
                f" | regime={item.get('regime_label', '-')}"
                f" | movement={item.get('movement_label', '-')}"
                f" | interpretation={item.get('interpretation', '-')}"
                f" | proposals={item.get('proposal_count', 0)}"
                f" | outcomes={item.get('outcome_count', 0)}"
                f" | research_only=yes | paper_execution_allowed=no | live_execution_allowed=no"
            )
            warning = item.get("minimum_sample_warning")
            if warning:
                lines.append(f"- sample_warning={warning}")
            recommendation = item.get("checkpoint_recommendation") or {}
            if recommendation:
                lines.append(
                    f"- checkpoint_recommendation={recommendation.get('checkpoint_code', '-')}"
                    f" | avg_return_pct={recommendation.get('avg_return_pct', 0)}"
                    f" | win_rate={recommendation.get('win_rate', 0)}"
                    f" | basis={recommendation.get('reason', '-')}"
                )
            checkpoint_metrics = item.get("checkpoint_metrics", []) or []
            if checkpoint_metrics:
                for metric in checkpoint_metrics:
                    lines.append(
                        f"- checkpoint={metric.get('checkpoint_code', '-')}"
                        f" | outcomes={metric.get('outcomes', 0)}"
                        f" | win_rate={metric.get('win_rate', 0)}"
                        f" | avg_return_pct={metric.get('avg_return_pct', 0)}"
                    )
            else:
                lines.append("- checkpoints=none")
            lines.append(
                f"- best_symbols={self._format_ranked_symbols_inline(item.get('best_symbols', []) or [])}"
            )
            lines.append(
                f"- worst_symbols={self._format_ranked_symbols_inline(item.get('worst_symbols', []) or [])}"
            )
        return lines

    def _render_ranked_inverse_symbols(self, rows: list[dict[str, Any]]) -> list[str]:
        if not rows:
            return ["- none"]
        return [
            f"- {item.get('symbol', '-')}"
            f" | outcomes={item.get('outcomes', 0)}"
            f" | avg_inverse_return_pct={item.get('avg_inverse_return_pct', 0)}"
            for item in rows
        ]

    def _format_ranked_symbols_inline(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "none"
        return "; ".join(
            f"{item.get('symbol', '-')}:outcomes={item.get('outcomes', 0)},avg_return_pct={item.get('avg_return_pct', 0)}"
            for item in rows
        )

    def _render_bucket_rows(self, rows: list[dict[str, Any]]) -> list[str]:
        if not rows:
            return ["- none"]
        return [
            f"- {item.get('bucket', '-')}"
            f" | outcomes={item.get('outcomes', 0)}"
            f" | {self._format_checkpoint_summary_inline(item.get('checkpoint_summaries', []))}"
            for item in rows
        ]

    def _format_checkpoint_summary_inline(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "no_checkpoints"
        return "; ".join(
            (
                f"{item.get('checkpoint_code', '-')}:"
                f"win_rate={item.get('win_rate', 0)},"
                f"avg_return_pct={item.get('avg_realized_return_pct', 0)},"
                f"avg_mfe_pct={item.get('avg_max_favorable_excursion_pct', 0)},"
                f"avg_mae_pct={item.get('avg_max_adverse_excursion_pct', 0)}"
            )
            for item in rows
        )

    def _to_float(self, value: Any) -> float | None:
        try:
            if value is None or value == "":
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    def _to_int(self, value: Any) -> int | None:
        try:
            if value is None or value == "":
                return None
            return int(value)
        except (TypeError, ValueError):
            return None

    def _minimum_sample_warning(self, proposal_count: int) -> str | None:
        if proposal_count >= self.MINIMUM_REGIME_SAMPLE_PROPOSALS:
            return None
        return (
            f"minimum sample warning: proposals={proposal_count}"
            f" < {self.MINIMUM_REGIME_SAMPLE_PROPOSALS}"
        )

    def _checkpoint_recommendation(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not rows:
            return {}
        best = max(
            rows,
            key=lambda item: (
                float(item.get("avg_return_pct", 0) or 0),
                float(item.get("win_rate", 0) or 0),
                int(item.get("outcomes", 0) or 0),
                str(item.get("checkpoint_code", "") or ""),
            ),
        )
        return {
            "checkpoint_code": best.get("checkpoint_code", "-"),
            "avg_return_pct": best.get("avg_return_pct", 0),
            "win_rate": best.get("win_rate", 0),
            "reason": "highest_avg_return_then_win_rate",
        }


class ReplayComparisonReport:
    """Read-only comparison of replay-only crypto pullback regimes across runs."""
    CONTINUATION_COST_SCENARIOS = (
        ("optimistic", 10.0),
        ("moderate", 25.0),
        ("conservative", 48.0),
        ("harsh", 75.0),
    )

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)
        self.summary_report = ReplaySummaryReport(
            config=self.config,
            usage_ledger=self.usage_ledger,
        )

    def build_report(self, *, replay_limit: int = 12) -> dict[str, Any]:
        recent_ticks = self.usage_ledger.list_recent_tick_runs(limit=max(1, replay_limit * 8))
        replay_runs = [
            row
            for row in recent_ticks
            if self._is_historical_replay_run(row)
        ]
        replay_runs.sort(
            key=lambda row: row.get("started_at") or datetime.min.astimezone(),
            reverse=True,
        )
        selected_runs = replay_runs[: max(1, replay_limit)]
        return {
            "status": "ok",
            "backend": self.usage_ledger.backend,
            "replay_limit": max(1, replay_limit),
            "runs_considered": len(replay_runs),
            "simulation_assumptions": self._simulation_assumptions(),
            "regimes": {
                ReplaySummaryReport.PULLBACK_CONTINUATION_STRATEGY_ID: self._build_regime_rows(
                    selected_runs=selected_runs,
                    strategy_id=ReplaySummaryReport.PULLBACK_CONTINUATION_STRATEGY_ID,
                    best_symbol_key="best_symbols",
                    worst_symbol_key="worst_symbols",
                    proposal_threshold=ReplaySummaryReport.MINIMUM_REGIME_SAMPLE_PROPOSALS,
                ),
                ReplaySummaryReport.PULLBACK_EXTREME_REVERSAL_STRATEGY_ID: self._build_regime_rows(
                    selected_runs=selected_runs,
                    strategy_id=ReplaySummaryReport.PULLBACK_EXTREME_REVERSAL_STRATEGY_ID,
                    best_symbol_key="best_symbols",
                    worst_symbol_key="worst_symbols",
                    proposal_threshold=ReplaySummaryReport.MINIMUM_REGIME_SAMPLE_PROPOSALS,
                ),
            },
        }

    def render(self, *, replay_limit: int = 12) -> str:
        report = self.build_report(replay_limit=replay_limit)
        if report.get("status") != "ok":
            return (
                "Replay Comparison Report\n"
                f"Status: {report.get('status', 'unknown')}\n"
                f"Reason: {report.get('reason', '-')}"
            )
        lines = [
            "Replay Comparison Report",
            (
                f"backend={report.get('backend', '-')}"
                f" | replay_limit={report.get('replay_limit', 0)}"
                f" | runs_considered={report.get('runs_considered', 0)}"
            ),
        ]
        assumptions = report.get("simulation_assumptions", {}) or {}
        lines.append(
            "Continuation Simulation Assumptions"
        )
        lines.append(
            f"research_only=yes | fee_bps={assumptions.get('fee_bps', 0)} | slippage_bps={assumptions.get('slippage_bps', 0)} | spread_bps={assumptions.get('spread_bps', 0)}"
        )
        regimes = report.get("regimes", {}) or {}
        for strategy_id in (
            ReplaySummaryReport.PULLBACK_CONTINUATION_STRATEGY_ID,
            ReplaySummaryReport.PULLBACK_EXTREME_REVERSAL_STRATEGY_ID,
        ):
            section = regimes.get(strategy_id, {}) or {}
            lines.append(f"Regime: {strategy_id}")
            lines.append(
                f"research_only=yes | paper_execution_allowed=no | live_execution_allowed=no | windows={len(section.get('runs', []) or [])}"
            )
            rows = section.get("runs", []) or []
            if not rows:
                lines.append("- none")
                continue
            for item in rows:
                lines.append(
                    f"- replay_run_id={item.get('replay_run_id', '-')}"
                    f" | date_range={item.get('date_range', '-')}"
                    f" | timeframe={item.get('timeframe', '-')}"
                    f" | proposals={item.get('proposals', 0)}"
                    f" | outcomes={item.get('outcomes', 0)}"
                    f" | sample_size_sufficient={'yes' if item.get('sample_size_sufficient') else 'no'}"
                )
                for checkpoint_code in ("15m", "1h", "1d", "7d"):
                    metric = (item.get("checkpoint_metrics", {}) or {}).get(checkpoint_code, {}) or {}
                    lines.append(
                        f"- {checkpoint_code}"
                        f" | win_rate={metric.get('win_rate', 0)}"
                        f" | avg_return_pct={metric.get('avg_return_pct', 0)}"
                    )
                if item.get("sample_warning"):
                    lines.append(f"- sample_warning={item.get('sample_warning')}")
                lines.append(f"- best_symbols={item.get('best_symbols', 'none')}")
                lines.append(f"- worst_symbols={item.get('worst_symbols', 'none')}")
            if strategy_id == ReplaySummaryReport.PULLBACK_CONTINUATION_STRATEGY_ID:
                simulation_rows = section.get("continuation_simulation", []) or []
                lines.append("Continuation Simulation")
                if not simulation_rows:
                    lines.append("- none")
                else:
                    for item in simulation_rows:
                        lines.append(
                            f"- replay_run_id={item.get('replay_run_id', '-')}"
                            f" | date_range={item.get('date_range', '-')}"
                            f" | timeframe={item.get('timeframe', '-')}"
                            f" | research_only=yes | paper_execution_allowed=no | live_execution_allowed=no"
                        )
                        for checkpoint_code in ("15m", "1h", "1d", "7d"):
                            checkpoint = (item.get("by_checkpoint", {}) or {}).get(checkpoint_code, {}) or {}
                            lines.append(
                                f"- checkpoint={checkpoint_code}"
                                f" | proposals={checkpoint.get('proposals', 0)}"
                                f" | gross_inverse_return_pct={checkpoint.get('gross_inverse_return_pct', 0)}"
                                f" | estimated_fee_pct={checkpoint.get('estimated_fee_pct', 0)}"
                                f" | estimated_spread_slippage_pct={checkpoint.get('estimated_spread_slippage_pct', 0)}"
                                f" | net_inverse_return_pct={checkpoint.get('net_inverse_return_pct', 0)}"
                                f" | net_inverse_win_rate={checkpoint.get('net_inverse_win_rate', 0)}"
                                f" | avg_adverse_excursion_pct={checkpoint.get('avg_adverse_excursion_pct', 0)}"
                                f" | avg_favourable_excursion_pct={checkpoint.get('avg_favourable_excursion_pct', 0)}"
                                f" | worst_adverse_excursion_pct={checkpoint.get('worst_adverse_excursion_pct', 0)}"
                                f" | best_favourable_excursion_pct={checkpoint.get('best_favourable_excursion_pct', 0)}"
                            )
                        lines.append(
                            f"- by_symbol={self._simulation_group_inline(item.get('by_symbol', []) or [])}"
                        )
                        lines.append(
                            f"- by_movement_bucket={self._simulation_group_inline(item.get('by_movement_bucket', []) or [])}"
                        )
                        lines.append(
                            f"- by_signal_score_bucket={self._simulation_group_inline(item.get('by_signal_score_bucket', []) or [])}"
                        )
                sensitivity = section.get("cost_sensitivity", {}) or {}
                lines.append("Continuation Cost Sensitivity")
                consistency = sensitivity.get("consistency_by_scenario", []) or []
                if consistency:
                    for item in consistency:
                        lines.append(
                            f"- scenario={item.get('scenario', '-')}"
                            f" | total_cost_bps={item.get('total_cost_bps', 0)}"
                            f" | survives_consistently={'yes' if item.get('survives_consistently') else 'no'}"
                            f" | surviving_windows={item.get('surviving_windows', 0)}"
                            f" | total_windows={item.get('total_windows', 0)}"
                        )
                window_rows = sensitivity.get("windows", []) or []
                if not window_rows:
                    lines.append("- none")
                else:
                    for item in window_rows:
                        lines.append(
                            f"- replay_run_id={item.get('replay_run_id', '-')}"
                            f" | date_range={item.get('date_range', '-')}"
                            f" | timeframe={item.get('timeframe', '-')}"
                            f" | best_checkpoint_by_net_return={item.get('best_checkpoint_by_net_return', '-')}"
                            f" | research_only=yes | paper_execution_allowed=no | live_execution_allowed=no"
                        )
                        for checkpoint_code in ("15m", "1h", "1d", "7d"):
                            checkpoint = (item.get("by_checkpoint", {}) or {}).get(checkpoint_code, {}) or {}
                            if not checkpoint:
                                continue
                            lines.append(
                                f"- checkpoint={checkpoint_code}"
                                f" | break_even_total_cost_bps={checkpoint.get('break_even_total_cost_bps', 0)}"
                            )
                            for scenario in checkpoint.get("cost_scenarios", []) or []:
                                lines.append(
                                    f"- scenario={scenario.get('scenario', '-')}"
                                    f" | total_cost_bps={scenario.get('total_cost_bps', 0)}"
                                    f" | net_inverse_return_pct={scenario.get('net_inverse_return_pct', 0)}"
                                    f" | net_inverse_win_rate={scenario.get('net_inverse_win_rate', 0)}"
                                )
        return "\n".join(lines)

    def _build_regime_rows(
        self,
        *,
        selected_runs: list[dict[str, Any]],
        strategy_id: str,
        best_symbol_key: str,
        worst_symbol_key: str,
        proposal_threshold: int,
    ) -> dict[str, Any]:
        rows: list[dict[str, Any]] = []
        for run in selected_runs:
            replay_run_id = str(run.get("tick_id", "") or "")
            summary = self.summary_report.build_report(replay_run_id=replay_run_id)
            if summary.get("status") != "ok":
                continue
            regime_rows = summary.get("regime_comparison", []) or []
            regime = next(
                (
                    item
                    for item in regime_rows
                    if str(item.get("strategy_id", "") or "") == strategy_id
                ),
                {},
            )
            if not regime:
                continue
            state_snapshot = run.get("state_snapshot_json", {}) if isinstance(run, dict) else {}
            run_info = state_snapshot.get("run", {}) if isinstance(state_snapshot, dict) else {}
            checkpoint_metrics = {
                str(item.get("checkpoint_code", "") or ""): {
                    "win_rate": item.get("win_rate", 0),
                    "avg_return_pct": item.get("avg_return_pct", 0),
                }
                for item in (regime.get("checkpoint_metrics", []) or [])
            }
            rows.append(
                {
                    "replay_run_id": replay_run_id,
                    "date_range": self._date_range_label(run_info),
                    "timeframe": str(run_info.get("timeframe", "-") or "-"),
                    "proposals": int(regime.get("proposal_count", 0) or 0),
                    "outcomes": int(regime.get("outcome_count", 0) or 0),
                    "checkpoint_metrics": checkpoint_metrics,
                    "best_symbols": self._symbols_inline(regime.get(best_symbol_key, []) or []),
                    "worst_symbols": self._symbols_inline(regime.get(worst_symbol_key, []) or []),
                    "sample_size_sufficient": int(regime.get("proposal_count", 0) or 0) >= proposal_threshold,
                    "sample_warning": regime.get("minimum_sample_warning"),
                }
            )
        result: dict[str, Any] = {"runs": rows}
        if strategy_id == ReplaySummaryReport.PULLBACK_CONTINUATION_STRATEGY_ID:
            result["continuation_simulation"] = self._build_continuation_simulation_rows(
                selected_runs=selected_runs,
            )
            result["cost_sensitivity"] = self._build_continuation_cost_sensitivity(
                selected_runs=selected_runs,
            )
        return result

    def _is_historical_replay_run(self, row: dict[str, Any]) -> bool:
        snapshot = row.get("state_snapshot_json", {}) if isinstance(row, dict) else {}
        run_info = snapshot.get("run", {}) if isinstance(snapshot, dict) else {}
        return str(run_info.get("pipeline", "") or "") == "historical_replay"

    def _date_range_label(self, run_info: dict[str, Any]) -> str:
        start = run_info.get("range_start")
        end = run_info.get("range_end")
        if start and end:
            return f"{start} to {end}"
        return "-"

    def _symbols_inline(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "none"
        return "; ".join(
            f"{item.get('symbol', '-')}:outcomes={item.get('outcomes', 0)},avg_return_pct={item.get('avg_return_pct', 0)}"
            for item in rows
        )

    def _simulation_assumptions(self) -> dict[str, float]:
        return {
            "fee_bps": float(self.config.simulated_crypto_fee_bps),
            "slippage_bps": float(self.config.simulated_crypto_slippage_bps),
            "spread_bps": float(self.config.simulated_crypto_spread_bps),
        }

    def _build_continuation_simulation_rows(
        self,
        *,
        selected_runs: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for run in selected_runs:
            replay_run_id = str(run.get("tick_id", "") or "")
            summary = self.summary_report.build_report(replay_run_id=replay_run_id)
            if summary.get("status") != "ok":
                continue
            proposals, outcomes, proposals_by_id = self._continuation_source_rows(replay_run_id=replay_run_id)
            if not proposals and not outcomes:
                continue
            state_snapshot = run.get("state_snapshot_json", {}) if isinstance(run, dict) else {}
            run_info = state_snapshot.get("run", {}) if isinstance(state_snapshot, dict) else {}
            rows.append(
                {
                    "replay_run_id": replay_run_id,
                    "date_range": self._date_range_label(run_info),
                    "timeframe": str(run_info.get("timeframe", "-") or "-"),
                    "by_checkpoint": self._continuation_simulation_by_checkpoint(
                        proposals=proposals,
                        outcomes=outcomes,
                    ),
                    "by_symbol": self._continuation_simulation_group(
                        proposals=proposals,
                        outcomes=outcomes,
                        proposals_by_id=proposals_by_id,
                        group_type="symbol",
                    ),
                    "by_movement_bucket": self._continuation_simulation_group(
                        proposals=proposals,
                        outcomes=outcomes,
                        proposals_by_id=proposals_by_id,
                        group_type="movement_bucket",
                    ),
                    "by_signal_score_bucket": self._continuation_simulation_group(
                        proposals=proposals,
                        outcomes=outcomes,
                        proposals_by_id=proposals_by_id,
                        group_type="signal_score_bucket",
                    ),
                }
            )
        return rows

    def _build_continuation_cost_sensitivity(
        self,
        *,
        selected_runs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        windows: list[dict[str, Any]] = []
        for run in selected_runs:
            replay_run_id = str(run.get("tick_id", "") or "")
            proposals, outcomes, _ = self._continuation_source_rows(replay_run_id=replay_run_id)
            if not outcomes:
                continue
            state_snapshot = run.get("state_snapshot_json", {}) if isinstance(run, dict) else {}
            run_info = state_snapshot.get("run", {}) if isinstance(state_snapshot, dict) else {}
            by_checkpoint = self._continuation_cost_sensitivity_by_checkpoint(outcomes=outcomes)
            windows.append(
                {
                    "replay_run_id": replay_run_id,
                    "date_range": self._date_range_label(run_info),
                    "timeframe": str(run_info.get("timeframe", "-") or "-"),
                    "by_checkpoint": by_checkpoint,
                    "best_checkpoint_by_net_return": self._best_checkpoint_by_net_return(by_checkpoint),
                }
            )
        consistency_by_scenario = []
        for scenario_name, total_cost_bps in self.CONTINUATION_COST_SCENARIOS:
            surviving_windows = 0
            for item in windows:
                best_checkpoint = item.get("best_checkpoint_by_net_return", "-")
                checkpoint = (item.get("by_checkpoint", {}) or {}).get(best_checkpoint, {}) or {}
                scenarios = checkpoint.get("cost_scenarios", []) or []
                match = next(
                    (
                        row for row in scenarios
                        if str(row.get("scenario", "") or "") == scenario_name
                    ),
                    {},
                )
                if float(match.get("net_inverse_return_pct", 0) or 0) > 0:
                    surviving_windows += 1
            consistency_by_scenario.append(
                {
                    "scenario": scenario_name,
                    "total_cost_bps": total_cost_bps,
                    "survives_consistently": bool(windows) and surviving_windows == len(windows),
                    "surviving_windows": surviving_windows,
                    "total_windows": len(windows),
                }
            )
        return {
            "windows": windows,
            "consistency_by_scenario": consistency_by_scenario,
        }

    def _continuation_source_rows(
        self,
        *,
        replay_run_id: str,
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, dict[str, Any]]]:
        note_prefix = f"historical_replay:{replay_run_id}:"
        proposals = self.usage_ledger.list_shadow_trade_proposals_by_note_prefix(note_prefix=note_prefix)
        outcomes = self.usage_ledger.list_shadow_trade_outcomes_by_note_prefix(note_prefix=note_prefix)
        proposals_by_id = {
            str(item.get("proposal_id", "") or ""): item for item in proposals
        }
        pullback_proposals = [
            item
            for item in proposals
            if str(item.get("strategy_id", "") or "") == ReplaySummaryReport.PULLBACK_REVERSAL_STRATEGY_ID
        ]
        moderate_proposals = self.summary_report._filter_pullback_rows_by_bucket(
            proposals=pullback_proposals,
            proposals_by_id=proposals_by_id,
            allowed_buckets={
                "-0.15% to -0.30%",
                "-0.30% to -0.50%",
                "-0.50% to -1.00%",
            },
        )
        moderate_ids = {str(item.get("proposal_id", "") or "") for item in moderate_proposals}
        moderate_outcomes = [
            item
            for item in outcomes
            if str(item.get("strategy_id", "") or "") == ReplaySummaryReport.PULLBACK_REVERSAL_STRATEGY_ID
            and str(item.get("proposal_id", "") or "") in moderate_ids
        ]
        return moderate_proposals, moderate_outcomes, proposals_by_id

    def _continuation_simulation_by_checkpoint(
        self,
        *,
        proposals: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in outcomes:
            grouped[str(row.get("checkpoint_code", "") or "").lower()].append(row)
        proposal_ids_by_checkpoint: dict[str, set[str]] = defaultdict(set)
        for row in outcomes:
            checkpoint_code = str(row.get("checkpoint_code", "") or "").lower()
            proposal_ids_by_checkpoint[checkpoint_code].add(str(row.get("proposal_id", "") or ""))
        return {
            checkpoint_code: self._simulation_metrics(
                rows=rows,
                proposal_count=len(proposal_ids_by_checkpoint.get(checkpoint_code, set())),
            )
            for checkpoint_code, rows in sorted(grouped.items())
        }

    def _continuation_cost_sensitivity_by_checkpoint(
        self,
        *,
        outcomes: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in outcomes:
            grouped[str(row.get("checkpoint_code", "") or "").lower()].append(row)
        return {
            checkpoint_code: self._cost_sensitivity_metrics(rows=rows)
            for checkpoint_code, rows in sorted(grouped.items())
        }

    def _continuation_simulation_group(
        self,
        *,
        proposals: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
        proposals_by_id: dict[str, dict[str, Any]],
        group_type: str,
    ) -> list[dict[str, Any]]:
        proposal_context_by_id = {
            proposal_id: self.summary_report._proposal_context(proposal)
            for proposal_id, proposal in proposals_by_id.items()
        }
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        proposal_ids_by_group: dict[str, set[str]] = defaultdict(set)
        for row in outcomes:
            proposal_id = str(row.get("proposal_id", "") or "")
            context = proposal_context_by_id.get(proposal_id, {})
            if group_type == "symbol":
                label = str(row.get("symbol", context.get("symbol", "-")) or "-")
            elif group_type == "movement_bucket":
                label = self.summary_report._movement_bucket(context.get("movement_pct"))
            else:
                label = self.summary_report._signal_score_bucket(context.get("signal_score"))
            grouped[label].append(row)
            proposal_ids_by_group[label].add(proposal_id)
        items = [
            {
                "label": label,
                **self._simulation_metrics(
                    rows=rows,
                    proposal_count=len(proposal_ids_by_group.get(label, set())),
                ),
            }
            for label, rows in sorted(grouped.items())
        ]
        return items

    def _simulation_metrics(
        self,
        *,
        rows: list[dict[str, Any]],
        proposal_count: int,
    ) -> dict[str, Any]:
        gross_returns: list[float] = []
        net_returns: list[float] = []
        favourable_excursions: list[float] = []
        adverse_excursions: list[float] = []
        estimated_fee_pct = self._round_trip_fee_pct()
        estimated_spread_slippage_pct = self._round_trip_spread_slippage_pct()
        for row in rows:
            realized = self.summary_report._to_float(row.get("realized_return_pct"))
            mfe = self.summary_report._to_float(row.get("max_favorable_excursion_pct"))
            mae = self.summary_report._to_float(row.get("max_adverse_excursion_pct"))
            if realized is not None:
                gross = -realized
                gross_returns.append(gross)
                net_returns.append(gross - estimated_fee_pct - estimated_spread_slippage_pct)
            if mae is not None:
                favourable_excursions.append(-mae)
            if mfe is not None:
                adverse_excursions.append(-mfe)
        return {
            "proposals": proposal_count,
            "outcomes": len(rows),
            "gross_inverse_return_pct": round(mean(gross_returns), 6) if gross_returns else 0.0,
            "estimated_fee_pct": round(estimated_fee_pct, 6),
            "estimated_spread_slippage_pct": round(estimated_spread_slippage_pct, 6),
            "net_inverse_return_pct": round(mean(net_returns), 6) if net_returns else 0.0,
            "net_inverse_win_rate": round(
                sum(1 for value in net_returns if value > 0) / len(net_returns),
                6,
            )
            if net_returns
            else 0.0,
            "avg_adverse_excursion_pct": round(mean(adverse_excursions), 6) if adverse_excursions else 0.0,
            "avg_favourable_excursion_pct": round(mean(favourable_excursions), 6) if favourable_excursions else 0.0,
            "worst_adverse_excursion_pct": round(min(adverse_excursions), 6) if adverse_excursions else 0.0,
            "best_favourable_excursion_pct": round(max(favourable_excursions), 6) if favourable_excursions else 0.0,
        }

    def _cost_sensitivity_metrics(self, *, rows: list[dict[str, Any]]) -> dict[str, Any]:
        gross_returns = [
            -realized
            for realized in (
                self.summary_report._to_float(row.get("realized_return_pct")) for row in rows
            )
            if realized is not None
        ]
        cost_scenarios = []
        for scenario_name, total_cost_bps in self.CONTINUATION_COST_SCENARIOS:
            total_cost_pct = total_cost_bps / 100.0
            net_returns = [value - total_cost_pct for value in gross_returns]
            cost_scenarios.append(
                {
                    "scenario": scenario_name,
                    "total_cost_bps": total_cost_bps,
                    "net_inverse_return_pct": round(mean(net_returns), 6) if net_returns else 0.0,
                    "net_inverse_win_rate": round(
                        sum(1 for value in net_returns if value > 0) / len(net_returns),
                        6,
                    )
                    if net_returns
                    else 0.0,
                }
            )
        return {
            "break_even_total_cost_bps": round((mean(gross_returns) if gross_returns else 0.0) * 100.0, 6),
            "cost_scenarios": cost_scenarios,
        }

    def _best_checkpoint_by_net_return(self, by_checkpoint: dict[str, dict[str, Any]]) -> str:
        best_checkpoint = "-"
        best_value = float("-inf")
        for checkpoint_code, metrics in by_checkpoint.items():
            moderate = next(
                (
                    row for row in (metrics.get("cost_scenarios", []) or [])
                    if str(row.get("scenario", "") or "") == "moderate"
                ),
                {},
            )
            value = float(moderate.get("net_inverse_return_pct", 0) or 0)
            if value > best_value:
                best_value = value
                best_checkpoint = checkpoint_code
        return best_checkpoint

    def _round_trip_fee_pct(self) -> float:
        return (float(self.config.simulated_crypto_fee_bps) * 2.0) / 100.0

    def _round_trip_spread_slippage_pct(self) -> float:
        spread_pct = float(self.config.simulated_crypto_spread_bps) / 100.0
        slippage_pct = (float(self.config.simulated_crypto_slippage_bps) * 2.0) / 100.0
        return spread_pct + slippage_pct

    def _simulation_group_inline(self, rows: list[dict[str, Any]]) -> str:
        if not rows:
            return "none"
        return "; ".join(
            f"{item.get('label', '-')}:gross={item.get('gross_inverse_return_pct', 0)},net={item.get('net_inverse_return_pct', 0)},net_win_rate={item.get('net_inverse_win_rate', 0)}"
            for item in rows
        )
