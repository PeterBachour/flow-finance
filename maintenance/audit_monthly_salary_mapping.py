#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def next_month_key(period: str) -> str:
    year, month = map(int, period.split('-', 1))
    if month == 12:
        return f'{year + 1:04d}-01'
    return f'{year:04d}-{month + 1:02d}'


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit reconciled salary -> Flow budget month mapping.')
    parser.add_argument('--db', type=Path, required=True)
    args = parser.parse_args()
    db = args.db.resolve()
    if not db.exists():
        print(f'error=db not found: {db}')
        return 2

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute('''
            SELECT p.period payroll_period,t.id transaction_id,t.booking_date,t.amount_cents,t.label
            FROM payroll_transaction_matches m
            JOIN payroll_records p ON p.id=m.payroll_record_id
            JOIN transactions t ON t.id=m.transaction_id
            WHERE t.amount_cents>0
            ORDER BY p.period,t.booking_date,t.id
        ''').fetchall()
        by_month: dict[str, list[sqlite3.Row]] = {}
        for row in rows:
            by_month.setdefault(next_month_key(row['payroll_period']), []).append(row)

        print(f'db={db}')
        print(f'reconciled_salary_rows={len(rows)}')
        anomalies = 0
        for month in sorted(by_month):
            items = by_month[month]
            total = sum(int(item['amount_cents']) for item in items)
            if len(items) != 1:
                anomalies += 1
            details = ', '.join(
                f"payroll={item['payroll_period']} booked={item['booking_date']} amount={item['amount_cents']/100:.2f}"
                for item in items
            )
            print(f'month={month} salary_count={len(items)} salary={total/100:.2f} {details}')
        print(f'summary mapped_months={len(by_month)} anomalous_months={anomalies} integrity={"ok" if anomalies == 0 else "review"}')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
