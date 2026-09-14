#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

GOAL_KEY = 'goal:lcl-vie'
CYCLE = '2026-09'
ALLOCATED_ON = '2026-08-29'
AMOUNT_CENTS = 10000
NOTE = 'cycle=2026-09; validated documentary Boursobank funding attributable to LCL Vie; September contribution already funded before cycle start'


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply validated current-cycle goal allocations to a Flow staging DB')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--cycle', default=CYCLE)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to modify production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3
    if args.cycle != CYCLE:
        print(f'error=this validated allocation set is only defined for cycle {CYCLE}')
        return 4

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    goal = conn.execute(
        'SELECT id,name,monthly_contribution_cents FROM financial_goals WHERE source_key=? AND is_active=1',
        (GOAL_KEY,),
    ).fetchone()
    if not goal:
        print(f'error=active goal not found: {GOAL_KEY}')
        return 5

    existing = conn.execute(
        'SELECT id,amount_cents FROM goal_allocations WHERE goal_id=? AND allocated_on=? AND note=? LIMIT 1',
        (goal['id'], ALLOCATED_ON, NOTE),
    ).fetchone()
    if existing:
        conn.execute(
            'UPDATE goal_allocations SET amount_cents=? WHERE id=?',
            (AMOUNT_CENTS, existing['id']),
        )
        action = 'updated'
    else:
        conn.execute(
            '''INSERT INTO goal_allocations(goal_id,account_id,amount_cents,allocated_on,note)
               VALUES(?,NULL,?,?,?)''',
            (goal['id'], AMOUNT_CENTS, ALLOCATED_ON, NOTE),
        )
        action = 'created'

    conn.commit()
    explicit = conn.execute(
        '''SELECT COALESCE(SUM(amount_cents),0)
           FROM goal_allocations
           WHERE goal_id=? AND note LIKE ?''',
        (goal['id'], f'cycle={args.cycle};%'),
    ).fetchone()[0]
    monthly = int(goal['monthly_contribution_cents'] or 0)
    remaining = max(0, monthly - int(explicit or 0))
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]

    print(
        f"allocation action={action} cycle={args.cycle} goal={goal['name']} amount={AMOUNT_CENTS/100:.2f} "
        f"allocated_on={ALLOCATED_ON} source=documentary_validated"
    )
    print(
        f"goal_status monthly_target={monthly/100:.2f} explicit_funded={int(explicit)/100:.2f} "
        f"remaining={remaining/100:.2f}"
    )
    print('unallocated_cycle_savings_reference=620.00 treatment=evidence_only reason=LDDS+LivretA not mapped to a specific goal')
    print(f'summary integrity={integrity} safe_to_spend_impact=0.00 reason=allocation already funded before current balance snapshot')
    conn.close()
    return 0 if integrity == 'ok' and remaining == 0 else 6


if __name__ == '__main__':
    raise SystemExit(main())
