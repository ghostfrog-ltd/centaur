from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from app.runtime.settings import RuntimeConfig, load_runtime_config
from .strategy_health_report import _as_dict, _fmt_pct
from app.storage.usage import RealDictCursor, UsageLedger


class CryptoHealthReport:
    """Read-only operator report for overnight crypto scan health."""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_report(self, *, lookback_hours: int = 36) -> dict[str, Any]:
        latest_tick = self.usage_ledger.get_latest_tick_run()
        checked_at = self._as_datetime((latest_tick or {}).get("ended_at")) or datetime.now().astimezone()
        overnight_rows = self._overnight_ticks(lookback_hours=lookback_hours)
        symbol_counts = self._overnight_symbol_counts(overnight_rows=overnight_rows)
        fitness_rows = self._latest_crypto_fitness_snapshot()
        configured_symbols = list(self.config.discovery_crypto_symbols)
        latest_overnight = overnight_rows[0] if overnight_rows else {}

        return {
            "status": "ok",
            "checked_at": checked_at.isoformat(),
            "backend": self.usage_ledger.backend,
            "lookback_hours": lookback_hours,
            "configured_discovery_symbols": configured_symbols,
            "configured_broker_symbols": list(self.config.alpaca_crypto_symbols),
            "overnight_summary": self._overnight_summary(overnight_rows=overnight_rows),
            "latest_overnight_tick": latest_overnight,
            "raw_preview_symbol_counts": symbol_counts["raw"],
            "suppressed_preview_symbol_counts": symbol_counts["suppressed"],
            "selected_candidate_symbol_counts": symbol_counts["selected"],
            "latest_crypto_fitness_snapshot": fitness_rows,
        }

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        report = report or self.build_report()
        if report.get("status") != "ok":
            return (
                "Crypto Health Report\n"
                f"Status: {report.get('status', 'unknown')}\n"
                f"Reason: {report.get('reason', '-')}"
            )

        summary = _as_dict(report.get("overnight_summary"))
        latest_tick = _as_dict(report.get("latest_overnight_tick"))
        discovery_symbols = report.get("configured_discovery_symbols", [])
        broker_symbols = report.get("configured_broker_symbols", [])

        lines = [
            "Crypto Health Report",
            (
                f"backend={report.get('backend', '-')}"
                f" | lookback={int(report.get('lookback_hours', 0) or 0)}h"
                f" | checked_at={report.get('checked_at', '-')}"
            ),
            (
                f"Configured crypto universe: discovery={len(discovery_symbols)}"
                f" | broker={len(broker_symbols)}"
            ),
            f"Symbols: {', '.join(discovery_symbols) if discovery_symbols else 'none'}",
        ]

        if summary:
            lines.append("Recent crypto-only tick summary:")
            lines.append(
                (
                    f"- ticks={int(summary.get('tick_count', 0) or 0)}"
                    f" | first={summary.get('first_started_at', '-')}"
                    f" | last={summary.get('last_started_at', '-')}"
                )
            )
            lines.append(
                (
                    f"- crypto bars fetched={int(summary.get('ticks_fetching_crypto_bars', 0) or 0)}"
                    f" | ticks with crypto raw preview={int(summary.get('ticks_with_crypto_raw_preview', 0) or 0)}"
                    f" | ticks with crypto suppressed preview={int(summary.get('ticks_with_crypto_suppressed_preview', 0) or 0)}"
                )
            )
            lines.append(
                (
                    f"- avg bars requested={summary.get('avg_bars_requested', '-')}"
                    f" | avg bars received={summary.get('avg_bars_received', '-')}"
                    f" | avg selected crypto candidates={summary.get('avg_selected_candidates', '-')}"
                )
            )
        else:
            lines.append("Recent crypto-only tick summary:")
            lines.append("- No crypto-only ticks found in the lookback window.")

        if latest_tick:
            lines.append("Latest crypto-only tick:")
            lines.append(
                (
                    f"- time={latest_tick.get('started_at', '-')}"
                    f" | crypto_mode={latest_tick.get('crypto_mode', '-')}"
                    f" | bars_requested={int(latest_tick.get('bars_requested', 0) or 0)}"
                    f" | bars_received={int(latest_tick.get('bars_received', 0) or 0)}"
                )
            )
            lines.append(
                (
                    f"- crypto_in_raw={'yes' if latest_tick.get('crypto_in_raw') else 'no'}"
                    f" | crypto_in_suppressed={'yes' if latest_tick.get('crypto_in_suppressed') else 'no'}"
                    f" | selected_candidates={int(latest_tick.get('selected_candidates_count', 0) or 0)}"
                )
            )

        lines.append("Recent crypto raw preview symbols:")
        raw_symbols = report.get("raw_preview_symbol_counts", [])
        if raw_symbols:
            for symbol, count in raw_symbols:
                lines.append(f"- {symbol}: {count}")
        else:
            lines.append("- none")

        lines.append("Recent crypto suppressed preview symbols:")
        suppressed_symbols = report.get("suppressed_preview_symbol_counts", [])
        if suppressed_symbols:
            for symbol, count in suppressed_symbols:
                lines.append(f"- {symbol}: {count}")
        else:
            lines.append("- none")

        lines.append("Recent selected overnight crypto candidates:")
        selected_symbols = report.get("selected_candidate_symbol_counts", [])
        if selected_symbols:
            for symbol, count in selected_symbols:
                lines.append(f"- {symbol}: {count}")
        else:
            lines.append("- none")

        lines.append("Latest crypto fitness snapshot:")
        fitness_rows = report.get("latest_crypto_fitness_snapshot", [])
        if fitness_rows:
            for row in fitness_rows:
                item = _as_dict(row)
                lines.append(
                    (
                        f"- {item.get('strategy_id', '-')}"
                        f" | {item.get('checkpoint_code', '-')}"
                        f" | rank={int(item.get('fitness_rank', 0) or 0)}"
                        f" | evidence={item.get('source_environment', '-')}"
                        f"/{item.get('environment', '-')}"
                        f" | proposals={int(item.get('evaluated_proposals', 0) or 0)}"
                        f" | avg={_fmt_pct(item.get('avg_realized_return_pct'))}"
                        f" | fit={_fmt_pct(item.get('composite_fitness_score'))}"
                    )
                )
        else:
            lines.append("- none")

        return "\n".join(lines)

    def _overnight_ticks(self, *, lookback_hours: int) -> list[dict[str, Any]]:
        cutoff = datetime.now().astimezone() - timedelta(hours=lookback_hours)
        query = """
            SELECT tick_id, started_at,
                   COALESCE(state_snapshot_json->'market_gate'->>'reason', '') AS reason,
                   COALESCE(state_snapshot_json->'crypto_data_latest_bars'->>'mode', '') AS crypto_mode,
                   COALESCE((state_snapshot_json->'crypto_data_latest_bars'->>'bars_requested')::int, 0) AS bars_requested,
                   COALESCE((state_snapshot_json->'crypto_data_latest_bars'->>'bars_received')::int, 0) AS bars_received,
                   COALESCE(jsonb_array_length(COALESCE(state_snapshot_json->'market_scan'->'selected_candidates', '[]'::jsonb)), 0) AS selected_candidates_count,
                   state_snapshot_json
            FROM control_tick_runs
            WHERE started_at >= %s
              AND COALESCE(state_snapshot_json->'market_gate'->>'reason', '') = 'crypto_only_window'
            ORDER BY started_at DESC
        """
        if self.usage_ledger.backend != "postgres":
            query = """
                SELECT tick_id, started_at,
                       COALESCE(json_extract(state_snapshot_json, '$.market_gate.reason'), '') AS reason,
                       COALESCE(json_extract(state_snapshot_json, '$.crypto_data_latest_bars.mode'), '') AS crypto_mode,
                       COALESCE(json_extract(state_snapshot_json, '$.crypto_data_latest_bars.bars_requested'), 0) AS bars_requested,
                       COALESCE(json_extract(state_snapshot_json, '$.crypto_data_latest_bars.bars_received'), 0) AS bars_received,
                       COALESCE(json_array_length(COALESCE(json_extract(state_snapshot_json, '$.market_scan.selected_candidates'), '[]')), 0) AS selected_candidates_count,
                       state_snapshot_json
                FROM control_tick_runs
                WHERE started_at >= ?
                  AND COALESCE(json_extract(state_snapshot_json, '$.market_gate.reason'), '') = 'crypto_only_window'
                ORDER BY started_at DESC
            """
        rows = self._query_rows(query=query, params=(cutoff,))
        normalized: list[dict[str, Any]] = []
        for row in rows:
            snapshot = row.get("state_snapshot_json")
            if not isinstance(snapshot, dict):
                snapshot = self._coerce_json(snapshot)
            strategy_state = _as_dict(snapshot.get("strategy_signals"))
            raw_preview = strategy_state.get("raw_signal_preview", []) or []
            suppressed_preview = strategy_state.get("suppressed_signal_preview", []) or []
            row_copy = dict(row)
            row_copy["state_snapshot_json"] = snapshot
            row_copy["crypto_in_raw"] = any(
                isinstance(item, dict) and str(item.get("strategy_id", "") or "") == "crypto_momentum.trend"
                for item in raw_preview
            )
            row_copy["crypto_in_suppressed"] = any(
                isinstance(item, dict) and str(item.get("strategy_id", "") or "") == "crypto_momentum.trend"
                for item in suppressed_preview
            )
            row_copy["started_at"] = self._as_datetime(row.get("started_at"))
            normalized.append(row_copy)
        return normalized

    def _overnight_summary(self, *, overnight_rows: list[dict[str, Any]]) -> dict[str, Any]:
        if not overnight_rows:
            return {}
        tick_count = len(overnight_rows)
        bars_requested_total = sum(int(row.get("bars_requested", 0) or 0) for row in overnight_rows)
        bars_received_total = sum(int(row.get("bars_received", 0) or 0) for row in overnight_rows)
        selected_total = sum(int(row.get("selected_candidates_count", 0) or 0) for row in overnight_rows)
        started_values = [row.get("started_at") for row in overnight_rows if isinstance(row.get("started_at"), datetime)]
        return {
            "tick_count": tick_count,
            "first_started_at": min(started_values).isoformat() if started_values else None,
            "last_started_at": max(started_values).isoformat() if started_values else None,
            "ticks_fetching_crypto_bars": sum(
                1 for row in overnight_rows if str(row.get("crypto_mode", "") or "") == "latest_crypto_bars"
            ),
            "ticks_with_crypto_raw_preview": sum(1 for row in overnight_rows if bool(row.get("crypto_in_raw"))),
            "ticks_with_crypto_suppressed_preview": sum(
                1 for row in overnight_rows if bool(row.get("crypto_in_suppressed"))
            ),
            "avg_bars_requested": round(bars_requested_total / tick_count, 2),
            "avg_bars_received": round(bars_received_total / tick_count, 2),
            "avg_selected_candidates": round(selected_total / tick_count, 2),
        }

    def _overnight_symbol_counts(
        self,
        *,
        overnight_rows: list[dict[str, Any]],
    ) -> dict[str, list[tuple[str, int]]]:
        raw_counts: Counter[str] = Counter()
        suppressed_counts: Counter[str] = Counter()
        selected_counts: Counter[str] = Counter()

        for row in overnight_rows:
            snapshot = _as_dict(row.get("state_snapshot_json"))
            strategy_state = _as_dict(snapshot.get("strategy_signals"))
            market_scan = _as_dict(snapshot.get("market_scan"))
            for item in strategy_state.get("raw_signal_preview", []) or []:
                if isinstance(item, dict) and str(item.get("strategy_id", "") or "") == "crypto_momentum.trend":
                    raw_counts[str(item.get("symbol", "") or "")] += 1
            for item in strategy_state.get("suppressed_signal_preview", []) or []:
                if isinstance(item, dict) and str(item.get("strategy_id", "") or "") == "crypto_momentum.trend":
                    suppressed_counts[str(item.get("symbol", "") or "")] += 1
            for item in market_scan.get("selected_candidates", []) or []:
                if isinstance(item, dict) and str(item.get("asset_class", "") or "") == "crypto":
                    selected_counts[str(item.get("symbol", "") or "")] += 1

        return {
            "raw": sorted(raw_counts.items(), key=lambda item: (-item[1], item[0])),
            "suppressed": sorted(suppressed_counts.items(), key=lambda item: (-item[1], item[0])),
            "selected": sorted(selected_counts.items(), key=lambda item: (-item[1], item[0])),
        }

    def _latest_crypto_fitness_snapshot(self) -> list[dict[str, Any]]:
        query = """
            SELECT strategy_id, checkpoint_code, fitness_rank, evaluated_proposals,
                   checkpoints_evaluated, composite_fitness_score,
                   avg_realized_return_pct, last_evaluated_at
            FROM strategy_fitness_snapshots
            WHERE captured_at = (
                SELECT MAX(captured_at) FROM strategy_fitness_snapshots
            )
              AND asset_class = 'crypto'
            ORDER BY fitness_rank ASC, checkpoint_code ASC, strategy_id ASC
        """
        return [dict(row) for row in self._query_rows(query=query, scope="core")]

    def _query_rows(
        self,
        *,
        query: str,
        params: tuple[Any, ...] = tuple(),
        scope: str = "default",
    ) -> list[dict[str, Any]]:
        if self.usage_ledger.backend == "postgres":
            with self.usage_ledger._connect_postgres(scope=scope) as connection:
                with connection.cursor(cursor_factory=RealDictCursor) as cursor:
                    cursor.execute(query, params)
                    rows = cursor.fetchall()
            return [dict(row) for row in rows]

        import sqlite3

        with self.usage_ledger._connect_sqlite() as connection:
            connection.row_factory = sqlite3.Row
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def _coerce_json(self, value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value in (None, ""):
            return {}
        import json

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
