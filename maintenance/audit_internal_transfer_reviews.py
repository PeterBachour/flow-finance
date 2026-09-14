#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def euros(cents: int) -> str:
    return f'{cents / 100:.2f}'


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit unresolved internal-transfer review candidates in a Flow staging DB')
    parser.add_argument('--db', type=Path, required=True)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to audit production flow.db with staging tool')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute('''
        SELECT c.id AS candidate_id,c.reason,c.confidence,c.status,
               t.id AS transaction_id,t.booking_date,t.amount_cents,t.label,
               t.category,t.transaction_type,t.is_internal_transfer,t.source_id
        FROM internal_transfer_candidates c
        JOIN transactions t ON t.id=c.transaction_id
        WHERE c.status='review'
        ORDER BY t.booking_date,t.id
    ''').fetchall()

    print(f'db={db_path}')
    for row in rows:
        print(
            f"review candidate_id={row['candidate_id']} transaction_id={row['transaction_id']} "
            f"date={row['booking_date']} amount={euros(int(row['amount_cents']))} "
            f"label={row['label']} confidence={row['confidence']} reason={row['reason']} "
            f"category={row['category']} type={row['transaction_type']} source={row['source_id']}"
        )
    print(f'summary internal_review={len(rows)}')
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
