#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.notion_import import RULES, CONFIRMED_TRANSACTIONS


def euro(cents: int) -> str:
    return f"{cents / 100:.2f}"


def in_force(rule: dict, as_of: date) -> bool:
    if rule.get('status') != 'active':
        return False
    start = rule.get('start')
    end = rule.get('end')
    if start and as_of < date.fromisoformat(start):
        return False
    if end and as_of > date.fromisoformat(end):
        return False
    return True


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().replace('É', 'E').replace('È', 'E').replace('À', 'A').split())


def main() -> int:
    parser = argparse.ArgumentParser(description='Reconcile current-cycle reserves against already-funded transfers and validated recurring commitments')
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True)
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
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    recurring = conn.execute('''
        SELECT label, merchant_key, amount_cents, category, is_active, detection_status, source_type
        FROM recurring_transactions
        WHERE is_active=1 AND detection_status='accepted'
    ''').fetchall()
    recurring_text = ' | '.join(
        normalize(f"{r['label']} {r['merchant_key']} {r['category']}") for r in recurring
    )

    # Confirmed transfers used to pre-fund the September cycle. These amounts have
    # already left the LCL current account and therefore must never be reserved a
    # second time from the current LCL balance.
    funded = [tx for tx in CONFIRMED_TRANSACTIONS if tx.get('status') == 'confirmed']
    funded_text = ' | '.join(normalize(f"{tx.get('label')} {tx.get('category')}") for tx in funded)

    reserve_total = 0
    informational_total = 0
    already_funded_total = 0
    overlap_total = 0

    print(f'db={db_path} as_of={as_of.isoformat()}')
    print('--- reconciled current-cycle rules ---')

    for rule in RULES:
        if not in_force(rule, as_of):
            continue
        cents = int(rule.get('cents') or 0)
        rtype = rule.get('type') or ''
        key = rule.get('key') or ''
        name = rule.get('name') or key
        comment = rule.get('comment') or ''
        name_norm = normalize(name)
        treatment = 'information_only'
        reason = 'not a cash reserve rule'

        if rtype == 'minimum_reserve':
            treatment = 'reserve_now'
            reason = 'minimum checking-account floor'
        elif rtype == 'spending_budget':
            treatment = 'budget_information'
            reason = 'spending budget is not an additional cash commitment'
            informational_total += cents
        elif key in {'rule:ldds-sep-dec', 'rule:livret-sep-dec'}:
            treatment = 'already_funded'
            reason = 'September transfer explicitly confirmed as already executed'
            already_funded_total += cents
        elif key in {'rule:boursobank-circuit', 'rule:lcl-vie-monthly', 'rule:insurance-monthly'}:
            treatment = 'already_funded'
            reason = 'September Boursobank funding already left LCL; downstream charges must not be reserved again from LCL'
            already_funded_total += cents
        elif key == 'rule:phone-monthly' or ('TELEPHONE' in name_norm and 'SFR' in recurring_text):
            treatment = 'covered_by_recurring'
            reason = 'covered by validated SFR mobile recurring commitment'
            overlap_total += cents
        elif rtype in {'monthly_expense', 'monthly_saving'}:
            treatment = 'reserve_now'
            reason = 'active monthly rule not evidenced as funded and not covered by validated recurrence'
        elif rtype in {'income_reference', 'income_allocation', 'account_routing', 'expense_treatment', 'debt'}:
            treatment = 'information_only'
            reason = 'semantic/routing rule, not an additional current-cycle reserve'

        if treatment == 'reserve_now':
            reserve_total += cents
        print(
            f"rule treatment={treatment} key={key} type={rtype} amount={euro(cents)} "
            f"name={name} reason={reason} comment={comment}"
        )

    print('--- active recurring commitments already handled upstream ---')
    for r in recurring:
        print(
            f"recurring label={r['label']} key={r['merchant_key']} amount={abs(int(r['amount_cents']))/100:.2f} "
            f"category={r['category']} source={r['source_type']}"
        )

    print('--- confirmed cycle funding evidence ---')
    for tx in funded:
        print(
            f"funded date={tx.get('date')} amount={abs(float(tx.get('amount') or 0)):.2f} "
            f"label={tx.get('label')} category={tx.get('category')}"
        )

    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    print(
        f"summary reserve_now={euro(reserve_total)} already_funded_reference={euro(already_funded_total)} "
        f"covered_by_recurring_reference={euro(overlap_total)} budget_information={euro(informational_total)} "
        f"integrity={integrity}"
    )
    conn.close()
    return 0 if integrity == 'ok' else 4


if __name__ == '__main__':
    raise SystemExit(main())
