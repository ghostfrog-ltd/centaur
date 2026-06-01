#!/usr/bin/env python3
"""Export the current Centaur pipeline as Mermaid.

This is documentation tooling only. It imports `build_default_pipeline()` and
turns the ordered StepDefinition list into a flowchart so the visual docs do not
drift from the actual tick runner.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.engine.pipelines import build_default_pipeline


def build_mermaid() -> str:
    steps = build_default_pipeline()
    lines = [
        "flowchart TD",
        '  start(["scheduled tick"])',
    ]

    previous_id = "start"
    for index, step in enumerate(steps, start=1):
        node_id = f"n{index:02d}"
        lines.append(f'  {node_id}["{step.name}"]')
        lines.append(f"  {previous_id} --> {node_id}")
        previous_id = node_id

    lines.append('  done(["tick complete"])')
    lines.append(f"  {previous_id} --> done")
    return "\n".join(lines) + "\n"


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
