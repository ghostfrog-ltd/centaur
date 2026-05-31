from __future__ import annotations

import unittest
from types import SimpleNamespace

from centaur.storage_layout import storage_layout_from_config


class StorageLayoutTests(unittest.TestCase):
    def test_default_layout_has_core_paper_live_lanes(self) -> None:
        layout = storage_layout_from_config(
            SimpleNamespace(
                centaur_environment="live",
                postgres_schema="",
                postgres_core_schema="core",
                postgres_paper_schema="paper",
                postgres_live_schema="live",
            )
        )

        self.assertEqual(layout.core.postgres_schema, "core")
        self.assertEqual(layout.paper.postgres_schema, "paper")
        self.assertEqual(layout.live.postgres_schema, "live")
        self.assertFalse(layout.core.execution_mutations_allowed)
        self.assertTrue(layout.paper.execution_mutations_allowed)
        self.assertTrue(layout.live.execution_mutations_allowed)

    def test_active_runtime_schema_maps_to_current_lane_only(self) -> None:
        layout = storage_layout_from_config(
            SimpleNamespace(
                centaur_environment="paper",
                postgres_schema="paper_ops",
                postgres_core_schema="core",
                postgres_paper_schema="paper",
                postgres_live_schema="live",
            )
        )

        self.assertEqual(layout.core.postgres_schema, "core")
        self.assertEqual(layout.paper.postgres_schema, "paper_ops")
        self.assertEqual(layout.live.postgres_schema, "live")


if __name__ == "__main__":
    unittest.main()
