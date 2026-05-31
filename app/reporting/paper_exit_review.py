from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from app.runtime.settings import RuntimeConfig, load_runtime_config
from app.storage.usage import RealDictCursor, UsageLedger


class PaperExitReview:
    """Read-only post-mortem for paper exits versus stored shadow checkpoints."""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_review(
        self,
        *,
        strategy_id: str = "mean_reversion.snapback",
        recent_limit: int = 30,
    ) -> dict[str, Any]:
        entry_orders = self._load_entry_orders(strategy_id=strategy_id)
        if not entry_orders:
            return {
                "status": "insufficient_data",
                "strategy_id": strategy_id,
                "reason": "No filled paper entry orders exist for this strategy.",
            }

        latest_exit_by_proposal = self._load_latest_exit_by_proposal()
        checkpoints_by_proposal = self._load_checkpoints_by_proposal(
            strategy_id=strategy_id
        )
        rows = self._build_rows(
            entry_orders=entry_orders,
            latest_exit_by_proposal=latest_exit_by_proposal,
            checkpoints_by_proposal=checkpoints_by_proposal,
        )
        recent_rows = rows[: max(1, int(recent_limit))]

        return {
            "status": "ok",
            "mode": "read_only_post_mortem",
            "strategy_id": strategy_id,
            "recent_limit": max(1, int(recent_limit)),
            "recent_summary": self._summarize(recent_rows),
            "all_time_summary": self._summarize(rows),
            "recent_rows": [self._public_row(row) for row in recent_rows[:12]],
            "reason": (
                "Compare actual paper exits to stored 15m/1h/1d/7d shadow outcomes; "
                "do not use this alone to change live paper exits."
            ),
        }

    def render(self, *, review: dict[str, Any] | None = None) -> str:
        review = review or self.build_review()
        if review.get("status") != "ok":
            return (
                "Paper Exit Review\n"
                f"Status: {review.get('status', 'unknown')}\n"
                f"Reason: {review.get('reason', '-')}"
            )

        recent = _as_dict(review.get("recent_summary"))
        all_time = _as_dict(review.get("all_time_summary"))
        lines = [
            "Paper Exit Review",
            (
                f"Strategy: {review.get('strategy_id', '-')}"
                f" | mode={review.get('mode', 'read_only_post_mortem')}"
                f" | recent_limit={review.get('recent_limit', 0)}"
            ),
            f"Reason: {review.get('reason', '-')}",
            "Recent sample:",
            f"- {_summary_text(recent)}",
            "All-time sample:",
            f"- {_summary_text(all_time)}",
            "Recent examples:",
        ]
        for row in review.get("recent_rows", []):
            item = _as_dict(row)
            lines.append(
                (
                    f"- {item.get('symbol', '-')}"
                    f" | entered={item.get('entry_submitted_at', '-')}"
                    f" | exit={item.get('exit_reason', '-')}/{item.get('exit_status', '-')}"
                    f" | paper={_fmt_pct(item.get('paper_return_pct'))}"
                    f" | 15m={_fmt_pct(item.get('shadow_15m'))}"
                    f" | 1h={_fmt_pct(item.get('shadow_1h'))}"
                    f" | 1d={_fmt_pct(item.get('shadow_1d'))}"
                    f" | 7d={_fmt_pct(item.get('shadow_7d'))}"
                    f" | target_hits={_target_hits_text(item.get('profit_target_hits'))}"
                    f" | best={item.get('best_shadow_window', '-')}"
                )
            )
        return "\n".join(lines)

    def _load_entry_orders(self, *, strategy_id: str) -> list[dict[str, Any]]:
        if self.usage_ledger.backend == "postgres":
            with self.usage_ledger._connect_postgres() as connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT proposal_id, strategy_id, symbol, submitted_at AS entry_submitted_at,
                               filled_avg_price AS entry_price
                        FROM paper_trade_orders
                        WHERE side = %s
                          AND status = %s
                          AND proposal_id <> %s
                          AND strategy_id = %s
                        ORDER BY submitted_at DESC, proposal_id DESC
                        """,
                        ("buy", "filled", "", strategy_id),
                    )
                    rows = cursor.fetchall()
            return [dict(row) for row in rows]

        with self.usage_ledger._connect_sqlite() as connection:
            rows = connection.execute(
                """
                SELECT proposal_id, strategy_id, symbol, submitted_at AS entry_submitted_at,
                       filled_avg_price AS entry_price
                FROM paper_trade_orders
                WHERE side = ?
                  AND status = ?
                  AND proposal_id <> ?
                  AND strategy_id = ?
                ORDER BY submitted_at DESC, proposal_id DESC
                """,
                ("buy", "filled", "", strategy_id),
            ).fetchall()
        return [dict(row) for row in rows]

    def _load_latest_exit_by_proposal(self) -> dict[str, dict[str, Any]]:
        if self.usage_ledger.backend == "postgres":
            with self.usage_ledger._connect_postgres() as connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT proposal_id, status AS exit_status, submitted_at AS exit_submitted_at,
                               filled_avg_price AS exit_price, raw_json
                        FROM paper_trade_orders
                        WHERE side = %s
                          AND proposal_id <> %s
                        ORDER BY proposal_id ASC, submitted_at DESC
                        """,
                        ("sell", ""),
                    )
                    rows = cursor.fetchall()
            ordered = [dict(row) for row in rows]
        else:
            with self.usage_ledger._connect_sqlite() as connection:
                rows = connection.execute(
                    """
                    SELECT proposal_id, status AS exit_status, submitted_at AS exit_submitted_at,
                           filled_avg_price AS exit_price, raw_json
                    FROM paper_trade_orders
                    WHERE side = ?
                      AND proposal_id <> ?
                    ORDER BY proposal_id ASC, submitted_at DESC
                    """,
                    ("sell", ""),
                ).fetchall()
            ordered = [dict(row) for row in rows]

        latest: dict[str, dict[str, Any]] = {}
        for row in ordered:
            proposal_id = str(row.get("proposal_id", "")).strip()
            if not proposal_id or proposal_id in latest:
                continue
            raw_json = row.get("raw_json")
            payload = self._coerce_json(raw_json)
            latest[proposal_id] = {
                **row,
                "exit_reason": str(payload.get("exit_reason", "") or "").strip(),
            }
        return latest

    def _load_checkpoints_by_proposal(
        self,
        *,
        strategy_id: str,
    ) -> dict[str, dict[str, Any]]:
        if self.usage_ledger.backend == "postgres":
            with self.usage_ledger._connect_postgres(scope="core") as connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(
                        """
                        SELECT p.proposal_id, o.checkpoint_code, o.realized_return_pct, o.raw_json
                        FROM shadow_trade_proposals p
                        JOIN shadow_trade_outcomes o ON o.proposal_id = p.proposal_id
                        WHERE p.strategy_id = %s
                          AND o.evaluated_at IS NOT NULL
                        ORDER BY p.proposal_id ASC, o.checkpoint_code ASC
                        """,
                        (strategy_id,),
                    )
                    rows = cursor.fetchall()
            ordered = [dict(row) for row in rows]
        else:
            with self.usage_ledger._connect_sqlite() as connection:
                rows = connection.execute(
                    """
                    SELECT p.proposal_id, o.checkpoint_code, o.realized_return_pct, o.raw_json
                    FROM shadow_trade_proposals p
                    JOIN shadow_trade_outcomes o ON o.proposal_id = p.proposal_id
                    WHERE p.strategy_id = ?
                      AND o.evaluated_at IS NOT NULL
                    ORDER BY p.proposal_id ASC, o.checkpoint_code ASC
                    """,
                    (strategy_id,),
                ).fetchall()
            ordered = [dict(row) for row in rows]

        grouped: dict[str, dict[str, Any]] = {}
        for row in ordered:
            proposal_id = str(row.get("proposal_id", "")).strip()
            checkpoint_code = str(row.get("checkpoint_code", "")).strip().lower()
            if not proposal_id or not checkpoint_code:
                continue
            proposal_group = grouped.setdefault(
                proposal_id,
                {"profit_target_hits": {}, "profit_target_statuses": {}},
            )
            proposal_group[checkpoint_code] = _to_float(row.get("realized_return_pct"))
            payload = self._coerce_json(row.get("raw_json"))
            for item in _as_list(payload.get("profit_target_ladder")):
                ladder_item = _as_dict(item)
                target_key = _target_key(ladder_item.get("target_pct"))
                if not target_key:
                    continue
                hit = bool(ladder_item.get("target_hit"))
                ambiguous = bool(ladder_item.get("ambiguous"))
                current_hit = bool(proposal_group["profit_target_hits"].get(target_key))
                proposal_group["profit_target_hits"][target_key] = current_hit or hit or ambiguous
                proposal_group["profit_target_statuses"].setdefault(
                    target_key,
                    str(ladder_item.get("status", "") or ""),
                )
        return grouped

    def _build_rows(
        self,
        *,
        entry_orders: list[dict[str, Any]],
        latest_exit_by_proposal: dict[str, dict[str, Any]],
        checkpoints_by_proposal: dict[str, dict[str, Any]],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for entry in entry_orders:
            proposal_id = str(entry.get("proposal_id", "")).strip()
            if not proposal_id:
                continue
            exit_row = latest_exit_by_proposal.get(proposal_id, {})
            checkpoints = checkpoints_by_proposal.get(proposal_id, {})
            entry_price = _to_float(entry.get("entry_price"))
            exit_price = _to_float(exit_row.get("exit_price"))
            paper_return_pct = None
            if (
                entry_price is not None
                and exit_price is not None
                and abs(entry_price) > 0
            ):
                paper_return_pct = round(((exit_price - entry_price) / entry_price) * 100.0, 4)
            row = {
                "proposal_id": proposal_id,
                "symbol": str(entry.get("symbol", "")).upper(),
                "entry_submitted_at": _to_datetime(entry.get("entry_submitted_at")),
                "exit_submitted_at": _to_datetime(exit_row.get("exit_submitted_at")),
                "exit_status": str(exit_row.get("exit_status", "") or "").strip(),
                "exit_reason": str(exit_row.get("exit_reason", "") or "").strip(),
                "paper_return_pct": paper_return_pct,
                "shadow_15m": checkpoints.get("15m"),
                "shadow_1h": checkpoints.get("1h"),
                "shadow_1d": checkpoints.get("1d"),
                "shadow_7d": checkpoints.get("7d"),
                "profit_target_hits": checkpoints.get("profit_target_hits", {}),
                "profit_target_statuses": checkpoints.get("profit_target_statuses", {}),
            }
            row["best_shadow_window"] = self._best_shadow_window(row)
            rows.append(row)
        rows.sort(
            key=lambda item: item.get("entry_submitted_at") or datetime.min,
            reverse=True,
        )
        return rows

    def _summarize(self, rows: list[dict[str, Any]]) -> dict[str, Any]:
        comparable = [
            row
            for row in rows
            if row.get("shadow_1h") is not None and row.get("shadow_1d") is not None
        ]
        extended_comparable = [
            row
            for row in rows
            if row.get("shadow_1d") is not None and row.get("shadow_7d") is not None
        ]
        holding_rows = [
            row for row in comparable if row.get("exit_reason") == "holding_window_elapsed"
        ]
        paper_vs_shadow = [
            row
            for row in rows
            if row.get("paper_return_pct") is not None and row.get("shadow_1h") is not None
        ]
        return {
            "sample_rows": len(rows),
            "with_1h_and_1d": len(comparable),
            "holding_window_elapsed_rows": len(holding_rows),
            "one_day_beats_one_hour_count": sum(
                1 for row in comparable if float(row["shadow_1d"]) > float(row["shadow_1h"])
            ),
            "one_hour_beats_one_day_count": sum(
                1 for row in comparable if float(row["shadow_1h"]) > float(row["shadow_1d"])
            ),
            "avg_delta_1d_minus_1h": _avg(
                [float(row["shadow_1d"]) - float(row["shadow_1h"]) for row in comparable]
            ),
            "with_1d_and_7d": len(extended_comparable),
            "seven_day_beats_one_day_count": sum(
                1 for row in extended_comparable if float(row["shadow_7d"]) > float(row["shadow_1d"])
            ),
            "one_day_beats_seven_day_count": sum(
                1 for row in extended_comparable if float(row["shadow_1d"]) > float(row["shadow_7d"])
            ),
            "avg_delta_7d_minus_1d": _avg(
                [float(row["shadow_7d"]) - float(row["shadow_1d"]) for row in extended_comparable]
            ),
            "holding_elapsed_avg_delta_1d_minus_1h": _avg(
                [float(row["shadow_1d"]) - float(row["shadow_1h"]) for row in holding_rows]
            ),
            "paper_minus_shadow_1h_avg": _avg(
                [
                    float(row["paper_return_pct"]) - float(row["shadow_1h"])
                    for row in paper_vs_shadow
                ]
            ),
            "paper_minus_shadow_1h_count": len(paper_vs_shadow),
            "profit_target_hit_counts": self._profit_target_hit_counts(rows),
        }

    def _profit_target_hit_counts(self, rows: list[dict[str, Any]]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for row in rows:
            hits = _as_dict(row.get("profit_target_hits"))
            for target_key, hit in hits.items():
                if hit:
                    counts[str(target_key)] = counts.get(str(target_key), 0) + 1
        return dict(sorted(counts.items(), key=lambda item: float(item[0])))

    def _best_shadow_window(self, row: dict[str, Any]) -> str:
        windows = {
            "15m": row.get("shadow_15m"),
            "1h": row.get("shadow_1h"),
            "1d": row.get("shadow_1d"),
            "7d": row.get("shadow_7d"),
        }
        values = {key: float(value) for key, value in windows.items() if value is not None}
        if not values:
            return ""
        return max(values, key=values.get)

    def _public_row(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "symbol": row.get("symbol", ""),
            "entry_submitted_at": _fmt_dt(row.get("entry_submitted_at")),
            "exit_status": row.get("exit_status", ""),
            "exit_reason": row.get("exit_reason", ""),
            "paper_return_pct": row.get("paper_return_pct"),
            "shadow_15m": row.get("shadow_15m"),
            "shadow_1h": row.get("shadow_1h"),
            "shadow_1d": row.get("shadow_1d"),
            "shadow_7d": row.get("shadow_7d"),
            "profit_target_hits": row.get("profit_target_hits", {}),
            "best_shadow_window": row.get("best_shadow_window", ""),
        }

    def _coerce_json(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value in (None, ""):
            return {}
        try:
            parsed = json.loads(str(value))
        except (TypeError, ValueError):
            return {}
        return parsed if isinstance(parsed, dict) else {}


def _summary_text(summary: dict[str, Any]) -> str:
    return (
        f"rows={summary.get('sample_rows', 0)}"
        f" | 1d>1h={summary.get('one_day_beats_one_hour_count', 0)}"
        f" | 1h>1d={summary.get('one_hour_beats_one_day_count', 0)}"
        f" | avg(1d-1h)={_fmt_pct(summary.get('avg_delta_1d_minus_1h'))}"
        f" | 7d>1d={summary.get('seven_day_beats_one_day_count', 0)}"
        f" | 1d>7d={summary.get('one_day_beats_seven_day_count', 0)}"
        f" | avg(7d-1d)={_fmt_pct(summary.get('avg_delta_7d_minus_1d'))}"
        f" | holding_avg(1d-1h)={_fmt_pct(summary.get('holding_elapsed_avg_delta_1d_minus_1h'))}"
        f" | paper-shadow1h={_fmt_pct(summary.get('paper_minus_shadow_1h_avg'))}"
        f" | target_hits={_target_counts_text(summary.get('profit_target_hit_counts'))}"
        f" | comparable={summary.get('with_1h_and_1d', 0)}"
        f" | extended={summary.get('with_1d_and_7d', 0)}"
    )


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _fmt_pct(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "-"
    return f"{number:+.2f}%"


def _fmt_dt(value: Any) -> str:
    parsed = _to_datetime(value)
    if parsed is None:
        return "-"
    return parsed.isoformat(sep=" ", timespec="seconds")


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _target_key(value: Any) -> str:
    number = _to_float(value)
    if number is None or number <= 0:
        return ""
    return f"{number:g}"


def _target_hits_text(value: Any) -> str:
    hits = _as_dict(value)
    if not hits:
        return "-"
    labels = [f"{key}%" for key, hit in sorted(hits.items(), key=lambda item: float(item[0])) if hit]
    return ",".join(labels) if labels else "none"


def _target_counts_text(value: Any) -> str:
    counts = _as_dict(value)
    if not counts:
        return "-"
    return ",".join(
        f"{key}%:{int(count)}"
        for key, count in sorted(counts.items(), key=lambda item: float(item[0]))
    )


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
