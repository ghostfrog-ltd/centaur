from __future__ import annotations

from types import SimpleNamespace
import unittest

from centaur.runtime import ModeContext, normalize_runtime_environment


class RuntimeContextTests(unittest.TestCase):
    def test_live_dry_defaults_to_live_environment(self) -> None:
        self.assertEqual(normalize_runtime_environment("", mode="live_dry"), "live")

    def test_live_dry_can_read_but_not_mutate_live_broker(self) -> None:
        context = ModeContext.from_config(SimpleNamespace(centaur_mode="live_dry"))

        self.assertEqual(context.environment, "live")
        self.assertTrue(context.can_read_live_broker)
        self.assertFalse(context.can_mutate_live_broker)

    def test_paper_cannot_read_or_mutate_live_broker(self) -> None:
        context = ModeContext.from_config(
            SimpleNamespace(centaur_mode="paper", centaur_environment="paper")
        )

        self.assertFalse(context.can_read_live_broker)
        self.assertFalse(context.can_mutate_live_broker)


if __name__ == "__main__":
    unittest.main()
