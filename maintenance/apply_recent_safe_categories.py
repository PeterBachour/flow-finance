#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

# Only deterministic, high-confidence merchant patterns. Ambiguous/person-to-person
# labels are intentionally excluded from automatic classification.
RULES = (
    ('POKAWA', 'Restaurants'),
    ('FIVE GUYS', 'Restaurants'),
    ('CHOPSTICKS', 'Restaurants'),
    ('CHEZ CAMILLE', 'Restaurants'),
    ('LE BAR BASQUE', 'Restaurants'),
    ('CHOPE MOI PIGALL', 'Restaurants'),
    ('INDIGO', 'Transport'),
    ('SMOVENGO', 'Transport'),
    ('LDLC', 'Shopping'),
    ('CABARET VERT', 'Loisirs'),
)

MONTHS = ('2026-07', '2026-08')


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply safe deterministic categories to recent unknown outflows.')
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
        before = conn.execute('''
            SELECT substr(booking_date,1,7) month, COUNT(*) rows, COALESCE(SUM(-amount_cents),0) amount
            FROM transactions
            WHERE substr(booking_date,1,7) IN (?,?)
              AND amount_cents<0
              AND COALESCE(category,'')=''
              AND COALESCE(status,'confirmed')='confirmed'
            GROUP BY substr(booking_date,1,7)
            ORDER BY month
        ''', MONTHS).fetchall()

        selected = []
        for pattern, category in RULES:
            rows = conn.execute('''
                SELECT id,booking_date,amount_cents,label,category
                FROM transactions
                WHERE substr(booking_date,1,7) IN (?,?)
                  AND amount_cents<0
                  AND COALESCE(category,'')=''
                  AND COALESCE(status,'confirmed')='confirmed'
                  AND UPPER(label) LIKE ?
                ORDER BY booking_date,id
            ''', (*MONTHS, f'%{pattern}%')).fetchall()
            for row in rows:
                selected.append((row, category, pattern))

        # Protect against a row matching multiple rules.
        by_id = {}
        for row, category, pattern in selected:
            txid = int(row['id'])
            existing = by_id.get(txid)
            if existing and existing[1] != category:
                print(f'error=conflicting rules id={txid} {existing[1]} vs {category}')
                return 3
            by_id[txid] = (row, category, pattern)

        print(f'mode={"apply" if args.apply else "dry-run"}')
        print('--- selected safe classifications ---')
        total = 0
        for txid in sorted(by_id):
            row, category, pattern = by_id[txid]
            amount = abs(int(row['amount_cents']))
            total += amount
            print(
                f"id={txid} date={row['booking_date']} amount={amount/100:.2f} "
                f"category={category} rule={pattern} label={row['label']}"
            )

        if args.apply:
            for txid, (_, category, _) in by_id.items():
                conn.execute(
                    "UPDATE transactions SET category=? WHERE id=? AND COALESCE(category,'')=''",
                    (category, txid),
                )
            conn.commit()

        print('--- before ---')
        for row in before:
            print(f"month={row['month']} unknown_rows={row['rows']} unknown={int(row['amount'])/100:.2f}")

        if args.apply:
            after = conn.execute('''
                SELECT substr(booking_date,1,7) month, COUNT(*) rows, COALESCE(SUM(-amount_cents),0) amount
                FROM transactions
                WHERE substr(booking_date,1,7) IN (?,?)
                  AND amount_cents<0
                  AND COALESCE(category,'')=''
                  AND COALESCE(status,'confirmed')='confirmed'
                GROUP BY substr(booking_date,1,7)
                ORDER BY month
            ''', MONTHS).fetchall()
            print('--- after ---')
            for row in after:
                print(f"month={row['month']} unknown_rows={row['rows']} unknown={int(row['amount'])/100:.2f}")

        print('--- summary ---')
        print(f'selected_rows={len(by_id)} selected_amount={total/100:.2f}')
        print(f'status={"applied" if args.apply else "ready"} integrity=ok')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
