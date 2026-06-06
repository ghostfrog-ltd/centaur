from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from app.framework.engine.replay import _max_checkpoint_window_minutes, _window_code_to_minutes
from app.framework.engine.research_cycle import ResearchCycleRunner
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class HistoricalReplayCoverageReport:
    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_report(self) -> dict[str, Any]:
        runner = ResearchCycleRunner(config=self.config, usage_ledger=self.usage_ledger)
        diagnostics = runner.build_historical_replay_diagnostics()
        inventory = diagnostics["inventory"]
        historical = dict(inventory.get("historical", {}) or {})
        sources = [str(item.get("source", "") or "") for item in historical.get("rows_by_source", [])]
        timeframes = [str(item.get("timeframe", "") or "") for item in historical.get("rows_by_timeframe", [])]
        symbol_timeframe_rows = self._symbol_timeframe_rows()
        return {
            "backend": inventory.get("backend"),
            "backend_detail": inventory.get("backend_detail"),
            "historical": historical,
            "available_sources": sources,
            "available_timeframes": timeframes,
            "symbol_timeframe_rows": symbol_timeframe_rows,
            "timeframe_existence": {
                "1Min": "1Min" in timeframes,
                "15Min": "15Min" in timeframes,
                "1Hour": "1Hour" in timeframes,
            },
            "future_outcome_coverage": self._future_outcome_coverage(symbol_timeframe_rows),
            "diagnostics": diagnostics,
        }

    def render(self) -> str:
        report = self.build_report()
        diagnostics = report["diagnostics"]
        lines = [
            "Historical Replay Coverage",
            f"selected_storage_backend={report.get('backend', '-')}",
            f"selected_storage_backend_detail={report.get('backend_detail', '-')}",
            f"available_historical_bar_sources={','.join(report.get('available_sources', []) or ['-'])}",
            "timeframe_exists_1Min=" + ("yes" if report["timeframe_existence"].get("1Min") else "no"),
            "timeframe_exists_15Min=" + ("yes" if report["timeframe_existence"].get("15Min") else "no"),
            "timeframe_exists_1Hour=" + ("yes" if report["timeframe_existence"].get("1Hour") else "no"),
        ]
        for row in report.get("symbol_timeframe_rows", []):
            lines.append(
                "symbol_timeframe="
                f"{row.get('symbol', '-')}"
                f" | asset_class={row.get('asset_class', '-')}"
                f" | timeframe={row.get('timeframe', '-')}"
                f" | earliest={self._fmt_dt(row.get('earliest_timestamp'))}"
                f" | latest={self._fmt_dt(row.get('latest_timestamp'))}"
                f" | bar_count={int(row.get('bar_count', 0) or 0)}"
            )
        coverage = report.get("future_outcome_coverage", {})
        for key in ("15m", "1h", "1d", "7d"):
            lines.append(
                f"enough_future_data_exists_for_{key}_outcome="
                + ("yes" if coverage.get(key) else "no")
            )
        lines.extend(
            [
                f"latest_available_historical_bar_at={self._fmt_dt(diagnostics.get('latest_available_historical_bar_at'))}",
                f"max_required_future_horizon={self._fmt_delta(diagnostics.get('max_required_future_horizon'))}",
                f"latest_valid_replay_window_end={self._fmt_dt(diagnostics.get('latest_valid_replay_window_end'))}",
                f"window_anchor_mode={diagnostics.get('window_anchor_mode', '-') or '-'}",
            ]
        )
        lines.extend(
            [
                f"replay_window_candidates_found={len(diagnostics.get('replay_window_candidates', []) or [])}",
                f"replay_window_candidates_accepted={int(diagnostics.get('replay_windows_accepted_count', 0) or 0)}",
                f"replay_window_candidates_rejected={int(diagnostics.get('replay_windows_rejected_count', 0) or 0)}",
            ]
        )
        for item in diagnostics.get("replay_window_acceptances", []) or []:
            lines.append(
                "accepted_replay_window="
                f"timeframe={item.get('timeframe', '-')}"
                f" | start_at={item.get('start_at', '-')}"
                f" | end_at={item.get('end_at', '-')}"
                f" | reason={item.get('reason', '-')}"
            )
        for timeframe, item in sorted((diagnostics.get("timeframe_historical_coverage", {}) or {}).items()):
            lines.append(
                "timeframe_historical_coverage="
                f"timeframe={timeframe}"
                f" | earliest={item.get('earliest_available_historical_bar_at', '-') or '-'}"
                f" | latest={item.get('latest_available_historical_bar_at', '-') or '-'}"
                f" | latest_valid_replay_window_end={item.get('latest_valid_replay_window_end', '-') or '-'}"
                f" | max_required_future_horizon={item.get('max_required_future_horizon', '-') or '-'}"
            )
        for item in diagnostics.get("replay_window_rejections", []) or []:
            lines.append(
                "rejected_replay_window="
                f"timeframe={item.get('timeframe', '-')}"
                f" | start_at={item.get('start_at', '-')}"
                f" | end_at={item.get('end_at', '-')}"
                f" | reason={item.get('reason', '-')}"
            )
        return "\n".join(lines)

    def _symbol_timeframe_rows(self) -> list[dict[str, Any]]:
        inventory = self.usage_ledger.summarize_historical_bars(as_of=datetime.now().astimezone())
        historical = dict(inventory.get("historical", {}) or {})
        min_at = historical.get("min_bar_timestamp")
        max_at = historical.get("max_bar_timestamp")
        rows: list[dict[str, Any]] = []
        for timeframe_row in historical.get("rows_by_timeframe", []) or []:
            timeframe = str(timeframe_row.get("timeframe", "") or "")
            if not timeframe:
                continue
            bars = self.usage_ledger.list_historical_bars(
                timeframe=timeframe,
                sources=["alpaca_market_data", "alpaca_crypto_data"],
                start_at=min_at if isinstance(min_at, datetime) else None,
                end_at=max_at if isinstance(max_at, datetime) else None,
            )
            grouped: dict[tuple[str, str], list[datetime]] = defaultdict(list)
            for row in bars:
                symbol = str(row.get("symbol", "") or "")
                asset_class = str(row.get("asset_class", "") or "")
                ts = row.get("bar_timestamp")
                if not symbol or not isinstance(ts, datetime):
                    continue
                grouped[(symbol, asset_class)].append(ts)
            for (symbol, asset_class), timestamps in sorted(grouped.items()):
                ordered = sorted(timestamps)
                rows.append(
                    {
                        "symbol": symbol,
                        "asset_class": asset_class or "unknown",
                        "timeframe": timeframe,
                        "earliest_timestamp": ordered[0],
                        "latest_timestamp": ordered[-1],
                        "bar_count": len(ordered),
                    }
                )
        return rows

    def _future_outcome_coverage(self, rows: list[dict[str, Any]]) -> dict[str, bool]:
        required = {"15m": 15, "1h": 60, "1d": 1440, "7d": 10080}
        observed_by_timeframe: dict[str, int] = defaultdict(int)
        for row in rows:
            timeframe = str(row.get("timeframe", "") or "")
            if not timeframe:
                continue
            try:
                observed_by_timeframe[timeframe] = max(
                    observed_by_timeframe[timeframe],
                    _window_code_to_minutes(self._coverage_window_code(row)),
                )
            except ValueError:
                continue
        supported_windows = tuple(getattr(self.config, "shadow_checkpoint_windows", ("15m", "1h", "1d", "7d")))
        supported_max = _max_checkpoint_window_minutes(supported_windows)
        return {
            key: any(minutes <= span for span in observed_by_timeframe.values()) or supported_max >= minutes
            for key, minutes in required.items()
        }

    def _coverage_window_code(self, row: dict[str, Any]) -> str:
        timeframe = str(row.get("timeframe", "") or "")
        if timeframe.endswith("Min"):
            return timeframe[:-3] + "m"
        if timeframe.endswith("Hour"):
            return timeframe[:-4] + "h"
        if timeframe.endswith("Day"):
            return timeframe[:-3] + "d"
        return "15m"

    def _fmt_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")

    def _fmt_delta(self, value: Any) -> str:
        if isinstance(value, timedelta):
            return str(value)
        return str(value or "-")
