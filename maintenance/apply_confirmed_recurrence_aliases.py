#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.recurrence_aliases import apply_confirmed_recurrence_aliases


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply explicitly confirmed recurring aliases to a Flow staging database')
    parser.add_argument('--db', type=Path, required=True)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to modify production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    result = apply_confirmed_recurrence_aliases(conn)
    conn.commit()
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]

    rows = conn.execute('''
        SELECT label,amount_cents,last_seen_date,next_expected_date,occurrence_count,
               confidence,source_type,is_active,detection_status
        FROM recurring_transactions
        WHERE source_type='confirmed_alias'
        ORDER BY label
    ''').fetchall()
    for row in rows:
        print(
            f"alias label={row['label']} amount={abs(int(row['amount_cents']))/100:.2f} "
            f"last_seen={row['last_seen_date']} next_expected={row['next_expected_date']} "
            f"occurrences={row['occurrence_count']} confidence={row['confidence']} "
            f"is_active={row['is_active']} status={row['detection_status']}"
        )

    print(
        f"summary merged_profiles={result['merged_profiles']} "
        f"merged_occurrences={result['merged_occurrences']} "
        f"active_profiles={result['active_profiles']} "
        f"historical_profiles={result['historical_profiles']} "
        f"latest_transaction_date={result['latest_transaction_date']} integrity={integrity}"
    )
    conn.close()
    return 0 if integrity == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
