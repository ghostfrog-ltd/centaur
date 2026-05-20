from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

if False:  # pragma: no cover
    from .config import RuntimeConfig
    from .usage import UsageLedger


@dataclass(slots=True)
class TickContext:
    tick_id: str
    started_at: datetime
    config: "RuntimeConfig"
    usage_ledger: "UsageLedger"
    state: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    def record_api_usage(
        self,
        *,
        source: str,
        endpoint: str,
        request_count: int = 1,
        success: bool = True,
        input_units: int = 0,
        output_units: int = 0,
        estimated_cost_usd: float | None = None,
        notes: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event = self.usage_ledger.record_api_call(
            tick_id=self.tick_id,
            requested_at=datetime.now().astimezone(),
            source=source,
            endpoint=endpoint,
            request_count=request_count,
            success=success,
            input_units=input_units,
            output_units=output_units,
            estimated_cost_usd=estimated_cost_usd,
            notes=notes,
            metadata=metadata or {},
        )
        self.state.setdefault("api_usage_events", []).append(event)
        return event


@dataclass(slots=True)
class StepProfile:
    name: str
    status: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    details: dict[str, Any] = field(default_factory=dict)
    error: str | None = None


@dataclass(slots=True)
class TickReport:
    tick_id: str
    status: str
    started_at: datetime
    ended_at: datetime
    duration_seconds: float
    step_profiles: list[StepProfile] = field(default_factory=list)
    state_snapshot: dict[str, Any] = field(default_factory=dict)
    tick_api_usage: list["ApiUsageSummary"] = field(default_factory=list)
    daily_api_usage: list["ApiUsageSummary"] = field(default_factory=list)
    tick_api_request_count: int = 0
    tick_estimated_cost_usd: float = 0.0
    daily_api_request_count: int = 0
    daily_estimated_cost_usd: float = 0.0
    daily_warning_threshold_usd: float = 0.0
    daily_limit_threshold_usd: float = 0.0
    budget_status: str = "unknown"
    operations_backend: str = "unknown"
    operations_backend_detail: str = ""
    persisted_tick_run: bool = False
    persistence_error: str | None = None


@dataclass(slots=True)
class ApiUsageSummary:
    usage_date: str
    source: str
    request_count: int
    success_count: int
    error_count: int
    input_units: int = 0
    output_units: int = 0
    estimated_cost_usd: float = 0.0
