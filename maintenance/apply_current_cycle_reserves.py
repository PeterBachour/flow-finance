#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

RESERVES = [
    {
        'key': 'reserve:safety-minimum',
        'label': 'Réserve minimale compte courant',
        'amount_cents': 20000,
        'kind': 'safety_reserve',
        'reason': 'active rule rule:safety-reserve',
    },
    {
        'key': 'reserve:tax-2026-09',
        'label': 'Solde impôt septembre 2026',
        'amount_cents': 11300,
        'kind': 'planned_commitment',
        'reason': 'active rule rule:tax-sep-nov; September not marked as paid',
    },
    {
        'key': 'reserve:apple-2026-09',
        'label': 'Apple septembre 2026',
        'amount_cents': 1398,
        'kind': 'planned_commitment',
        'reason': 'active monthly rule; not covered by validated recurring profile',
    },
    {
        'key': 'reserve:velib-2026-09',
        'label': 'Vélib septembre 2026',
        'amount_cents': 930,
        'kind': 'planned_commitment',
        'reason': 'active monthly rule; not covered by validated recurring profile',
    },
]


def ensure_table(conn: sqlite3.Connection) -> None:
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS cycle_reserves (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        reserve_key TEXT NOT NULL UNIQUE,
        cycle_month TEXT NOT NULL,
        label TEXT NOT NULL,
        amount_cents INTEGER NOT NULL,
        kind TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'active',
        source_type TEXT NOT NULL DEFAULT 'manual_reconciled',
        source_status TEXT NOT NULL DEFAULT 'confirmed',
        reason TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_cycle_reserves_month_status
      ON cycle_reserves(cycle_month,status);
    ''')


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply reconciled current-cycle reserves to a Flow staging DB')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--cycle', default='2026-09')
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
    ensure_table(conn)

    # Only this reconciled set is active for the selected cycle. Old rows from
    # prior staging experiments are retained but deactivated for auditability.
    conn.execute("UPDATE cycle_reserves SET status='inactive', updated_at=CURRENT_TIMESTAMP WHERE cycle_month=?", (args.cycle,))

    total = 0
    for item in RESERVES:
        key = f"{item['key']}:{args.cycle}"
        conn.execute('''
            INSERT INTO cycle_reserves(
                reserve_key,cycle_month,label,amount_cents,kind,status,source_type,source_status,reason
            ) VALUES(?,?,?,?,?,'active','manual_reconciled','confirmed',?)
            ON CONFLICT(reserve_key) DO UPDATE SET
                cycle_month=excluded.cycle_month,
                label=excluded.label,
                amount_cents=excluded.amount_cents,
                kind=excluded.kind,
                status='active',
                source_type='manual_reconciled',
                source_status='confirmed',
                reason=excluded.reason,
                updated_at=CURRENT_TIMESTAMP
        ''', (key, args.cycle, item['label'], item['amount_cents'], item['kind'], item['reason']))
        total += item['amount_cents']
        print(
            f"reserve cycle={args.cycle} kind={item['kind']} amount={item['amount_cents']/100:.2f} "
            f"label={item['label']} reason={item['reason']}"
        )

    conn.commit()
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    active_total = conn.execute(
        "SELECT COALESCE(SUM(amount_cents),0) FROM cycle_reserves WHERE cycle_month=? AND status='active'",
        (args.cycle,),
    ).fetchone()[0]
    count = conn.execute(
        "SELECT COUNT(*) FROM cycle_reserves WHERE cycle_month=? AND status='active'",
        (args.cycle,),
    ).fetchone()[0]
    print(
        f'summary cycle={args.cycle} active_reserves={count} reserve_now={active_total/100:.2f} '
        f'integrity={integrity}'
    )
    conn.close()
    return 0 if integrity == 'ok' and active_total == total else 5


if __name__ == '__main__':
    raise SystemExit(main())
