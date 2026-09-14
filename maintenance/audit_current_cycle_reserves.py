#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.notion_dataset import CONFIRMED_TRANSACTIONS, GOALS, RULES


def active_in_month(rule: dict, month_start: date, month_end: date) -> bool:
    if rule.get('status') != 'active':
        return False
    start = date.fromisoformat(rule['start']) if rule.get('start') else date.min
    end = date.fromisoformat(rule['end']) if rule.get('end') else date.max
    return start <= month_end and end >= month_start


def euros(cents: int | None) -> str:
    return f'{(cents or 0)/100:.2f}'


def main() -> int:
    parser = argparse.ArgumentParser(description='Audit current-cycle reserves, savings and goals without mutating Flow')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', type=date.fromisoformat, required=True)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to audit production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    month_start = args.as_of.replace(day=1)
    if month_start.month == 12:
        month_end = date(month_start.year, 12, 31)
    else:
        month_end = date(month_start.year, month_start.month + 1, 1).fromordinal(
            date(month_start.year, month_start.month + 1, 1).toordinal() - 1
        )

    print(f'db={db_path} as_of={args.as_of.isoformat()} cycle_month={month_start:%Y-%m}')
    print('--- source-confirmed cycle funding ---')
    source_funding = [
        tx for tx in CONFIRMED_TRANSACTIONS
        if tx.get('date', '')[:7] in {month_start.isoformat()[:7], (month_start.fromordinal(month_start.toordinal()-1)).isoformat()[:7]}
        and tx.get('amount', 0) < 0
        and ('préparation septembre' in tx.get('label', '').lower() or 'circuit' in tx.get('label', '').lower())
    ]
    for tx in source_funding:
        print(f"funding date={tx['date']} amount={abs(tx['amount']):.2f} label={tx['label']} destination={tx.get('destination')}")

    funded_keys = set()
    for tx in source_funding:
        label = tx.get('label', '').lower()
        if 'ldds' in label:
            funded_keys.add('rule:ldds-sep-dec')
        if 'livret a' in label:
            funded_keys.add('rule:livret-sep-dec')
        if 'boursobank' in label:
            funded_keys.add('rule:boursobank-circuit')

    print('--- active cycle rules ---')
    reserve_total = 0
    informational_total = 0
    for rule in RULES:
        if not active_in_month(rule, month_start, month_end):
            continue
        rtype = rule.get('type')
        cents = int(rule.get('cents') or 0)
        key = rule.get('key')
        if rtype == 'minimum_reserve':
            treatment = 'reserve_floor'
            reserve_total += cents
        elif rtype in {'monthly_saving', 'monthly_expense'}:
            if key in funded_keys:
                treatment = 'already_funded'
            else:
                treatment = 'reserve_candidate'
                reserve_total += cents
        elif rtype in {'spending_budget', 'spending_cap'}:
            treatment = 'budget_information'
            informational_total += cents
        else:
            treatment = 'information'
        print(
            f"rule treatment={treatment} key={key} type={rtype} amount={euros(cents)} "
            f"name={rule.get('name')} comment={rule.get('comment')}"
        )

    print('--- active goals ---')
    monthly_goal_total = 0
    for goal in GOALS:
        if not goal.get('active'):
            continue
        monthly = int(round(float(goal.get('monthly') or 0) * 100))
        monthly_goal_total += monthly
        print(
            f"goal key={goal.get('key')} monthly={euros(monthly)} current={float(goal.get('current') or 0):.2f} "
            f"target={float(goal.get('target') or 0):.2f} target_date={goal.get('date')} name={goal.get('name')}"
        )

    print(
        f'summary rule_reserve_candidates={euros(reserve_total)} monthly_goals_raw={euros(monthly_goal_total)} '
        f'budget_information={euros(informational_total)} warning=goals_not_auto_added_due_to_overlap_risk '
        f'integrity={conn.execute("PRAGMA integrity_check").fetchone()[0]}'
    )
    conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
