#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def euros(cents: int) -> str:
    return f"{abs(int(cents))/100:.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit real transfer evidence that may fund current-cycle financial goals')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
    parser.add_argument('--lookback-days', type=int, default=20)
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
    start = as_of - timedelta(days=max(1, args.lookback_days))

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    print(f'db={db_path}')
    print(f'as_of={as_of.isoformat()} evidence_window={start.isoformat()}->{as_of.isoformat()}')

    goals = conn.execute('''
        SELECT id,name,source_key,monthly_contribution_cents,priority,target_date,current_cents,target_cents
        FROM financial_goals
        WHERE is_active=1
        ORDER BY priority,target_date,name
    ''').fetchall()
    print('--- active goals ---')
    for g in goals:
        print(
            f"goal id={g['id']} key={g['source_key']} monthly={euros(g['monthly_contribution_cents'] or 0)} "
            f"priority={g['priority']} target_date={g['target_date']} name={g['name']}"
        )

    rows = conn.execute('''
        SELECT t.id,t.booking_date,t.amount_cents,t.label,t.category,t.transaction_type,
               t.is_internal_transfer,t.destination_account_id,t.source_type,t.source_key,
               a.name AS source_account, da.name AS destination_account
        FROM transactions t
        LEFT JOIN accounts a ON a.id=t.account_id
        LEFT JOIN accounts da ON da.id=t.destination_account_id
        WHERE t.booking_date>=? AND t.booking_date<=? AND t.amount_cents<0
          AND (
              t.is_internal_transfer=1
              OR lower(COALESCE(t.category,'')) LIKE '%épargne%'
              OR lower(COALESCE(t.category,'')) LIKE '%invest%'
              OR lower(t.label) LIKE '%livret%'
              OR lower(t.label) LIKE '%ldds%'
              OR lower(t.label) LIKE '%bourso%'
              OR lower(t.label) LIKE '%predica%'
              OR lower(t.label) LIKE '%lcl vie%'
          )
        ORDER BY t.booking_date,t.id
    ''', (start.isoformat(), as_of.isoformat())).fetchall()

    print('--- bank transfer evidence ---')
    total = 0
    for r in rows:
        total += abs(int(r['amount_cents']))
        destination = r['destination_account'] or 'unknown'
        print(
            f"tx id={r['id']} date={r['booking_date']} amount={euros(r['amount_cents'])} "
            f"internal={r['is_internal_transfer']} source_account={r['source_account']} destination={destination} "
            f"category={r['category']} label={r['label']} source_type={r['source_type']} source_key={r['source_key']}"
        )

    documented = []
    if 'financial_rules' in {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}:
        documented = conn.execute('''
            SELECT source_key,rule_type,name,value_cents,start_date,end_date,comment
            FROM financial_rules
            WHERE status='active' AND (
                rule_type='monthly_saving'
                OR lower(name) LIKE '%ldds%'
                OR lower(name) LIKE '%livret%'
                OR lower(name) LIKE '%lcl vie%'
                OR lower(name) LIKE '%boursobank%'
            )
            ORDER BY source_key
        ''').fetchall()
    print('--- documentary saving rules ---')
    for r in documented:
        print(
            f"rule key={r['source_key']} type={r['rule_type']} amount={euros(r['value_cents'] or 0)} "
            f"start={r['start_date']} end={r['end_date']} name={r['name']} comment={r['comment']}"
        )

    print('--- mapping policy ---')
    print('rule=destination_account_or_explicit_label_is_evidence_not_goal_allocation')
    print('rule=do_not_map_ldds_or_livret_a_to_a_specific_goal_without_explicit_goal_decision')
    print('rule=boursobank_funding_can_only_cover_lcl_vie_goal_up_to_the_amount_explicitly attributable_to_lcl_vie')
    print('rule=goal_allocations_remain_the_only authoritative mapping used by the safe-to-spend goal layer')

    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    print(
        f'summary active_goals={len(goals)} evidence_rows={len(rows)} evidence_total={total/100:.2f} '
        f'documentary_saving_rules={len(documented)} integrity={integrity}'
    )
    conn.close()
    return 0 if integrity == 'ok' else 5


if __name__ == '__main__':
    raise SystemExit(main())
