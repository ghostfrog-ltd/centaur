#!/usr/bin/env python3
"""Refresh Mermaid visual docs from the current code.

Run this after changing orchestration, pipeline steps, graph nodes, or edges.
The script keeps generated Mermaid files in sync so the web frontend and docs
show the current runtime shape without manual copying.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.engine.control_graph import build_control_graph_mermaid
from scripts.export_pipeline_mermaid import build_mermaid


GENERATED_FILES = {
    PROJECT_ROOT / "docs/visuals/current_pipeline.mmd": build_mermaid,
    PROJECT_ROOT / "docs/visuals/current_langgraph_bridge.mmd": build_control_graph_mermaid,
}

HAND_AUTHORED_FILES = [
    PROJECT_ROOT / "docs/visuals/entry_decision_funnel.mmd",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Update generated Mermaid visual documentation."
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Fail if generated Mermaid files are out of date.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stale: list[Path] = []

    for path, builder in GENERATED_FILES.items():
        content = builder()
        if args.check:
            existing = path.read_text(encoding="utf-8") if path.exists() else ""
            if existing != content:
                stale.append(path)
            continue

        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"Updated {path.relative_to(PROJECT_ROOT)}")

    for path in HAND_AUTHORED_FILES:
        if not path.exists():
            stale.append(path)

    if args.check and stale:
        print("Mermaid visuals are stale or missing:", file=sys.stderr)
        for path in stale:
            print(f"- {path.relative_to(PROJECT_ROOT)}", file=sys.stderr)
        raise SystemExit(1)

    if args.check:
        print("Mermaid visuals are current.")


if __name__ == "__main__":
    main()
