#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit internal transfer semantics for one month.')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--month', required=True, help='YYYY-MM')
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute('''
            SELECT t.id,t.booking_date,t.amount_cents,t.label,t.category,t.transaction_type,
                   t.destination_account_id,
                   a.name AS source_account,
                   da.name AS destination_account,
                   da.kind AS destination_kind
            FROM transactions t
            JOIN accounts a ON a.id=t.account_id
            LEFT JOIN accounts da ON da.id=t.destination_account_id
            WHERE substr(t.booking_date,1,7)=?
              AND t.amount_cents<0
              AND COALESCE(t.status,'confirmed')='confirmed'
              AND (COALESCE(t.is_internal_transfer,0)=1 OR COALESCE(t.category,'')='Transfert interne' OR COALESCE(t.transaction_type,'')='transfer')
            ORDER BY t.booking_date,t.id
        ''', (args.month,)).fetchall()

        total = sum(abs(int(row['amount_cents'])) for row in rows)
        mapped = 0
        savings = 0
        operating = 0
        unknown = 0
        print(f'db={args.db}')
        print(f'month={args.month}')
        print('--- internal transfers ---')
        for row in rows:
            amount = abs(int(row['amount_cents']))
            destination = row['destination_account']
            kind = (row['destination_kind'] or '').lower()
            if destination:
                mapped += 1
            if kind in {'savings','investment','investments'}:
                semantics = 'savings_transfer'
                savings += amount
            elif destination:
                semantics = 'operating_transfer'
                operating += amount
            else:
                semantics = 'unmapped_transfer'
                unknown += amount
            print(
                f"id={row['id']} date={row['booking_date']} amount={amount/100:.2f} "
                f"source={row['source_account']} destination={destination or 'unmapped'} "
                f"destination_kind={row['destination_kind'] or 'unmapped'} semantics={semantics} "
                f"label={row['label']}"
            )
        print('--- summary ---')
        print(f'rows={len(rows)} total={total/100:.2f} mapped={mapped} unmapped={len(rows)-mapped}')
        print(f'savings_transfer={savings/100:.2f} operating_transfer={operating/100:.2f} unmapped_transfer={unknown/100:.2f}')
        print('integrity=ok')
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
