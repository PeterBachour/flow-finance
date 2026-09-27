#!/usr/bin/env bash
set -euo pipefail

FLOW_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
AS_OF="$(date +%F)"

cd "$FLOW_DIR"
exec docker compose run --rm --no-deps flow-finance \
  python maintenance/capture_forecast_snapshot.py --as-of "$AS_OF"
