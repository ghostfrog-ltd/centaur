from __future__ import annotations

import argparse
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from centaur.dashboard_snapshot import DEFAULT_SNAPSHOT_PATH, write_dashboard_snapshot


def main() -> None:
    args = parse_args()
    output = Path(args.output) if args.output else DEFAULT_SNAPSHOT_PATH
    write_dashboard_snapshot(output_path=output)
    print(output, flush=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Emit a Centaur dashboard snapshot as JSON.")
    parser.add_argument(
        "--output",
        type=str,
        default="",
        help="Optional output file path for the JSON snapshot.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
