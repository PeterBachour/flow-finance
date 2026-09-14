#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

RULES = (
    ('HONGLI INFORMATI', 'Shopping'),
    ('SLIM CO', 'Loisirs'),
)
MONTHS = ('2026-07', '2026-08')


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply third pass of externally verified recent transaction categories.')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    db = args.db.resolve()
    if not db.exists():
        print(f'error=db not found: {db}')
        return 2

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ','.join('?' for _ in MONTHS)
        rows = conn.execute(f'''
            SELECT id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer,
                   COALESCE(exclude_from_analytics,0) AS exclude_from_analytics
            FROM transactions
            WHERE substr(booking_date,1,7) IN ({placeholders})
              AND amount_cents<0
              AND COALESCE(status,'confirmed')='confirmed'
              AND COALESCE(is_internal_transfer,0)=0
              AND COALESCE(exclude_from_analytics,0)=0
              AND COALESCE(category,'')=''
            ORDER BY booking_date,id
        ''', MONTHS).fetchall()

        selected = []
        for row in rows:
            label = normalize(row['label'])
            matches = [(needle, category) for needle, category in RULES if needle in label]
            if len(matches) > 1:
                print(f"error=ambiguous rules id={row['id']} label={row['label']} matches={matches}")
                return 3
            if matches:
                needle, category = matches[0]
                selected.append((row, needle, category))

        print(f'mode={"apply" if args.apply else "dry-run"}')
        print('--- selected verified classifications pass3 ---')
        for row, needle, category in selected:
            print(
                f"id={row['id']} date={row['booking_date']} amount={abs(int(row['amount_cents']))/100:.2f} "
                f"category={category} rule={needle} label={row['label']}"
            )

        selected_total = sum(abs(int(row['amount_cents'])) for row, _, _ in selected)
        before = {}
        for month in MONTHS:
            stat = conn.execute('''
                SELECT COUNT(*) rows,COALESCE(SUM(-amount_cents),0) amount
                FROM transactions
                WHERE substr(booking_date,1,7)=?
                  AND amount_cents<0
                  AND COALESCE(status,'confirmed')='confirmed'
                  AND COALESCE(is_internal_transfer,0)=0
                  AND COALESCE(exclude_from_analytics,0)=0
                  AND COALESCE(category,'')=''
            ''', (month,)).fetchone()
            before[month] = (int(stat['rows']), int(stat['amount']))

        if args.apply:
            for row, _, category in selected:
                conn.execute('UPDATE transactions SET category=? WHERE id=?', (category, int(row['id'])))
            conn.commit()

        print('--- before ---')
        for month in MONTHS:
            count, amount = before[month]
            print(f'month={month} unknown_rows={count} unknown={amount/100:.2f}')

        print('--- after ---')
        for month in MONTHS:
            stat = conn.execute('''
                SELECT COUNT(*) rows,COALESCE(SUM(-amount_cents),0) amount
                FROM transactions
                WHERE substr(booking_date,1,7)=?
                  AND amount_cents<0
                  AND COALESCE(status,'confirmed')='confirmed'
                  AND COALESCE(is_internal_transfer,0)=0
                  AND COALESCE(exclude_from_analytics,0)=0
                  AND COALESCE(category,'')=''
            ''', (month,)).fetchone()
            count = int(stat['rows'])
            amount = int(stat['amount'])
            if not args.apply:
                month_selected = sum(
                    abs(int(row['amount_cents'])) for row, _, _ in selected
                    if row['booking_date'].startswith(month)
                )
                month_count = sum(1 for row, _, _ in selected if row['booking_date'].startswith(month))
                count -= month_count
                amount -= month_selected
            print(f'month={month} unknown_rows={count} unknown={amount/100:.2f}')

        print('--- summary ---')
        print(f'selected_rows={len(selected)} selected_amount={selected_total/100:.2f}')
        print(f'status={"applied" if args.apply else "ready"} integrity=ok')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
