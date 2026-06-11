from __future__ import annotations

import unittest
from types import SimpleNamespace

from app.framework.storage.usage import UsageLedger


class _Cursor:
    def __init__(self, rows):
        self.rows = list(rows)
        self.executed: list[tuple[str, object]] = []
        self.fetch_index = 0

    def execute(self, query, params=None):
        self.executed.append((str(query), params))

    def fetchall(self):
        if self.rows and isinstance(self.rows[0], list):
            rows = self.rows[self.fetch_index] if self.fetch_index < len(self.rows) else []
            self.fetch_index += 1
            return list(rows)
        return list(self.rows)


class UsageLedgerReadOnlyStartupTests(unittest.TestCase):
    def test_read_only_schema_access_verifies_required_schemas_exist(self) -> None:
        ledger = object.__new__(UsageLedger)
        ledger.config = SimpleNamespace()
        ledger._postgres_core_schema_name = lambda: "core"  # type: ignore[method-assign]
        ledger._postgres_execution_schema_name = lambda: "paper"  # type: ignore[method-assign]
        cursor = _Cursor([("core",), ("paper",)])

        ledger._verify_postgres_read_only_schema_access(cursor)

        self.assertEqual(len(cursor.executed), 1)
        self.assertIn("information_schema.schemata", cursor.executed[0][0])

    def test_read_only_schema_access_fails_clearly_when_schema_missing(self) -> None:
        ledger = object.__new__(UsageLedger)
        ledger.config = SimpleNamespace()
        ledger._postgres_core_schema_name = lambda: "core"  # type: ignore[method-assign]
        ledger._postgres_execution_schema_name = lambda: "paper"  # type: ignore[method-assign]
        cursor = _Cursor([("core",)])

        with self.assertRaises(RuntimeError) as raised:
            ledger._verify_postgres_read_only_schema_access(cursor)

        self.assertIn("Read-only PostgreSQL report startup requires existing operations schemas", str(raised.exception))
        self.assertIn("paper", str(raised.exception))

    def test_lock_timeout_error_is_classified_clearly(self) -> None:
        ledger = object.__new__(UsageLedger)
        ledger.config = SimpleNamespace(database_url="postgres://example")

        reason = ledger._classify_postgres_connection_error(
            RuntimeError("canceling statement due to lock timeout")
        )

        self.assertEqual(
            reason,
            "operations store bootstrap lock timed out; retry shortly or use the read-only report startup path",
        )

    def test_write_enabled_schema_access_requires_existing_research_tables(self) -> None:
        ledger = object.__new__(UsageLedger)
        ledger.config = SimpleNamespace()
        ledger._postgres_core_schema_name = lambda: "core"  # type: ignore[method-assign]
        ledger._postgres_execution_schema_name = lambda: "paper"  # type: ignore[method-assign]
        ledger._postgres_search_path_schemas = lambda *, scope: ["paper"]  # type: ignore[method-assign]
        cursor = _Cursor(
            [
                [("core",), ("paper",)],
                [
                    ("paper", "strategy_variant_definitions"),
                    ("paper", "strategy_variant_evaluations"),
                    ("paper", "market_data_historical_bars"),
                ],
            ]
        )

        ledger._verify_postgres_write_enabled_schema_access(cursor)

        self.assertEqual(len(cursor.executed), 2)

    def test_write_enabled_schema_access_fails_clearly_when_table_missing(self) -> None:
        ledger = object.__new__(UsageLedger)
        ledger.config = SimpleNamespace()
        ledger._postgres_core_schema_name = lambda: "core"  # type: ignore[method-assign]
        ledger._postgres_execution_schema_name = lambda: "paper"  # type: ignore[method-assign]
        ledger._postgres_search_path_schemas = lambda *, scope: ["paper"]  # type: ignore[method-assign]
        cursor = _Cursor(
            [
                [("core",), ("paper",)],
                [
                    ("paper", "strategy_variant_definitions"),
                    ("paper", "market_data_historical_bars"),
                ],
            ]
        )

        with self.assertRaises(RuntimeError) as raised:
            ledger._verify_postgres_write_enabled_schema_access(cursor)

        self.assertIn("missing table(s): strategy_variant_evaluations", str(raised.exception))
