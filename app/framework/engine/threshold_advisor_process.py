from __future__ import annotations

import json
from datetime import datetime

from app.framework.engine.threshold_advisor_worker import (
    ThresholdAdvisorWorkerPaths,
    process_threshold_advisor_once,
)


def main() -> None:
    paths = ThresholdAdvisorWorkerPaths.default()
    try:
        result = process_threshold_advisor_once(paths=paths)
        print(json.dumps(result, sort_keys=True), flush=True)
    except Exception as exc:  # pragma: no cover - process boundary
        print(
            json.dumps(
                {
                    "status": "error",
                    "errored_at": datetime.now().astimezone().isoformat(),
                    "trade_authority": "none",
                    "error": f"{type(exc).__name__}: {exc}",
                },
                sort_keys=True,
            ),
            flush=True,
        )
    finally:
        paths.worker_lock_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
