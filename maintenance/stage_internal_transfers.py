#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.imports import normalize_label
from app.transfer_intelligence import detect_internal_transfers, ensure_transfer_schema


def main() -> int:
    parser = argparse.ArgumentParser(description='Detect and review internal transfers in a Flow staging DB')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=100)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to run transfer staging directly on production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    ensure_transfer_schema(conn)
    result = detect_internal_transfers(conn)
    conn.commit()

    account_count = conn.execute('SELECT COUNT(*) FROM accounts WHERE is_active=1').fetchone()[0]
    confirmed_rows = conn.execute('SELECT COUNT(*) FROM transactions WHERE is_internal_transfer=1').fetchone()[0]
    identity_rows = conn.execute("SELECT COUNT(*) FROM internal_transfer_candidates WHERE status='confirmed_identity'").fetchone()[0]
    all_review_rows = conn.execute('''
        SELECT c.id,t.booking_date,t.amount_cents,t.label,a.name account_name,c.reason,c.confidence
        FROM internal_transfer_candidates c
        JOIN transactions t ON t.id=c.transaction_id
        JOIN accounts a ON a.id=t.account_id
        WHERE c.status='review'
        ORDER BY t.booking_date,t.id
    ''').fetchall()
    review_rows = all_review_rows[:max(1, args.limit)]

    grouped: dict[str, dict] = {}
    for row in all_review_rows:
        key = normalize_label(row['label'])
        item = grouped.setdefault(key, {
            'label': key,
            'count': 0,
            'total_cents': 0,
            'min_cents': None,
            'max_cents': None,
            'first_date': row['booking_date'],
            'last_date': row['booking_date'],
        })
        amount = int(row['amount_cents'])
        item['count'] += 1
        item['total_cents'] += amount
        item['min_cents'] = amount if item['min_cents'] is None else min(item['min_cents'], amount)
        item['max_cents'] = amount if item['max_cents'] is None else max(item['max_cents'], amount)
        item['first_date'] = min(item['first_date'], row['booking_date'])
        item['last_date'] = max(item['last_date'], row['booking_date'])

    print(f'db={db_path}')
    print(f'active_accounts={account_count}')
    print(
        f'confirmed_pairs={result["confirmed_pairs"]} '
        f'confirmed_identity={identity_rows} '
        f'confirmed_transaction_rows={confirmed_rows}'
    )
    print(f'review_candidates={len(all_review_rows)} review_groups={len(grouped)}')
    print('--- review groups ---')
    for item in sorted(grouped.values(), key=lambda x: (-x['count'], x['label'])):
        print(
            f"group count={item['count']} first={item['first_date']} last={item['last_date']} "
            f"total={item['total_cents']/100:.2f} min={item['min_cents']/100:.2f} max={item['max_cents']/100:.2f} "
            f"label={item['label']}"
        )

    if review_rows:
        print('--- review rows ---')
    for row in review_rows:
        amount = row['amount_cents'] / 100
        print(
            f"review date={row['booking_date']} amount={amount:.2f} account={row['account_name']} "
            f"label={row['label']} confidence={row['confidence']:.2f}"
        )
    print('summary ' + ' '.join([
        f'active_accounts={account_count}',
        f'confirmed_pairs={result["confirmed_pairs"]}',
        f'confirmed_identity={identity_rows}',
        f'confirmed_transaction_rows={confirmed_rows}',
        f'review_candidates={len(all_review_rows)}',
        f'review_groups={len(grouped)}',
    ]))
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
