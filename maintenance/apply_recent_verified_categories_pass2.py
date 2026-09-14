#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

RULES = (
    ('LGA 55', 'Restaurants'),
    ('LE GERMAIN', 'Restaurants'),
    ('AYNOUDIS', 'Alimentation'),
    ('MAG0679', 'Shopping'),
)
MONTHS = ('2026-07', '2026-08')


def norm(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def category_for(label: str) -> tuple[str, str] | None:
    n = norm(label)
    for pattern, category in RULES:
        if pattern in n:
            return pattern, category
    return None


def unknown_summary(conn: sqlite3.Connection) -> dict[str, tuple[int, int]]:
    result = {}
    for month in MONTHS:
        row = conn.execute('''
            SELECT COUNT(*) AS n, COALESCE(SUM(-amount_cents),0) AS total
            FROM transactions
            WHERE substr(booking_date,1,7)=?
              AND amount_cents<0
              AND COALESCE(status,'confirmed')='confirmed'
              AND COALESCE(is_internal_transfer,0)=0
              AND COALESCE(exclude_from_analytics,0)=0
              AND COALESCE(category,'')=''
        ''', (month,)).fetchone()
        result[month] = (int(row['n']), int(row['total']))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply second verified merchant classification pass for Jul/Aug 2026 unknown outflows.')
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
        before = unknown_summary(conn)
        rows = conn.execute('''
            SELECT id,booking_date,amount_cents,label,category
            FROM transactions
            WHERE substr(booking_date,1,7) IN ('2026-07','2026-08')
              AND amount_cents<0
              AND COALESCE(status,'confirmed')='confirmed'
              AND COALESCE(is_internal_transfer,0)=0
              AND COALESCE(exclude_from_analytics,0)=0
              AND COALESCE(category,'')=''
            ORDER BY booking_date,id
        ''').fetchall()

        selected = []
        for row in rows:
            match = category_for(row['label'])
            if match:
                pattern, category = match
                selected.append((row, pattern, category))

        print(f'mode={"apply" if args.apply else "dry-run"}')
        print('--- selected verified classifications ---')
        total = 0
        for row, pattern, category in selected:
            amount = abs(int(row['amount_cents']))
            total += amount
            print(f"id={row['id']} date={row['booking_date']} amount={amount/100:.2f} category={category} rule={pattern} label={row['label']}")

        if args.apply:
            for row, _, category in selected:
                conn.execute('UPDATE transactions SET category=? WHERE id=? AND COALESCE(category,\'\')=\'\'', (category, int(row['id'])))
            conn.commit()

        after = unknown_summary(conn) if args.apply else before
        if not args.apply:
            projected = {}
            for month, (count, cents) in before.items():
                month_rows = [r for r, _, _ in selected if r['booking_date'].startswith(month)]
                projected[month] = (count - len(month_rows), cents - sum(abs(int(r['amount_cents'])) for r in month_rows))
            after = projected

        print('--- before ---')
        for month in MONTHS:
            n, cents = before[month]
            print(f'month={month} unknown_rows={n} unknown={cents/100:.2f}')
        print('--- after ---')
        for month in MONTHS:
            n, cents = after[month]
            print(f'month={month} unknown_rows={n} unknown={cents/100:.2f}')
        print('--- summary ---')
        print(f'selected_rows={len(selected)} selected_amount={total/100:.2f}')
        print(f'status={"applied" if args.apply else "ready"} integrity=ok')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
