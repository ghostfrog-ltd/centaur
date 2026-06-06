from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace
import unittest
from zoneinfo import ZoneInfo

from app.framework.engine.replay import (
    HistoricalReplayRequest,
    load_replay_history,
    replay_shadow_training,
)
from app.framework.runtime.models import TickContext


class _ReplayLedger:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.recorded_proposals: list[dict[str, object]] = []
        self.recorded_outcomes: list[dict[str, object]] = []

    def list_historical_bars(
        self,
        *,
        timeframe: str,
        sources: list[str],
        start_at: datetime | None = None,
        end_at: datetime | None = None,
        symbols: list[str] | None = None,
    ) -> list[dict[str, object]]:
        filtered = []
        for row in self.rows:
            if timeframe != row.get("timeframe"):
                continue
            if str(row.get("source", "")) not in sources:
                continue
            if start_at is not None and row["bar_timestamp"] < start_at:
                continue
            if end_at is not None and row["bar_timestamp"] > end_at:
                continue
            if symbols and str(row.get("symbol", "")) not in symbols:
                continue
            filtered.append(dict(row))
        return filtered

    def list_shadow_proposal_events(
        self,
        *,
        start_at: datetime,
        end_at: datetime,
    ) -> list[dict[str, object]]:
        return []

    def record_shadow_trade_proposals(self, *, proposals: list[dict[str, object]]) -> None:
        self.recorded_proposals.extend(proposals)

    def record_shadow_trade_outcomes(self, *, outcomes: list[dict[str, object]]) -> int:
        self.recorded_outcomes.extend(outcomes)
        return len(outcomes)


class HistoricalReplayTests(unittest.TestCase):
    def test_replay_surfaces_research_signal_and_skip_diagnostics(self) -> None:
        tz = ZoneInfo("UTC")
        replay_end = datetime(2026, 6, 6, 12, 16, tzinfo=tz)
        bars = [
            self._bar(ts=datetime(2026, 6, 6, 11, 59, tzinfo=tz), close=100.0),
            self._bar(ts=datetime(2026, 6, 6, 12, 0, tzinfo=tz), close=99.5),
            self._bar(ts=datetime(2026, 6, 6, 12, 15, tzinfo=tz), close=99.8),
        ]
        ledger = _ReplayLedger(bars)
        config = self._config()
        context = TickContext(
            tick_id="replay-test",
            started_at=replay_end,
            config=config,
            usage_ledger=ledger,
        )
        context.metadata["historical_replay_request"] = HistoricalReplayRequest(
            days=1,
            timeframe="1Min",
            equity_symbols=(),
            crypto_symbols=("AVAX/USD",),
            max_timestamps=0,
            start_at=datetime(2026, 6, 6, 11, 59, tzinfo=tz),
            end_at=replay_end,
        )

        load_result = load_replay_history(context)
        training_result = replay_shadow_training(context)

        self.assertTrue(load_result["historical_store_only"])
        self.assertEqual(load_result["stale_or_account_only_source_skipped"], 0)
        self.assertEqual(training_result["replay_timestamps_processed"], 2)
        self.assertGreaterEqual(training_result["candidates_evaluated"], 1)
        self.assertGreaterEqual(training_result["signals_generated"], 1)
        self.assertEqual(training_result["paper_execution_signals_generated"], 0)
        self.assertGreaterEqual(training_result["paper_research_signals_generated"], 1)
        self.assertGreaterEqual(training_result["outcomes_recorded"], 1)
        self.assertGreaterEqual(
            training_result["outcome_checkpoints_skipped_not_enough_future_data"],
            1,
        )
        self.assertEqual(training_result["stale_or_account_only_source_skipped"], 0)
        self.assertTrue(
            any(
                proposal.get("strategy_id") == "crypto_pullback.downside_reversal_watch"
                for proposal in ledger.recorded_proposals
            )
        )

    def _config(self) -> SimpleNamespace:
        return SimpleNamespace(
            centaur_environment="paper",
            centaur_mode="paper",
            shadow_stop_loss_pct=0.02,
            shadow_target_multiple=2.0,
            shadow_min_opportunity_score=55.0,
            shadow_checkpoint_windows=("15m",),
            shadow_proposal_cooldown_minutes=30,
            shadow_proposal_limit=5,
            shadow_execution_spread_bps=0.0,
            shadow_entry_slippage_bps=0.0,
            shadow_exit_slippage_bps=0.0,
            shadow_fixed_round_trip_cost_usd=0.0,
            shadow_profit_target_ladder_pct=(1.25, 2.0, 3.0, 4.0, 6.0),
            paper_execution_default_notional_usd=10.0,
            discovery_target_count=6,
            paper_execution_allowed_strategies=(
                "mean_reversion.snapback",
                "crypto_momentum.trend",
                "momentum.volatility_breakout",
            ),
            crypto_momentum_stop_loss_pct=0.01,
            crypto_momentum_target_multiple=2.0,
            crypto_momentum_min_signal_score=60.0,
            crypto_momentum_min_movement_pct=0.15,
            crypto_momentum_max_movement_pct=2.5,
            crypto_momentum_min_discovery_score=2.5,
            crypto_momentum_min_trade_count=2,
            crypto_momentum_min_volume_gbp=50000.0,
            crypto_momentum_max_spread_pct=0.25,
        )

    def _bar(self, *, ts: datetime, close: float) -> dict[str, object]:
        return {
            "batch_id": "batch",
            "captured_at": ts,
            "source": "alpaca_crypto_data",
            "asset_class": "crypto",
            "symbol": "AVAX/USD",
            "timeframe": "1Min",
            "canonical_instrument_id": "AVAX-USD-SPOT",
            "venue": "ALPACA",
            "venue_symbol": "AVAX/USD",
            "bar_timestamp": ts,
            "quote_currency": "USD",
            "usd_to_gbp_rate": 0.79,
            "open_price": close,
            "high_price": close + 0.2,
            "low_price": close - 0.2,
            "close_price": close,
            "open_price_gbp": close * 0.79,
            "high_price_gbp": (close + 0.2) * 0.79,
            "low_price_gbp": (close - 0.2) * 0.79,
            "close_price_gbp": close * 0.79,
            "volume": 100,
            "trade_count": 5,
            "vwap": close,
        }


if __name__ == "__main__":
    unittest.main()
