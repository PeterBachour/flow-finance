#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def parse_euros(value: str) -> int:
    normalized = value.strip().replace(' ', '').replace(',', '.')
    return int(round(float(normalized) * 100))


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply a confirmed manual balance snapshot to a Flow staging DB')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--balance', required=True, help='Balance in EUR, e.g. 953.25')
    parser.add_argument('--date', required=True, dest='balance_date', help='Snapshot date YYYY-MM-DD')
    parser.add_argument('--account-id', type=int)
    parser.add_argument('--note', default='user-confirmed manual checking balance')
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to modify production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    try:
        snapshot_date = date.fromisoformat(args.balance_date)
        balance_cents = parse_euros(args.balance)
    except Exception as exc:
        print(f'error=invalid snapshot input: {exc}')
        return 4

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    if args.account_id is not None:
        account = conn.execute('SELECT * FROM accounts WHERE id=? AND is_active=1', (args.account_id,)).fetchone()
    else:
        accounts = conn.execute('''
            SELECT * FROM accounts
            WHERE is_active=1 AND include_in_safe_to_spend=1
            ORDER BY id
        ''').fetchall()
        if len(accounts) != 1:
            print(f'error=expected exactly one safe-to-spend account, found {len(accounts)}; pass --account-id')
            conn.close()
            return 5
        account = accounts[0]

    if account is None:
        print('error=account not found')
        conn.close()
        return 6

    previous_balance = int(account['current_balance_cents'] or 0)
    previous_date = account['balance_as_of']
    source_key = f'manual-balance:{account["id"]}:{snapshot_date.isoformat()}'

    conn.execute('''
        INSERT INTO account_balance_history(
            account_id,balance_cents,balance_date,status,source_type,source_id,source_date,
            source_status,confidence,source_key
        ) VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_key) DO UPDATE SET
            balance_cents=excluded.balance_cents,
            balance_date=excluded.balance_date,
            status=excluded.status,
            source_type=excluded.source_type,
            source_id=excluded.source_id,
            source_date=excluded.source_date,
            source_status=excluded.source_status,
            confidence=excluded.confidence
    ''', (
        account['id'], balance_cents, snapshot_date.isoformat(), 'confirmed', 'manual_balance',
        args.note, snapshot_date.isoformat(), 'confirmed', 1.0, source_key,
    ))

    current_as_of = date.fromisoformat(previous_date) if previous_date else None
    if current_as_of is None or snapshot_date >= current_as_of:
        conn.execute(
            '''UPDATE accounts
               SET current_balance_cents=?,balance_as_of=?,source_status='confirmed',confidence=1.0
               WHERE id=?''',
            (balance_cents, snapshot_date.isoformat(), account['id']),
        )

    conn.commit()
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    updated = conn.execute('SELECT current_balance_cents,balance_as_of FROM accounts WHERE id=?', (account['id'],)).fetchone()

    print(f'db={db_path}')
    print(
        f"account_id={account['id']} account={account['name']} previous_balance={previous_balance/100:.2f} "
        f"previous_as_of={previous_date}"
    )
    print(
        f"snapshot balance={balance_cents/100:.2f} date={snapshot_date.isoformat()} "
        f"source_type=manual_balance confidence=1.0"
    )
    print(
        f"current_balance={int(updated['current_balance_cents'])/100:.2f} "
        f"balance_as_of={updated['balance_as_of']} integrity={integrity}"
    )
    conn.close()
    return 0 if integrity == 'ok' else 1


if __name__ == '__main__':
    raise SystemExit(main())
