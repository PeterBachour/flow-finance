#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Backfill missing bank-statement balance snapshots from validated import metadata.'
    )
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
        imports_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='imports'"
        ).fetchone()
        history_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='account_balance_history'"
        ).fetchone()
        if not imports_table or not history_table:
            print('error=required schema missing')
            return 3

        rows = conn.execute(
            '''SELECT i.id,i.account_id,i.filename,i.period_end,i.closing_balance_cents,
                      COALESCE(i.quality_status,'unverified') AS quality_status
               FROM imports i
               WHERE i.status IN ('completed','duplicate')
                 AND i.period_end IS NOT NULL
                 AND i.closing_balance_cents IS NOT NULL
               ORDER BY i.period_end,i.id'''
        ).fetchall()

        selected = []
        for row in rows:
            existing = conn.execute(
                '''SELECT id FROM account_balance_history
                   WHERE account_id=?
                     AND balance_date=?
                     AND source_type='bank_statement'
                   LIMIT 1''',
                (row['account_id'], row['period_end']),
            ).fetchone()
            if existing:
                continue
            selected.append(row)

        print(f'mode={"apply" if args.apply else "dry-run"}')
        print('--- missing statement balance snapshots ---')
        for row in selected:
            print(
                f"import_id={row['id']} account_id={row['account_id']} date={row['period_end']} "
                f"balance={int(row['closing_balance_cents'])/100:.2f} quality={row['quality_status']} "
                f"filename={row['filename']}"
            )

        if args.apply:
            for row in selected:
                source_key = f"statement-balance:import:{row['id']}:{row['period_end']}:{row['closing_balance_cents']}"
                conn.execute(
                    '''INSERT INTO account_balance_history(
                           account_id,balance_cents,balance_date,status,
                           source_type,source_id,source_date,source_status,confidence,source_key
                       ) VALUES(?,?,?,?,?,?,?,?,?,?)
                       ON CONFLICT(source_key) DO NOTHING''',
                    (
                        row['account_id'],
                        row['closing_balance_cents'],
                        row['period_end'],
                        'confirmed',
                        'bank_statement',
                        f"import:{row['id']}",
                        row['period_end'],
                        'confirmed',
                        1.0 if row['quality_status'] == 'ok' else 0.9,
                        source_key,
                    ),
                )
            conn.commit()

        created = len(selected) if args.apply else 0
        print('--- summary ---')
        print(f'candidates={len(selected)} created={created}')
        print(f'status={"applied" if args.apply else "ready"} integrity=ok')
        return 0
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
