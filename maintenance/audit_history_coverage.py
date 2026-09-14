#!/usr/bin/env python3
import argparse
import json
import sqlite3
from datetime import date
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.history_coverage import build_history_coverage
from app.imports import ensure_import_schema
from app.bulk_import import ensure_bulk_schema


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit read-only de la couverture historique Flow')
    parser.add_argument('--db', default='/data/flow.db')
    parser.add_argument('--months', type=int, default=24)
    parser.add_argument('--as-of', default=None)
    parser.add_argument('--fail-on-gaps', action='store_true')
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    ensure_import_schema(conn)
    ensure_bulk_schema(conn)
    as_of = date.fromisoformat(args.as_of) if args.as_of else None
    report = build_history_coverage(conn, as_of=as_of, months=args.months)
    conn.close()

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.fail_on_gaps:
        summary = report['summary']
        if summary['missing_statement_months'] or summary['review_months']:
            return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
