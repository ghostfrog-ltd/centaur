from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from typing import Any

from .config import RuntimeConfig, load_runtime_config
from app.storage.layout import storage_layout_from_config
from .usage import UsageLedger


class EvidenceReport:
    """Read-only index of counterfactual and shadow evidence streams."""

    def __init__(
        self,
        *,
        config: RuntimeConfig | None = None,
        usage_ledger: UsageLedger | None = None,
    ) -> None:
        self.config = config or load_runtime_config()
        self.usage_ledger = usage_ledger or UsageLedger(config=self.config)

    def build_report(self, *, tick_limit: int = 120) -> dict[str, Any]:
        recent_ticks = self.usage_ledger.list_recent_tick_runs(limit=max(1, tick_limit))
        latest_tick = self.usage_ledger.get_latest_tick_run()
        checked_at = datetime.now().astimezone()
        return {
            "status": "ok",
            "checked_at": checked_at.isoformat(),
            "backend": self.usage_ledger.backend,
            "latest_tick_id": (latest_tick or {}).get("tick_id"),
            "tick_limit": max(1, tick_limit),
            "streams": self._evidence_streams(),
            "storage_separation": self._storage_separation_summary(),
            "execution_router_intents": self._execution_router_intent_summary(),
            "trailing_drawdown": self._trailing_drawdown_summary(recent_ticks),
        }

    def render(self, *, report: dict[str, Any] | None = None) -> str:
        report = report or self.build_report()
        if report.get("status") != "ok":
            return (
                "Centaur Evidence Report\n"
                f"Status: {report.get('status', 'unknown')}\n"
                f"Reason: {report.get('reason', '-')}"
            )

        lines = [
            "Centaur Evidence Report",
            (
                f"backend={report.get('backend', '-')}"
                f" | latest_tick={report.get('latest_tick_id', '-')}"
                f" | checked_at={report.get('checked_at', '-')}"
            ),
            "Evidence streams to include before action:",
        ]
        for stream in report.get("streams", []):
            item = _as_dict(stream)
            lines.append(
                (
                    f"- {item.get('name', '-')}"
                    f" | mode={item.get('mode', '-')}"
                    f" | source={item.get('source', '-')}"
                    f" | action_rule={item.get('action_rule', '-')}"
                )
            )

        storage = _as_dict(report.get("storage_separation"))
        lines.append("Paper/live storage separation:")
        lines.extend(self._render_storage_separation_lines(storage))

        router_intents = _as_dict(report.get("execution_router_intents"))
        lines.append("Execution router intents:")
        if not router_intents.get("recent"):
            lines.append(f"- {router_intents.get('reason', 'No router intents recorded yet.')}")
        else:
            lines.append(
                (
                    f"- recent={int(router_intents.get('recent_count', 0) or 0)}"
                    f" | live_dry={int(router_intents.get('live_dry_count', 0) or 0)}"
                    f" | latest_tick={router_intents.get('latest_tick_id', '-')}"
                    f" | latest_status={router_intents.get('latest_status', '-')}"
                )
            )
            for item in router_intents.get("recent", [])[:5]:
                intent = _as_dict(item)
                lines.append(
                    (
                        f"- {intent.get('recorded_at', '-')}"
                        f" | {intent.get('mode', '-')}/{intent.get('lane', '-')}"
                        f" | {intent.get('action', '-')}"
                        f" | broker={intent.get('broker_id', '-')}"
                        f" | symbol={intent.get('symbol') or intent.get('order_id') or '-'}"
                        f" | status={intent.get('status', '-')}"
                    )
                )

        trailing = _as_dict(report.get("trailing_drawdown"))
        lines.append("Trailing drawdown observer:")
        if not trailing.get("lanes"):
            lines.append(f"- {trailing.get('reason', 'No observations yet.')}")
        else:
            for lane in trailing.get("lanes", []):
                item = _as_dict(lane)
                lines.append(
                    (
                        f"- {item.get('broker_id', '-')}"
                        f" | observations={int(item.get('observations', 0) or 0)}"
                        f" | would_block_ticks={int(item.get('would_block_ticks', 0) or 0)}"
                        f" | max_giveback={_fmt_currency(item.get('max_giveback_usd'))}"
                        f" ({_fmt_pct(item.get('max_giveback_pct'))})"
                        f" | latest_giveback={_fmt_currency(item.get('latest_giveback_usd'))}"
                        f" | latest_would_block={item.get('latest_would_block', False)}"
                    )
                )
        lines.append(
            "Decision rule: treat this as evidence only; promote any observer into execution policy only by explicit override."
        )
        return "\n".join(lines)

    def _evidence_streams(self) -> list[dict[str, str]]:
        return [
            {
                "name": "Shadow checkpoints",
                "mode": "counterfactual",
                "source": "shadow_trade_outcomes: 15m/1h/1d/7d",
                "action_rule": "review via --paper-exit-review before changing exits",
            },
            {
                "name": "Profit target ladder",
                "mode": "counterfactual",
                "source": "shadow_trade_outcomes.raw_json.profit_target_ladder",
                "action_rule": "compare 1.25/2/3/4/6 percent hits before changing targets",
            },
            {
                "name": "Holding-window advice",
                "mode": "recommendation_only",
                "source": "--holding-window-advice",
                "action_rule": "no managed-exit change without explicit override",
            },
            {
                "name": "Threshold GA advice",
                "mode": "recommendation_or_guarded_paper_rails",
                "source": "--threshold-advice and adaptive threshold state",
                "action_rule": "must stay inside approved suppress-threshold rails",
            },
            {
                "name": "Signal visibility trail",
                "mode": "diagnostic",
                "source": "raw/suppressed/surviving signal previews in tick snapshots",
                "action_rule": "distinguish no signal from fitness suppression",
            },
            {
                "name": "Crypto overnight health",
                "mode": "diagnostic",
                "source": "--crypto-health",
                "action_rule": "check data/fitness before changing crypto knobs",
            },
            {
                "name": "Live execution intelligence",
                "mode": "read_only_monitor",
                "source": "status/dashboard live-vs-paper follower diagnostics",
                "action_rule": "live still follows same-tick submitted paper orders only",
            },
            {
                "name": "Execution router intents",
                "mode": "audit_trail",
                "source": "execution_router_intents table and --evidence-report",
                "action_rule": "review live_dry intended actions before promoting behavior",
            },
            {
                "name": "Trailing drawdown observer",
                "mode": "observe_only",
                "source": "trailing_drawdown_observer tick snapshots",
                "action_rule": "records would-block only; does not affect entries/exits",
            },
            {
                "name": "Exit deferral and Friday exit reasons",
                "mode": "audit_trail",
                "source": "paper/live order exit_reason values",
                "action_rule": "review max_hold_red_deferred and friday_no_weekend_carry separately",
            },
        ]

    def render_storage_separation_report(
        self,
        *,
        report: dict[str, Any] | None = None,
    ) -> str:
        report = report or self._storage_separation_summary()
        lines = ["Centaur Paper/Live Storage Separation Report"]
        lines.extend(self._render_storage_separation_lines(report))
        lines.append(
            "Decision rule: live may consume reviewed paper/shadow fitness evidence, but live outcome rows must not be treated as paper evidence and paper rows must not be treated as live P/L."
        )
        return "\n".join(lines)

    def _storage_separation_summary(self) -> dict[str, Any]:
        orders = self.usage_ledger.list_recent_paper_trade_orders(limit=25)
        proposals = self.usage_ledger.list_recent_shadow_trade_proposals(limit=25)
        fitness = self.usage_ledger.list_latest_strategy_fitness_snapshots(limit=25)
        backend = str(getattr(self.usage_ledger, "backend", "") or "").lower()
        storage_layout = storage_layout_from_config(self.config)
        return {
            "status": "ok",
            "checked_at": datetime.now().astimezone().isoformat(),
            "backend": self.usage_ledger.backend,
            "runtime_mode": getattr(self.config, "centaur_mode", ""),
            "runtime_environment": getattr(self.config, "centaur_environment", ""),
            "database_url_source": getattr(self.config, "database_url_source", ""),
            "postgres_schema": getattr(self.config, "postgres_schema", ""),
            "storage_layout": storage_layout.as_dict(),
            "physical_split_status": (
                "postgres_schema_and_row_level_provenance"
                if backend == "postgres"
                and str(getattr(self.config, "postgres_schema", "") or "").strip()
                else "row_level_provenance_shared_postgres"
                if backend == "postgres"
                else "dev_only_local_backend"
            ),
            "rows_sampled": {
                "broker_orders": len(orders),
                "shadow_proposals": len(proposals),
                "strategy_fitness": len(fitness),
            },
            "broker_orders": _summarize_provenance_rows(
                orders,
                fields=(
                    "environment",
                    "mode",
                    "source_environment",
                    "broker_id",
                    "execution_provider",
                ),
            ),
            "shadow_proposals": _summarize_provenance_rows(
                proposals,
                fields=(
                    "environment",
                    "mode",
                    "source_environment",
                    "source",
                    "execution_provider",
                ),
            ),
            "strategy_fitness": _summarize_provenance_rows(
                fitness,
                fields=(
                    "environment",
                    "mode",
                    "source_environment",
                    "broker_id",
                    "execution_provider",
                ),
            ),
            "next_step": (
                "Run paper and live with their lane schemas/databases when migrating deployment; "
                "keep core reviewed evidence shared and paper/live execution evidence separated."
            ),
        }

    def _render_storage_separation_lines(self, storage: dict[str, Any]) -> list[str]:
        if not storage:
            return ["- No storage-separation summary available."]
        sampled = _as_dict(storage.get("rows_sampled"))
        lines = [
            (
                f"- backend={storage.get('backend', '-')}"
                f" | mode={storage.get('runtime_mode', '-')}"
                f" | environment={storage.get('runtime_environment', '-')}"
                f" | database_url_source={storage.get('database_url_source', '-')}"
                f" | postgres_schema={storage.get('postgres_schema') or '-'}"
            ),
            f"- physical_split={storage.get('physical_split_status', '-')}",
        ]
        layout = _as_dict(storage.get("storage_layout"))
        if layout:
            for lane_name in ("core", "paper", "live"):
                lane = _as_dict(layout.get(lane_name))
                if not lane:
                    continue
                lines.append(
                    (
                        f"- lane={lane_name}"
                        f" | schema={lane.get('postgres_schema') or '-'}"
                        f" | logs={lane.get('log_dir') or '-'}"
                        f" | evidence={lane.get('evidence_dir') or '-'}"
                        f" | execution_mutations={bool(lane.get('execution_mutations_allowed'))}"
                    )
                )
        lines.append(
            (
                f"- sampled_rows: broker_orders={int(sampled.get('broker_orders', 0) or 0)}"
                f" | shadow_proposals={int(sampled.get('shadow_proposals', 0) or 0)}"
                f" | strategy_fitness={int(sampled.get('strategy_fitness', 0) or 0)}"
            )
        )
        for label, key in (
            ("broker_orders", "broker_orders"),
            ("shadow_proposals", "shadow_proposals"),
            ("strategy_fitness", "strategy_fitness"),
        ):
            summary = _as_dict(storage.get(key))
            lines.append(
                (
                    f"- {label}: sampled={int(summary.get('sampled', 0) or 0)}"
                    f" | missing_required={int(summary.get('missing_required_rows', 0) or 0)}"
                    f" | groups={_format_group_counts(summary.get('groups'))}"
                )
            )
        lines.append(f"- next_step={storage.get('next_step', '-')}")
        return lines

    def _execution_router_intent_summary(self) -> dict[str, Any]:
        rows = self.usage_ledger.list_recent_execution_router_intents(limit=25)
        if not rows:
            return {
                "status": "insufficient_data",
                "recent": [],
                "reason": "No execution_router_intents rows found.",
            }
        latest = rows[0]
        return {
            "status": "ok",
            "recent_count": len(rows),
            "live_dry_count": sum(1 for row in rows if row.get("status") == "live_dry_intent"),
            "latest_tick_id": latest.get("tick_id"),
            "latest_status": latest.get("status"),
            "recent": rows,
        }

    def _trailing_drawdown_summary(self, ticks: list[dict[str, Any]]) -> dict[str, Any]:
        lane_rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for tick in ticks:
            snapshot = _as_dict(tick.get("state_snapshot_json"))
            observer = _as_dict(snapshot.get("trailing_drawdown_observer"))
            lanes = _as_dict(observer.get("lanes"))
            for broker_id, lane in lanes.items():
                item = _as_dict(lane)
                if not item:
                    continue
                lane_rows[str(broker_id)].append(
                    {
                        **item,
                        "tick_id": tick.get("tick_id"),
                        "started_at": tick.get("started_at"),
                    }
                )
        summaries = []
        for broker_id, rows in sorted(lane_rows.items()):
            observed = [row for row in rows if row.get("status") == "observed"]
            if not observed:
                continue
            latest = observed[0]
            summaries.append(
                {
                    "broker_id": broker_id,
                    "observations": len(observed),
                    "would_block_ticks": sum(
                        1 for row in observed if row.get("would_block_new_entries")
                    ),
                    "max_giveback_usd": max(
                        _to_float(row.get("giveback_usd")) or 0.0 for row in observed
                    ),
                    "max_giveback_pct": max(
                        _to_float(row.get("giveback_pct")) or 0.0 for row in observed
                    ),
                    "latest_tick_id": latest.get("tick_id"),
                    "latest_giveback_usd": latest.get("giveback_usd"),
                    "latest_giveback_pct": latest.get("giveback_pct"),
                    "latest_would_block": bool(latest.get("would_block_new_entries")),
                }
            )
        return {
            "status": "ok" if summaries else "insufficient_data",
            "lanes": summaries,
            "reason": "No trailing_drawdown_observer snapshots found in recent ticks.",
        }


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _summarize_provenance_rows(
    rows: list[dict[str, Any]],
    *,
    fields: tuple[str, ...],
) -> dict[str, Any]:
    required_fields = ("environment", "mode", "source_environment")
    groups: dict[str, int] = defaultdict(int)
    missing_required = 0
    for row in rows:
        if any(str(row.get(field, "") or "").strip() == "" for field in required_fields):
            missing_required += 1
        group_key = " / ".join(
            str(row.get(field, "") or "-").strip() or "-" for field in fields
        )
        groups[group_key] += 1
    return {
        "sampled": len(rows),
        "missing_required_rows": missing_required,
        "groups": dict(sorted(groups.items())),
    }


def _format_group_counts(value: Any) -> str:
    groups = _as_dict(value)
    if not groups:
        return "-"
    return ", ".join(f"{key}={count}" for key, count in list(groups.items())[:6])


def _coerce_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if value in (None, ""):
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _to_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_currency(value: Any) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "$-"
    return f"${numeric:.2f}"


def _fmt_pct(value: Any) -> str:
    numeric = _to_float(value)
    if numeric is None:
        return "-%"
    return f"{numeric * 100.0:.2f}%"
