#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit pre-existing internal-transfer flags in a Flow staging database')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--limit', type=int, default=200)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to audit/mutate production flow.db through staging maintenance')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    total = conn.execute('SELECT COUNT(*) FROM transactions WHERE is_internal_transfer=1').fetchone()[0]
    paired = conn.execute('''
        SELECT COUNT(DISTINCT transaction_id) FROM (
          SELECT debit_transaction_id transaction_id FROM internal_transfer_matches WHERE status='confirmed'
          UNION ALL
          SELECT credit_transaction_id transaction_id FROM internal_transfer_matches WHERE status='confirmed'
        )
    ''').fetchone()[0] if conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='internal_transfer_matches'").fetchone() else 0

    rows = conn.execute('''
        SELECT t.id,t.booking_date,t.amount_cents,t.label,t.category,t.transaction_type,
               CASE WHEN m.transaction_id IS NULL THEN 0 ELSE 1 END has_confirmed_pair
        FROM transactions t
        LEFT JOIN (
          SELECT debit_transaction_id transaction_id FROM internal_transfer_matches WHERE status='confirmed'
          UNION
          SELECT credit_transaction_id transaction_id FROM internal_transfer_matches WHERE status='confirmed'
        ) m ON m.transaction_id=t.id
        WHERE t.is_internal_transfer=1
        ORDER BY t.booking_date,t.id
        LIMIT ?
    ''', (max(1,args.limit),)).fetchall()

    by_category = conn.execute('''
        SELECT COALESCE(category,'<null>') category,COALESCE(transaction_type,'<null>') transaction_type,COUNT(*) c
        FROM transactions
        WHERE is_internal_transfer=1
        GROUP BY category,transaction_type
        ORDER BY c DESC,category
    ''').fetchall()

    print(f'db={db_path}')
    print(f'premarked_internal_rows={total} confirmed_pair_rows={paired} unpaired_premarked_rows={max(0,total-paired)}')
    print('--- breakdown ---')
    for row in by_category:
        print(f"group count={row['c']} category={row['category']} transaction_type={row['transaction_type']}")
    print('--- rows ---')
    for row in rows:
        print(
            f"flagged date={row['booking_date']} amount={row['amount_cents']/100:.2f} "
            f"paired={row['has_confirmed_pair']} category={row['category']} type={row['transaction_type']} label={row['label']}"
        )
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
