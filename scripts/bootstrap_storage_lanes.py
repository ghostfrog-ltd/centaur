from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.framework.runtime.settings import load_runtime_config
from app.framework.storage.layout import storage_layout_from_config
from app.framework.storage.usage import UsageLedger


def main() -> int:
    config = load_runtime_config()
    layout = storage_layout_from_config(config)
    lanes = (layout.core, layout.paper, layout.live)
    initialized: list[str] = []

    for lane in lanes:
        lane_config = replace(config, postgres_schema=lane.postgres_schema)
        ledger = UsageLedger(config=lane_config)
        initialized.append(
            f"{lane.name}:schema={lane.postgres_schema}:backend={ledger.backend}"
        )

    print("Centaur storage lanes initialized")
    for item in initialized:
        print(f"- {item}")
    print(
        "Decision rule: core remains the shared reviewed-evidence brain; "
        "paper/live schemas are execution and evidence lanes."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
