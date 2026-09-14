#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

TARGETS = (
    ('2026-08-29', -10000, 'VIR INST PETER BACHOUR'),
    ('2026-08-29', -10000, 'VIR SEPA M PETER BACHOUR'),
    ('2026-08-29', -52000, 'VIR SEPA M PETER BACHOUR'),
)


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def main() -> int:
    parser = argparse.ArgumentParser(description='Tag validated August 2026 own-account transfers as savings semantics.')
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
        rows = conn.execute('''
            SELECT id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer
            FROM transactions
            WHERE booking_date='2026-08-29'
              AND amount_cents<0
              AND COALESCE(status,'confirmed')='confirmed'
              AND COALESCE(is_internal_transfer,0)=1
            ORDER BY id
        ''').fetchall()

        selected = []
        used_ids: set[int] = set()
        for target_date, target_amount, target_label in TARGETS:
            matches = [
                row for row in rows
                if int(row['id']) not in used_ids
                and row['booking_date'] == target_date
                and int(row['amount_cents']) == target_amount
                and normalize(row['label']) == target_label
            ]
            if not matches:
                print(f'error=missing target date={target_date} amount={target_amount/100:.2f} label={target_label}')
                return 3
            row = matches[0]
            used_ids.add(int(row['id']))
            selected.append(row)

        print(f'mode={"apply" if args.apply else "dry-run"}')
        print('--- selected validated savings transfers ---')
        for row in selected:
            print(
                f"id={row['id']} date={row['booking_date']} amount={abs(int(row['amount_cents']))/100:.2f} "
                f"label={row['label']} old_type={row['transaction_type']} internal={row['is_internal_transfer']}"
            )

        selected_ids = [int(row['id']) for row in selected]
        total = sum(abs(int(row['amount_cents'])) for row in selected)
        if total != 72000:
            print(f'error=unexpected selected total {total/100:.2f}')
            return 4

        if args.apply:
            placeholders = ','.join('?' for _ in selected_ids)
            conn.execute(
                f"UPDATE transactions SET transaction_type='saving' WHERE id IN ({placeholders})",
                selected_ids,
            )
            conn.commit()

        # In dry-run mode the selected rows are still tagged as generic transfers in
        # the database. Exclude them explicitly from the operating-transfer total so
        # the preview reflects the post-apply semantics instead of double counting.
        placeholders = ','.join('?' for _ in selected_ids)
        operating = conn.execute(f'''
            SELECT COALESCE(SUM(-amount_cents),0) total
            FROM transactions
            WHERE substr(booking_date,1,7)='2026-08'
              AND amount_cents<0
              AND COALESCE(is_internal_transfer,0)=1
              AND COALESCE(transaction_type,'') NOT IN ('saving','investment')
              AND id NOT IN ({placeholders})
        ''', selected_ids).fetchone()['total'] if not args.apply else conn.execute('''
            SELECT COALESCE(SUM(-amount_cents),0) total
            FROM transactions
            WHERE substr(booking_date,1,7)='2026-08'
              AND amount_cents<0
              AND COALESCE(is_internal_transfer,0)=1
              AND COALESCE(transaction_type,'') NOT IN ('saving','investment')
        ''').fetchone()['total']

        savings = total if not args.apply else conn.execute('''
            SELECT COALESCE(SUM(-amount_cents),0) total
            FROM transactions
            WHERE substr(booking_date,1,7)='2026-08'
              AND amount_cents<0
              AND COALESCE(is_internal_transfer,0)=1
              AND transaction_type IN ('saving','investment')
        ''').fetchone()['total']

        total_internal = int(savings) + int(operating)
        if total_internal != 237000:
            print(f'error=unexpected internal total {total_internal/100:.2f}')
            return 5

        print('--- summary ---')
        print(f'savings_transfer={int(savings)/100:.2f}')
        print(f'operating_transfer={int(operating)/100:.2f}')
        print(f'total_internal={total_internal/100:.2f}')
        print(f'status={"applied" if args.apply else "ready"} integrity=ok')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
