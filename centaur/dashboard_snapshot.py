from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from .status import StatusReporter

DEFAULT_SNAPSHOT_PATH = Path(__file__).resolve().parent.parent / "var" / "dashboard_snapshot.json"


def write_dashboard_snapshot(
    *,
    output_path: Path | None = None,
    reporter: StatusReporter | None = None,
    include_visuals: bool = False,
    include_logs: bool = False,
) -> Path:
    destination = output_path or DEFAULT_SNAPSHOT_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        _json_safe(
            (reporter or StatusReporter()).snapshot(
                include_visuals=include_visuals,
                include_logs=include_logs,
            )
        ),
        indent=2,
    )
    temp_path = destination.with_suffix(destination.suffix + ".tmp")
    temp_path.write_text(payload + "\n", encoding="utf-8")
    temp_path.replace(destination)
    return destination


def _json_safe(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value
