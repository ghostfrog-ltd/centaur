from __future__ import annotations

from datetime import date, datetime
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import RealDictCursor, UsageLedger
from app.heartbeat.support import _find_most_protective_managed_entry_order


class OvernightGivebackReport:
    """Read-only report for overnight-to-morning mark-to-market giveback."""

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
        days: int = 7,
        start_hour: int = 1,
        end_hour: int = 9,
        timezone: str = "Europe/London",
        max_snapshot_age_minutes: int = 90,
    ) -> dict[str, Any]:
        if self.usage_ledger.backend != "postgres":
            return {
                "status": "unsupported_backend",
                "reason": "overnight_giveback_report_requires_postgres",
                "backend": self.usage_ledger.backend,
            }

        comparison_dates = self._comparison_dates(
            days=max(1, days),
            timezone=timezone,
        )
        recent_orders = self._recent_orders(limit=500)
        comparisons = [
            self._build_day_comparison(
                session_date=item,
                start_hour=start_hour,
                end_hour=end_hour,
                timezone=timezone,
                max_snapshot_age_minutes=max(1, max_snapshot_age_minutes),
                recent_orders=recent_orders,
            )
            for item in comparison_dates
        ]
        complete = [item for item in comparisons if item.get("complete")]
        ranked_symbols = self._rank_symbol_giveback(comparisons=complete)
        return {
            "status": "ok",
            "backend": self.usage_ledger.backend,
            "checked_at": datetime.now().astimezone().isoformat(),
            "broker_id": "alpaca_paper",
            "days_requested": days,
            "timezone": timezone,
            "window": {
                "start_hour": start_hour,
                "end_hour": end_hour,
                "max_snapshot_age_minutes": max_snapshot_age_minutes,
            },
            "comparisons": comparisons,
            "complete_days": len(complete),
            "ranked_symbol_giveback": ranked_symbols,
            "missing_entry_plan_symbols": self._latest_missing_entry_plan_symbols(
                recent_orders=recent_orders
            ),
        }

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        report = report or self.build_report()
        if report.get("status") != "ok":
            return (
                "Overnight Giveback Report\n"
                f"Status: {report.get('status', 'unknown')}\n"
                f"Reason: {report.get('reason', '-')}"
            )

        window = _as_dict(report.get("window"))
        start_hour = int(window.get("start_hour", 1) or 1)
        end_hour = int(window.get("end_hour", 9) or 9)
        lines = [
            "Overnight Giveback Report",
            (
                f"broker={report.get('broker_id', '-')}"
                f" | backend={report.get('backend', '-')}"
                f" | checked_at={report.get('checked_at', '-')}"
            ),
            (
                f"Window={start_hour:02d}:00->{end_hour:02d}:00"
                f" {report.get('timezone', '-')}"
                f" | complete_days={int(report.get('complete_days', 0) or 0)}"
            ),
        ]

        lines.append("Daily 01:00->09:00 mark-to-market:")
        comparisons = report.get("comparisons", [])
        if not comparisons:
            lines.append("- no snapshots found")
        for row in comparisons:
            item = _as_dict(row)
            if not item.get("complete"):
                reasons = ", ".join(item.get("reasons", []) or []) or "incomplete"
                lines.append(f"- {item.get('date', '-')}: incomplete | {reasons}")
                continue
            lines.append(
                (
                    f"- {item.get('date', '-')}"
                    f" | equity={_fmt_signed_currency(item.get('equity_delta_usd'))}"
                    f" | open_pl={_fmt_signed_currency(item.get('open_pl_delta_usd'))}"
                    f" | position_value={_fmt_signed_currency(item.get('position_value_delta_usd'))}"
                    f" | start={item.get('start_snapshot_at', '-')}"
                    f" | end={item.get('end_snapshot_at', '-')}"
                )
            )
            movers = item.get("position_moves", [])
            if movers:
                top = sorted(
                    [_as_dict(move) for move in movers],
                    key=lambda move: float(move.get("unrealized_pl_delta_usd") or 0),
                )[:4]
                for move in top:
                    lines.append(
                        (
                            f"  - {move.get('symbol', '-')}"
                            f" | upl={_fmt_signed_currency(move.get('unrealized_pl_delta_usd'))}"
                            f" | {move.get('plan_status', '-')}"
                            f" | strategy={move.get('strategy_id', '-') or '-'}"
                        )
                    )

        lines.append("Worst repeated symbol giveback:")
        ranked = report.get("ranked_symbol_giveback", [])
        if ranked:
            for row in ranked[:8]:
                item = _as_dict(row)
                lines.append(
                    (
                        f"- {item.get('symbol', '-')}"
                        f" | total={_fmt_signed_currency(item.get('total_delta_usd'))}"
                        f" | days={int(item.get('days', 0) or 0)}"
                        f" | worst={_fmt_signed_currency(item.get('worst_delta_usd'))}"
                        f" | plan={item.get('plan_status', '-')}"
                        f" | strategy={item.get('strategy_id', '-') or '-'}"
                    )
                )
        else:
            lines.append("- none")

        missing = report.get("missing_entry_plan_symbols", [])
        lines.append("Currently unmanaged/missing entry plans:")
        if missing:
            for row in missing:
                item = _as_dict(row)
                lines.append(
                    (
                        f"- {item.get('symbol', '-')}"
                        f" | upl={_fmt_signed_currency(item.get('unrealized_pl_usd'))}"
                        f" | entry={_fmt_number(item.get('avg_entry_price'), 4)}"
                        f" | current={_fmt_number(item.get('current_price'), 4)}"
                    )
                )
        else:
            lines.append("- none")

        lines.append(
            "Note: this is a read-only diagnostic; it does not change exits, stops, sizing, or broker routing."
        )
        return "\n".join(lines)

    def _comparison_dates(self, *, days: int, timezone: str) -> list[date]:
        with self.usage_ledger._connect_postgres(scope="execution") as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT (captured_at AT TIME ZONE %s)::date AS session_date
                    FROM broker_account_snapshots
                    WHERE broker_id = 'alpaca_paper'
                    ORDER BY session_date DESC
                    LIMIT %s
                    """,
                    (timezone, days),
                )
                rows = cursor.fetchall()
        return [row["session_date"] for row in rows if row.get("session_date") is not None]

    def _recent_orders(self, *, limit: int) -> list[dict[str, Any]]:
        with self.usage_ledger._connect_postgres(scope="execution") as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT *
                    FROM paper_trade_orders
                    WHERE broker_id = 'alpaca_paper'
                    ORDER BY COALESCE(submitted_at::timestamptz, captured_at) DESC, order_id DESC
                    LIMIT %s
                    """,
                    (limit,),
                )
                rows = cursor.fetchall()
        return [dict(row) for row in rows]

    def _build_day_comparison(
        self,
        *,
        session_date: date,
        start_hour: int,
        end_hour: int,
        timezone: str,
        max_snapshot_age_minutes: int,
        recent_orders: list[dict[str, Any]],
    ) -> dict[str, Any]:
        start_snapshot = self._nearest_snapshot(
            session_date=session_date,
            hour=start_hour,
            timezone=timezone,
            max_snapshot_age_minutes=max_snapshot_age_minutes,
        )
        end_snapshot = self._nearest_snapshot(
            session_date=session_date,
            hour=end_hour,
            timezone=timezone,
            max_snapshot_age_minutes=max_snapshot_age_minutes,
        )
        reasons = []
        if start_snapshot is None:
            reasons.append(f"missing_{start_hour:02d}00_snapshot")
        if end_snapshot is None:
            reasons.append(f"missing_{end_hour:02d}00_snapshot")
        if start_snapshot is None or end_snapshot is None:
            return {
                "date": session_date.isoformat(),
                "complete": False,
                "reasons": reasons,
            }

        position_moves = self._position_moves(
            start_snapshot=start_snapshot,
            end_snapshot=end_snapshot,
            recent_orders=recent_orders,
        )
        return {
            "date": session_date.isoformat(),
            "complete": True,
            "start_snapshot_at": str(start_snapshot.get("local_time")),
            "end_snapshot_at": str(end_snapshot.get("local_time")),
            "equity_delta_usd": _delta(end_snapshot.get("equity"), start_snapshot.get("equity")),
            "open_pl_delta_usd": _delta(
                end_snapshot.get("open_position_unrealized_pl"),
                start_snapshot.get("open_position_unrealized_pl"),
            ),
            "position_value_delta_usd": _delta(
                end_snapshot.get("position_market_value"),
                start_snapshot.get("position_market_value"),
            ),
            "position_moves": position_moves,
        }

    def _nearest_snapshot(
        self,
        *,
        session_date: date,
        hour: int,
        timezone: str,
        max_snapshot_age_minutes: int,
    ) -> dict[str, Any] | None:
        target = f"{session_date.isoformat()} {int(hour):02d}:00:00 {timezone}"
        with self.usage_ledger._connect_postgres(scope="execution") as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT captured_at AT TIME ZONE %s AS local_time,
                           ABS(EXTRACT(EPOCH FROM (captured_at - %s::timestamptz))) / 60.0 AS age_minutes,
                           equity, cash, position_market_value, open_position_unrealized_pl, raw_json
                    FROM broker_account_snapshots
                    WHERE broker_id = 'alpaca_paper'
                    ORDER BY ABS(EXTRACT(EPOCH FROM (captured_at - %s::timestamptz))) ASC
                    LIMIT 1
                    """,
                    (timezone, target, target),
                )
                row = cursor.fetchone()
        if row is None:
            return None
        snapshot = dict(row)
        age_minutes = _to_float(snapshot.get("age_minutes"))
        if age_minutes is None or age_minutes > max_snapshot_age_minutes:
            return None
        return snapshot

    def _position_moves(
        self,
        *,
        start_snapshot: dict[str, Any],
        end_snapshot: dict[str, Any],
        recent_orders: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        start_positions = {
            str(position.get("symbol", "")).upper(): position
            for position in _positions_from_snapshot(start_snapshot)
            if str(position.get("symbol", "")).strip()
        }
        end_positions = {
            str(position.get("symbol", "")).upper(): position
            for position in _positions_from_snapshot(end_snapshot)
            if str(position.get("symbol", "")).strip()
        }
        rows = []
        for symbol in sorted(set(start_positions) | set(end_positions)):
            entry_order = _find_most_protective_managed_entry_order(
                symbol=symbol,
                orders=recent_orders,
                broker_id="alpaca_paper",
            )
            rows.append(
                {
                    "symbol": symbol,
                    "unrealized_pl_delta_usd": _delta(
                        (end_positions.get(symbol) or {}).get("unrealized_pl"),
                        (start_positions.get(symbol) or {}).get("unrealized_pl"),
                    ),
                    "start_unrealized_pl_usd": _to_float(
                        (start_positions.get(symbol) or {}).get("unrealized_pl")
                    ),
                    "end_unrealized_pl_usd": _to_float(
                        (end_positions.get(symbol) or {}).get("unrealized_pl")
                    ),
                    "plan_status": "managed" if entry_order else "missing_entry_plan",
                    "strategy_id": str((entry_order or {}).get("strategy_id") or ""),
                    "stop_loss_price": _to_float((entry_order or {}).get("stop_loss_price")),
                    "take_profit_price": _to_float((entry_order or {}).get("take_profit_price")),
                }
            )
        return rows

    def _rank_symbol_giveback(self, *, comparisons: list[dict[str, Any]]) -> list[dict[str, Any]]:
        grouped: dict[str, dict[str, Any]] = {}
        for comparison in comparisons:
            for move in comparison.get("position_moves", []):
                item = _as_dict(move)
                delta = _to_float(item.get("unrealized_pl_delta_usd")) or 0.0
                if delta >= 0:
                    continue
                symbol = str(item.get("symbol", "")).upper()
                if not symbol:
                    continue
                row = grouped.setdefault(
                    symbol,
                    {
                        "symbol": symbol,
                        "total_delta_usd": 0.0,
                        "days": 0,
                        "worst_delta_usd": 0.0,
                        "plan_status": item.get("plan_status", ""),
                        "strategy_id": item.get("strategy_id", ""),
                    },
                )
                row["total_delta_usd"] = round(float(row["total_delta_usd"]) + delta, 6)
                row["days"] = int(row["days"]) + 1
                row["worst_delta_usd"] = min(float(row["worst_delta_usd"]), delta)
                if item.get("plan_status") == "managed":
                    row["plan_status"] = "managed"
                    row["strategy_id"] = item.get("strategy_id", "")
        return sorted(grouped.values(), key=lambda item: float(item["total_delta_usd"]))

    def _latest_missing_entry_plan_symbols(
        self,
        *,
        recent_orders: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        with self.usage_ledger._connect_postgres(scope="execution") as connection:
            with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                cursor.execute(
                    """
                    SELECT raw_json
                    FROM broker_account_snapshots
                    WHERE broker_id = 'alpaca_paper'
                    ORDER BY captured_at DESC
                    LIMIT 1
                    """
                )
                row = cursor.fetchone()
        if row is None:
            return []
        missing = []
        for position in _positions_from_snapshot(dict(row)):
            symbol = str(position.get("symbol", "")).upper()
            if not symbol:
                continue
            entry_order = _find_most_protective_managed_entry_order(
                symbol=symbol,
                orders=recent_orders,
                broker_id="alpaca_paper",
            )
            if entry_order is not None:
                continue
            missing.append(
                {
                    "symbol": symbol,
                    "unrealized_pl_usd": _to_float(position.get("unrealized_pl")),
                    "avg_entry_price": _to_float(position.get("avg_entry_price")),
                    "current_price": _to_float(position.get("current_price")),
                }
            )
        return sorted(missing, key=lambda item: float(item.get("unrealized_pl_usd") or 0))


def _positions_from_snapshot(snapshot: dict[str, Any]) -> list[dict[str, Any]]:
    raw = snapshot.get("raw_json") or {}
    if not isinstance(raw, dict):
        return []
    positions = raw.get("positions") or []
    return [position for position in positions if isinstance(position, dict)]


def _delta(end_value: Any, start_value: Any) -> float:
    end = _to_float(end_value) or 0.0
    start = _to_float(start_value) or 0.0
    return round(end - start, 6)


def _to_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _fmt_signed_currency(value: Any, *, decimals: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        return "$-"
    return f"${number:+.{decimals}f}"


def _fmt_number(value: Any, decimals: int = 2) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return f"{number:.{decimals}f}"
