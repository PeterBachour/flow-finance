#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.payroll_reconciliation import (
    budget_month_for_salary_date,
    credible_employer_candidates,
    period_has_bank_coverage,
    reconcile_payroll,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Reconcile payslips to same-period salary credits and report the next Flow budget month'
    )
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

    coverage = conn.execute('SELECT MIN(period_start) start,MAX(period_end) end FROM imports').fetchone()
    coverage_start = coverage['start']
    coverage_end = coverage['end']

    old_tx_ids = [r['transaction_id'] for r in conn.execute('SELECT transaction_id FROM payroll_transaction_matches').fetchall()]
    conn.execute('DELETE FROM payroll_transaction_matches')
    if old_tx_ids:
        placeholders = ','.join('?' for _ in old_tx_ids)
        conn.execute(
            f"UPDATE transactions SET category=NULL,transaction_type=CASE WHEN amount_cents>0 THEN 'income' ELSE transaction_type END "
            f"WHERE id IN ({placeholders}) AND category='Salaire'",
            tuple(old_tx_ids),
        )

    reconcile_payroll(conn)
    conn.commit()

    matches = conn.execute('''
        SELECT p.period,p.net_paid_cents,p.source_filename,t.booking_date,t.amount_cents,t.label,m.confidence,m.match_reason
        FROM payroll_transaction_matches m
        JOIN payroll_records p ON p.id=m.payroll_record_id
        JOIN transactions t ON t.id=m.transaction_id
        ORDER BY p.period,p.id
    ''').fetchall()
    for row in matches:
        print(
            f"match={row['period']} payroll={row['net_paid_cents']} tx={row['booking_date']}:{row['amount_cents']} "
            f"budget_month={budget_month_for_salary_date(row['booking_date'])} "
            f"confidence={row['confidence']} label={row['label']}"
        )

    matched_ids = {r['payroll_record_id'] for r in conn.execute('SELECT payroll_record_id FROM payroll_transaction_matches').fetchall()}
    no_coverage = []
    no_salary = []
    with_candidate = []
    for payroll in conn.execute('SELECT id,period,employer,net_paid_cents,source_filename FROM payroll_records ORDER BY period,id').fetchall():
        if payroll['id'] in matched_ids:
            continue
        period = payroll['period']
        if not period_has_bank_coverage(period, coverage_start, coverage_end):
            no_coverage.append(period)
            continue
        candidates = credible_employer_candidates(conn, period, payroll['employer'])
        if candidates:
            with_candidate.append(period)
            print(
                f"unresolved_candidate period={period} payroll={payroll['net_paid_cents']} file={payroll['source_filename']} "
                + ' candidates=' + repr([(r['booking_date'], r['amount_cents'], r['label']) for r in candidates])
            )
        else:
            no_salary.append(period)

    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    print(
        f"summary matched={len(matches)} unresolved_total={len(no_coverage)+len(no_salary)+len(with_candidate)} "
        f"unresolved_no_bank_coverage={len(no_coverage)} salary_not_observed_on_account={len(no_salary)} "
        f"unresolved_with_employer_candidate={len(with_candidate)} integrity={integrity}"
    )
    print(f'unresolved_no_bank_coverage_periods={no_coverage}')
    print(f'salary_not_observed_periods={no_salary}')
    print(f'unresolved_with_employer_candidate_periods={with_candidate}')
    conn.close()
    return 1 if integrity != 'ok' or with_candidate else 0


if __name__ == '__main__':
    raise SystemExit(main())
