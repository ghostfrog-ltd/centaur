"""LangGraph/Pydantic graph for the scheduled heartbeat cron.

This is the orchestration owner for the scheduled control tick. Each heartbeat
step folder contributes one auditable graph node; this module supplies the typed
state, node input, node output, success-path edges, and halt-on-error routing.
"""

from __future__ import annotations

from datetime import datetime
from operator import add
from time import perf_counter
from typing import Annotated, Any, Sequence

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from app.heartbeat.contracts import HeartbeatStepDefinition
from app.framework.runtime.models import StepProfile, TickContext

from .pipeline import build_heartbeat_cron_pipeline


class HeartbeatCronNodeInput(BaseModel):
    """Typed input contract for one heartbeat graph node."""

    model_config = ConfigDict(frozen=True)

    tick_id: str
    node_name: str
    step_index: int
    step_total: int
    state_keys_before: tuple[str, ...] = Field(default_factory=tuple)

    @classmethod
    def from_state(
        cls,
        *,
        state: "HeartbeatCronGraphState",
        node_name: str,
        step_index: int,
        step_total: int,
    ) -> "HeartbeatCronNodeInput":
        return cls(
            tick_id=state.context.tick_id,
            node_name=node_name,
            step_index=step_index,
            step_total=step_total,
            state_keys_before=tuple(sorted(state.context.state.keys())),
        )


class HeartbeatCronNodeOutput(BaseModel):
    """Typed output contract for one heartbeat graph node."""

    model_config = ConfigDict(arbitrary_types_allowed=True, frozen=True)

    node_name: str
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
            "last_node_name": self.node_name,
            "last_node_status": self.status,
            "halted": self.halted,
        }


class HeartbeatCronGraphState(BaseModel):
    """Pydantic state carried through the heartbeat LangGraph."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    # TickContext still carries the rich runtime objects and mutable state while
    # the graph migration is underway. The graph-owned lists below are typed so
    # each node emits auditable profiles without hiding failures in loose dicts.
    context: Any
    step_profiles: Annotated[list[StepProfile], add] = Field(default_factory=list)
    node_outputs: Annotated[list[HeartbeatCronNodeOutput], add] = Field(
        default_factory=list
    )
    halted: bool = False
    last_node_name: str | None = None
    last_node_status: str = "pending"


def heartbeat_cron_step_names(
    steps: Sequence[HeartbeatStepDefinition] | None = None,
) -> list[str]:
    """Return the ordered LangGraph node names for the heartbeat cron."""

    return [step.name for step in (steps or build_heartbeat_cron_pipeline())]


def heartbeat_cron_edges(
    steps: Sequence[HeartbeatStepDefinition] | None = None,
) -> list[tuple[str, str]]:
    """Return the primary success-path graph edges for tests and docs."""

    names = heartbeat_cron_step_names(steps)
    if not names:
        return [(START, END)]
    edges: list[tuple[str, str]] = [(START, names[0])]
    edges.extend((left, right) for left, right in zip(names, names[1:]))
    edges.append((names[-1], END))
    return edges


def build_heartbeat_cron_state_graph(
    steps: Sequence[HeartbeatStepDefinition] | None = None,
    *,
    logger: Any | None = None,
) -> StateGraph:
    """Build the scheduled heartbeat `StateGraph`.

    A node error records `context.state["last_error"]`, emits an error profile,
    and routes directly to `END`. That preserves capital-gate ordering by never
    allowing later risk/execution nodes to run after an upstream failure.
    """

    graph = StateGraph(HeartbeatCronGraphState)
    step_list = list(steps or build_heartbeat_cron_pipeline())
    if not step_list:
        graph.add_edge(START, END)
        return graph

    total = len(step_list)
    for index, step in enumerate(step_list, start=1):
        # Each folder-owned step becomes exactly one LangGraph node. The node
        # name is the contract name, so diagrams, logs, and state profiles align.
        graph.add_node(
            step.name,
            _build_node(
                step=step,
                index=index,
                total=total,
                logger=logger,
            ),
        )

    graph.add_edge(START, step_list[0].name)
    for index, step in enumerate(step_list, start=1):
        next_name = step_list[index].name if index < total else END
        # A failed node routes to END immediately. Later risk/execution nodes
        # never run after an upstream error, preserving capital-gate ordering.
        graph.add_conditional_edges(
            step.name,
            _route_after_node,
            {
                "continue": next_name,
                "halt": END,
            },
        )
    return graph


def build_heartbeat_cron_graph(
    steps: Sequence[HeartbeatStepDefinition] | None = None,
    *,
    logger: Any | None = None,
) -> Any:
    """Compile the scheduled heartbeat LangGraph."""

    return build_heartbeat_cron_state_graph(steps, logger=logger).compile()


def run_heartbeat_cron_graph(
    context: TickContext,
    *,
    steps: Sequence[HeartbeatStepDefinition] | None = None,
    logger: Any | None = None,
) -> HeartbeatCronGraphState:
    """Run the heartbeat LangGraph and return validated Pydantic graph state."""

    graph = build_heartbeat_cron_graph(steps, logger=logger)
    result = graph.invoke(HeartbeatCronGraphState(context=context))
    return HeartbeatCronGraphState.model_validate(result)


def build_heartbeat_cron_graph_mermaid(
    steps: Sequence[HeartbeatStepDefinition] | None = None,
) -> str:
    """Render the heartbeat LangGraph success path as Mermaid."""

    step_list = list(steps or build_heartbeat_cron_pipeline())
    lines = [
        "flowchart TD",
        '  start(["scheduled heartbeat cron"])',
    ]

    previous_id = "start"
    for index, step in enumerate(step_list, start=1):
        node_id = f"n{index:02d}"
        lines.append(f'  {node_id}["{step.name}"]')
        lines.append(f"  {previous_id} --> {node_id}")
        previous_id = node_id

    lines.append('  done(["heartbeat complete"])')
    lines.append(f"  {previous_id} --> done")
    lines.append("  classDef typed fill:#eef7f4,stroke:#28705f,color:#10231f")
    if step_list:
        node_ids = ",".join(f"n{index:02d}" for index in range(1, len(step_list) + 1))
        lines.append(f"  class {node_ids} typed")
    return "\n".join(lines) + "\n"


def _build_node(
    *,
    step: HeartbeatStepDefinition,
    index: int,
    total: int,
    logger: Any | None,
) -> Any:
    def run_node(state: HeartbeatCronGraphState) -> dict[str, object]:
        node_input = HeartbeatCronNodeInput.from_state(
            state=state,
            node_name=step.name,
            step_index=index,
            step_total=total,
        )
        profile = _run_step(
            context=state.context,
            step=step,
            node_input=node_input,
            logger=logger,
        )
        output = HeartbeatCronNodeOutput(
            node_name=step.name,
            status=profile.status,
            profile=profile,
            state_keys_after=tuple(sorted(state.context.state.keys())),
        )
        return output.as_state_update()

    return run_node


def _run_step(
    *,
    context: TickContext,
    step: HeartbeatStepDefinition,
    node_input: HeartbeatCronNodeInput,
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
        # Keep failure evidence on both the profile and TickContext. Operators
        # can see which step halted the heartbeat without later nodes mutating
        # trading state after the error.
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


def _route_after_node(state: HeartbeatCronGraphState) -> str:
    if state.halted or state.last_node_status != "ok":
        return "halt"
    return "continue"
