#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sqlite3
from collections import defaultdict
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def euros(cents: int | None) -> str:
    return f"{int(cents or 0) / 100:.2f}"


def merchant_key(label: str | None) -> str:
    text = (label or '').upper().strip()
    text = re.sub(r'^CB\s+', '', text)
    text = re.sub(r'\s+\d{2}/\d{2}/\d{2}$', '', text)
    text = re.sub(r'\b\d{2,}\b', '', text)
    text = re.sub(r'[^A-ZÀ-ÖØ-Ý0-9*\-\' ]+', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    words = text.split()
    return ' '.join(words[:4]) if words else 'UNKNOWN'


def main() -> int:
    parser = argparse.ArgumentParser(description='Group still-unclassified debit transactions by normalized merchant for review.')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
    parser.add_argument('--months', type=int, default=6)
    parser.add_argument('--limit', type=int, default=40)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to audit production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    as_of = date.fromisoformat(args.as_of)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    rows = conn.execute('''
        SELECT id,booking_date,amount_cents,label,source_key
        FROM transactions
        WHERE booking_date>=date(?, ?, 'start of month')
          AND booking_date<date(?, 'start of month')
          AND amount_cents<0
          AND COALESCE(status,'confirmed')='confirmed'
          AND COALESCE(is_internal_transfer,0)=0
          AND (category IS NULL OR trim(category)='')
        ORDER BY booking_date,id
    ''', (as_of.isoformat(), f'-{max(1,args.months)} months', as_of.isoformat())).fetchall()

    groups: dict[str, dict] = defaultdict(lambda: {'count': 0, 'amount': 0, 'labels': defaultdict(int), 'first': None, 'last': None})
    for row in rows:
        key = merchant_key(row['label'])
        amount = abs(int(row['amount_cents']))
        g = groups[key]
        g['count'] += 1
        g['amount'] += amount
        g['labels'][row['label']] += 1
        g['first'] = row['booking_date'] if g['first'] is None or row['booking_date'] < g['first'] else g['first']
        g['last'] = row['booking_date'] if g['last'] is None or row['booking_date'] > g['last'] else g['last']

    ranked = sorted(groups.items(), key=lambda kv: (-kv[1]['count'], -kv[1]['amount'], kv[0]))
    print(f'db={db_path}')
    print(f'as_of={as_of.isoformat()} groups={len(groups)} rows={len(rows)} amount={euros(sum(abs(int(r["amount_cents"])) for r in rows))}')
    print('--- merchant groups ---')
    for key, g in ranked[:max(1,args.limit)]:
        samples = sorted(g['labels'].items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        sample_text = ' | '.join(label for label, _count in samples)
        recurrent = g['count'] >= 2
        print(
            f"merchant={key} rows={g['count']} amount={euros(g['amount'])} first={g['first']} last={g['last']} "
            f"repeated={str(recurrent).lower()} samples={sample_text}"
        )

    repeated_rows = sum(g['count'] for g in groups.values() if g['count'] >= 2)
    repeated_amount = sum(g['amount'] for g in groups.values() if g['count'] >= 2)
    singleton_rows = sum(g['count'] for g in groups.values() if g['count'] == 1)
    singleton_amount = sum(g['amount'] for g in groups.values() if g['count'] == 1)
    print('--- interpretation ---')
    print('rule=repeated merchant groups are review candidates for reusable categorization rules')
    print('rule=normalization is audit-only and must not mutate labels or categories')
    print('rule=singletons remain transaction-level review candidates unless a deterministic merchant rule already exists')
    print(
        f'summary repeated_rows={repeated_rows} repeated_amount={euros(repeated_amount)} '
        f'singleton_rows={singleton_rows} singleton_amount={euros(singleton_amount)} '
        f'integrity={conn.execute("PRAGMA integrity_check").fetchone()[0]}'
    )
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
