#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.financial_integrity import build_financial_integrity
from app.imports import ensure_import_schema


def _ensure_recurring_columns(conn: sqlite3.Connection) -> None:
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(recurring_transactions)').fetchall()}
    for name, sql_type in {
        'usual_day': 'INTEGER',
        'next_expected_date': 'TEXT',
        'last_seen_date': 'TEXT',
        "detection_status": "TEXT NOT NULL DEFAULT 'accepted'",
    }.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE recurring_transactions ADD COLUMN {name} {sql_type}')


def exit_code(result: dict, fail_on_hard: bool = False) -> int:
    if fail_on_hard:
        return 1 if int(result.get('hard_issue_count', 0)) > 0 else 0
    return exit_code(result, args.fail_on_hard)


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit Flow bank statements, history and Safe to Spend integrity.')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', type=date.fromisoformat, default=date.today())
    parser.add_argument('--months', type=int, default=24)
    parser.add_argument('--json', action='store_true', dest='as_json')
    parser.add_argument('--fail-on-hard', action='store_true')
    args = parser.parse_args()

    db = args.db.resolve()
    if not db.exists():
        print(f'error=db not found: {db}', file=sys.stderr)
        return 2

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        ensure_import_schema(conn)
        _ensure_recurring_columns(conn)
        result = build_financial_integrity(
            conn,
            as_of=args.as_of,
            months=max(1, min(args.months, 36)),
        )
        conn.commit()
    finally:
        conn.close()

    if args.as_json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return exit_code(result, args.fail_on_hard)

    statements = result['statement_audit']['summary']
    safe = result['safe_to_spend_breakdown']
    print(
        f"as_of={result['as_of']} status={result['status']} issues={result['issue_count']} "
        f"hard_issues={result.get('hard_issue_count', 0)} reviews={result.get('review_issue_count', 0)}"
    )
    print('--- bank statements ---')
    print(
        f"statements={statements['statement_count']} "
        f"reconciled={statements['reconciled_count']} "
        f"reviews={statements.get('review_count', 0)} "
        f"warnings={statements['warning_count']} "
        f"arithmetic_errors={statements['arithmetic_error_count']} "
        f"missing_snapshots={statements['missing_balance_snapshot_count']}"
    )
    for item in result['statement_audit']['statements']:
        if item['integrity_status'] == 'warning':
            print(
                f"warning period={item['period_end']} import={item['import_id']} "
                f"issues={','.join(item.get('hard_issues') or item['issues'])} filename={item['filename']}"
            )
        elif item['integrity_status'] == 'reconciled_with_review':
            print(
                f"review period={item['period_end']} import={item['import_id']} "
                f"issues={','.join(item.get('review_issues') or item['issues'])} filename={item['filename']}"
            )

    print('--- safe to spend ---')
    for item in safe['components']:
        sign = '-' if item['operator'] == '-' else '+'
        print(f"{sign} {item['label']}: {item['amount_cents']/100:.2f} EUR")
    value = safe['safe_to_spend_cents']
    print(f"= safe_to_spend: {'unavailable' if value is None else f'{value/100:.2f} EUR'}")
    print(f"arithmetic_consistent={str(safe['arithmetic_consistent']).lower()}")

    print('--- recent months ---')
    for item in result['monthly_audit']['months'][-6:]:
        print(
            f"month={item['month']} income={item['income_cents']/100:.2f} "
            f"consumption={item['consumption_cents']/100:.2f} "
            f"savings={item['savings_cents']/100:.2f} "
            f"internal_out={item['internal_transfer_out_cents']/100:.2f} "
            f"coverage={item['classification_coverage_pct']:.1f}%"
        )

    return 0 if result['status'] == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
