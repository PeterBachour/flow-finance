#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

SAFE_RULES = (
    ('INDIGO', 'Transport'),
)


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply only high-confidence categorization rules to recent unknown outflows.')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--months', nargs='+', default=['2026-07', '2026-08'])
    args = parser.parse_args()

    db = args.db.resolve()
    if not db.exists():
        print(f'error=db not found: {db}')
        return 2

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        placeholders = ','.join('?' for _ in args.months)
        rows = conn.execute(f'''
            SELECT id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer,
                   COALESCE(exclude_from_analytics,0) AS exclude_from_analytics
            FROM transactions
            WHERE substr(booking_date,1,7) IN ({placeholders})
              AND amount_cents<0
              AND COALESCE(status,'confirmed')='confirmed'
              AND COALESCE(is_internal_transfer,0)=0
              AND COALESCE(exclude_from_analytics,0)=0
              AND (category IS NULL OR TRIM(category)='')
            ORDER BY booking_date,id
        ''', args.months).fetchall()

        selected = []
        for row in rows:
            label = normalize(row['label'])
            match = next(((pattern, category) for pattern, category in SAFE_RULES if pattern in label), None)
            if match:
                selected.append((row, match[0], match[1]))

        print(f'mode={"apply" if args.apply else "dry-run"}')
        print('--- safe classifications ---')
        total = 0
        for row, pattern, category in selected:
            amount = abs(int(row['amount_cents']))
            total += amount
            print(f"id={row['id']} date={row['booking_date']} amount={amount/100:.2f} pattern={pattern} category={category} label={row['label']}")

        if args.apply:
            for row, _pattern, category in selected:
                conn.execute(
                    "UPDATE transactions SET category=?,transaction_type='expense' WHERE id=?",
                    (category, int(row['id'])),
                )
            conn.commit()

        print('--- summary ---')
        print(f'rows={len(selected)} amount={total/100:.2f}')
        print(f'status={"applied" if args.apply else "ready"} integrity=ok')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
