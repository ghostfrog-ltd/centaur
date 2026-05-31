from __future__ import annotations

import os
import sqlite3
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from centaur.config import load_config_defaults_from_file, load_runtime_config
from centaur.usage import UsageLedger


class EnvironmentMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_env = dict(os.environ)
        self._tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmpdir.name) / "centaur.sqlite3"
        os.environ.update(
            {
                "CENTAUR_MODE": "paper",
                "CENTAUR_ENVIRONMENT": "paper",
                "OPERATIONS_DB_BACKEND": "sqlite",
                "USAGE_LEDGER_DB_PATH": str(self.db_path),
                "DATABASE_URL": "",
                "POSTGRES_HOST": "",
                "POSTGRES_DB": "",
                "POSTGRES_USER": "",
                "POSTGRES_PASSWORD": "",
                "POSTGRES_SCHEMA": "",
                "PAPER_EXECUTION_ENABLED": "false",
                "LIVE_EXECUTION_ENABLED": "false",
            }
        )
        self.config = load_runtime_config()
        self.ledger = UsageLedger(config=self.config)

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._old_env)
        self._tmpdir.cleanup()

    def test_order_rows_distinguish_paper_and_live_followers(self) -> None:
        self.ledger.record_paper_trade_orders(
            tick_id="test-tick",
            captured_at=datetime.now().astimezone(),
            orders=[
                {
                    "id": "paper-order",
                    "symbol": "AAPL",
                    "side": "buy",
                    "status": "filled",
                    "broker_id": "alpaca_paper",
                    "proposal_id": "proposal-1",
                    "source": "alpaca",
                },
                {
                    "id": "live-order",
                    "symbol": "AAPL",
                    "side": "buy",
                    "status": "filled",
                    "broker_id": "alpaca_live",
                    "proposal_id": "proposal-1",
                    "source": "alpaca",
                },
            ],
        )

        rows = {
            row["order_id"]: row
            for row in self.ledger.list_recent_paper_trade_orders(limit=10)
        }

        self.assertEqual(rows["paper-order"]["environment"], "paper")
        self.assertEqual(rows["paper-order"]["mode"], "paper")
        self.assertEqual(rows["paper-order"]["source_environment"], "shadow")
        self.assertEqual(rows["paper-order"]["execution_provider"], "alpaca_paper")
        self.assertEqual(rows["paper-order"]["canonical_instrument_id"], "AAPL-US-EQUITY")
        self.assertEqual(rows["paper-order"]["venue"], "alpaca")
        self.assertEqual(rows["paper-order"]["venue_symbol"], "AAPL")

        self.assertEqual(rows["live-order"]["environment"], "live")
        self.assertEqual(rows["live-order"]["mode"], "live")
        self.assertEqual(rows["live-order"]["source_environment"], "paper")
        self.assertEqual(rows["live-order"]["execution_provider"], "alpaca_live")

    def test_fitness_snapshots_carry_evidence_origin(self) -> None:
        self.ledger.record_strategy_fitness_snapshots(
            tick_id="test-tick",
            captured_at=datetime.now().astimezone(),
            summaries=[
                {
                    "strategy_id": "mean_reversion.snapback",
                    "strategy_family": "mean_reversion",
                    "profile_id": "snapback",
                    "asset_class": "equity",
                    "checkpoint_code": "1h",
                    "evaluated_proposals": 1,
                    "checkpoints_evaluated": 2,
                    "win_count": 1,
                    "loss_count": 1,
                }
            ],
            environment="paper",
            mode="paper",
            source_environment="shadow",
            broker_id="alpaca_paper",
            data_provider="alpaca",
            execution_provider="shadow",
        )

        row = self.ledger.list_latest_strategy_fitness_snapshots(limit=1)[0]

        self.assertEqual(row["environment"], "paper")
        self.assertEqual(row["mode"], "paper")
        self.assertEqual(row["source_environment"], "shadow")
        self.assertEqual(row["broker_id"], "alpaca_paper")
        self.assertEqual(row["data_provider"], "alpaca")
        self.assertEqual(row["execution_provider"], "shadow")

    def test_execution_router_intents_are_persisted_with_instrument_metadata(self) -> None:
        self.ledger.record_execution_router_intent(
            tick_id="test-tick",
            recorded_at=datetime.now().astimezone(),
            environment="live",
            mode="live_dry",
            lane="live",
            action="entry",
            broker_id="alpaca_live",
            status="live_dry_intent",
            strategy_id="mean_reversion.snapback",
            intended_order={"symbol": "AAPL", "side": "buy", "notional": "10"},
        )

        row = self.ledger.list_recent_execution_router_intents(limit=1)[0]

        self.assertEqual(row["environment"], "live")
        self.assertEqual(row["mode"], "live_dry")
        self.assertEqual(row["lane"], "live")
        self.assertEqual(row["action"], "entry")
        self.assertEqual(row["broker_id"], "alpaca_live")
        self.assertEqual(row["status"], "live_dry_intent")
        self.assertEqual(row["strategy_id"], "mean_reversion.snapback")
        self.assertEqual(row["canonical_instrument_id"], "AAPL-US-EQUITY")
        self.assertEqual(row["venue"], "alpaca")
        self.assertEqual(row["venue_symbol"], "AAPL")
        self.assertEqual(row["intended_order_json"]["symbol"], "AAPL")

    def test_latest_bars_carry_instrument_metadata(self) -> None:
        now = datetime.now().astimezone()
        self.ledger.record_latest_bars(
            tick_id="test-tick",
            captured_at=now,
            source="alpaca_crypto_data",
            bars_by_symbol={
                "BTC/USD": {
                    "t": now.isoformat(),
                    "o": 100.0,
                    "h": 101.0,
                    "l": 99.0,
                    "c": 100.5,
                    "v": 10,
                    "n": 2,
                    "vw": 100.2,
                }
            },
        )

        row = self.ledger.get_latest_bars_for_tick(
            tick_id="test-tick",
            sources=["alpaca_crypto_data"],
        )[0]

        self.assertEqual(row["asset_class"], "crypto")
        self.assertEqual(row["canonical_instrument_id"], "BTC-USD-SPOT")
        self.assertEqual(row["venue"], "alpaca")
        self.assertEqual(row["venue_symbol"], "BTC/USD")

    def test_historical_bars_carry_instrument_metadata(self) -> None:
        now = datetime.now().astimezone()
        self.ledger.record_historical_bars(
            batch_id="batch-1",
            captured_at=now,
            source="alpaca_crypto_data",
            asset_class="crypto",
            timeframe="1Min",
            bars_by_symbol={
                "BTC/USD": [
                    {
                        "t": now.isoformat(),
                        "o": 100.0,
                        "h": 101.0,
                        "l": 99.0,
                        "c": 100.5,
                        "v": 10,
                        "n": 2,
                        "vw": 100.2,
                    }
                ]
            },
        )

        row = self.ledger.list_historical_bars(
            timeframe="1Min",
            sources=["alpaca_crypto_data"],
            symbols=["BTC/USD"],
        )[0]

        self.assertEqual(row["asset_class"], "crypto")
        self.assertEqual(row["canonical_instrument_id"], "BTC-USD-SPOT")
        self.assertEqual(row["venue"], "alpaca")
        self.assertEqual(row["venue_symbol"], "BTC/USD")

    def test_candidate_signals_carry_instrument_metadata(self) -> None:
        self.ledger.record_strategy_candidate_signals(
            tick_id="test-tick",
            signals=[
                {
                    "strategy_id": "mean_reversion.snapback",
                    "strategy_family": "mean_reversion",
                    "profile_id": "snapback",
                    "source": "alpaca",
                    "symbol": "AAPL",
                    "asset_class": "equity",
                    "entry_price": 100.0,
                    "stop_loss_price": 98.0,
                    "target_price": 103.0,
                    "holding_window_code": "1h",
                    "holding_window_minutes": 60,
                }
            ],
        )

        with sqlite3.connect(self.db_path) as connection:
            connection.row_factory = sqlite3.Row
            row = connection.execute(
                """
                SELECT canonical_instrument_id, venue, venue_symbol
                FROM strategy_candidate_signals
                WHERE tick_id = ?
                """,
                ("test-tick",),
            ).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row["canonical_instrument_id"], "AAPL-US-EQUITY")
        self.assertEqual(row["venue"], "alpaca")
        self.assertEqual(row["venue_symbol"], "AAPL")

    def test_shadow_proposals_and_outcomes_carry_evidence_origin(self) -> None:
        now = datetime.now().astimezone()
        self.ledger.record_shadow_trade_proposals(
            proposals=[
                {
                    "proposal_id": "proposal-1",
                    "tick_id": "test-tick",
                    "proposed_at": now.isoformat(),
                    "environment": "live",
                    "mode": "live",
                    "source_environment": "shadow",
                    "data_provider": "alpaca",
                    "execution_provider": "shadow",
                    "strategy_id": "mean_reversion.snapback",
                    "strategy_family": "mean_reversion",
                    "profile_id": "snapback",
                    "source": "alpaca",
                    "symbol": "AAPL",
                    "asset_class": "equity",
                    "entry_price": 100.0,
                    "stop_loss_price": 98.0,
                    "target_price": 103.0,
                    "holding_window_code": "1h",
                    "holding_window_minutes": 60,
                    "checkpoint_windows": [
                        {
                            "checkpoint_code": "1h",
                            "checkpoint_minutes": 60,
                            "due_at": now.isoformat(),
                        }
                    ],
                }
            ]
        )

        due = self.ledger.list_due_shadow_trade_outcomes(as_of=now, limit=1)[0]

        self.assertEqual(due["environment"], "live")
        self.assertEqual(due["mode"], "live")
        self.assertEqual(due["source_environment"], "shadow")
        self.assertEqual(due["data_provider"], "alpaca")
        self.assertEqual(due["execution_provider"], "shadow")
        self.assertEqual(due["canonical_instrument_id"], "AAPL-US-EQUITY")
        self.assertEqual(due["venue"], "alpaca")
        self.assertEqual(due["venue_symbol"], "AAPL")

    def test_legacy_live_activation_flags_make_runtime_label_live(self) -> None:
        os.environ.pop("CENTAUR_MODE", None)
        os.environ.pop("CENTAUR_ENVIRONMENT", None)
        os.environ["LIVE_EXECUTION_ENABLED"] = "true"
        os.environ["LIVE_EXECUTION_KILL_SWITCH"] = "false"
        os.environ["LIVE_EXECUTION_ACTIVATION_ACK"] = "LIVE_TRADING_APPROVED"

        config = load_runtime_config()

        self.assertEqual(config.centaur_mode, "live")
        self.assertEqual(config.centaur_environment, "live")

    def test_live_dry_runtime_defaults_to_live_environment(self) -> None:
        os.environ["CENTAUR_MODE"] = "live_dry"
        os.environ.pop("CENTAUR_ENVIRONMENT", None)

        config = load_runtime_config()

        self.assertEqual(config.centaur_mode, "live_dry")
        self.assertEqual(config.centaur_environment, "live")

    def test_postgres_schema_is_normalized_from_environment(self) -> None:
        os.environ["POSTGRES_SCHEMA"] = "Live Ops-2026!"

        config = load_runtime_config()

        self.assertEqual(config.postgres_schema, "liveops2026")

    def test_centaur_config_file_supplies_lane_defaults(self) -> None:
        config_path = Path(self._tmpdir.name) / "live.yaml"
        config_path.write_text(
            "\n".join(
                [
                    "mode: live",
                    "environment: live",
                    "database: centaur_live",
                    "core_postgres_schema: core",
                    "paper_postgres_schema: paper",
                    "live_postgres_schema: live",
                    "postgres_schema: live",
                    "enabled_strategies:",
                    "  - mean_reversion.snapback",
                    "  - crypto_momentum.trend",
                    "live_enabled_strategies:",
                    "  - mean_reversion.snapback",
                ]
            ),
            encoding="utf-8",
        )
        for key in (
            "CENTAUR_MODE",
            "CENTAUR_ENVIRONMENT",
            "POSTGRES_DB",
            "POSTGRES_SCHEMA",
            "PAPER_EXECUTION_ALLOWED_STRATEGIES",
            "LIVE_EXECUTION_ALLOWED_STRATEGIES",
        ):
            os.environ.pop(key, None)
        os.environ["CENTAUR_CONFIG"] = str(config_path)

        load_config_defaults_from_file()

        self.assertEqual(os.environ["CENTAUR_MODE"], "live")
        self.assertEqual(os.environ["POSTGRES_SCHEMA"], "live")
        self.assertNotIn("LIVE_EXECUTION_MAX_DAILY_ORDERS", os.environ)
        self.assertNotIn("LIVE_EXECUTION_MAX_LATEST_BAR_AGE_SECONDS", os.environ)
        self.assertEqual(
            os.environ["PAPER_EXECUTION_ALLOWED_STRATEGIES"],
            "mean_reversion.snapback,crypto_momentum.trend",
        )
        self.assertEqual(
            os.environ["LIVE_EXECUTION_ALLOWED_STRATEGIES"],
            "mean_reversion.snapback",
        )


if __name__ == "__main__":
    unittest.main()
