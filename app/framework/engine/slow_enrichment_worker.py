from __future__ import annotations

import json
from datetime import datetime

from app.framework.engine.slow_enrichment_queue import (
    SlowEnrichmentQueuePaths,
    process_slow_enrichment_queue_until_idle,
)


def main() -> None:
    paths = SlowEnrichmentQueuePaths.default()
    try:
        result = process_slow_enrichment_queue_until_idle(paths=paths)
        print(json.dumps({"status": "ok", **result}, sort_keys=True), flush=True)
    except Exception as exc:  # pragma: no cover - process boundary
        print(
            json.dumps(
                {
                    "status": "error",
                    "errored_at": datetime.now().astimezone().isoformat(),
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
