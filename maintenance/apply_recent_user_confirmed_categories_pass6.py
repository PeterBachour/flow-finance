#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

TARGETS = {
    1861: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1866: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1867: ('Alimentation', 'USER_CONFIRMED_FOOD'),
    1901: ('Alimentation', 'USER_CONFIRMED_FOOD'),
}

EXPECTED = {
    1861: ('2026-07-06', -3400, 'LE MONT VALLON'),
    1866: ('2026-07-09', -1000, 'S.I.H.T HOTEL ME'),
    1867: ('2026-07-10', -572, 'S.I.H.T HOTEL ME'),
    1901: ('2026-08-03', -4500, 'ST GERMAIN PAR'),
}


def unknown_summary(conn: sqlite3.Connection, month: str) -> tuple[int, int]:
    row = conn.execute(
        '''SELECT COALESCE(SUM(-amount_cents), 0) AS total, COUNT(*) AS rows
           FROM transactions
           WHERE substr(booking_date,1,7)=?
             AND amount_cents<0
             AND COALESCE(category,'')='' ''',
        (month,),
    ).fetchone()
    return int(row['total']), int(row['rows'])


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply final user-confirmed Jul-Aug food classifications.')
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
            f'''SELECT id, booking_date, amount_cents, label, category
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
            tx_id = int(row['id'])
            exp_date, exp_amount, exp_label = EXPECTED[tx_id]
            if (
                row['booking_date'] != exp_date
                or int(row['amount_cents']) != exp_amount
                or exp_label not in (row['label'] or '').upper()
            ):
                print(f'error=transaction {tx_id} no longer matches expected movement')
                return 4

        before = {m: unknown_summary(conn, m) for m in ('2026-07', '2026-08')}

        print(f'mode={"apply" if args.apply else "dry-run"}')
        print('--- selected final user-confirmed classifications ---')
        total = 0
        for row in rows:
            category, rule = TARGETS[int(row['id'])]
            amount = abs(int(row['amount_cents']))
            total += amount
            print(
                f"id={row['id']} date={row['booking_date']} amount={amount/100:.2f} "
                f"old_category={row['category'] or 'NULL'} new_category={category} "
                f"rule={rule} label={row['label']}"
            )

        if args.apply:
            for row in rows:
                category, _ = TARGETS[int(row['id'])]
                conn.execute('UPDATE transactions SET category=? WHERE id=?', (category, int(row['id'])))
            conn.commit()

        after = {m: unknown_summary(conn, m) for m in ('2026-07', '2026-08')}

        print('--- before ---')
        for month in ('2026-07', '2026-08'):
            amount, count = before[month]
            print(f'month={month} unknown_rows={count} unknown={amount/100:.2f}')
        print('--- after ---')
        for month in ('2026-07', '2026-08'):
            amount, count = after[month]
            print(f'month={month} unknown_rows={count} unknown={amount/100:.2f}')
        print('--- summary ---')
        print(f'selected_rows={len(rows)} selected_amount={total/100:.2f}')
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        print(f'status={"applied" if args.apply else "ready"} integrity={integrity}')
        return 0 if integrity == 'ok' else 5
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
