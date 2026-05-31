from __future__ import annotations

import unittest
from datetime import datetime, timedelta
from types import SimpleNamespace

from app.reporting.evidence_report import EvidenceReport


class FakeUsageLedger:
    backend = "postgres"

    def list_recent_paper_trade_orders(self, *, limit: int = 5) -> list[dict]:
        return [
            {
                "environment": "paper",
                "mode": "paper",
                "source_environment": "paper",
                "broker_id": "alpaca_paper",
                "execution_provider": "alpaca_paper",
            },
            {
                "environment": "live",
                "mode": "live",
                "source_environment": "paper",
                "broker_id": "alpaca_live",
                "execution_provider": "alpaca_live",
                "submitted_at": datetime.now().astimezone().isoformat(),
            },
        ][:limit]

    def list_recent_shadow_trade_proposals(self, *, limit: int = 5) -> list[dict]:
        return [
            {
                "environment": "paper",
                "mode": "paper",
                "source_environment": "shadow",
                "source": "shadow",
                "execution_provider": "shadow",
            }
        ][:limit]

    def list_latest_strategy_fitness_snapshots(self, *, limit: int = 8) -> list[dict]:
        return [
            {
                "environment": "paper",
                "mode": "paper",
                "source_environment": "shadow",
                "broker_id": "alpaca_paper",
                "execution_provider": "shadow",
            }
        ][:limit]

    def list_recent_tick_runs(self, *, limit: int = 24) -> list[dict]:
        started_at = datetime.now().astimezone()
        return [
            {
                "tick_id": "tick-1",
                "started_at": started_at,
                "state_snapshot_json": {
                    "market_data_latest_bars": {
                        "raw": {
                            "AAPL": {
                                "t": (started_at - timedelta(seconds=10)).isoformat()
                            }
                        }
                    },
                    "crypto_data_latest_bars": {
                        "raw": {
                            "BTC/USD": {
                                "t": (started_at - timedelta(seconds=20)).isoformat()
                            }
                        }
                    },
                },
            }
        ][:limit]


class StorageSeparationReportTests(unittest.TestCase):
    def test_report_summarizes_lane_schema_separation(self) -> None:
        reporter = EvidenceReport(
            config=SimpleNamespace(
                centaur_mode="live",
                centaur_environment="live",
                database_url_source="env",
                postgres_schema="",
                postgres_core_schema="core",
                postgres_paper_schema="paper",
                postgres_live_schema="live",
            ),
            usage_ledger=FakeUsageLedger(),
        )

        report = reporter.render_storage_separation_report()

        self.assertIn("Centaur Paper/Live Storage Separation Report", report)
        self.assertIn("physical_split=schema_separated_shared_postgres", report)
        self.assertIn("separation_enforcement=shared_core_plus_lane_schemas", report)
        self.assertIn("lane=core | schema=core", report)
        self.assertIn("lane=paper | schema=paper", report)
        self.assertIn("lane=live | schema=live", report)
        self.assertIn("broker_orders: sampled=2", report)
        self.assertIn("shadow_proposals: sampled=1", report)
        self.assertIn("strategy_fitness: sampled=1", report)
        self.assertIn("missing_required=0", report)

if __name__ == "__main__":
    unittest.main()
