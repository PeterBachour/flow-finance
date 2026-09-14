#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.safe_to_spend import calculate_safe_to_spend, recurring_is_fresh


def euros(cents: int | None) -> str:
    if cents is None:
        return 'unavailable'
    return f'{cents / 100:.2f}'


def _next_month_same_day(value: date, day: int) -> date:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(1, day), max_day))


def _dates(first: date, usual_day: int, start: date, end: date) -> list[date]:
    current = first
    while current < start:
        current = _next_month_same_day(current, usual_day)
    out = []
    while current <= end:
        out.append(current)
        current = _next_month_same_day(current, usual_day)
    return out


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone())


def main() -> int:
    parser = argparse.ArgumentParser(description='Validate Flow safe-to-spend against a staging database')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument(
        '--horizon-days',
        type=int,
        default=None,
        help='Optional manual horizon override. Omit to use the predicted next salary.',
    )
    parser.add_argument('--as-of', type=str)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to run safe-to-spend staging validator on production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    as_of_arg = date.fromisoformat(args.as_of) if args.as_of else None
    manual_horizon = max(0, args.horizon_days) if args.horizon_days is not None else None
    result = calculate_safe_to_spend(
        conn,
        as_of=as_of_arg,
        horizon_days=manual_horizon,
        stale_reference_date=date.today(),
    )

    reserved_cents = (
        result.safety_reserve_cents
        + result.planned_commitments_cents
        + result.recurring_commitments_cents
        + result.goal_contributions_cents
    )

    print(f'db={db_path}')
    print(
        f'as_of={result.as_of} horizon_end={result.horizon_end} '
        f'horizon_days={result.horizon_days} horizon_mode={result.horizon_mode} '
        f'next_salary_date={result.next_salary_date}'
    )
    print(f'balance={euros(result.balance_cents)} included_accounts={result.included_account_count}')
    print(f'safety_reserve={euros(result.safety_reserve_cents)}')
    print(
        f'planned_commitments={euros(result.planned_commitments_cents)} '
        f'planned_occurrences={result.planned_occurrence_count}'
    )

    cycle_month = result.as_of[:7]
    if _table_exists(conn, 'cycle_reserves'):
        cycle_rows = conn.execute('''
            SELECT label,amount_cents,kind,reason,source_type
            FROM cycle_reserves
            WHERE cycle_month=? AND status='active' AND source_status='confirmed'
            ORDER BY CASE kind WHEN 'safety_reserve' THEN 0 ELSE 1 END,label
        ''', (cycle_month,)).fetchall()
        if cycle_rows:
            print('--- cycle reserves ---')
            for row in cycle_rows:
                print(
                    f"cycle_reserve kind={row['kind']} amount={euros(int(row['amount_cents']))} "
                    f"label={row['label']} source={row['source_type']} reason={row['reason']}"
                )

    print(
        f'recurring_commitments={euros(result.recurring_commitments_cents)} '
        f'recurring_occurrences={result.recurring_occurrence_count} '
        f'included_profiles={result.recurring_included_count} '
        f'stale_excluded_profiles={result.recurring_stale_excluded_count}'
    )
    print('--- recurring details ---')
    as_of_date = date.fromisoformat(result.as_of)
    start = as_of_date + timedelta(days=1)
    end = date.fromisoformat(result.horizon_end)
    recurring_rows = conn.execute('''
        SELECT label,amount_cents,usual_day,day_of_month,next_expected_date,last_seen_date,confidence,source_type
        FROM recurring_transactions
        WHERE is_active=1 AND detection_status='accepted' AND amount_cents<0
        ORDER BY COALESCE(next_expected_date,'9999-12-31'),label
    ''').fetchall()
    for row in recurring_rows:
        source_type = (row['source_type'] or '').lower()
        auto_detected = source_type in {'history', 'auto', 'detected'}
        fresh = recurring_is_fresh(row['last_seen_date'], as_of_date) if auto_detected else True
        if not fresh:
            print(
                f"recurring_excluded label={row['label']} reason=stale_history "
                f"last_seen={row['last_seen_date']} confidence={row['confidence']}"
            )
            continue
        day = int(row['usual_day'] or row['day_of_month'] or 1)
        if row['next_expected_date']:
            first = date.fromisoformat(row['next_expected_date'])
        else:
            max_day = calendar.monthrange(start.year, start.month)[1]
            first = date(start.year, start.month, min(max(1, day), max_day))
        occurrences = _dates(first, day, start, end)
        if not occurrences:
            continue
        total = abs(int(row['amount_cents'])) * len(occurrences)
        print(
            f"recurring_included label={row['label']} unit={euros(abs(int(row['amount_cents'])))} "
            f"dates={[d.isoformat() for d in occurrences]} total={euros(total)} "
            f"last_seen={row['last_seen_date']} confidence={row['confidence']}"
        )

    print(
        f'goal_contributions={euros(result.goal_contributions_cents)} '
        f'goals={result.goal_count} goal_mode={result.goal_contribution_mode}'
    )
    print(f'calculated_safe_to_spend={euros(result.calculated_safe_to_spend_cents)}')
    print(f'safe_to_spend={euros(result.safe_to_spend_cents)} status={result.safe_to_spend_status}')
    print(
        f'data_freshness balance_age_days={result.balance_age_days} '
        f'balance_is_stale={str(result.balance_is_stale).lower()}'
    )
    print(
        'summary '
        f'safe_to_spend_status={result.safe_to_spend_status} '
        f'safe_to_spend_cents={result.safe_to_spend_cents} '
        f'calculated_safe_to_spend_cents={result.calculated_safe_to_spend_cents} '
        f'balance_cents={result.balance_cents} '
        f'reserved_cents={reserved_cents} '
        f'horizon_days={result.horizon_days} '
        f'horizon_mode={result.horizon_mode} '
        f'next_salary_date={result.next_salary_date} '
        f'cycle_reserves={result.cycle_reserve_count} '
        f'goal_mode={result.goal_contribution_mode} '
        f'recurring_included={result.recurring_included_count} '
        f'recurring_stale_excluded={result.recurring_stale_excluded_count} '
        f'balance_is_stale={str(result.balance_is_stale).lower()}'
    )
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
