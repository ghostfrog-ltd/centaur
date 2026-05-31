from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import mean, median
from typing import Any

from app.runtime.settings import RuntimeConfig, load_runtime_config
from app.storage.usage import RealDictCursor, UsageLedger


WINDOW_ORDER = {
    "15m": 15,
    "30m": 30,
    "1h": 60,
    "2h": 120,
    "4h": 240,
    "1d": 1440,
    "7d": 10080,
}


class HoldingWindowAdvisor:
    """Recommendation-only fitness adviser for strategy holding windows."""

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
        strategy_id: str = "mean_reversion.snapback",
        current_window: str = "1h",
    ) -> dict[str, Any]:
        outcomes = self._load_outcomes(strategy_id=strategy_id)
        grouped = self._group_by_proposal(outcomes)
        if not grouped:
            return {
                "status": "insufficient_data",
                "strategy_id": strategy_id,
                "current_window": current_window,
                "reason": "No evaluated shadow outcomes exist for this strategy.",
            }

        available_windows = self._available_windows(grouped)
        complete_all = self._proposal_ids(
            grouped,
            required_windows=("15m", "1h", "1d"),
        )
        recent_30 = self._proposal_ids(
            grouped,
            required_windows=("15m", "1h", "1d"),
            days=30,
        )
        long_complete_all = self._proposal_ids(
            grouped,
            required_windows=("1h", "1d", "7d"),
        )
        long_complete_30 = self._proposal_ids(
            grouped,
            required_windows=("1h", "1d", "7d"),
            days=30,
        )
        recent_7 = self._proposal_ids(
            grouped,
            required_windows=("15m", "1h"),
            days=7,
        )
        recent_1 = self._proposal_ids(
            grouped,
            required_windows=("15m", "1h"),
            days=1,
        )

        all_window_stats = self._fixed_window_stats(
            grouped,
            complete_all,
            windows=("15m", "1h", "1d"),
        )
        recent_30_stats = self._fixed_window_stats(
            grouped,
            recent_30,
            windows=("15m", "1h", "1d"),
        )
        long_all_stats = self._fixed_window_stats(
            grouped,
            long_complete_all,
            windows=("1h", "1d", "7d"),
        )
        long_30_stats = self._fixed_window_stats(
            grouped,
            long_complete_30,
            windows=("1h", "1d", "7d"),
        )
        recent_7_stats = self._fixed_window_stats(
            grouped,
            recent_7,
            windows=("15m", "1h"),
        )
        recent_1_stats = self._fixed_window_stats(
            grouped,
            recent_1,
            windows=("15m", "1h"),
        )
        policy_stats = self._policy_stats(grouped, complete_all)
        recent_policy_stats = self._policy_stats(grouped, recent_30)
        best_window_counts = self._best_window_counts(
            grouped,
            complete_all,
            windows=("15m", "1h", "1d"),
        )
        recommendation = self._recommendation(
            current_window=current_window,
            all_window_stats=all_window_stats,
            recent_7_stats=recent_7_stats,
            recent_1_stats=recent_1_stats,
            policy_stats=policy_stats,
            recent_policy_stats=recent_policy_stats,
        )
        return {
            "status": "ok",
            "mode": "recommendation_only",
            "strategy_id": strategy_id,
            "current_window": current_window,
            "available_windows": available_windows,
            "sample_counts": {
                "complete_15m_1h_1d": len(complete_all),
                "complete_15m_1h_1d_30d": len(recent_30),
                "complete_1h_1d_7d": len(long_complete_all),
                "complete_1h_1d_7d_30d": len(long_complete_30),
                "complete_15m_1h_7d": len(recent_7),
                "complete_15m_1h_1d_1d": len(recent_1),
            },
            "fixed_windows_all": all_window_stats,
            "fixed_windows_30d": recent_30_stats,
            "fixed_windows_long_all": long_all_stats,
            "fixed_windows_long_30d": long_30_stats,
            "fixed_windows_7d": recent_7_stats,
            "fixed_windows_1d": recent_1_stats,
            "best_window_counts_all": best_window_counts,
            "policy_stats_all": policy_stats,
            "policy_stats_30d": recent_policy_stats,
            "recommendation": recommendation,
            "reason": recommendation.get("reason", ""),
        }

    def render(self, *, advice: dict[str, Any] | None = None) -> str:
        advice = advice or self.build_advice()
        if advice.get("status") != "ok":
            return (
                "Holding Window Fitness Advice\n"
                f"Status: {advice.get('status', 'unknown')}\n"
                f"Reason: {advice.get('reason', '-')}"
            )

        recommendation = _as_dict(advice.get("recommendation"))
        lines = [
            "Holding Window Fitness Advice",
            (
                f"Strategy: {advice.get('strategy_id', '-')}"
                f" | current={advice.get('current_window', '-')}"
                f" | mode={advice.get('mode', 'recommendation_only')}"
            ),
            (
                f"Recommendation: {recommendation.get('action', '-')}"
                f" | candidate={recommendation.get('candidate_policy', '-')}"
                f" | confidence={recommendation.get('confidence', '-')}"
            ),
            f"Reason: {recommendation.get('reason', '-')}",
            (
                "Samples: "
                f"all={_as_dict(advice.get('sample_counts')).get('complete_15m_1h_1d', 0)}"
                f" | 30d={_as_dict(advice.get('sample_counts')).get('complete_15m_1h_1d_30d', 0)}"
                f" | 1h/1d/7d={_as_dict(advice.get('sample_counts')).get('complete_1h_1d_7d', 0)}"
                f" | 7d={_as_dict(advice.get('sample_counts')).get('complete_15m_1h_7d', 0)}"
                f" | 1d={_as_dict(advice.get('sample_counts')).get('complete_15m_1h_1d_1d', 0)}"
            ),
            "Fixed windows, all complete 15m/1h/1d proposals:",
        ]
        for window, metrics in _as_dict(advice.get("fixed_windows_all")).items():
            lines.append(f"- {window}: {self._metrics_text(metrics)}")

        if int(_as_dict(advice.get("sample_counts")).get("complete_1h_1d_7d", 0) or 0) > 0:
            lines.append("Extended checkpoints, all complete 1h/1d/7d proposals:")
            for window, metrics in _as_dict(advice.get("fixed_windows_long_all")).items():
                lines.append(f"- {window}: {self._metrics_text(metrics)}")

        lines.append("Fixed windows, recent 7d 15m/1h proposals:")
        for window, metrics in _as_dict(advice.get("fixed_windows_7d")).items():
            lines.append(f"- {window}: {self._metrics_text(metrics)}")

        lines.append("Simple dynamic policy backtests, all complete proposals:")
        for policy_id, metrics in _as_dict(advice.get("policy_stats_all")).items():
            lines.append(f"- {policy_id}: {self._metrics_text(metrics)}")

        return "\n".join(lines)

    def _load_outcomes(self, *, strategy_id: str) -> list[dict[str, Any]]:
        if self.usage_ledger.backend == "postgres":
            return self._load_outcomes_postgres(strategy_id=strategy_id)
        return self._load_outcomes_sqlite(strategy_id=strategy_id)

    def _load_outcomes_postgres(self, *, strategy_id: str) -> list[dict[str, Any]]:
        with self.usage_ledger._connect_postgres(scope="core") as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT p.proposal_id, p.proposed_at, p.symbol, p.asset_class,
                           p.strategy_id, p.holding_window_code,
                           o.checkpoint_code, o.checkpoint_minutes, o.outcome_status,
                           o.realized_return_pct, o.max_favorable_excursion_pct,
                           o.max_adverse_excursion_pct
                    FROM shadow_trade_proposals p
                    JOIN shadow_trade_outcomes o ON o.proposal_id = p.proposal_id
                    WHERE p.strategy_id = %s
                      AND o.evaluated_at IS NOT NULL
                    ORDER BY p.proposed_at ASC, p.proposal_id ASC, o.checkpoint_minutes ASC
                    """,
                    (strategy_id,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _load_outcomes_sqlite(self, *, strategy_id: str) -> list[dict[str, Any]]:
        with self.usage_ledger._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT p.proposal_id, p.proposed_at, p.symbol, p.asset_class,
                       p.strategy_id, p.holding_window_code,
                       o.checkpoint_code, o.checkpoint_minutes, o.outcome_status,
                       o.realized_return_pct, o.max_favorable_excursion_pct,
                       o.max_adverse_excursion_pct
                FROM shadow_trade_proposals p
                JOIN shadow_trade_outcomes o ON o.proposal_id = p.proposal_id
                WHERE p.strategy_id = ?
                  AND o.evaluated_at IS NOT NULL
                ORDER BY p.proposed_at ASC, p.proposal_id ASC, o.checkpoint_minutes ASC
                """,
                (strategy_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def _group_by_proposal(
        self,
        rows: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for row in rows:
            proposal_id = str(row.get("proposal_id", "")).strip()
            checkpoint_code = str(row.get("checkpoint_code", "")).strip().lower()
            if not proposal_id or not checkpoint_code:
                continue
            item = grouped.setdefault(
                proposal_id,
                {
                    "proposal_id": proposal_id,
                    "proposed_at": _to_datetime(row.get("proposed_at")),
                    "symbol": row.get("symbol"),
                    "windows": {},
                },
            )
            item["windows"][checkpoint_code] = row
        return grouped

    def _proposal_ids(
        self,
        grouped: dict[str, dict[str, Any]],
        *,
        required_windows: tuple[str, ...],
        days: int | None = None,
    ) -> list[str]:
        latest = max(
            (
                item.get("proposed_at")
                for item in grouped.values()
                if isinstance(item.get("proposed_at"), datetime)
            ),
            default=None,
        )
        cutoff = latest - timedelta(days=days) if days and latest else None
        proposal_ids: list[str] = []
        for proposal_id, item in grouped.items():
            windows = _as_dict(item.get("windows"))
            if not all(window in windows for window in required_windows):
                continue
            proposed_at = item.get("proposed_at")
            if cutoff is not None and isinstance(proposed_at, datetime) and proposed_at < cutoff:
                continue
            proposal_ids.append(proposal_id)
        return proposal_ids

    def _available_windows(self, grouped: dict[str, dict[str, Any]]) -> list[str]:
        windows: set[str] = set()
        for item in grouped.values():
            windows.update(_as_dict(item.get("windows")).keys())
        return sorted(windows, key=lambda value: WINDOW_ORDER.get(value, 999999))

    def _fixed_window_stats(
        self,
        grouped: dict[str, dict[str, Any]],
        proposal_ids: list[str],
        *,
        windows: tuple[str, ...],
    ) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for window in windows:
            rows = [
                _as_dict(_as_dict(grouped[proposal_id].get("windows")).get(window))
                for proposal_id in proposal_ids
                if window in _as_dict(grouped[proposal_id].get("windows"))
            ]
            result[window] = self._metrics(
                [
                    _to_float(row.get("realized_return_pct"))
                    for row in rows
                ],
                statuses=[str(row.get("outcome_status", "")) for row in rows],
                mfe_values=[
                    _to_float(row.get("max_favorable_excursion_pct"))
                    for row in rows
                ],
                mae_values=[
                    _to_float(row.get("max_adverse_excursion_pct"))
                    for row in rows
                ],
            )
        return result

    def _policy_stats(
        self,
        grouped: dict[str, dict[str, Any]],
        proposal_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        policies: dict[str, list[float | None]] = defaultdict(list)
        for proposal_id in proposal_ids:
            windows = _as_dict(grouped[proposal_id].get("windows"))
            if not all(window in windows for window in ("15m", "1h", "1d")):
                continue
            r15 = _to_float(_as_dict(windows.get("15m")).get("realized_return_pct"))
            r1h = _to_float(_as_dict(windows.get("1h")).get("realized_return_pct"))
            r1d = _to_float(_as_dict(windows.get("1d")).get("realized_return_pct"))
            if r15 is None or r1h is None or r1d is None:
                continue
            policies["fixed_15m"].append(r15)
            policies["fixed_1h"].append(r1h)
            policies["fixed_1d"].append(r1d)
            policies["take_15m_profit_else_1h"].append(r15 if r15 > 0 else r1h)
            policies["take_1h_profit_else_1d"].append(r1h if r1h > 0 else r1d)
            policies["take_15m_profit_then_1h_profit_else_1d"].append(
                r15 if r15 > 0 else (r1h if r1h > 0 else r1d)
            )
        return {policy_id: self._metrics(values) for policy_id, values in policies.items()}

    def _best_window_counts(
        self,
        grouped: dict[str, dict[str, Any]],
        proposal_ids: list[str],
        *,
        windows: tuple[str, ...],
    ) -> dict[str, Any]:
        counts: Counter[str] = Counter()
        for proposal_id in proposal_ids:
            proposal_windows = _as_dict(grouped[proposal_id].get("windows"))
            returns: dict[str, float] = {}
            for window in windows:
                value = _to_float(
                    _as_dict(proposal_windows.get(window)).get("realized_return_pct")
                )
                if value is not None:
                    returns[window] = value
            if len(returns) == len(windows):
                counts[max(returns, key=returns.get)] += 1
        return dict(counts)

    def _metrics(
        self,
        values: list[float | None],
        *,
        statuses: list[str] | None = None,
        mfe_values: list[float | None] | None = None,
        mae_values: list[float | None] | None = None,
    ) -> dict[str, Any]:
        clean = [float(value) for value in values if value is not None]
        if not clean:
            return {"n": 0}
        losses = [abs(value) for value in clean if value < 0]
        downside_avg = mean(losses) if losses else 0.0
        avg_return = mean(clean)
        med_return = median(clean)
        win_count = sum(1 for value in clean if value > 0)
        score = avg_return + (med_return * 0.35) - (downside_avg * 0.15)
        status_counts = Counter(statuses or [])
        mfe_clean = [float(value) for value in (mfe_values or []) if value is not None]
        mae_clean = [float(value) for value in (mae_values or []) if value is not None]
        return {
            "n": len(clean),
            "avg_return_pct": round(avg_return, 6),
            "median_return_pct": round(med_return, 6),
            "win_count": win_count,
            "loss_count": sum(1 for value in clean if value < 0),
            "win_rate": round(win_count / len(clean), 6),
            "worst_return_pct": round(min(clean), 6),
            "best_return_pct": round(max(clean), 6),
            "downside_avg_pct": round(downside_avg, 6),
            "score": round(score, 6),
            "target_hits": int(status_counts.get("target_hit", 0)),
            "stop_hits": int(status_counts.get("stop_hit", 0)),
            "time_exits": int(status_counts.get("time_exit", 0)),
            "avg_mfe_pct": round(mean(mfe_clean), 6) if mfe_clean else None,
            "avg_mae_pct": round(mean(mae_clean), 6) if mae_clean else None,
        }

    def _recommendation(
        self,
        *,
        current_window: str,
        all_window_stats: dict[str, dict[str, Any]],
        recent_7_stats: dict[str, dict[str, Any]],
        recent_1_stats: dict[str, dict[str, Any]],
        policy_stats: dict[str, dict[str, Any]],
        recent_policy_stats: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        fixed_1h = _as_dict(all_window_stats.get(current_window))
        dynamic_extend = _as_dict(policy_stats.get("take_1h_profit_else_1d"))
        recent_fixed_15m = _as_dict(recent_7_stats.get("15m"))
        recent_fixed_1h = _as_dict(recent_7_stats.get("1h"))
        today_15m = _as_dict(recent_1_stats.get("15m"))
        today_1h = _as_dict(recent_1_stats.get("1h"))
        recent_dynamic = _as_dict(recent_policy_stats.get("take_1h_profit_else_1d"))
        recent_fixed_1h_complete = _as_dict(recent_policy_stats.get("fixed_1h"))

        if int(fixed_1h.get("n", 0) or 0) < 50:
            return {
                "action": "collect_more_evidence",
                "candidate_policy": current_window,
                "confidence": "low",
                "reason": "Fewer than 50 complete shadow outcomes are available for this holding-window test.",
            }

        dynamic_score = float(dynamic_extend.get("score", 0) or 0)
        fixed_score = float(fixed_1h.get("score", 0) or 0)
        dynamic_avg = float(dynamic_extend.get("avg_return_pct", 0) or 0)
        fixed_avg = float(fixed_1h.get("avg_return_pct", 0) or 0)
        recent_dynamic_avg = float(recent_dynamic.get("avg_return_pct", 0) or 0)
        recent_fixed_avg = float(recent_fixed_1h_complete.get("avg_return_pct", 0) or 0)

        if (
            int(recent_fixed_15m.get("n", 0) or 0) >= 30
            and float(recent_fixed_15m.get("avg_return_pct", 0) or 0)
            > float(recent_fixed_1h.get("avg_return_pct", 0) or 0) + 0.1
        ):
            return {
                "action": "test_dynamic_exit",
                "candidate_policy": "shorten_when_recent_15m_beats_1h",
                "confidence": "medium",
                "reason": (
                    "Recent 15m outcomes are materially better than 1h outcomes; "
                    "do not blindly extend the holding window."
                ),
            }

        if (
            dynamic_score > fixed_score + 0.05
            and dynamic_avg > fixed_avg + 0.05
            and recent_dynamic_avg >= recent_fixed_avg
        ):
            return {
                "action": "test_dynamic_exit",
                "candidate_policy": "take_1h_profit_else_extend_to_1d_shadow_only",
                "confidence": "medium",
                "reason": (
                    "All-time outcomes favor selling profitable 1h trades and extending "
                    "unprofitable 1h trades to the 1d checkpoint, but this should stay "
                    "shadow-only until the downside profile is reviewed."
                ),
            }

        return {
            "action": "hold_current_rule",
            "candidate_policy": current_window,
            "confidence": "medium",
            "reason": (
                "The current 1h window is not proven optimal, but the available evidence "
                "does not yet justify changing live paper exits automatically."
            ),
        }

    def _metrics_text(self, metrics: dict[str, Any]) -> str:
        if int(metrics.get("n", 0) or 0) <= 0:
            return "n=0"
        return (
            f"n={metrics.get('n', 0)}"
            f" | avg={float(metrics.get('avg_return_pct', 0)):+.2f}%"
            f" | med={float(metrics.get('median_return_pct', 0)):+.2f}%"
            f" | win={float(metrics.get('win_rate', 0)) * 100:.1f}%"
            f" | worst={float(metrics.get('worst_return_pct', 0)):+.2f}%"
            f" | score={float(metrics.get('score', 0)):+.2f}"
        )


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _to_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value is None:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
