#!/usr/bin/env python3
"""Export the current Centaur pipeline as Mermaid.

This is documentation tooling only. It imports `build_default_pipeline()` and
turns the ordered StepDefinition list into a flowchart so the visual docs do not
drift from the actual tick runner. Each node includes its heartbeat step
pipeline reference and is grouped by the runtime ownership lane it belongs to,
so the graph stays tied to the code and folder structure instead of becoming a
detached step list.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from dataclasses import dataclass
import inspect
from pathlib import Path
import sys
from typing import Callable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.framework.engine.pipelines import build_default_pipeline


@dataclass(frozen=True, slots=True)
class PipelineLane:
    key: str
    title: str
    class_name: str
    prefixes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PipelineNode:
    node_id: str
    name: str
    runner_ref: str
    lane: PipelineLane


PIPELINE_LANES: tuple[PipelineLane, ...] = (
    PipelineLane(
        key="runtime",
        title="Runtime control / app.heartbeat.steps + app.framework.runtime",
        class_name="runtime",
        prefixes=("control.", "context."),
    ),
    PipelineLane(
        key="broker",
        title="Broker sync / app.heartbeat.steps + app.framework.adapters",
        class_name="broker",
        prefixes=("alpaca.", "alpaca_live.", "trading212_paper."),
    ),
    PipelineLane(
        key="risk",
        title="Risk gates / app.heartbeat.steps + app.framework.runtime",
        class_name="risk",
        prefixes=("risk.",),
    ),
    PipelineLane(
        key="maintenance",
        title="Maintenance / app.heartbeat.steps",
        class_name="maintenance",
        prefixes=("maintenance.",),
    ),
    PipelineLane(
        key="market",
        title="Market data + FX / app.heartbeat.steps + app.framework.adapters",
        class_name="market",
        prefixes=("market.", "crypto.", "fx.", "trading212."),
    ),
    PipelineLane(
        key="execution",
        title="Execution routing / app.heartbeat.steps + app.framework.runtime",
        class_name="execution",
        prefixes=("execution.",),
    ),
    PipelineLane(
        key="research",
        title="Research, evidence, and analysis / app.heartbeat.steps + app.framework.engine",
        class_name="research",
        prefixes=("shadow.", "strategy.", "analysis.", "evaluation.", "slow."),
    ),
    PipelineLane(
        key="notifications",
        title="Operator notifications / app.heartbeat.steps + app.framework.runtime",
        class_name="notifications",
        prefixes=("notifications.",),
    ),
)

DEFAULT_LANE = PipelineLane(
    key="other",
    title="Other runtime ownership",
    class_name="other",
    prefixes=(),
)


def build_mermaid() -> str:
    steps = build_default_pipeline()
    nodes = [
        PipelineNode(
            node_id=f"n{index:02d}",
            name=step.name,
            runner_ref=_runner_reference(step.runner),
            lane=_lane_for_step(step.name),
        )
        for index, step in enumerate(steps, start=1)
    ]
    node_ids_by_lane: dict[str, list[PipelineNode]] = defaultdict(list)
    for node in nodes:
        node_ids_by_lane[node.lane.key].append(node)

    lines = [
        "flowchart TD",
        '  start(["scheduled tick"])',
    ]

    for lane in _lanes_for_nodes(nodes):
        lane_nodes = node_ids_by_lane[lane.key]
        lines.append(f'  subgraph lane_{lane.key}["{_escape_mermaid_text(lane.title)}"]')
        for node in lane_nodes:
            label = (
                f"{_escape_mermaid_text(node.name)}"
                f"<br/>{_escape_mermaid_text(node.runner_ref)}"
            )
            lines.append(f'    {node.node_id}["{label}"]')
        lines.append("  end")

    previous_id = "start"
    for node in nodes:
        lines.append(f"  {previous_id} --> {node.node_id}")
        previous_id = node.node_id

    lines.append('  done(["tick complete"])')
    lines.append(f"  {previous_id} --> done")
    lines.extend(_class_definitions())
    for lane in _lanes_for_nodes(nodes):
        lane_nodes = node_ids_by_lane[lane.key]
        node_ids = ",".join(node.node_id for node in lane_nodes)
        if node_ids:
            lines.append(f"  class {node_ids} {lane.class_name}")
    return "\n".join(lines) + "\n"


def _lanes_for_nodes(nodes: Sequence[PipelineNode]) -> list[PipelineLane]:
    lane_by_key = {lane.key: lane for lane in (*PIPELINE_LANES, DEFAULT_LANE)}
    seen = {node.lane.key for node in nodes}
    return [lane for lane in lane_by_key.values() if lane.key in seen]


def _lane_for_step(step_name: str) -> PipelineLane:
    for lane in PIPELINE_LANES:
        if step_name.startswith(lane.prefixes):
            return lane
    return DEFAULT_LANE


def _runner_reference(runner: Callable[..., object]) -> str:
    unwrapped = inspect.unwrap(runner)
    source_file = inspect.getsourcefile(unwrapped) or inspect.getfile(unwrapped)
    source_path = Path(source_file).resolve()
    try:
        source_ref = source_path.relative_to(PROJECT_ROOT)
    except ValueError:
        source_ref = Path(unwrapped.__module__.replace(".", "/") + ".py")
    runner_name = getattr(unwrapped, "__name__", unwrapped.__class__.__name__)
    return f"{source_ref}::{runner_name}"


def _escape_mermaid_text(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _class_definitions() -> list[str]:
    return [
        "  classDef runtime fill:#eef7f4,stroke:#28705f,color:#10231f",
        "  classDef broker fill:#f7fbff,stroke:#2f6f9f,color:#13283a",
        "  classDef risk fill:#fff1f0,stroke:#b0413e,color:#3d1716",
        "  classDef maintenance fill:#f5f1ff,stroke:#7756b3,color:#261a3d",
        "  classDef market fill:#fff8e6,stroke:#b78313,color:#3d2a09",
        "  classDef execution fill:#edf7ff,stroke:#1f6feb,color:#10233f",
        "  classDef research fill:#f2f5f7,stroke:#657174,color:#172022",
        "  classDef notifications fill:#eef5f1,stroke:#0f8b8d,color:#10231f",
        "  classDef other fill:#ffffff,stroke:#657174,color:#172022",
    ]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the current Centaur control pipeline as Mermaid."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/visuals/current_pipeline.mmd"),
        help="Path to write the Mermaid file.",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print Mermaid to stdout instead of writing a file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    mermaid = build_mermaid()
    if args.stdout:
        print(mermaid, end="")
        return

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(mermaid, encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
