#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

TARGETS = {
    1929: ('Shopping', 'USER_CONFIRMED_PARIS_MADELEINE_IS_LDLC'),
}


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply user-confirmed recent transaction classifications, pass 4.')
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
            f'''SELECT id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer
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

        row = rows[0]
        if int(row['id']) == 1929:
            if row['booking_date'] != '2026-08-18' or int(row['amount_cents']) != -27385 or 'PARIS MADELEINE' not in (row['label'] or '').upper():
                print('error=transaction 1929 no longer matches expected Paris Madeleine movement')
                return 4

        before = conn.execute('''
            SELECT COALESCE(SUM(-amount_cents),0) total, COUNT(*) rows
            FROM transactions
            WHERE substr(booking_date,1,7)='2026-08'
              AND amount_cents<0
              AND COALESCE(category,'')=''
        ''').fetchone()

        if args.apply:
            for row in rows:
                category, _ = TARGETS[int(row['id'])]
                conn.execute(
                    'UPDATE transactions SET category=? WHERE id=?',
                    (category, int(row['id'])),
                )
            conn.commit()

        after_unknown = int(before['total']) - total
        after_rows = int(before['rows']) - len(rows)

        print('--- before ---')
        print(f"month=2026-08 unknown_rows={int(before['rows'])} unknown={int(before['total'])/100:.2f}")
        print('--- after ---')
        print(f"month=2026-08 unknown_rows={after_rows} unknown={after_unknown/100:.2f}")
        print('--- summary ---')
        print(f'selected_rows={len(rows)} selected_amount={total/100:.2f}')
        print(f'status={"applied" if args.apply else "ready"} integrity=ok')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
