from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from app.framework.engine.replay import (
    _eligible_replay_timestamps,
    _max_checkpoint_window_minutes,
    _supported_checkpoint_windows,
)
from app.framework.runtime.settings import RuntimeConfig, load_runtime_config
from app.framework.storage.usage import UsageLedger


class HistoricalBarsStatusReport:
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
        days: int | None = None,
        timeframe: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        equity_symbols: tuple[str, ...] | None = None,
        crypto_symbols: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        as_of = end_at or datetime.now().astimezone()
        resolved_timeframe = (
            (timeframe or self.config.historical_replay_default_timeframe).strip()
            or self.config.historical_replay_default_timeframe
        )
        resolved_days = max(1, days or self.config.historical_replay_default_days)
        resolved_end_at = end_at or as_of
        resolved_start_at = start_at or (resolved_end_at - timedelta(days=resolved_days))
        resolved_equity_symbols = equity_symbols or self.config.discovery_equity_symbols
        resolved_crypto_symbols = crypto_symbols or self.config.discovery_crypto_symbols
        symbol_filters = list(resolved_equity_symbols) + list(resolved_crypto_symbols)
        expected_sources = ["alpaca_market_data", "alpaca_crypto_data"]
        inventory = self.usage_ledger.summarize_historical_bars(as_of=as_of)

        supported_windows = _supported_checkpoint_windows(
            timeframe=resolved_timeframe,
            checkpoint_windows=self.config.shadow_checkpoint_windows,
        )
        lookahead_minutes = _max_checkpoint_window_minutes(supported_windows)
        data_end_at = resolved_end_at + timedelta(minutes=lookahead_minutes)
        rows = self.usage_ledger.list_historical_bars(
            timeframe=resolved_timeframe,
            sources=expected_sources,
            start_at=resolved_start_at,
            end_at=data_end_at,
            symbols=symbol_filters,
        )
        ordered_timestamps = sorted(
            {
                row["bar_timestamp"]
                for row in rows
                if isinstance(row.get("bar_timestamp"), datetime)
            }
        )
        replay_timestamps = [
            timestamp
            for timestamp in ordered_timestamps
            if resolved_start_at <= timestamp < resolved_end_at
        ]
        eligible_timestamps = _eligible_replay_timestamps(
            timestamps=ordered_timestamps,
            replay_timestamps=replay_timestamps,
            supported_windows=supported_windows,
            max_timestamps=0,
        )

        available_timeframes = {
            str(item.get("timeframe", "") or "")
            for item in inventory.get("historical", {}).get("rows_by_timeframe", [])
        }
        available_sources = {
            str(item.get("source", "") or "")
            for item in inventory.get("historical", {}).get("rows_by_source", [])
        }
        if not rows:
            if resolved_timeframe not in available_timeframes:
                replay_reason = "timeframe_not_present_in_historical_store"
            elif not (available_sources & set(expected_sources)):
                replay_reason = "expected_replay_sources_missing_from_historical_store"
            else:
                replay_reason = "no_matching_historical_rows_for_requested_range"
        elif not replay_timestamps:
            replay_reason = "no_timestamps_inside_requested_window"
        elif not eligible_timestamps:
            replay_reason = "not_enough_future_data_for_checkpoint_windows"
        else:
            replay_reason = "ok"

        return {
            "status": "ok",
            "backend": inventory.get("backend"),
            "backend_detail": inventory.get("backend_detail"),
            "as_of": as_of,
            "historical": inventory.get("historical", {}),
            "latest": inventory.get("latest", {}),
            "replay_readiness": {
                "requested_timeframe": resolved_timeframe,
                "requested_days": resolved_days,
                "requested_start_at": resolved_start_at,
                "requested_end_at": resolved_end_at,
                "data_range_end": data_end_at,
                "checkpoint_windows": list(supported_windows),
                "expected_sources": expected_sources,
                "requested_symbol_count": len(symbol_filters),
                "requested_equity_symbols": list(resolved_equity_symbols),
                "requested_crypto_symbols": list(resolved_crypto_symbols),
                "matching_rows": len(rows),
                "replay_timestamps": len(replay_timestamps),
                "eligible_timestamps": len(eligible_timestamps),
                "can_replay_requested_range": bool(eligible_timestamps),
                "reason": replay_reason,
                "historical_sources_present": sorted(available_sources),
                "historical_timeframes_present": sorted(available_timeframes),
            },
        }

    def render(
        self,
        *,
        days: int | None = None,
        timeframe: str | None = None,
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        equity_symbols: tuple[str, ...] | None = None,
        crypto_symbols: tuple[str, ...] | None = None,
    ) -> str:
        report = self.build_report(
            days=days,
            timeframe=timeframe,
            start_at=start_at,
            end_at=end_at,
            equity_symbols=equity_symbols,
            crypto_symbols=crypto_symbols,
        )
        historical = report.get("historical", {})
        latest = report.get("latest", {})
        replay = report.get("replay_readiness", {})
        symbol_rows = historical.get("symbol_rows", []) or []
        symbol_sample = ", ".join(
            str(row.get("symbol", "") or "") for row in symbol_rows[:10] if row.get("symbol")
        ) or "-"
        lines = [
            "Historical Bars Status",
            (
                f"backend={report.get('backend', '-')}"
                f" | backend_detail={report.get('backend_detail', '-')}"
                f" | as_of={self._format_dt(report.get('as_of'))}"
            ),
            "Historical Store",
            (
                f"total_historical_bars={historical.get('total_rows', 0)}"
                f" | last_1_day={historical.get('last_1_day_rows', 0)}"
                f" | last_5_day={historical.get('last_5_day_rows', 0)}"
                f" | symbols_covered={historical.get('distinct_symbols', 0)}"
            ),
            (
                f"min_bar_timestamp={self._format_dt(historical.get('min_bar_timestamp'))}"
                f" | max_bar_timestamp={self._format_dt(historical.get('max_bar_timestamp'))}"
                f" | newest_bar_age={self._format_age(historical.get('newest_bar_age_seconds'))}"
            ),
            f"symbol_sample={symbol_sample}",
            "Rows By Source",
        ]
        rows_by_source = historical.get("rows_by_source", []) or []
        if rows_by_source:
            for row in rows_by_source:
                lines.append(f"- {row.get('source', '-')}: {row.get('rows', 0)}")
        else:
            lines.append("- none")
        lines.append("Rows By Timeframe")
        rows_by_timeframe = historical.get("rows_by_timeframe", []) or []
        if rows_by_timeframe:
            for row in rows_by_timeframe:
                lines.append(f"- {row.get('timeframe', '-')}: {row.get('rows', 0)}")
        else:
            lines.append("- none")
        lines.extend(
            [
                "Latest Store",
                (
                    f"total_latest_rows={latest.get('total_rows', 0)}"
                    f" | min_bar_timestamp={self._format_dt(latest.get('min_bar_timestamp'))}"
                    f" | max_bar_timestamp={self._format_dt(latest.get('max_bar_timestamp'))}"
                ),
            ]
        )
        latest_rows_by_source = latest.get("rows_by_source", []) or []
        if latest_rows_by_source:
            for row in latest_rows_by_source:
                lines.append(f"- latest/{row.get('source', '-')}: {row.get('rows', 0)}")
        else:
            lines.append("- latest/none")
        lines.extend(
            [
                "Replay Readiness",
                (
                    f"requested_timeframe={replay.get('requested_timeframe', '-')}"
                    f" | requested_start_at={self._format_dt(replay.get('requested_start_at'))}"
                    f" | requested_end_at={self._format_dt(replay.get('requested_end_at'))}"
                    f" | data_range_end={self._format_dt(replay.get('data_range_end'))}"
                ),
                (
                    f"matching_rows={replay.get('matching_rows', 0)}"
                    f" | replay_timestamps={replay.get('replay_timestamps', 0)}"
                    f" | eligible_timestamps={replay.get('eligible_timestamps', 0)}"
                    f" | can_replay={'yes' if replay.get('can_replay_requested_range') else 'no'}"
                ),
                (
                    f"reason={replay.get('reason', '-')}"
                    f" | checkpoint_windows={','.join(replay.get('checkpoint_windows', []) or ['-'])}"
                ),
                (
                    f"expected_sources={','.join(replay.get('expected_sources', []) or ['-'])}"
                    f" | historical_sources_present={','.join(replay.get('historical_sources_present', []) or ['-'])}"
                    f" | historical_timeframes_present={','.join(replay.get('historical_timeframes_present', []) or ['-'])}"
                ),
            ]
        )
        return "\n".join(lines)

    def _format_dt(self, value: Any) -> str:
        if isinstance(value, datetime):
            return value.isoformat()
        return str(value or "-")

    def _format_age(self, value: Any) -> str:
        if value is None:
            return "-"
        seconds = int(float(value or 0))
        days, remainder = divmod(seconds, 86400)
        hours, remainder = divmod(remainder, 3600)
        minutes, secs = divmod(remainder, 60)
        parts = []
        if days:
            parts.append(f"{days}d")
        if hours or days:
            parts.append(f"{hours}h")
        if minutes or hours or days:
            parts.append(f"{minutes}m")
        parts.append(f"{secs}s")
        return "".join(parts)
