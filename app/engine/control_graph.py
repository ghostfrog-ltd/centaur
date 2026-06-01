"""LangGraph bridge for Centaur's control tick.

This module is the first behaviour-preserving migration layer from the legacy
ordered pipeline to LangGraph. Each current `StepDefinition` remains the body
of one auditable graph node, so capital gates such as market readiness, CFO
risk, execution routing, live following, and notifications keep their existing
names and order while typed node contracts are introduced around them.
"""

from __future__ import annotations

from datetime import datetime
from operator import add
from time import perf_counter
from typing import Annotated, Any, Sequence

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from app.runtime.models import StepProfile, TickContext

from .pipelines import StepDefinition, build_default_pipeline


class ControlNodeInput(BaseModel):
    """Typed input contract for one control graph node."""

    model_config = ConfigDict(frozen=True)

    tick_id: str
    step_name: str
    step_index: int
    step_total: int
    state_keys_before: tuple[str, ...] = Field(default_factory=tuple)

    @classmethod
    def from_state(
        cls,
        *,
        state: "ControlGraphState",
        step_name: str,
        step_index: int,
        step_total: int,
    ) -> "ControlNodeInput":
        return cls(
            tick_id=state.context.tick_id,
            step_name=step_name,
            step_index=step_index,
            step_total=step_total,
            state_keys_before=tuple(sorted(state.context.state.keys())),
        )


class ControlNodeOutput(BaseModel):
    """Typed output contract for one control graph node."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    step_name: str
    status: str
    profile: StepProfile
    state_keys_after: tuple[str, ...] = Field(default_factory=tuple)

    @property
    def halted(self) -> bool:
        return self.status != "ok"

    def as_state_update(self) -> dict[str, object]:
        return {
            "step_profiles": [self.profile],
            "node_outputs": [self],
            "last_step_name": self.step_name,
            "last_step_status": self.status,
            "halted": self.halted,
        }


class ControlGraphState(BaseModel):
    """Pydantic state carried between LangGraph control-tick nodes."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    context: Any
    step_profiles: Annotated[list[StepProfile], add] = Field(default_factory=list)
    node_outputs: Annotated[list[ControlNodeOutput], add] = Field(default_factory=list)
    halted: bool = False
    last_step_name: str | None = None
    last_step_status: str = "pending"


def control_graph_step_names(
    steps: Sequence[StepDefinition] | None = None,
) -> list[str]:
    """Return the ordered graph node names for the control tick."""

    return [step.name for step in (steps or build_default_pipeline())]


def control_graph_edges(
    steps: Sequence[StepDefinition] | None = None,
) -> list[tuple[str, str]]:
    """Return the primary success-path graph edges for visualization/tests."""

    names = control_graph_step_names(steps)
    if not names:
        return [(START, END)]
    edges: list[tuple[str, str]] = [(START, names[0])]
    edges.extend((left, right) for left, right in zip(names, names[1:]))
    edges.append((names[-1], END))
    return edges


def build_control_state_graph(
    steps: Sequence[StepDefinition] | None = None,
    *,
    logger: Any | None = None,
) -> StateGraph:
    """Build a LangGraph `StateGraph` from the current control pipeline.

    Error handling deliberately mirrors `ControlPipelineRunner`: a failing node
    records `context.state["last_error"]`, emits an error profile, and routes to
    `END` so later risk/execution nodes do not run after an upstream failure.
    """

    graph = StateGraph(ControlGraphState)
    step_list = list(steps or build_default_pipeline())
    if not step_list:
        graph.add_edge(START, END)
        return graph

    total = len(step_list)
    for index, step in enumerate(step_list, start=1):
        graph.add_node(
            step.name,
            _build_step_node(
                step=step,
                index=index,
                total=total,
                logger=logger,
            ),
        )

    graph.add_edge(START, step_list[0].name)
    for index, step in enumerate(step_list, start=1):
        next_name = step_list[index].name if index < total else END
        graph.add_conditional_edges(
            step.name,
            _route_after_step,
            {
                "continue": next_name,
                "halt": END,
            },
        )
    return graph


def build_control_graph(
    steps: Sequence[StepDefinition] | None = None,
    *,
    logger: Any | None = None,
) -> Any:
    """Compile the control-tick LangGraph bridge."""

    return build_control_state_graph(steps, logger=logger).compile()


def run_control_graph(
    context: TickContext,
    *,
    steps: Sequence[StepDefinition] | None = None,
    logger: Any | None = None,
) -> ControlGraphState:
    """Run the LangGraph bridge and return validated Pydantic graph state."""

    graph = build_control_graph(steps, logger=logger)
    result = graph.invoke(ControlGraphState(context=context))
    return ControlGraphState.model_validate(result)


def build_control_graph_mermaid(
    steps: Sequence[StepDefinition] | None = None,
) -> str:
    """Render the LangGraph bridge success path as Mermaid."""

    step_list = list(steps or build_default_pipeline())
    lines = [
        "flowchart TD",
        '  start(["scheduled tick"])',
    ]

    previous_id = "start"
    for index, step in enumerate(step_list, start=1):
        node_id = f"n{index:02d}"
        lines.append(f'  {node_id}["{step.name}"]')
        lines.append(f"  {previous_id} --> {node_id}")
        previous_id = node_id

    lines.append('  done(["tick complete"])')
    lines.append(f"  {previous_id} --> done")
    lines.append("  classDef typed fill:#eef7f4,stroke:#28705f,color:#10231f")
    if step_list:
        node_ids = ",".join(f"n{index:02d}" for index in range(1, len(step_list) + 1))
        lines.append(f"  class {node_ids} typed")
    return "\n".join(lines) + "\n"


def _build_step_node(
    *,
    step: StepDefinition,
    index: int,
    total: int,
    logger: Any | None,
) -> Any:
    def run_step(state: ControlGraphState) -> dict[str, object]:
        node_input = ControlNodeInput.from_state(
            state=state,
            step_name=step.name,
            step_index=index,
            step_total=total,
        )
        profile = _run_step(
            context=state.context,
            step=step,
            node_input=node_input,
            logger=logger,
        )
        output = ControlNodeOutput(
            step_name=step.name,
            status=profile.status,
            profile=profile,
            state_keys_after=tuple(sorted(state.context.state.keys())),
        )
        return output.as_state_update()

    return run_step


def _run_step(
    *,
    context: TickContext,
    step: StepDefinition,
    node_input: ControlNodeInput,
    logger: Any | None,
) -> StepProfile:
    started_at = datetime.now().astimezone()
    started_perf = perf_counter()
    if logger is not None:
        logger.step_start(
            step_name=step.name,
            index=node_input.step_index,
            total=node_input.step_total,
            started_at=started_at,
        )

    details: dict[str, Any]
    status = "ok"
    error: str | None = None

    try:
        details = step.runner(context) or {}
    except Exception as exc:
        details = {"error_type": type(exc).__name__}
        error = str(exc)
        status = "error"
        context.state["last_error"] = {
            "step": step.name,
            "message": error,
        }

    ended_at = datetime.now().astimezone()
    profile = StepProfile(
        name=step.name,
        status=status,
        started_at=started_at,
        ended_at=ended_at,
        duration_seconds=perf_counter() - started_perf,
        details=details,
        error=error,
    )
    if logger is not None:
        logger.step_end(
            profile=profile,
            index=node_input.step_index,
            total=node_input.step_total,
        )
    return profile


def _route_after_step(state: ControlGraphState) -> str:
    if state.halted or state.last_step_status != "ok":
        return "halt"
    return "continue"
