#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"

DAYS=180
CHUNK_DAYS=30
TIMEFRAME="1Hour"
MAX_REPLAY_TIMESTAMPS=0
EQUITY_SYMBOLS=""
CRYPTO_SYMBOLS=""
START_AT=""
END_AT=""
SLEEP_SECONDS=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --days)
      DAYS="$2"
      shift 2
      ;;
    --chunk-days)
      CHUNK_DAYS="$2"
      shift 2
      ;;
    --timeframe)
      TIMEFRAME="$2"
      shift 2
      ;;
    --max-replay-timestamps)
      MAX_REPLAY_TIMESTAMPS="$2"
      shift 2
      ;;
    --equity-symbols)
      EQUITY_SYMBOLS="$2"
      shift 2
      ;;
    --crypto-symbols)
      CRYPTO_SYMBOLS="$2"
      shift 2
      ;;
    --start-at)
      START_AT="$2"
      shift 2
      ;;
    --end-at)
      END_AT="$2"
      shift 2
      ;;
    --sleep-seconds)
      SLEEP_SECONDS="$2"
      shift 2
      ;;
    -h|--help)
      cat <<'EOF'
Usage:
  bash scripts/run_replay_chunks.sh [options]

Options:
  --days N                    Total lookback window when --start-at is not provided. Default: 180
  --chunk-days N              Chunk size in days. Default: 30
  --timeframe VALUE           Replay timeframe, for example 1Hour or 1Min. Default: 1Hour
  --max-replay-timestamps N   Optional cap per chunk. Default: 0 (all eligible timestamps)
  --equity-symbols CSV        Optional equity symbol override
  --crypto-symbols CSV        Optional crypto symbol override
  --start-at ISO              Optional ISO start datetime/date
  --end-at ISO                Optional ISO end datetime/date
  --sleep-seconds N           Pause between chunks. Default: 1
EOF
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      exit 1
      ;;
  esac
done

export DAYS CHUNK_DAYS START_AT END_AT
RANGES="$("$PYTHON_BIN" - <<'PY'
import os
from datetime import datetime, timedelta

days = int(os.environ["DAYS"])
chunk_days = int(os.environ["CHUNK_DAYS"])
start_raw = os.environ.get("START_AT", "").strip()
end_raw = os.environ.get("END_AT", "").strip()

def parse_dt(raw: str) -> datetime:
    normalized = raw.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.now().astimezone().tzinfo)
    return dt

end_at = parse_dt(end_raw) if end_raw else datetime.now().astimezone()
start_at = parse_dt(start_raw) if start_raw else end_at - timedelta(days=days)
if chunk_days <= 0:
    raise SystemExit("chunk_days must be positive")
if start_at >= end_at:
    raise SystemExit("start_at must be before end_at")

index = 1
cursor = start_at
while cursor < end_at:
    chunk_end = min(cursor + timedelta(days=chunk_days), end_at)
    print(f"{index}\t{cursor.isoformat()}\t{chunk_end.isoformat()}")
    cursor = chunk_end
    index += 1
PY
)"

if [[ -z "$RANGES" ]]; then
  echo "No replay chunks generated." >&2
  exit 1
fi

while IFS=$'\t' read -r CHUNK_INDEX CHUNK_START CHUNK_END; do
  echo "==== Replay Chunk ${CHUNK_INDEX} | ${CHUNK_START} -> ${CHUNK_END} | timeframe=${TIMEFRAME} ===="
  CMD=("$PYTHON_BIN" "main.py" "--replay" "--timeframe" "$TIMEFRAME" "--replay-start-at" "$CHUNK_START" "--replay-end-at" "$CHUNK_END")
  if [[ "$MAX_REPLAY_TIMESTAMPS" != "0" ]]; then
    CMD+=("--max-replay-timestamps" "$MAX_REPLAY_TIMESTAMPS")
  fi
  if [[ -n "$EQUITY_SYMBOLS" ]]; then
    CMD+=("--equity-symbols" "$EQUITY_SYMBOLS")
  fi
  if [[ -n "$CRYPTO_SYMBOLS" ]]; then
    CMD+=("--crypto-symbols" "$CRYPTO_SYMBOLS")
  fi

  (
    cd "$ROOT_DIR"
    "${CMD[@]}"
  )

  if [[ "$SLEEP_SECONDS" != "0" ]]; then
    sleep "$SLEEP_SECONDS"
  fi
done <<< "$RANGES"
