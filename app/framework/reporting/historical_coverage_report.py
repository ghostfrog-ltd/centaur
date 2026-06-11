from __future__ import annotations

from collections import Counter
from datetime import datetime
import sys
from time import monotonic
from typing import Any

from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger
from app.framework.strategies.registry import build_strategy_registry

REPLAY_TIMEFRAMES = ("15Min", "1Hour", "1Day")
AUXILIARY_TIMEFRAMES = ("1Min",)
ALL_TIMEFRAMES = REPLAY_TIMEFRAMES + AUXILIARY_TIMEFRAMES
HOLDING_WINDOW_TO_TIMEFRAME = {
    "15m": "15Min",
    "1h": "1Hour",
    "1d": "1Day",
}


class HistoricalCoverageReport:
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
        started = monotonic()
        self._log_report_phase("build_report", "start")
        equity_profiles = self._equity_strategy_profiles()
        equity_symbols = list(self.config.discovery_equity_symbols)
        try:
            coverage_rows = self.usage_ledger.summarize_historical_bar_coverage(
                asset_class="equity",
                symbols=equity_symbols,
                timeframes=list(ALL_TIMEFRAMES),
            )
        except Exception as exc:
            result = {
                "status": "temporarily_unavailable",
                "backend": self.usage_ledger.backend,
                "reason": self._report_failure_reason(exc),
                "equity_strategy_profiles": equity_profiles,
                "equity_symbols": equity_symbols,
            }
            self._log_report_phase("build_report", "failed", elapsed_ms=int((monotonic() - started) * 1000))
            return result
        coverage_index = {
            (str(row.get("symbol", "")), str(row.get("timeframe", ""))): row
            for row in coverage_rows
        }
        per_symbol_rows: list[dict[str, Any]] = []
        timeframe_counts = Counter()
        symbol_gap_count = 0
        for symbol in equity_symbols:
            symbol_has_any = False
            for timeframe in ALL_TIMEFRAMES:
                row = dict(coverage_index.get((symbol, timeframe), {}))
                row_count = int(row.get("row_count", 0) or 0)
                if row_count > 0:
                    symbol_has_any = True
                    timeframe_counts[timeframe] += 1
                per_symbol_rows.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "row_count": row_count,
                        "earliest_bar_timestamp": row.get("earliest_bar_timestamp"),
                        "latest_bar_timestamp": row.get("latest_bar_timestamp"),
                        "sources": list(row.get("sources", []) or []),
                        "venues": list(row.get("venues", []) or []),
                        "distinct_bar_days": int(row.get("distinct_bar_days", 0) or 0),
                        "gap_hint": self._gap_hint(
                            row_count=row_count,
                            distinct_bar_days=int(row.get("distinct_bar_days", 0) or 0),
                            timeframe=timeframe,
                        ),
                    }
                )
            if not symbol_has_any:
                symbol_gap_count += 1
        timeframe_summary = [
            self._timeframe_summary(
                timeframe=timeframe,
                symbols=equity_symbols,
                per_symbol_rows=per_symbol_rows,
            )
            for timeframe in ALL_TIMEFRAMES
        ]
        verdict = self._verdict(
            equity_symbols=equity_symbols,
            timeframe_summary=timeframe_summary,
            symbol_gap_count=symbol_gap_count,
        )
        result = {
            "status": "ok",
            "backend": self.usage_ledger.backend,
            "equity_strategy_profiles": equity_profiles,
            "equity_symbols": equity_symbols,
            "checked_replay_timeframes": list(REPLAY_TIMEFRAMES),
            "checked_auxiliary_timeframes": list(AUXILIARY_TIMEFRAMES),
            "timeframe_coverage_counts": dict(timeframe_counts),
            "symbol_coverage_gap_count": symbol_gap_count,
            "timeframe_summary": timeframe_summary,
            "rows": per_symbol_rows,
            "verdict": verdict,
        }
        self._log_report_phase("build_report", "done", elapsed_ms=int((monotonic() - started) * 1000))
        return result

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        started = monotonic()
        self._log_report_phase("render", "start")
        report = report or self.build_report()
        if report.get("status") != "ok":
            rendered = (
                "Historical Coverage Report\n"
                f"status={report.get('status', 'unknown')}\n"
                f"reason={report.get('reason', '-')}"
            )
            self._log_report_phase("render", "done", elapsed_ms=int((monotonic() - started) * 1000))
            return rendered
        lines = [
            "Historical Coverage Report",
            f"backend={report.get('backend', '-')}",
            "equity_strategy_profiles="
            + ",".join(
                f"{item.get('strategy_id', '-')}/{item.get('profile_id', '-')}"
                f"@{item.get('replay_timeframe', '-')}"
                for item in report.get("equity_strategy_profiles", []) or []
            ),
            "equity_symbols=" + ",".join(report.get("equity_symbols", []) or ["-"]),
            "checked_replay_timeframes="
            + ",".join(report.get("checked_replay_timeframes", []) or ["-"]),
            "checked_auxiliary_timeframes="
            + ",".join(report.get("checked_auxiliary_timeframes", []) or ["-"]),
            f"symbol_coverage_gap_count={report.get('symbol_coverage_gap_count', 0)}",
            "Timeframe Summary",
        ]
        for item in report.get("timeframe_summary", []) or []:
            lines.append(
                f"timeframe={item.get('timeframe', '-')}"
                f" | symbols_with_rows={item.get('symbols_with_rows', 0)}/{item.get('symbol_count', 0)}"
                f" | total_rows={item.get('total_rows', 0)}"
                f" | earliest={self._fmt_dt(item.get('earliest_bar_timestamp'))}"
                f" | latest={self._fmt_dt(item.get('latest_bar_timestamp'))}"
            )
            lines.append(
                f"  missing_symbols={','.join(item.get('missing_symbols', []) or ['none'])}"
            )
        lines.append("Per Symbol Coverage")
        for row in report.get("rows", []) or []:
            lines.append(
                f"symbol={row.get('symbol', '-')}"
                f" | timeframe={row.get('timeframe', '-')}"
                f" | row_count={row.get('row_count', 0)}"
                f" | earliest={self._fmt_dt(row.get('earliest_bar_timestamp'))}"
                f" | latest={self._fmt_dt(row.get('latest_bar_timestamp'))}"
                f" | source={','.join(row.get('sources', []) or ['-'])}"
                f" | venue={','.join(row.get('venues', []) or ['-'])}"
                f" | distinct_bar_days={row.get('distinct_bar_days', 0)}"
                f" | gap_hint={row.get('gap_hint', '-')}"
            )
        lines.append(f"verdict={report.get('verdict', 'mixed')}")
        rendered = "\n".join(lines)
        self._log_report_phase("render", "done", elapsed_ms=int((monotonic() - started) * 1000))
        return rendered

    def _report_failure_reason(self, exc: Exception) -> str:
        message = str(exc).strip()
        lowered = message.lower()
        if "lock timeout" in lowered or "locknotavailable" in lowered:
            return "historical_coverage_query_lock_timeout"
        return f"{type(exc).__name__}: {message}" if message else type(exc).__name__

    def _equity_strategy_profiles(self) -> list[dict[str, str]]:
        rows: list[dict[str, str]] = []
        for strategy in build_strategy_registry():
            for profile in strategy.build_profiles(self.config):
                if "equity" not in tuple(str(item) for item in profile.asset_classes):
                    continue
                rows.append(
                    {
                        "strategy_id": str(profile.strategy_id),
                        "profile_id": str(profile.profile_id),
                        "replay_timeframe": HOLDING_WINDOW_TO_TIMEFRAME.get(
                            str(profile.holding_window_code),
                            str(profile.holding_window_code),
                        ),
                    }
                )
        rows.sort(key=lambda item: (item["strategy_id"], item["profile_id"]))
        return rows

    def _timeframe_summary(
        self,
        *,
        timeframe: str,
        symbols: list[str],
        per_symbol_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        rows = [row for row in per_symbol_rows if str(row.get("timeframe", "")) == timeframe]
        present = [row for row in rows if int(row.get("row_count", 0) or 0) > 0]
        missing_symbols = sorted(
            str(row.get("symbol", ""))
            for row in rows
            if int(row.get("row_count", 0) or 0) <= 0
        )
        earliest = min(
            (row.get("earliest_bar_timestamp") for row in present if isinstance(row.get("earliest_bar_timestamp"), datetime)),
            default=None,
        )
        latest = max(
            (row.get("latest_bar_timestamp") for row in present if isinstance(row.get("latest_bar_timestamp"), datetime)),
            default=None,
        )
        return {
            "timeframe": timeframe,
            "symbol_count": len(symbols),
            "symbols_with_rows": len(present),
            "missing_symbols": missing_symbols,
            "total_rows": sum(int(row.get("row_count", 0) or 0) for row in present),
            "earliest_bar_timestamp": earliest,
            "latest_bar_timestamp": latest,
        }

    def _gap_hint(self, *, row_count: int, distinct_bar_days: int, timeframe: str) -> str:
        if row_count <= 0:
            return "no_rows"
        if distinct_bar_days <= 0:
            return "rows_without_distinct_days"
        if timeframe != "1Day" and distinct_bar_days == 1 and row_count <= 8:
            return "single_day_only"
        if distinct_bar_days <= 5:
            return "short_span"
        return "not_checked_for_intraday_session_gaps"

    def _verdict(
        self,
        *,
        equity_symbols: list[str],
        timeframe_summary: list[dict[str, Any]],
        symbol_gap_count: int,
    ) -> str:
        summary_by_timeframe = {
            str(item.get("timeframe", "")): item for item in timeframe_summary
        }
        symbol_count = len(equity_symbols)
        one_min_present = int(summary_by_timeframe.get("1Min", {}).get("symbols_with_rows", 0) or 0)
        replay_present = {
            timeframe: int(summary_by_timeframe.get(timeframe, {}).get("symbols_with_rows", 0) or 0)
            for timeframe in REPLAY_TIMEFRAMES
        }
        if symbol_gap_count > 0:
            return "symbol_coverage_gap"
        if one_min_present > 0 and all(count <= 0 for count in replay_present.values()):
            return "only_1min_backfilled"
        missing_full = [
            timeframe for timeframe, count in replay_present.items() if count <= 0 and symbol_count > 0
        ]
        if len(missing_full) == 1:
            timeframe = missing_full[0]
            return {
                "15Min": "missing_15min_bars",
                "1Hour": "missing_1hour_bars",
                "1Day": "missing_1day_bars",
            }.get(timeframe, "mixed")
        if len(missing_full) > 1:
            return "mixed"
        partial_missing = any(
            int(summary_by_timeframe.get(timeframe, {}).get("symbols_with_rows", 0) or 0) < symbol_count
            for timeframe in REPLAY_TIMEFRAMES
        )
        if partial_missing:
            return "mixed"
        return "mixed"

    def _fmt_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")

    def _log_report_phase(self, phase: str, status: str, *, elapsed_ms: int | None = None) -> None:
        suffix = f" elapsed_ms={elapsed_ms}" if elapsed_ms is not None else ""
        print(
            f"report_diagnostic report=historical_coverage_report phase={phase} status={status}{suffix}",
            file=sys.stderr,
            flush=True,
        )
