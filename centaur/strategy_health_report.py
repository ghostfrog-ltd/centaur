from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any

from .config import RuntimeConfig, load_runtime_config
from .holding_window_advisor import HoldingWindowAdvisor
from .paper_exit_review import PaperExitReview
from .usage import RealDictCursor, UsageLedger


@dataclass(frozen=True, slots=True)
class ClosedTradeSummary:
    strategy_id: str
    closed_trades: int
    realized_pnl_usd: float
    avg_trade_pnl_usd: float
    wins: int
    non_wins: int
    first_entry_at: datetime | None
    last_exit_at: datetime | None


class StrategyHealthReport:
    """Read-only operator report that bundles recent strategy health signals."""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_report(
        self,
        *,
        strategy_id: str = "mean_reversion.snapback",
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        signal_lookback_days = min(max(lookback_days, 1), 14)
        latest_tick = self.usage_ledger.get_latest_tick_run()
        checked_at = self._as_datetime((latest_tick or {}).get("ended_at")) or datetime.now().astimezone()
        closed_by_strategy = self._closed_trade_summaries()
        recent_daily_pnl = self._recent_daily_realized_pnl(
            strategy_id=strategy_id,
            lookback_days=min(max(lookback_days, 1), 14),
        )
        exit_reasons = self._recent_exit_reason_breakdown(
            strategy_id=strategy_id,
            lookback_days=lookback_days,
        )
        proposal_counts = self._proposal_counts(lookback_days=lookback_days)
        candidate_signal_counts = self._candidate_signal_counts(lookback_days=lookback_days)
        raw_preview_counts, suppressed_preview_counts = self._preview_signal_counts(
            lookback_days=signal_lookback_days
        )
        latest_fitness = self._latest_fitness_snapshot()
        exit_review = PaperExitReview(
            config=self.config,
            usage_ledger=self.usage_ledger,
        ).build_review(strategy_id=strategy_id)
        holding_advice = HoldingWindowAdvisor(
            config=self.config,
            usage_ledger=self.usage_ledger,
        ).build_advice(strategy_id=strategy_id)
        return {
            "status": "ok",
            "checked_at": checked_at.isoformat(),
            "backend": self.usage_ledger.backend,
            "strategy_id": strategy_id,
            "lookback_days": lookback_days,
            "signal_lookback_days": signal_lookback_days,
            "closed_trade_summaries": [asdict(item) for item in closed_by_strategy],
            "recent_daily_realized_pnl": recent_daily_pnl,
            "recent_exit_reason_breakdown": exit_reasons,
            "recent_proposal_counts": proposal_counts,
            "recent_candidate_signal_counts": candidate_signal_counts,
            "recent_raw_preview_counts": raw_preview_counts,
            "recent_suppressed_preview_counts": suppressed_preview_counts,
            "latest_fitness_snapshot": latest_fitness,
            "paper_exit_review": exit_review,
            "holding_window_advice": holding_advice,
        }

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        report = report or self.build_report()
        if report.get("status") != "ok":
            return (
                "Strategy Health Report\n"
                f"Status: {report.get('status', 'unknown')}\n"
                f"Reason: {report.get('reason', '-')}"
            )

        strategy_id = str(report.get("strategy_id", "-"))
        lines = [
            "Strategy Health Report",
            (
                f"Strategy: {strategy_id}"
                f" | backend={report.get('backend', '-')}"
                f" | lookback={report.get('lookback_days', 0)}d"
                f" | checked_at={report.get('checked_at', '-')}"
            ),
            "Actual paper P/L by strategy:",
        ]
        for row in report.get("closed_trade_summaries", [])[:8]:
            item = _as_dict(row)
            lines.append(
                (
                    f"- {item.get('strategy_id', '-')}"
                    f" | closed={int(item.get('closed_trades', 0) or 0)}"
                    f" | pnl={_fmt_signed_currency(item.get('realized_pnl_usd'))}"
                    f" | avg/trade={_fmt_signed_currency(item.get('avg_trade_pnl_usd'), decimals=4)}"
                    f" | wins={int(item.get('wins', 0) or 0)}/{int(item.get('closed_trades', 0) or 0)}"
                )
            )

        lines.append(f"Recent daily realized P/L for {strategy_id}:")
        daily_rows = report.get("recent_daily_realized_pnl", [])
        if daily_rows:
            for row in daily_rows:
                item = _as_dict(row)
                lines.append(
                    (
                        f"- {item.get('exit_date', '-')}"
                        f" | pnl={_fmt_signed_currency(item.get('realized_pnl_usd'), decimals=4)}"
                        f" | closed={int(item.get('closed_trades', 0) or 0)}"
                        f" | wins={int(item.get('wins', 0) or 0)}"
                        f" | non_wins={int(item.get('non_wins', 0) or 0)}"
                    )
                )
        else:
            lines.append("- No recent closed trades.")

        lines.append(f"Recent exit reasons for {strategy_id}:")
        exit_rows = report.get("recent_exit_reason_breakdown", [])
        if exit_rows:
            for row in exit_rows:
                item = _as_dict(row)
                lines.append(
                    (
                        f"- {item.get('exit_reason', '-')}"
                        f" | trades={int(item.get('trades', 0) or 0)}"
                        f" | avg={_fmt_pct(item.get('avg_return_pct'))}"
                        f" | worst={_fmt_pct(item.get('worst_pct'))}"
                        f" | best={_fmt_pct(item.get('best_pct'))}"
                    )
                )
        else:
            lines.append("- No recent exit reasons available.")

        lines.append("Recent proposal counts:")
        for strategy_name, count in report.get("recent_proposal_counts", []):
            lines.append(f"- {strategy_name}: {count}")

        lines.append("Recent non-suppressed candidate signals:")
        for strategy_name, status_counts in report.get("recent_candidate_signal_counts", []):
            pieces = ", ".join(f"{status}={count}" for status, count in status_counts.items())
            lines.append(f"- {strategy_name}: {pieces or 'none'}")

        lines.append(
            f"Recent raw preview counts ({int(report.get('signal_lookback_days', 0) or 0)}d snapshot window):"
        )
        for strategy_name, count in report.get("recent_raw_preview_counts", []):
            lines.append(f"- {strategy_name}: {count}")

        lines.append(
            f"Recent suppressed preview counts ({int(report.get('signal_lookback_days', 0) or 0)}d snapshot window):"
        )
        for strategy_name, count in report.get("recent_suppressed_preview_counts", []):
            lines.append(f"- {strategy_name}: {count}")

        lines.append("Latest strategy fitness snapshot:")
        for row in report.get("latest_fitness_snapshot", [])[:8]:
            item = _as_dict(row)
            lines.append(
                (
                    f"- rank={int(item.get('fitness_rank', 0) or 0)}"
                    f" | {item.get('strategy_id', '-')}"
                    f" | {item.get('checkpoint_code', '-')}"
                    f" | proposals={int(item.get('evaluated_proposals', 0) or 0)}"
                    f" | avg={_fmt_pct(item.get('avg_realized_return_pct'))}"
                    f" | fit={_fmt_pct(item.get('composite_fitness_score'))}"
                )
            )

        review = _as_dict(report.get("paper_exit_review"))
        if review.get("status") == "ok":
            recent = _as_dict(review.get("recent_summary"))
            all_time = _as_dict(review.get("all_time_summary"))
            lines.append("Paper exit review:")
            lines.append(f"- recent: {_exit_summary_text(recent)}")
            lines.append(f"- all-time: {_exit_summary_text(all_time)}")

        advice = _as_dict(report.get("holding_window_advice"))
        if advice.get("status") == "ok":
            recommendation = _as_dict(advice.get("recommendation"))
            sample_counts = _as_dict(advice.get("sample_counts"))
            fixed_7d = _as_dict(advice.get("fixed_windows_7d"))
            lines.append("Holding-window advice:")
            lines.append(
                (
                    f"- action={recommendation.get('action', '-')}"
                    f" | candidate={recommendation.get('candidate_policy', '-')}"
                    f" | confidence={recommendation.get('confidence', '-')}"
                )
            )
            lines.append(
                (
                    f"- recent samples: 15m/1h={sample_counts.get('complete_15m_1h_7d', 0)}"
                    f" | 15m avg={_fmt_pct(_as_dict(fixed_7d.get('15m')).get('avg_return_pct'))}"
                    f" | 1h avg={_fmt_pct(_as_dict(fixed_7d.get('1h')).get('avg_return_pct'))}"
                )
            )
            lines.append(f"- {recommendation.get('reason', '-')}")

        return "\n".join(lines)

    def _closed_trade_summaries(self) -> list[ClosedTradeSummary]:
        query = """
            WITH fills AS (
                SELECT proposal_id, strategy_id, symbol, side, submitted_at,
                       COALESCE(filled_qty, 0) AS filled_qty,
                       COALESCE(filled_avg_price, 0) AS filled_avg_price
                FROM paper_trade_orders
                WHERE status = 'filled'
                  AND proposal_id <> ''
            ),
            round_trips AS (
                SELECT proposal_id, strategy_id, symbol,
                       MIN(submitted_at) FILTER (WHERE side = 'buy') AS entry_at,
                       MAX(submitted_at) FILTER (WHERE side = 'sell') AS exit_at,
                       SUM(filled_qty * filled_avg_price) FILTER (WHERE side = 'buy') AS buy_value,
                       SUM(filled_qty * filled_avg_price) FILTER (WHERE side = 'sell') AS sell_value,
                       COUNT(*) FILTER (WHERE side = 'buy') AS buys,
                       COUNT(*) FILTER (WHERE side = 'sell') AS sells
                FROM fills
                GROUP BY proposal_id, strategy_id, symbol
                HAVING COUNT(*) FILTER (WHERE side = 'buy') > 0
                   AND COUNT(*) FILTER (WHERE side = 'sell') > 0
            )
            SELECT strategy_id,
                   COUNT(*) AS closed_trades,
                   COALESCE(SUM(sell_value - buy_value), 0) AS realized_pnl_usd,
                   COALESCE(AVG(sell_value - buy_value), 0) AS avg_trade_pnl_usd,
                   SUM(CASE WHEN sell_value - buy_value > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN sell_value - buy_value <= 0 THEN 1 ELSE 0 END) AS non_wins,
                   MIN(entry_at) AS first_entry_at,
                   MAX(exit_at) AS last_exit_at
            FROM round_trips
            GROUP BY strategy_id
            ORDER BY realized_pnl_usd DESC, strategy_id ASC
        """
        rows = self._query_rows(query=query)
        return [
            ClosedTradeSummary(
                strategy_id=str(row.get("strategy_id", "") or ""),
                closed_trades=int(row.get("closed_trades", 0) or 0),
                realized_pnl_usd=float(row.get("realized_pnl_usd", 0) or 0),
                avg_trade_pnl_usd=float(row.get("avg_trade_pnl_usd", 0) or 0),
                wins=int(row.get("wins", 0) or 0),
                non_wins=int(row.get("non_wins", 0) or 0),
                first_entry_at=self._as_datetime(row.get("first_entry_at")),
                last_exit_at=self._as_datetime(row.get("last_exit_at")),
            )
            for row in rows
        ]

    def _recent_daily_realized_pnl(
        self,
        *,
        strategy_id: str,
        lookback_days: int,
    ) -> list[dict[str, Any]]:
        query = """
            WITH fills AS (
                SELECT proposal_id, strategy_id, symbol, side, submitted_at,
                       COALESCE(filled_qty, 0) AS filled_qty,
                       COALESCE(filled_avg_price, 0) AS filled_avg_price
                FROM paper_trade_orders
                WHERE status = 'filled'
                  AND proposal_id <> ''
                  AND strategy_id = ?
            ),
            round_trips AS (
                SELECT proposal_id, symbol,
                       MAX(submitted_at) FILTER (WHERE side = 'sell') AS exit_at,
                       SUM(filled_qty * filled_avg_price) FILTER (WHERE side = 'buy') AS buy_value,
                       SUM(filled_qty * filled_avg_price) FILTER (WHERE side = 'sell') AS sell_value
                FROM fills
                GROUP BY proposal_id, symbol
                HAVING COUNT(*) FILTER (WHERE side = 'buy') > 0
                   AND COUNT(*) FILTER (WHERE side = 'sell') > 0
            )
            SELECT DATE(exit_at) AS exit_date,
                   SUM(sell_value - buy_value) AS realized_pnl_usd,
                   COUNT(*) AS closed_trades,
                   SUM(CASE WHEN sell_value - buy_value > 0 THEN 1 ELSE 0 END) AS wins,
                   SUM(CASE WHEN sell_value - buy_value <= 0 THEN 1 ELSE 0 END) AS non_wins
            FROM round_trips
            WHERE exit_at >= ?
            GROUP BY DATE(exit_at)
            ORDER BY DATE(exit_at) DESC
        """
        cutoff = datetime.now().astimezone() - timedelta(days=lookback_days)
        rows = self._query_rows(query=query, params=(strategy_id, cutoff))
        return [dict(row) for row in rows]

    def _recent_exit_reason_breakdown(
        self,
        *,
        strategy_id: str,
        lookback_days: int,
    ) -> list[dict[str, Any]]:
        query = """
            WITH fills AS (
                SELECT proposal_id, strategy_id, symbol, side, submitted_at,
                       COALESCE(filled_avg_price, 0) AS filled_avg_price,
                       raw_json
                FROM paper_trade_orders
                WHERE status = 'filled'
                  AND proposal_id <> ''
                  AND strategy_id = ?
            ),
            latest_exit AS (
                SELECT proposal_id,
                       MAX(submitted_at) AS exit_at
                FROM fills
                WHERE side = 'sell'
                GROUP BY proposal_id
            ),
            entry_fill AS (
                SELECT proposal_id, submitted_at AS entry_at, filled_avg_price AS entry_price
                FROM fills
                WHERE side = 'buy'
            )
            SELECT COALESCE(jsonb_extract_path_text(f.raw_json, 'exit_reason'), '') AS exit_reason,
                   COUNT(*) AS trades,
                   AVG(((f.filled_avg_price - e.entry_price) / NULLIF(e.entry_price, 0)) * 100.0) AS avg_return_pct,
                   MIN(((f.filled_avg_price - e.entry_price) / NULLIF(e.entry_price, 0)) * 100.0) AS worst_pct,
                   MAX(((f.filled_avg_price - e.entry_price) / NULLIF(e.entry_price, 0)) * 100.0) AS best_pct
            FROM latest_exit x
            JOIN fills f
              ON f.proposal_id = x.proposal_id
             AND f.submitted_at = x.exit_at
             AND f.side = 'sell'
            JOIN entry_fill e
              ON e.proposal_id = x.proposal_id
            WHERE x.exit_at >= ?
            GROUP BY COALESCE(jsonb_extract_path_text(f.raw_json, 'exit_reason'), '')
            ORDER BY trades DESC, exit_reason ASC
        """
        if self.usage_ledger.backend == "postgres":
            query = query.replace("?", "%s")
        else:
            query = query.replace(
                "COALESCE(jsonb_extract_path_text(f.raw_json, 'exit_reason'), '')",
                "COALESCE(json_extract(f.raw_json, '$.exit_reason'), '')",
            )
        cutoff = datetime.now().astimezone() - timedelta(days=lookback_days)
        rows = self._query_rows(query=query, params=(strategy_id, cutoff))
        return [dict(row) for row in rows]

    def _proposal_counts(self, *, lookback_days: int) -> list[tuple[str, int]]:
        query = """
            SELECT strategy_id, COUNT(*) AS proposals
            FROM shadow_trade_proposals
            WHERE proposed_at >= ?
            GROUP BY strategy_id
            ORDER BY proposals DESC, strategy_id ASC
        """
        cutoff = datetime.now().astimezone() - timedelta(days=lookback_days)
        rows = self._query_rows(query=query, params=(cutoff,))
        return [
            (str(row.get("strategy_id", "") or ""), int(row.get("proposals", 0) or 0))
            for row in rows
        ]

    def _candidate_signal_counts(
        self,
        *,
        lookback_days: int,
    ) -> list[tuple[str, dict[str, int]]]:
        cutoff_tick = (datetime.now().astimezone() - timedelta(days=lookback_days)).strftime("%Y%m%d")
        query = """
            SELECT strategy_id,
                   COALESCE(jsonb_extract_path_text(raw_json, 'allocation_status'), '') AS allocation_status,
                   COUNT(*) AS signals
            FROM strategy_candidate_signals
            WHERE tick_id >= ?
            GROUP BY strategy_id, COALESCE(jsonb_extract_path_text(raw_json, 'allocation_status'), '')
            ORDER BY strategy_id ASC, allocation_status ASC
        """
        if self.usage_ledger.backend != "postgres":
            query = query.replace(
                "COALESCE(jsonb_extract_path_text(raw_json, 'allocation_status'), '')",
                "COALESCE(json_extract(raw_json, '$.allocation_status'), '')",
            )
        rows = self._query_rows(query=query, params=(cutoff_tick,))
        grouped: dict[str, dict[str, int]] = defaultdict(dict)
        for row in rows:
            strategy_name = str(row.get("strategy_id", "") or "")
            status = str(row.get("allocation_status", "") or "")
            grouped[strategy_name][status or "unknown"] = int(row.get("signals", 0) or 0)
        return sorted(grouped.items(), key=lambda item: (-sum(item[1].values()), item[0]))

    def _preview_signal_counts(
        self,
        *,
        lookback_days: int,
    ) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
        cutoff = datetime.now().astimezone() - timedelta(days=lookback_days)
        query = """
            SELECT tick_id, started_at, state_snapshot_json
            FROM control_tick_runs
            WHERE started_at >= ?
            ORDER BY started_at DESC
            LIMIT 500
        """
        rows = self._query_rows(query=query, params=(cutoff,))
        raw_counts: Counter[str] = Counter()
        suppressed_counts: Counter[str] = Counter()
        for row in rows:
            snapshot = row.get("state_snapshot_json")
            if not isinstance(snapshot, dict):
                snapshot = self._coerce_json(snapshot)
            strategy_state = _as_dict(snapshot.get("strategy_signals"))
            for item in strategy_state.get("raw_signal_preview", []) or []:
                if isinstance(item, dict):
                    raw_counts[str(item.get("strategy_id", "") or "")] += 1
            for item in strategy_state.get("suppressed_signal_preview", []) or []:
                if isinstance(item, dict):
                    suppressed_counts[str(item.get("strategy_id", "") or "")] += 1
        return (
            sorted(raw_counts.items(), key=lambda item: (-item[1], item[0])),
            sorted(suppressed_counts.items(), key=lambda item: (-item[1], item[0])),
        )

    def _latest_fitness_snapshot(self) -> list[dict[str, Any]]:
        query = """
            SELECT strategy_id, checkpoint_code, fitness_rank, evaluated_proposals,
                   checkpoints_evaluated, composite_fitness_score,
                   avg_realized_return_pct, last_evaluated_at
            FROM strategy_fitness_snapshots
            WHERE captured_at = (
                SELECT MAX(captured_at) FROM strategy_fitness_snapshots
            )
            ORDER BY fitness_rank ASC, checkpoint_code ASC, strategy_id ASC
        """
        return [dict(row) for row in self._query_rows(query=query)]

    def _query_rows(
        self,
        *,
        query: str,
        params: tuple[Any, ...] = tuple(),
    ) -> list[dict[str, Any]]:
        if self.usage_ledger.backend == "postgres":
            pg_query = query.replace("?", "%s")
            with self.usage_ledger._connect_postgres() as connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(pg_query, params)
                    rows = cursor.fetchall()
            return [dict(row) for row in rows]

        with self.usage_ledger._connect_sqlite() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def _coerce_json(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value in (None, ""):
            return {}
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError, json.JSONDecodeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _as_datetime(self, value: Any) -> datetime | None:
        if isinstance(value, datetime):
            return value
        if value in (None, ""):
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _fmt_signed_currency(value: Any, *, decimals: int = 2) -> str:
    try:
        if value in (None, ""):
            return "-"
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"${number:+.{decimals}f}"


def _fmt_pct(value: Any) -> str:
    try:
        if value in (None, ""):
            return "-"
        number = float(value)
    except (TypeError, ValueError):
        return "-"
    return f"{number:+.2f}%"


def _exit_summary_text(summary: dict[str, Any]) -> str:
    return (
        f"rows={summary.get('sample_rows', 0)}"
        f" | 1d>1h={summary.get('one_day_beats_one_hour_count', 0)}"
        f" | 1h>1d={summary.get('one_hour_beats_one_day_count', 0)}"
        f" | 7d>1d={summary.get('seven_day_beats_one_day_count', 0)}"
        f" | avg(1d-1h)={_fmt_pct(summary.get('avg_delta_1d_minus_1h'))}"
        f" | avg(7d-1d)={_fmt_pct(summary.get('avg_delta_7d_minus_1d'))}"
        f" | paper-shadow1h={_fmt_pct(summary.get('paper_minus_shadow_1h_avg'))}"
    )
