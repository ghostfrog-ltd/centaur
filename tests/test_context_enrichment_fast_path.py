from __future__ import annotations

import importlib
from types import SimpleNamespace
import unittest


class ContextEnrichmentFastPathTests(unittest.TestCase):
    def test_enriches_only_selected_candidates_from_discovery_target(self) -> None:
        enrichment = importlib.import_module(
            "app.heartbeat.steps.25_context_enrichment.implementation.main"
        )
        ranked_candidates = [
            {"symbol": "AAPL", "source": "alpaca_market_data", "selected": True},
            {"symbol": "MSFT", "source": "alpaca_market_data", "selected": True},
            {"symbol": "NVDA", "source": "alpaca_market_data", "selected": False},
        ]
        selected_candidates = ranked_candidates[:2]
        seen_symbols: list[str] = []

        def fake_enrich(context: object, *, candidates: list[dict[str, object]], lookback_periods: int) -> list[dict[str, object]]:
            self.assertEqual(lookback_periods, 20)
            seen_symbols.extend(str(item["symbol"]) for item in candidates)
            return [
                {
                    **item,
                    "technical_context_ready": True,
                    "price_trigger_20": False,
                    "volume_surge_20": False,
                    "volatility_floor_pass_20": False,
                }
                for item in candidates
            ]

        original = enrichment._enrich_candidates_with_technicals
        try:
            enrichment._enrich_candidates_with_technicals = fake_enrich
            context = SimpleNamespace(
                state={
                    "market_scan": {
                        "ranked_candidates": ranked_candidates,
                        "selected_candidates": selected_candidates,
                    }
                }
            )

            result = enrichment.run_implementation(context)
        finally:
            enrichment._enrich_candidates_with_technicals = original

        self.assertEqual(seen_symbols, ["AAPL", "MSFT"])
        self.assertEqual(result["candidates_enriched"], 2)
        self.assertEqual(result["selected_candidates"], 2)
        self.assertEqual(result["candidate_policy"], "selected_from_discovery_target_count")
        self.assertEqual(
            [item["symbol"] for item in context.state["context_enrichment"]["candidates"]],
            ["AAPL", "MSFT"],
        )


if __name__ == "__main__":
    unittest.main()
