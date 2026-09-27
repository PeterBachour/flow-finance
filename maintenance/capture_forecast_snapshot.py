#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import date
import sys

from app.db import connection
from app.forecast_accuracy import capture_daily_forecast
from app.v2_migrations import ensure_v2_schema


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Capture the daily Flow forecast without changing the transaction ledger')
    parser.add_argument('--as-of', type=date.fromisoformat, default=date.today(), help='Forecast date in YYYY-MM-DD format')
    args = parser.parse_args(argv)

    with connection() as conn:
        ensure_v2_schema(conn)
        result = capture_daily_forecast(conn, as_of=args.as_of)

    print(
        f"status={result['status']} as_of={result['as_of']} "
        f"captured_modes={','.join(result.get('captured_modes', [])) or '-'}"
    )
    if result['status'] == 'unavailable':
        print(f"reason={result.get('reason', 'forecast_unavailable')}", file=sys.stderr)
        return 2
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
