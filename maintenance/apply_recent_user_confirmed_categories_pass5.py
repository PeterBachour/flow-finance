#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

TARGETS = {
    1856: ('Remboursement', 'USER_CONFIRMED_REIMBURSEMENT'),
    1857: ('Remboursement', 'USER_CONFIRMED_REIMBURSEMENT'),
    1877: ('Remboursement', 'USER_CONFIRMED_REIMBURSEMENT'),
    1862: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1880: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1888: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1894: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1921: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1923: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1927: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1930: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1932: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1933: ('Alimentation', 'USER_CONFIRMED_FOOD'),
}

EXPECTED = {
    1856: ('2026-07-02', -5700, 'NORMAN NOURRY'),
    1857: ('2026-07-02', -14000, 'JOY MATTAR'),
    1877: ('2026-07-20', -1600, 'AHMAD A'),
    1862: ('2026-07-08', -1822, 'SUPERMERCADO BAR'),
    1880: ('2026-07-20', -1464, 'SC- LA PERLE D'),
    1888: ('2026-07-27', -700, 'DAL S DISTRIBUT'),
    1894: ('2026-07-30', -149, 'CARNOT DISTRI'),
    1921: ('2026-08-10', -225, 'CARNOT DISTRI'),
    1923: ('2026-08-11', -165, 'CARNOT DISTRI'),
    1927: ('2026-08-17', -225, 'CARNOT DISTRI'),
    1930: ('2026-08-18', -448, 'CARNOT DISTRI'),
    1932: ('2026-08-19', -3200, 'VALE DE PRADOS'),
    1933: ('2026-08-19', -1100, 'DAMES MAGIC'),
}

MONTHS = ('2026-07', '2026-08')


def unknown_summary(conn: sqlite3.Connection, month: str) -> tuple[int, int]:
    row = conn.execute(
        '''SELECT COALESCE(SUM(-amount_cents),0) AS total, COUNT(*) AS rows
           FROM transactions
           WHERE substr(booking_date,1,7)=?
             AND amount_cents<0
             AND COALESCE(category,'')='' ''',
        (month,),
    ).fetchone()
    return int(row['rows']), int(row['total'])


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply user-confirmed transaction classifications, pass 5.')
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
        ids = tuple(TARGETS)
        placeholders = ','.join('?' for _ in ids)
        rows = conn.execute(
            f'''SELECT id,booking_date,amount_cents,label,category
                FROM transactions
                WHERE id IN ({placeholders})
                ORDER BY id''',
            ids,
        ).fetchall()

        if len(rows) != len(ids):
            found = {int(r['id']) for r in rows}
            missing = [i for i in ids if i not in found]
            print(f'error=missing transaction ids {missing}')
            return 3

        for row in rows:
            expected_date, expected_amount, expected_fragment = EXPECTED[int(row['id'])]
            label = (row['label'] or '').upper()
            if row['booking_date'] != expected_date or int(row['amount_cents']) != expected_amount or expected_fragment not in label:
                print(f"error=transaction {row['id']} no longer matches expected movement")
                return 4

        before = {month: unknown_summary(conn, month) for month in MONTHS}

        print(f'mode={"apply" if args.apply else "dry-run"}')
        print('--- selected user-confirmed classifications ---')
        total = 0
        for row in rows:
            category, rule = TARGETS[int(row['id'])]
            amount = abs(int(row['amount_cents']))
            total += amount
            print(
                f"id={row['id']} date={row['booking_date']} amount={amount/100:.2f} "
                f"old_category={row['category'] or 'NULL'} new_category={category} rule={rule} label={row['label']}"
            )

        if args.apply:
            for row in rows:
                category, _ = TARGETS[int(row['id'])]
                conn.execute('UPDATE transactions SET category=? WHERE id=?', (category, int(row['id'])))
            conn.commit()

        after = {month: unknown_summary(conn, month) if args.apply else before[month] for month in MONTHS}

        print('--- before ---')
        for month in MONTHS:
            rows_count, cents = before[month]
            print(f'month={month} unknown_rows={rows_count} unknown={cents/100:.2f}')
        print('--- after ---')
        for month in MONTHS:
            rows_count, cents = after[month]
            print(f'month={month} unknown_rows={rows_count} unknown={cents/100:.2f}')
        print('--- summary ---')
        print(f'selected_rows={len(rows)} selected_amount={total/100:.2f}')
        print(f'status={"applied" if args.apply else "ready"} integrity=ok')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
