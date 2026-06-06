from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from math import floor
from statistics import mean
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


@dataclass(frozen=True, slots=True)
class ThresholdGene:
    base_threshold: float
    starvation_ticks: int
    starvation_step: float
    overactivity_ticks: int
    tighten_step: float
    target_low: int
    target_high: int


@dataclass(frozen=True, slots=True)
class CandidateSignal:
    strategy_id: str
    symbol: str
    asset_class: str
    signal_score: float
    target_return_pct: float
    fitness_score: float
    checkpoints_evaluated: int
    paper_allowed: bool
    proposal_viable: bool


@dataclass(frozen=True, slots=True)
class TickSignals:
    tick_id: str
    started_at: Any
    raw_count: int
    actual_survivors: int
    actual_proposals: int
    candidate_signals: tuple[CandidateSignal, ...]


class ThresholdAdvisor:
    """Genetic adviser plus guarded paper-only adaptive threshold controller."""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_advice(
        self,
        *,
        tick_limit: int = 720,
        population_size: int = 44,
        generations: int = 28,
        seed: int = 17011,
        current_threshold: float | None = None,
    ) -> dict[str, Any]:
        active_threshold = self._round_threshold(
            float(
                self.config.strategy_allocation_suppress_threshold
                if current_threshold is None
                else current_threshold
            )
        )
        ticks = self._load_tick_signals(limit=tick_limit)
        if len(ticks) < 20:
            return self._empty_advice(
                tick_count=len(ticks),
                reason="Not enough tick history with raw signal diagnostics for GA advice.",
            )

        train_size = max(12, int(len(ticks) * 0.7))
        if len(ticks) - train_size < 6:
            train_size = max(1, len(ticks) - 6)
        train_ticks = ticks[:train_size]
        test_ticks = ticks[train_size:]

        rng = random.Random(seed)
        seed_genes = self._seed_genes(active_threshold)
        population_target = max(8, population_size)
        random_count = max(0, population_target - len(seed_genes))
        population = list(seed_genes)
        population.extend(self._random_gene(rng) for _ in range(random_count))
        best_gene = population[0]
        best_score = float("-inf")

        for _ in range(max(1, generations)):
            scored = [
                (self._evaluate_gene(gene, train_ticks)["score"], gene)
                for gene in population
            ]
            scored.sort(key=lambda item: item[0], reverse=True)
            if scored[0][0] > best_score:
                best_score = scored[0][0]
                best_gene = scored[0][1]

            elites = [gene for _, gene in scored[: max(2, len(scored) // 5)]]
            next_population = list(elites)
            while len(next_population) < len(population):
                left = rng.choice(elites)
                right = rng.choice(elites)
                child = self._mutate_gene(self._crossover_gene(left, right, rng), rng)
                next_population.append(child)
            population = next_population

        train_result = self._evaluate_gene(best_gene, train_ticks)
        test_result = self._evaluate_gene(best_gene, test_ticks or train_ticks)
        all_result = self._evaluate_gene(best_gene, ticks)
        recommended_threshold = self._round_threshold(all_result["ending_threshold"])
        delta = round(recommended_threshold - active_threshold, 3)
        action = "hold"
        if delta <= -0.049:
            action = "loosen"
        elif delta >= 0.049:
            action = "tighten"

        confidence = self._confidence(
            train_result=train_result,
            test_result=test_result,
            all_result=all_result,
            tick_count=len(ticks),
            action=action,
        )

        return {
            "status": "ok",
            "mode": "recommendation_only",
            "current_threshold": active_threshold,
            "recommended_threshold": recommended_threshold,
            "delta": delta,
            "action": action,
            "confidence": confidence,
            "hard_floor": self._advisor_floor(),
            "hard_ceiling": self._advisor_ceiling(),
            "tick_count": len(ticks),
            "train_tick_count": len(train_ticks),
            "test_tick_count": len(test_ticks),
            "gene": {
                "base_threshold": self._round_threshold(best_gene.base_threshold),
                "starvation_ticks": best_gene.starvation_ticks,
                "starvation_step": round(best_gene.starvation_step, 3),
                "overactivity_ticks": best_gene.overactivity_ticks,
                "tighten_step": round(best_gene.tighten_step, 3),
                "target_low": best_gene.target_low,
                "target_high": best_gene.target_high,
            },
            "train": self._public_result(train_result),
            "test": self._public_result(test_result),
            "all": self._public_result(all_result),
            "reason": self._reason(
                action=action,
                current_threshold=active_threshold,
                recommended_threshold=recommended_threshold,
                result=all_result,
            ),
        }

    def effective_threshold(
        self,
        *,
        tick_id: str,
        now: datetime,
        current_signal_preview: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        base_threshold = self._round_threshold(
            float(self.config.strategy_allocation_suppress_threshold)
        )
        hard_floor = self._round_threshold(float(self.config.strategy_threshold_adaptive_floor))
        hard_ceiling = self._round_threshold(float(self.config.strategy_threshold_adaptive_ceiling))
        if hard_floor > hard_ceiling:
            hard_floor, hard_ceiling = hard_ceiling, hard_floor
        band_width = max(
            0.0,
            float(self.config.strategy_threshold_adaptive_band_width),
        )
        max_step = max(
            0.0,
            float(self.config.strategy_threshold_adaptive_max_step),
        )
        min_confidence = (
            str(self.config.strategy_threshold_adaptive_min_confidence or "medium")
            .strip()
            .lower()
        )
        min_ticks = max(0, int(self.config.strategy_threshold_adaptive_min_ticks))
        cooldown_minutes = max(
            0,
            int(self.config.strategy_threshold_adaptive_cooldown_minutes),
        )

        state = self.usage_ledger.get_strategy_threshold_adaptive_state()
        state_threshold = _as_float((state or {}).get("effective_threshold"))
        if state_threshold is not None and state_threshold < -7.00:
            state_threshold = -7.00
        state_floor = (
            min(hard_floor, state_threshold)
            if state_threshold is not None
            else hard_floor
        )
        current_effective = self._clamp_to_range(
            state_threshold if state_threshold is not None else base_threshold,
            floor=state_floor,
            ceiling=hard_ceiling,
        )

        base_result = {
            "enabled": bool(self.config.strategy_threshold_adaptive_enabled),
            "mode": "adaptive_paper_only"
            if self.config.strategy_threshold_adaptive_enabled
            else "fixed_config",
            "base_threshold": base_threshold,
            "effective_threshold": current_effective,
            "previous_threshold": current_effective,
            "floor": hard_floor,
            "ceiling": hard_ceiling,
            "hard_floor": hard_floor,
            "hard_ceiling": hard_ceiling,
            "band_width": round(band_width, 3),
            "cliff_safety_gap": round(
                max(0.0, float(self.config.strategy_threshold_adaptive_cliff_safety_gap)),
                3,
            ),
            "max_step": round(max_step, 3),
            "min_confidence": min_confidence,
            "cooldown_minutes": cooldown_minutes,
            "min_ticks": min_ticks,
            "applied": False,
            "source_tick_id": tick_id,
        }

        if not self.config.strategy_threshold_adaptive_enabled:
            return {
                **base_result,
                "reason": "Adaptive threshold controller is disabled; using fixed config threshold.",
            }

        advice = self.build_advice(
            tick_limit=720,
            population_size=32,
            generations=18,
            current_threshold=current_effective,
        )
        result = {
            **base_result,
            "advice": advice,
            "advice_status": advice.get("status", "unknown"),
            "action": advice.get("action", "hold"),
            "confidence": advice.get("confidence", "low"),
            "recommended_threshold": advice.get(
                "recommended_threshold",
                current_effective,
            ),
        }

        if advice.get("status") != "ok":
            return {
                **result,
                "reason": advice.get(
                    "reason",
                    "GA advice is unavailable; holding the last effective threshold.",
                ),
            }

        cliff_governor = self._current_cliff_governor(
            current_signal_preview=current_signal_preview or [],
            current_effective=current_effective,
            hard_floor=hard_floor,
            hard_ceiling=hard_ceiling,
            max_step=max_step,
            safety_gap=max(
                0.0,
                float(self.config.strategy_threshold_adaptive_cliff_safety_gap),
            ),
        )
        result["cliff_governor"] = cliff_governor
        if cliff_governor.get("action") == "loosen":
            new_threshold = float(cliff_governor["new_threshold"])
            reason = (
                "Cliff governor loosen: allowed cliff "
                f"{float(cliff_governor['allowed_cliff']):.3f}, "
                f"nearest blocked cliff "
                f"{self._fmt_optional_threshold(cliff_governor.get('nearest_blocked_cliff'))}, "
                f"moved from {current_effective:.2f} to {new_threshold:.2f} "
                "without admitting blocked signals."
            )
            persisted = {
                **result,
                "effective_threshold": new_threshold,
                "previous_threshold": current_effective,
                "applied": True,
                "action": "loosen",
                "confidence": "medium",
                "recommended_threshold": cliff_governor.get("candidate_threshold"),
                "reason": reason,
            }
            self.usage_ledger.record_strategy_threshold_adaptive_state(
                effective_threshold=new_threshold,
                updated_at=now,
                source_tick_id=tick_id,
                reason=reason,
                advice={
                    **advice,
                    "cliff_governor": cliff_governor,
                    "mode": "current_tick_cliff_governor",
                },
            )
            return persisted

        confidence = str(advice.get("confidence", "low")).lower()
        if self._confidence_rank(confidence) < self._confidence_rank(min_confidence):
            return {
                **result,
                "reason": (
                    f"GA confidence {confidence} is below the configured "
                    f"{min_confidence} minimum; holding threshold."
                ),
            }

        tick_count = int(advice.get("tick_count", 0) or 0)
        if tick_count < min_ticks:
            return {
                **result,
                "reason": (
                    f"GA evidence has {tick_count} ticks; waiting for at least "
                    f"{min_ticks} before adapting."
                ),
            }

        action = str(advice.get("action", "hold"))
        recommended = self._clamp_to_range(
            float(advice.get("recommended_threshold", current_effective) or current_effective),
            floor=hard_floor,
            ceiling=hard_ceiling,
        )
        local_floor = self._clamp_to_range(
            recommended - band_width,
            floor=hard_floor,
            ceiling=hard_ceiling,
        )
        local_ceiling = self._clamp_to_range(
            recommended + band_width,
            floor=hard_floor,
            ceiling=hard_ceiling,
        )
        result = {
            **result,
            "local_floor": local_floor,
            "local_ceiling": local_ceiling,
            "local_band_center": recommended,
        }
        catch_up_allowed = self._catch_up_allowed(
            advice=advice,
            action=action,
            current_threshold=current_effective,
            recommended_threshold=recommended,
        )

        updated_at = (state or {}).get("updated_at")
        if isinstance(updated_at, datetime) and not catch_up_allowed:
            elapsed = now - updated_at
            if elapsed < timedelta(minutes=cooldown_minutes):
                remaining = timedelta(minutes=cooldown_minutes) - elapsed
                return {
                    **result,
                    "last_updated_at": updated_at.isoformat(),
                    "reason": (
                        "Adaptive threshold cooldown is active; "
                        f"about {max(0, int(remaining.total_seconds() // 60))} minutes remain."
                    ),
                }

        new_threshold = current_effective
        if action == "loosen" and recommended < current_effective:
            new_threshold = max(current_effective - max_step, recommended, hard_floor)
        elif action == "tighten" and recommended > current_effective:
            new_threshold = min(current_effective + max_step, recommended, hard_ceiling)
        new_threshold = self._clamp_to_range(
            new_threshold,
            floor=hard_floor,
            ceiling=hard_ceiling,
        )

        if new_threshold == current_effective:
            return {
                **result,
                "effective_threshold": current_effective,
                "reason": "GA action does not require an in-band threshold change right now.",
            }

        reason = (
            f"Adaptive {action}: GA {confidence} confidence recommends "
            f"{recommended:.2f}; moved from {current_effective:.2f} to "
            f"{new_threshold:.2f} within paper-only rails."
        )
        persisted = {
            **result,
            "effective_threshold": new_threshold,
            "previous_threshold": current_effective,
            "applied": True,
            "catch_up_allowed": catch_up_allowed,
            "reason": reason,
        }
        self.usage_ledger.record_strategy_threshold_adaptive_state(
            effective_threshold=new_threshold,
            updated_at=now,
            source_tick_id=tick_id,
            reason=reason,
            advice=advice,
        )
        return persisted

    def _current_cliff_governor(
        self,
        *,
        current_signal_preview: list[dict[str, Any]],
        current_effective: float,
        hard_floor: float,
        hard_ceiling: float,
        max_step: float,
        safety_gap: float,
    ) -> dict[str, Any]:
        candidate_signals = [
            signal
            for signal in (
                self._candidate_signal_from_preview(item)
                for item in current_signal_preview
                if isinstance(item, dict)
            )
            if signal is not None
        ]
        if not candidate_signals:
            return {
                "status": "no_current_signals",
                "action": "hold",
                "reason": "No current annotated signals are available for cliff governance.",
            }

        tradeable_allowed = [
            signal
            for signal in candidate_signals
            if signal.paper_allowed
            and signal.proposal_viable
            and signal.checkpoints_evaluated
            >= int(self.config.strategy_allocation_min_checkpoints)
        ]
        if not tradeable_allowed:
            return {
                "status": "no_tradeable_allowed_cliff",
                "action": "hold",
                "reason": "No current paper-allowed proposal-viable signals are present.",
            }

        allowed_cliff_signal = max(
            tradeable_allowed,
            key=lambda signal: signal.fitness_score,
        )
        allowed_cliff = allowed_cliff_signal.fitness_score
        candidate_threshold = self._threshold_below_score(allowed_cliff)
        if candidate_threshold >= current_effective:
            return {
                "status": "already_admitted",
                "action": "hold",
                "allowed_cliff": round(allowed_cliff, 6),
                "candidate_threshold": candidate_threshold,
                "reason": "The current threshold already admits the best allowed cliff.",
            }

        blocked_signals = [
            signal
            for signal in candidate_signals
            if not (
                signal.paper_allowed
                and signal.proposal_viable
                and signal.checkpoints_evaluated
                >= int(self.config.strategy_allocation_min_checkpoints)
            )
        ]
        nearest_blocked_cliff = (
            max((signal.fitness_score for signal in blocked_signals), default=None)
        )
        if nearest_blocked_cliff is not None:
            minimum_safe_threshold = self._round_threshold(
                nearest_blocked_cliff + safety_gap
            )
            if candidate_threshold < minimum_safe_threshold:
                return {
                    "status": "blocked_cliff_too_close",
                    "action": "hold",
                    "allowed_cliff": round(allowed_cliff, 6),
                    "candidate_threshold": candidate_threshold,
                    "nearest_blocked_cliff": round(nearest_blocked_cliff, 6),
                    "minimum_safe_threshold": minimum_safe_threshold,
                    "safety_gap": round(safety_gap, 3),
                    "reason": "The allowed cliff is too close to a blocked/disallowed cliff.",
                }
        elif candidate_threshold < hard_floor:
            return {
                "status": "below_static_floor_without_blocked_reference",
                "action": "hold",
                "allowed_cliff": round(allowed_cliff, 6),
                "candidate_threshold": candidate_threshold,
                "floor": hard_floor,
                "reason": "The allowed cliff is below the static floor and no blocked cliff is visible to bound the move.",
            }

        if max_step <= 0:
            return {
                "status": "max_step_zero",
                "action": "hold",
                "allowed_cliff": round(allowed_cliff, 6),
                "candidate_threshold": candidate_threshold,
                "reason": "Adaptive max step is zero, so the cliff governor cannot move.",
            }

        new_threshold = max(
            current_effective - max_step,
            candidate_threshold,
        )
        new_threshold = self._clamp_to_range(
            new_threshold,
            floor=min(hard_floor, candidate_threshold),
            ceiling=hard_ceiling,
        )
        if new_threshold == current_effective:
            return {
                "status": "no_step_needed",
                "action": "hold",
                "allowed_cliff": round(allowed_cliff, 6),
                "candidate_threshold": candidate_threshold,
                "nearest_blocked_cliff": (
                    round(nearest_blocked_cliff, 6)
                    if nearest_blocked_cliff is not None
                    else None
                ),
                "reason": "The candidate threshold does not require a new step.",
            }

        return {
            "status": "clean_allowed_cliff",
            "action": "loosen",
            "allowed_strategy": allowed_cliff_signal.strategy_id,
            "allowed_symbol": allowed_cliff_signal.symbol,
            "allowed_cliff": round(allowed_cliff, 6),
            "candidate_threshold": candidate_threshold,
            "new_threshold": new_threshold,
            "previous_threshold": current_effective,
            "nearest_blocked_cliff": (
                round(nearest_blocked_cliff, 6)
                if nearest_blocked_cliff is not None
                else None
            ),
            "safety_gap": round(safety_gap, 3),
            "tradeable_allowed_count": len(tradeable_allowed),
            "blocked_count": len(blocked_signals),
            "reason": "A clean current allowed-strategy cliff can be followed safely.",
        }

    def render(self, *, advice: dict[str, Any] | None = None) -> str:
        advice = advice or self.build_advice()
        if advice.get("status") != "ok":
            return (
                "GA Threshold Advice\n"
                f"Status: {advice.get('status', 'unknown')}\n"
                f"Reason: {advice.get('reason', '-')}"
            )

        gene = advice.get("gene", {})
        all_result = advice.get("all", {})
        train_result = advice.get("train", {})
        test_result = advice.get("test", {})
        lines = [
            "GA Threshold Advice",
            (
                "Recommendation: "
                f"{advice['action']} | current={advice['current_threshold']:.2f} | "
                f"recommended={advice['recommended_threshold']:.2f} | "
                f"confidence={advice['confidence']}"
            ),
            f"Reason: {advice.get('reason', '-')}",
            (
                "Hard rails: "
                f"{advice['hard_ceiling']:.2f} to {advice['hard_floor']:.2f} | "
                "mode=recommendation_only"
            ),
            (
                "Evidence: "
                f"ticks={advice['tick_count']} | train={advice['train_tick_count']} | "
                f"test={advice['test_tick_count']}"
            ),
            (
                "Evolved policy: "
                f"base={float(gene.get('base_threshold', 0)):.2f} | "
                f"starve={gene.get('starvation_ticks')} ticks x "
                f"{float(gene.get('starvation_step', 0)):.2f} | "
                f"overactive={gene.get('overactivity_ticks')} ticks x "
                f"{float(gene.get('tighten_step', 0)):.2f} | "
                f"target={gene.get('target_low')}-{gene.get('target_high')} survivors/tick"
            ),
            (
                "Train score: "
                f"{float(train_result.get('score', 0)):.2f} | "
                f"avg tradeable={float(train_result.get('avg_tradeable_survivors', 0)):.2f} | "
                f"avg survivors={float(train_result.get('avg_survivors', 0)):.2f} | "
                f"flatline ticks={int(train_result.get('flatline_ticks', 0))}"
            ),
            (
                "Test score: "
                f"{float(test_result.get('score', 0)):.2f} | "
                f"avg tradeable={float(test_result.get('avg_tradeable_survivors', 0)):.2f} | "
                f"avg survivors={float(test_result.get('avg_survivors', 0)):.2f} | "
                f"flatline ticks={int(test_result.get('flatline_ticks', 0))}"
            ),
            (
                "All-window result: "
                f"ending_threshold={float(all_result.get('ending_threshold', 0)):.2f} | "
                f"avg tradeable fitness={float(all_result.get('avg_tradeable_fitness', 0)):.2f} | "
                f"non-tradeable survivors={int(all_result.get('non_tradeable_survivors', 0))}"
            ),
        ]
        return "\n".join(lines)

    def _load_tick_signals(self, *, limit: int) -> list[TickSignals]:
        rows = self.usage_ledger.list_recent_tick_runs(limit=max(24, limit * 5))
        ticks: list[TickSignals] = []
        for row in reversed(rows):
            if row.get("status") != "ok":
                continue
            snapshot = _as_dict(row.get("state_snapshot_json"))
            signals_state = _as_dict(snapshot.get("strategy_signals"))
            allocation = _as_dict(signals_state.get("allocation"))
            raw_preview = _as_list(signals_state.get("raw_signal_preview"))
            if not raw_preview:
                raw_preview = _as_list(allocation.get("raw_signals"))
            candidate_signals = tuple(
                signal
                for signal in (
                    self._candidate_signal_from_preview(item)
                    for item in raw_preview
                    if isinstance(item, dict)
                )
                if signal is not None
            )
            raw_count = int(allocation.get("signals_in", len(raw_preview)) or len(raw_preview))
            if raw_count <= 0 or not candidate_signals:
                continue
            shadow = _as_dict(snapshot.get("shadow_trade_proposals"))
            ticks.append(
                TickSignals(
                    tick_id=str(row.get("tick_id", "")),
                    started_at=row.get("started_at"),
                    raw_count=raw_count,
                    actual_survivors=int(
                        allocation.get(
                            "signals_out",
                            signals_state.get("signals_generated", 0),
                        )
                        or 0
                    ),
                    actual_proposals=int(shadow.get("proposals_created", 0) or 0),
                    candidate_signals=candidate_signals,
                )
            )
        return ticks[-limit:]

    def _candidate_signal_from_preview(
        self,
        item: dict[str, Any],
    ) -> CandidateSignal | None:
        fitness_score = _as_float(item.get("fitness_composite_score"))
        if fitness_score is None:
            return None
        strategy_id = str(item.get("strategy_id", "")).strip()
        allowed_strategies = {
            str(value).strip().lower()
            for value in self.config.paper_execution_allowed_strategies
            if str(value).strip()
        }
        paper_allowed = (
            strategy_id.lower() in allowed_strategies
            if allowed_strategies
            else True
        )
        signal_score = _as_float(item.get("signal_score")) or 0.0
        target_return_pct = _as_float(item.get("target_return_pct")) or 0.0
        proposal_viable = (
            paper_allowed
            and signal_score >= float(self.config.shadow_min_opportunity_score)
            and target_return_pct >= self._paper_min_projected_gain_pct(item)
        )
        return CandidateSignal(
            strategy_id=strategy_id,
            symbol=str(item.get("symbol", "")).upper(),
            asset_class=str(item.get("asset_class", "")),
            signal_score=signal_score,
            target_return_pct=target_return_pct,
            fitness_score=fitness_score,
            checkpoints_evaluated=int(item.get("fitness_checkpoints_evaluated", 0) or 0),
            paper_allowed=paper_allowed,
            proposal_viable=proposal_viable,
        )

    def _paper_min_projected_gain_pct(self, item: dict[str, Any]) -> float:
        asset_class = str(item.get("asset_class", "")).strip().lower()
        if asset_class == "crypto":
            return float(self.config.paper_execution_crypto_min_projected_gain_pct)
        return float(self.config.paper_execution_min_projected_gain_pct)

    def _evaluate_gene(
        self,
        gene: ThresholdGene,
        ticks: list[TickSignals],
    ) -> dict[str, Any]:
        threshold = self._clamp_threshold(gene.base_threshold)
        starvation_streak = 0
        overactivity_streak = 0
        survivors_by_tick: list[int] = []
        tradeable_by_tick: list[int] = []
        allowed_fitness: list[float] = []
        tradeable_fitness: list[float] = []
        threshold_changes = 0
        flatline_ticks = 0
        overactive_ticks = 0
        tradeable_ticks = 0
        non_tradeable_survivors = 0
        score = 0.0

        for tick in ticks:
            allowed = [
                signal
                for signal in tick.candidate_signals
                if signal.fitness_score > threshold
            ]
            tradeable = [signal for signal in allowed if signal.proposal_viable]
            survivor_count = len(allowed)
            tradeable_count = len(tradeable)
            survivors_by_tick.append(survivor_count)
            tradeable_by_tick.append(tradeable_count)
            allowed_fitness.extend(signal.fitness_score for signal in allowed)
            tradeable_fitness.extend(signal.fitness_score for signal in tradeable)
            non_tradeable_survivors += survivor_count - tradeable_count
            if tradeable_count > 0:
                tradeable_ticks += 1

            if tradeable_count == 0:
                flatline_ticks += 1
                starvation_streak += 1
                overactivity_streak = 0
                score -= 1.75
                if survivor_count > 0:
                    score -= 0.9 * survivor_count
            elif gene.target_low <= tradeable_count <= gene.target_high:
                starvation_streak = 0
                overactivity_streak = 0
                score += 3.25
            elif tradeable_count < gene.target_low:
                starvation_streak += 1
                overactivity_streak = 0
                score += 0.4
            else:
                overactive_ticks += 1
                overactivity_streak += 1
                starvation_streak = 0
                score -= 0.9 * (tradeable_count - gene.target_high)

            if non_tradeable_survivors:
                score -= (survivor_count - tradeable_count) * 0.45

            if tradeable:
                avg_tradeable = mean(signal.fitness_score for signal in tradeable)
                score += max(-2.5, min(2.5, avg_tradeable / 3.0))
                weak_tradeable = [
                    signal for signal in tradeable if signal.fitness_score < -6.0
                ]
                score -= len(weak_tradeable) * 0.35
            elif allowed:
                avg_allowed = mean(signal.fitness_score for signal in allowed)
                score += max(-2.0, min(2.0, avg_allowed / 4.0))
                weak_allowed = [
                    signal for signal in allowed if signal.fitness_score < -6.0
                ]
                score -= len(weak_allowed) * 2.5

            if starvation_streak >= gene.starvation_ticks:
                new_threshold = self._clamp_threshold(threshold - gene.starvation_step)
                if new_threshold != threshold:
                    threshold_changes += 1
                threshold = new_threshold
                starvation_streak = 0
            elif overactivity_streak >= gene.overactivity_ticks:
                new_threshold = self._clamp_threshold(threshold + gene.tighten_step)
                if new_threshold != threshold:
                    threshold_changes += 1
                threshold = new_threshold
                overactivity_streak = 0

        score -= threshold_changes * 0.35
        avg_survivors = mean(survivors_by_tick) if survivors_by_tick else 0.0
        avg_tradeable_survivors = mean(tradeable_by_tick) if tradeable_by_tick else 0.0
        avg_allowed_fitness = mean(allowed_fitness) if allowed_fitness else 0.0
        avg_tradeable_fitness = mean(tradeable_fitness) if tradeable_fitness else 0.0
        return {
            "score": round(score, 6),
            "ending_threshold": self._round_threshold(threshold),
            "avg_survivors": round(avg_survivors, 6),
            "avg_tradeable_survivors": round(avg_tradeable_survivors, 6),
            "avg_allowed_fitness": round(avg_allowed_fitness, 6),
            "avg_tradeable_fitness": round(avg_tradeable_fitness, 6),
            "flatline_ticks": flatline_ticks,
            "overactive_ticks": overactive_ticks,
            "tradeable_ticks": tradeable_ticks,
            "non_tradeable_survivors": non_tradeable_survivors,
            "threshold_changes": threshold_changes,
            "tick_count": len(ticks),
        }

    def _random_gene(self, rng: random.Random) -> ThresholdGene:
        target_low = rng.randint(1, 2)
        return ThresholdGene(
            base_threshold=self._round_threshold(
                rng.uniform(self._advisor_floor(), -5.15)
            ),
            starvation_ticks=rng.randint(2, 10),
            starvation_step=rng.choice((0.05, 0.075, 0.1, 0.125, 0.15)),
            overactivity_ticks=rng.randint(2, 10),
            tighten_step=rng.choice((0.05, 0.075, 0.1, 0.125, 0.15)),
            target_low=target_low,
            target_high=rng.randint(max(2, target_low), 4),
        )

    def _seed_genes(self, active_threshold: float) -> list[ThresholdGene]:
        floor = self._advisor_floor()
        ceiling = self._advisor_ceiling()
        thresholds: list[float] = []
        value = self._clamp_threshold(active_threshold)
        while value >= floor:
            thresholds.append(self._round_threshold(value))
            value = self._round_threshold(value - 0.05)
        value = self._round_threshold(active_threshold + 0.05)
        while value <= min(ceiling, active_threshold + 0.2):
            thresholds.append(self._round_threshold(value))
            value = self._round_threshold(value + 0.05)

        genes: list[ThresholdGene] = []
        seen: set[tuple[float, int, int]] = set()
        for threshold in thresholds:
            for target_high in (2, 4):
                key = (threshold, 1, target_high)
                if key in seen:
                    continue
                seen.add(key)
                genes.append(
                    ThresholdGene(
                        base_threshold=threshold,
                        starvation_ticks=4,
                        starvation_step=0.05,
                        overactivity_ticks=4,
                        tighten_step=0.05,
                        target_low=1,
                        target_high=target_high,
                    )
                )
        return genes

    def _crossover_gene(
        self,
        left: ThresholdGene,
        right: ThresholdGene,
        rng: random.Random,
    ) -> ThresholdGene:
        return ThresholdGene(
            base_threshold=rng.choice((left.base_threshold, right.base_threshold)),
            starvation_ticks=rng.choice((left.starvation_ticks, right.starvation_ticks)),
            starvation_step=rng.choice((left.starvation_step, right.starvation_step)),
            overactivity_ticks=rng.choice((left.overactivity_ticks, right.overactivity_ticks)),
            tighten_step=rng.choice((left.tighten_step, right.tighten_step)),
            target_low=rng.choice((left.target_low, right.target_low)),
            target_high=rng.choice((left.target_high, right.target_high)),
        )

    def _mutate_gene(self, gene: ThresholdGene, rng: random.Random) -> ThresholdGene:
        base_threshold = gene.base_threshold
        starvation_ticks = gene.starvation_ticks
        starvation_step = gene.starvation_step
        overactivity_ticks = gene.overactivity_ticks
        tighten_step = gene.tighten_step
        target_low = gene.target_low
        target_high = gene.target_high

        if rng.random() < 0.25:
            base_threshold = self._round_threshold(base_threshold + rng.choice((-0.1, -0.05, 0.05, 0.1)))
        if rng.random() < 0.2:
            starvation_ticks = max(2, min(12, starvation_ticks + rng.choice((-2, -1, 1, 2))))
        if rng.random() < 0.2:
            starvation_step = max(0.025, min(0.2, starvation_step + rng.choice((-0.025, 0.025))))
        if rng.random() < 0.2:
            overactivity_ticks = max(2, min(12, overactivity_ticks + rng.choice((-2, -1, 1, 2))))
        if rng.random() < 0.2:
            tighten_step = max(0.025, min(0.2, tighten_step + rng.choice((-0.025, 0.025))))
        if rng.random() < 0.15:
            target_low = max(1, min(2, target_low + rng.choice((-1, 1))))
        if rng.random() < 0.15:
            target_high = max(target_low, min(5, target_high + rng.choice((-1, 1))))

        return ThresholdGene(
            base_threshold=self._clamp_threshold(base_threshold),
            starvation_ticks=starvation_ticks,
            starvation_step=round(starvation_step, 3),
            overactivity_ticks=overactivity_ticks,
            tighten_step=round(tighten_step, 3),
            target_low=target_low,
            target_high=target_high,
        )

    def _confidence(
        self,
        *,
        train_result: dict[str, Any],
        test_result: dict[str, Any],
        all_result: dict[str, Any],
        tick_count: int,
        action: str,
    ) -> str:
        if tick_count < 80:
            return "low"
        train_score = float(train_result.get("score", 0) or 0)
        test_score = float(test_result.get("score", 0) or 0)
        test_tradeable = float(test_result.get("avg_tradeable_survivors", 0) or 0)
        all_tradeable = float(all_result.get("avg_tradeable_survivors", 0) or 0)
        all_non_tradeable = int(all_result.get("non_tradeable_survivors", 0) or 0)
        test_flatline_ratio = float(test_result.get("flatline_ticks", 0) or 0) / max(1, int(test_result.get("tick_count", 1) or 1))
        if action == "hold" and test_score > 0:
            return "medium"
        if train_score > 0 and test_score > 0 and test_flatline_ratio < 0.35:
            return "high" if tick_count >= 240 else "medium"
        if (
            action in {"loosen", "tighten"}
            and tick_count >= 120
            and all_non_tradeable == 0
            and all_tradeable >= 0.5
            and test_tradeable >= 0.25
        ):
            return "medium"
        if test_score > -5:
            return "medium"
        return "low"

    def _reason(
        self,
        *,
        action: str,
        current_threshold: float,
        recommended_threshold: float,
        result: dict[str, Any],
    ) -> str:
        avg_survivors = float(result.get("avg_survivors", 0) or 0)
        avg_tradeable = float(result.get("avg_tradeable_survivors", 0) or 0)
        flatline_ticks = int(result.get("flatline_ticks", 0) or 0)
        if action == "hold":
            return (
                f"GA policy keeps the threshold near {current_threshold:.2f}; "
                f"average tradeable survivors are {avg_tradeable:.2f}/tick "
                f"({avg_survivors:.2f} total) with {flatline_ticks} flatline ticks."
            )
        if action == "loosen":
            return (
                f"GA policy recommends loosening toward {recommended_threshold:.2f} "
                f"to improve tradeable survivors while staying above the "
                f"{self._advisor_floor():.2f} hard floor."
            )
        return (
            f"GA policy recommends tightening toward {recommended_threshold:.2f} "
            f"because the recent window allows more signals than the activity target."
        )

    def _public_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "score": result.get("score", 0),
            "ending_threshold": result.get("ending_threshold", 0),
            "avg_survivors": result.get("avg_survivors", 0),
            "avg_tradeable_survivors": result.get("avg_tradeable_survivors", 0),
            "avg_allowed_fitness": result.get("avg_allowed_fitness", 0),
            "avg_tradeable_fitness": result.get("avg_tradeable_fitness", 0),
            "flatline_ticks": result.get("flatline_ticks", 0),
            "overactive_ticks": result.get("overactive_ticks", 0),
            "tradeable_ticks": result.get("tradeable_ticks", 0),
            "non_tradeable_survivors": result.get("non_tradeable_survivors", 0),
            "threshold_changes": result.get("threshold_changes", 0),
            "tick_count": result.get("tick_count", 0),
        }

    def _empty_advice(self, *, tick_count: int, reason: str) -> dict[str, Any]:
        return {
            "status": "insufficient_data",
            "mode": "recommendation_only",
            "current_threshold": self._round_threshold(
                float(self.config.strategy_allocation_suppress_threshold)
            ),
            "recommended_threshold": self._round_threshold(
                float(self.config.strategy_allocation_suppress_threshold)
            ),
            "action": "hold",
            "confidence": "low",
            "tick_count": tick_count,
            "reason": reason,
        }

    def _clamp_threshold(self, value: float) -> float:
        return max(
            self._advisor_floor(),
            min(self._advisor_ceiling(), self._round_threshold(value)),
        )

    def _clamp_to_range(self, value: float, *, floor: float, ceiling: float) -> float:
        return max(floor, min(ceiling, self._round_threshold(float(value))))

    def _confidence_rank(self, confidence: str) -> int:
        return {"low": 1, "medium": 2, "high": 3}.get(confidence, 0)

    def _catch_up_allowed(
        self,
        *,
        advice: dict[str, Any],
        action: str,
        current_threshold: float,
        recommended_threshold: float,
    ) -> bool:
        if action not in {"loosen", "tighten"}:
            return False
        if recommended_threshold == current_threshold:
            return False
        all_result = _as_dict(advice.get("all"))
        avg_tradeable = float(all_result.get("avg_tradeable_survivors", 0) or 0)
        non_tradeable = int(all_result.get("non_tradeable_survivors", 0) or 0)
        if avg_tradeable <= 0 or non_tradeable > 0:
            return False
        return self._confidence_rank(str(advice.get("confidence", "low")).lower()) >= self._confidence_rank(
            str(self.config.strategy_threshold_adaptive_min_confidence or "medium").lower()
        )

    def _advisor_floor(self) -> float:
        return self._round_threshold(
            min(-6.0, float(self.config.strategy_threshold_adaptive_floor))
        )

    def _advisor_ceiling(self) -> float:
        return self._round_threshold(
            max(-5.0, float(self.config.strategy_threshold_adaptive_ceiling))
        )

    def _round_threshold(self, value: float) -> float:
        return round(round(value / 0.05) * 0.05, 2)

    def _threshold_below_score(self, score: float) -> float:
        step = 0.05
        return round(floor((float(score) - 0.000001) / step) * step, 2)

    def _fmt_optional_threshold(self, value: Any) -> str:
        numeric = _as_float(value)
        return "none" if numeric is None else f"{numeric:.3f}"


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _as_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None
