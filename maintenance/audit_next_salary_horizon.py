#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import sqlite3
import sys
from datetime import date, timedelta
from pathlib import Path
from statistics import median

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def _shift_weekend_back(value: date) -> date:
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def _candidate_for_month(year: int, month: int, usual_day: int) -> date:
    day = min(max(1, usual_day), calendar.monthrange(year, month)[1])
    return _shift_weekend_back(date(year, month, day))


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit the next salary horizon from reconciled payroll bank credits')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
    parser.add_argument('--lookback', type=int, default=8)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to audit production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    as_of = date.fromisoformat(args.as_of)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    rows = conn.execute('''
        SELECT p.period,p.net_paid_cents,t.booking_date,t.amount_cents,t.label,m.confidence
        FROM payroll_transaction_matches m
        JOIN payroll_records p ON p.id=m.payroll_record_id
        JOIN transactions t ON t.id=m.transaction_id
        WHERE t.amount_cents > 0
        ORDER BY t.booking_date DESC,t.id DESC
        LIMIT ?
    ''', (max(3, args.lookback),)).fetchall()
    if len(rows) < 3:
        print(f'error=insufficient reconciled salary history count={len(rows)}')
        return 4

    ordered = list(reversed(rows))
    dates = [date.fromisoformat(r['booking_date']) for r in ordered]
    days = [d.day for d in dates]
    recent_days = days[-min(6, len(days)):]
    usual_day = int(round(median(recent_days)))

    year, month = as_of.year, as_of.month
    candidate = _candidate_for_month(year, month, usual_day)
    if candidate <= as_of:
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
        candidate = _candidate_for_month(year, month, usual_day)

    print(f'db={db_path}')
    print(f'as_of={as_of.isoformat()} reconciled_salary_count={len(rows)} usual_day={usual_day}')
    print('--- recent reconciled salaries ---')
    for r in ordered:
        print(
            f"salary period={r['period']} date={r['booking_date']} amount={int(r['amount_cents'])/100:.2f} "
            f"payroll_net={int(r['net_paid_cents'])/100:.2f} confidence={float(r['confidence']):.4f} label={r['label']}"
        )
    horizon_end = candidate - timedelta(days=1)
    print(f'next_salary_candidate={candidate.isoformat()}')
    print(f'safe_to_spend_horizon_end={horizon_end.isoformat()}')
    print(f'horizon_days={(horizon_end-as_of).days}')
    print('prediction_method=median_recent_reconciled_salary_day_with_weekend_shift_back')
    print('integrity=' + conn.execute('PRAGMA integrity_check').fetchone()[0])
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
