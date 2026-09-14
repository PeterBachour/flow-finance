#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from collections import defaultdict
from pathlib import Path


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def merchant_key(label: str | None) -> str:
    value = normalize(label)
    prefixes = ('CB ', 'PRLV ', 'VIR ', 'VIR.', 'VIREMENT ', 'PRET ', 'COTISATION ', 'FRAIS ')
    for prefix in prefixes:
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    # Keep the first stable tokens and remove common trailing card dates/codes.
    tokens = [t for t in value.replace('/', ' ').split() if not (len(t) in {5, 8} and any(c.isdigit() for c in t))]
    return ' '.join(tokens[:4]) or value


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit recent unclassified confirmed outflows for Flow.')
    parser.add_argument('--db', type=Path, required=True)
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
            SELECT id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer
            FROM transactions
            WHERE substr(booking_date,1,7) IN ({placeholders})
              AND amount_cents<0
              AND COALESCE(status,'confirmed')='confirmed'
              AND COALESCE(is_internal_transfer,0)=0
              AND COALESCE(category,'')=''
              AND COALESCE(exclude_from_analytics,0)=0
            ORDER BY booking_date,id
        ''', args.months).fetchall()

        print(f'db={db}')
        print(f'months={",".join(args.months)}')
        print('--- unknown transactions ---')
        per_month = defaultdict(int)
        grouped = defaultdict(lambda: {'amount': 0, 'count': 0, 'rows': []})
        for row in rows:
            month = row['booking_date'][:7]
            amount = abs(int(row['amount_cents']))
            per_month[month] += amount
            key = merchant_key(row['label'])
            grouped[key]['amount'] += amount
            grouped[key]['count'] += 1
            grouped[key]['rows'].append(row)
            print(f"id={row['id']} date={row['booking_date']} amount={amount/100:.2f} label={row['label']}")

        print('--- grouped candidates ---')
        for key, data in sorted(grouped.items(), key=lambda item: (-item[1]['amount'], -item[1]['count'], item[0])):
            ids = ','.join(str(r['id']) for r in data['rows'])
            months = ','.join(sorted({r['booking_date'][:7] for r in data['rows']}))
            print(f"merchant={key} rows={data['count']} amount={data['amount']/100:.2f} months={months} ids={ids}")

        print('--- summary ---')
        for month in args.months:
            print(f'month={month} unknown={per_month[month]/100:.2f}')
        print(f'rows={len(rows)} total={sum(per_month.values())/100:.2f} groups={len(grouped)} integrity=ok')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
