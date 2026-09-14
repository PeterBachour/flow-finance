#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def table_exists(conn: sqlite3.Connection, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone())


def euros(cents: int | None) -> str:
    return f"{int(cents or 0) / 100:.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Audit active financial goals against existing allocations and current-cycle saving transfers.'
    )
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
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
    cycle = as_of.strftime('%Y-%m')
    cycle_start = f'{cycle}-01'

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    goals = conn.execute('''
        SELECT id,name,target_cents,current_cents,monthly_contribution_cents,target_date,priority,source_key
        FROM financial_goals
        WHERE is_active=1
        ORDER BY priority ASC, COALESCE(target_date,'9999-12-31'), id
    ''').fetchall()

    print(f'db={db_path}')
    print(f'as_of={as_of.isoformat()} cycle={cycle} active_goals={len(goals)}')
    print('--- active goals ---')

    raw_monthly = 0
    allocated_this_cycle = 0
    remaining_after_explicit_allocations = 0
    explicit_allocation_rows = 0

    cycle_note_prefix = f'cycle={cycle};%'

    for goal in goals:
        monthly = int(goal['monthly_contribution_cents'] or 0)
        raw_monthly += monthly
        allocations = conn.execute('''
            SELECT ga.amount_cents,ga.allocated_on,ga.note,a.name AS account_name
            FROM goal_allocations ga
            LEFT JOIN accounts a ON a.id=ga.account_id
            WHERE ga.goal_id=?
              AND (
                    (ga.allocated_on>=? AND ga.allocated_on<=?)
                    OR ga.note LIKE ?
                  )
            ORDER BY ga.allocated_on,ga.id
        ''', (goal['id'], cycle_start, as_of.isoformat(), cycle_note_prefix)).fetchall()
        funded = sum(max(0, int(row['amount_cents'] or 0)) for row in allocations)
        allocated_this_cycle += funded
        explicit_allocation_rows += len(allocations)
        remaining = max(0, monthly - funded)
        remaining_after_explicit_allocations += remaining
        status = 'funded' if monthly > 0 and remaining == 0 else ('partially_funded' if funded > 0 else 'unfunded')
        if monthly == 0:
            status = 'no_monthly_target'
        print(
            f"goal key={goal['source_key']} monthly={euros(monthly)} explicit_funded={euros(funded)} "
            f"remaining={euros(remaining)} status={status} priority={goal['priority']} "
            f"current={euros(goal['current_cents'])} target={euros(goal['target_cents'])} "
            f"target_date={goal['target_date']} name={goal['name']}"
        )
        for row in allocations:
            treatment = 'prefunded_cycle' if row['allocated_on'] < cycle_start and (row['note'] or '').startswith(f'cycle={cycle};') else 'current_cycle'
            print(
                f"  allocation date={row['allocated_on']} amount={euros(row['amount_cents'])} "
                f"account={row['account_name']} treatment={treatment} note={row['note']}"
            )

    print('--- current-cycle saving / investment transfer evidence ---')
    saving_rows = conn.execute('''
        SELECT t.booking_date,t.amount_cents,t.label,t.category,t.destination_account_id,
               da.name AS destination_name,t.source_type,t.source_key
        FROM transactions t
        LEFT JOIN accounts da ON da.id=t.destination_account_id
        WHERE t.booking_date>=?
          AND t.booking_date<=?
          AND t.amount_cents<0
          AND (
              t.category IN ('Épargne','Investissement','Transfert interne')
              OR t.is_internal_transfer=1
          )
        ORDER BY t.booking_date,t.id
    ''', (cycle_start, as_of.isoformat())).fetchall()

    transfer_total = 0
    for row in saving_rows:
        amount = abs(int(row['amount_cents']))
        transfer_total += amount
        print(
            f"transfer date={row['booking_date']} amount={euros(amount)} label={row['label']} "
            f"category={row['category']} destination={row['destination_name']} "
            f"source={row['source_type']} source_key={row['source_key']}"
        )

    print('--- prior-cycle funding explicitly documented for this cycle ---')
    prior_rows = conn.execute('''
        SELECT t.booking_date,t.amount_cents,t.label,t.category,t.destination_account_id,
               da.name AS destination_name,t.source_type,t.source_key
        FROM transactions t
        LEFT JOIN accounts da ON da.id=t.destination_account_id
        WHERE t.booking_date>=date(?, '-10 days')
          AND t.booking_date<?
          AND t.amount_cents<0
          AND (
              lower(t.label) LIKE '%septembre%'
              OR lower(t.label) LIKE '%préparation septembre%'
          )
        ORDER BY t.booking_date,t.id
    ''', (cycle_start, cycle_start)).fetchall()

    prior_total = 0
    for row in prior_rows:
        amount = abs(int(row['amount_cents']))
        prior_total += amount
        print(
            f"prefunded date={row['booking_date']} amount={euros(amount)} label={row['label']} "
            f"destination={row['destination_name']} source={row['source_type']} source_key={row['source_key']}"
        )

    print('--- interpretation ---')
    print('rule=goal_allocations are authoritative explicit goal funding')
    print('rule=allocation note cycle=YYYY-MM may assign a prefunded allocation to that budget cycle even when allocated_on is before month start')
    print('rule=saving transfers without an explicit goal mapping remain evidence_only to avoid false attribution')
    print('rule=prior-cycle transfers labelled as preparation for this cycle are evidence_only until mapped to a goal')
    print(
        f'summary raw_monthly_goals={euros(raw_monthly)} explicit_goal_funding={euros(allocated_this_cycle)} '
        f'remaining_after_explicit_allocations={euros(remaining_after_explicit_allocations)} '
        f'explicit_allocation_rows={explicit_allocation_rows} current_cycle_transfer_evidence={euros(transfer_total)} '
        f'prior_cycle_prefunding_evidence={euros(prior_total)} '
        f'warning=do_not_apply_remaining_to_safe_to_spend_until_goal_mapping_is_validated '
        f'integrity={conn.execute("PRAGMA integrity_check").fetchone()[0]}'
    )

    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
