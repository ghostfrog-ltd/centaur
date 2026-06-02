"""Typed heartbeat cron node contracts."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.framework.runtime.models import TickContext

PipelineResult = dict[str, Any]
HeartbeatRunner = Callable[[TickContext], PipelineResult]


class HeartbeatStepDefinition(BaseModel):
    """One auditable LangGraph node owned by a heartbeat step folder."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    # `contract` is data; `runner` is behaviour. Keeping both together lets the
    # graph execute a step while docs/tests can still inspect its audit metadata.
    contract: "HeartbeatStepContract"
    runner: HeartbeatRunner

    @property
    def name(self) -> str:
        return self.contract.name

    @property
    def implementation_ref(self) -> str:
        return self.contract.implementation_ref

    @property
    def reads_state(self) -> tuple[str, ...]:
        return self.contract.reads_state

    @property
    def writes_state(self) -> tuple[str, ...]:
        return self.contract.writes_state

    @property
    def safety_notes(self) -> str:
        return self.contract.safety_notes

    @property
    def runner_ref(self) -> str:
        return f"{self.runner.__module__.replace('.', '/')}.py::{self.runner.__name__}"


class HeartbeatStepContract(BaseModel):
    """Typed contract and audit metadata for one heartbeat step pipeline."""

    model_config = ConfigDict(frozen=True)

    # These fields are deliberately small and stable. They are used by Mermaid
    # visuals, tests, and operator review to prove what each step owns.
    name: str
    implementation_ref: str
    reads_state: tuple[str, ...] = Field(default_factory=tuple)
    writes_state: tuple[str, ...] = Field(default_factory=tuple)
    safety_notes: str
