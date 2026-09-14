#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.bulk_import import ensure_bulk_schema, parse_payroll
from app.data_intelligence import ensure_intelligence_schema, reconcile_payroll
from app.imports import ensure_import_schema, parse_statement, statement_metadata
from app.import_identity import ensure_identity_schema, import_rows_occurrence_safe


def _fresh_db(path: Path) -> None:
    old = os.environ.get('FLOW_DB_PATH')
    os.environ['FLOW_DB_PATH'] = str(path)
    try:
        if 'app.db' in sys.modules:
            del sys.modules['app.db']
        from app import db
        db.DB_PATH = path
        db.init_db()
    finally:
        if old is None:
            os.environ.pop('FLOW_DB_PATH', None)
        else:
            os.environ['FLOW_DB_PATH'] = old


def _pdfs(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.glob('*.pdf'))
    return [path] if path.suffix.lower() == '.pdf' else []


def _period_window(period: str) -> tuple[date, date] | None:
    try:
        year, month = (int(v) for v in period.split('-', 1))
    except Exception:
        return None
    start = date(year, month, 1) - timedelta(days=7)
    if month == 12:
        end = date(year + 1, 1, 8)
    else:
        end = date(year, month + 1, 8)
    return start, end


def _candidate_rows(conn: sqlite3.Connection, period: str, net_paid_cents: int) -> list[sqlite3.Row]:
    window = _period_window(period)
    if not window:
        return []
    start, end = window
    return conn.execute(
        '''SELECT id,booking_date,amount_cents,label,ABS(amount_cents-?) amount_diff
           FROM transactions
           WHERE amount_cents>0 AND is_internal_transfer=0
             AND booking_date>=? AND booking_date<?
           ORDER BY amount_diff,booking_date,id LIMIT 3''',
        (net_paid_cents, start.isoformat(), end.isoformat()),
    ).fetchall()


def _employer_candidates(conn: sqlite3.Connection, period: str) -> list[sqlite3.Row]:
    """Return only employer transactions credible as the salary for the period.

    A small reimbursement carrying the employer name must not turn a genuinely
    missing salary into an ambiguous payroll match. Salary classification uses
    the actual month through the first seven days of the following month and a
    conservative 1,000 EUR minimum amount.
    """
    try:
        year, month = (int(v) for v in period.split('-', 1))
    except Exception:
        return []
    start = date(year, month, 1)
    if month == 12:
        end = date(year + 1, 1, 8)
    else:
        end = date(year, month + 1, 8)
    return conn.execute(
        '''SELECT id,booking_date,amount_cents,label
           FROM transactions
           WHERE amount_cents>=100000 AND is_internal_transfer=0
             AND booking_date>=? AND booking_date<?
             AND (
               UPPER(label) LIKE '%KARDHAM%'
               OR UPPER(label) LIKE '%SALAIRE%'
               OR UPPER(label) LIKE '%PAYROLL%'
             )
           ORDER BY booking_date,id''',
        (start.isoformat(), end.isoformat()),
    ).fetchall()


def _period_in_bank_coverage(period: str | None, coverage_start: str | None, coverage_end: str | None) -> bool:
    if not period or not coverage_start or not coverage_end:
        return False
    try:
        year, month = (int(v) for v in period.split('-', 1))
        month_start = date(year, month, 1)
        month_end = date(year, month, 28)
        while True:
            candidate = month_end + timedelta(days=1)
            if candidate.month != month:
                break
            month_end = candidate
        cov_start = date.fromisoformat(coverage_start)
        cov_end = date.fromisoformat(coverage_end)
    except Exception:
        return False
    return month_end >= cov_start and month_start <= cov_end


def main() -> int:
    parser = argparse.ArgumentParser(description='Stage bank statements and payroll PDFs in an isolated Flow database')
    parser.add_argument('--statements', type=Path, required=True)
    parser.add_argument('--payroll', type=Path, required=True)
    parser.add_argument('--diagnostic', action='store_true', help='Print parsed payroll values and nearest bank candidates')
    parser.add_argument('--unresolved-only', action='store_true', help='With --diagnostic, print only payroll records not reconciled')
    args = parser.parse_args()

    statements = _pdfs(args.statements)
    payroll_files = _pdfs(args.payroll)
    if not statements:
        print('error=no bank statement PDFs found')
        return 2
    if not payroll_files:
        print('error=no payroll PDFs found')
        return 3

    with tempfile.TemporaryDirectory(prefix='flow-payroll-stage-') as tmp:
        db_path = Path(tmp) / 'flow.db'
        _fresh_db(db_path)
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        conn.execute('PRAGMA foreign_keys = ON')
        ensure_import_schema(conn)
        ensure_identity_schema(conn)
        ensure_bulk_schema(conn)
        ensure_intelligence_schema(conn)

        account_id = conn.execute(
            "INSERT INTO accounts(name,kind,is_active,include_in_safe_to_spend) VALUES('LCL staging','checking',1,1)"
        ).lastrowid

        imported_transactions = 0
        statement_errors = 0
        statement_periods: list[tuple[str | None, str | None]] = []
        for path in statements:
            try:
                data = path.read_bytes()
                source_type, bank, rows = parse_statement(path.name, data)
                metadata = statement_metadata(data, bank, rows)
                statement_periods.append((metadata.get('period_start'), metadata.get('period_end')))
                cur = conn.execute(
                    '''INSERT INTO imports(account_id,filename,source_type,bank,status,total_rows,period_start,period_end,
                       opening_balance_cents,closing_balance_cents,debit_total_cents,credit_total_cents)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                    (account_id, path.name, source_type, bank, 'processing', len(rows), metadata.get('period_start'),
                     metadata.get('period_end'), metadata.get('opening_balance_cents'), metadata.get('closing_balance_cents'),
                     metadata.get('debit_total_cents') or 0, metadata.get('credit_total_cents') or 0),
                )
                result = import_rows_occurrence_safe(conn, cur.lastrowid, account_id, rows)
                conn.execute("UPDATE imports SET status='completed',imported_rows=?,duplicate_rows=?,review_rows=? WHERE id=?",
                             (result['imported'], result['duplicates'], result['review'], cur.lastrowid))
                imported_transactions += result['imported']
            except Exception as exc:
                statement_errors += 1
                print(f'statement_warning={path.name}: {exc}')

        coverage_starts = [p[0] for p in statement_periods if p[0]]
        coverage_ends = [p[1] for p in statement_periods if p[1]]
        coverage_start = min(coverage_starts) if coverage_starts else None
        coverage_end = max(coverage_ends) if coverage_ends else None

        payroll_errors = 0
        parsed_payrolls: list[tuple[str, dict]] = []
        for path in payroll_files:
            try:
                data = path.read_bytes()
                payload, warnings = parse_payroll(path.name, data)
                parsed_payrolls.append((path.name, payload))
                if warnings:
                    print(f"payroll_warning={path.name}: {' | '.join(warnings)}")
                if not payload.get('period') or payload.get('net_paid_cents') is None:
                    payroll_errors += 1
                    continue
                source_hash = hashlib.sha256(data).hexdigest()
                conn.execute('''INSERT OR IGNORE INTO payroll_records(
                    period,employer,gross_cents,net_before_tax_cents,net_paid_cents,taxable_net_cents,
                    withholding_tax_cents,withholding_rate,reimbursements_cents,bonuses_cents,source_filename,source_hash
                ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (
                    payload.get('period'), payload.get('employer'), payload.get('gross_cents'), payload.get('net_before_tax_cents'),
                    payload.get('net_paid_cents'), payload.get('taxable_net_cents'), payload.get('withholding_tax_cents'),
                    payload.get('withholding_rate'), payload.get('reimbursements_cents'), payload.get('bonuses_cents'),
                    path.name, source_hash,
                ))
            except Exception as exc:
                payroll_errors += 1
                print(f'payroll_error={path.name}: {exc}')

        conn.commit()
        match_result = reconcile_payroll(conn)
        conn.commit()

        matched_files = {
            row['source_filename']
            for row in conn.execute('''
                SELECT p.source_filename
                FROM payroll_transaction_matches m
                JOIN payroll_records p ON p.id=m.payroll_record_id
            ''').fetchall()
        }

        unresolved_no_bank_coverage = 0
        salary_not_observed_on_account = 0
        unresolved_with_employer_candidate = 0
        unresolved_periods_no_coverage: list[str] = []
        unresolved_periods_no_salary: list[str] = []
        unresolved_periods_with_candidate: list[str] = []

        for filename, payload in parsed_payrolls:
            if filename in matched_files:
                continue
            period = payload.get('period')
            if not _period_in_bank_coverage(period, coverage_start, coverage_end):
                unresolved_no_bank_coverage += 1
                unresolved_periods_no_coverage.append(str(period))
                continue
            employer_rows = _employer_candidates(conn, period) if period else []
            if not employer_rows:
                salary_not_observed_on_account += 1
                unresolved_periods_no_salary.append(str(period))
            else:
                unresolved_with_employer_candidate += 1
                unresolved_periods_with_candidate.append(str(period))

        if args.diagnostic:
            print(f'bank_coverage={coverage_start}->{coverage_end}')
            print('--- payroll diagnostics ---')
            for filename, payload in parsed_payrolls:
                if args.unresolved_only and filename in matched_files:
                    continue
                period = payload.get('period')
                net_paid = payload.get('net_paid_cents')
                if not _period_in_bank_coverage(period, coverage_start, coverage_end):
                    coverage = 'no_bank_coverage'
                elif not _employer_candidates(conn, period):
                    coverage = 'salary_not_observed_on_account'
                else:
                    coverage = 'in_coverage_with_employer_candidate'
                print(
                    f"payroll={filename} period={period} coverage={coverage} employer={payload.get('employer')} "
                    f"gross={payload.get('gross_cents')} net_before_tax={payload.get('net_before_tax_cents')} "
                    f"net_paid={net_paid} taxable={payload.get('taxable_net_cents')} withholding={payload.get('withholding_tax_cents')}"
                )
                if period and net_paid is not None and coverage != 'no_bank_coverage':
                    candidates = _candidate_rows(conn, period, net_paid)
                    for idx, row in enumerate(candidates, start=1):
                        print(
                            f"  candidate{idx}={row['booking_date']} amount={row['amount_cents']} "
                            f"diff={row['amount_diff']} label={row['label']}"
                        )
                    employer_rows = _employer_candidates(conn, period)
                    for idx, row in enumerate(employer_rows, start=1):
                        print(
                            f"  employer_candidate{idx}={row['booking_date']} amount={row['amount_cents']} label={row['label']}"
                        )

        matches = conn.execute('''
            SELECT p.period,p.net_paid_cents,p.source_filename,t.booking_date,t.amount_cents,t.label,m.confidence
            FROM payroll_transaction_matches m
            JOIN payroll_records p ON p.id=m.payroll_record_id
            JOIN transactions t ON t.id=m.transaction_id
            ORDER BY p.period
        ''').fetchall()
        for row in matches:
            print(
                f"match={row['period']} payroll={row['net_paid_cents']} tx={row['booking_date']}:{row['amount_cents']} "
                f"confidence={row['confidence']} label={row['label']}"
            )

        duplicate_groups = conn.execute('''
            SELECT booking_date,amount_cents,UPPER(TRIM(label)) normalized_label,COUNT(*) c
            FROM transactions
            WHERE amount_cents>0
            GROUP BY booking_date,amount_cents,UPPER(TRIM(label))
            HAVING c>1
            ORDER BY booking_date,amount_cents
        ''').fetchall()
        if duplicate_groups:
            print('--- repeated income signatures (informational) ---')
            for row in duplicate_groups:
                print(
                    f"repeated_income={row['booking_date']} amount={row['amount_cents']} "
                    f"count={row['c']} label={row['normalized_label']}"
                )

        payroll_count = conn.execute('SELECT COUNT(*) FROM payroll_records').fetchone()[0]
        salary_tx_count = conn.execute("SELECT COUNT(*) FROM transactions WHERE amount_cents>0 AND (UPPER(label) LIKE '%KARDHAM%' OR category='Salaire')").fetchone()[0]

        print(
            f'summary statements={len(statements)} statement_errors={statement_errors} transactions={imported_transactions} '
            f'bank_coverage={coverage_start}->{coverage_end} payroll_files={len(payroll_files)} payroll_records={payroll_count} '
            f'payroll_errors={payroll_errors} matched={match_result["matched"]} unresolved_total={match_result["unresolved"]} '
            f'unresolved_no_bank_coverage={unresolved_no_bank_coverage} '
            f'salary_not_observed_on_account={salary_not_observed_on_account} '
            f'unresolved_with_employer_candidate={unresolved_with_employer_candidate} '
            f'salary_transactions={salary_tx_count} repeated_income_groups={len(duplicate_groups)}'
        )
        print(f'unresolved_no_bank_coverage_periods={sorted(unresolved_periods_no_coverage)}')
        print(f'salary_not_observed_periods={sorted(unresolved_periods_no_salary)}')
        print(f'unresolved_with_employer_candidate_periods={sorted(unresolved_periods_with_candidate)}')
        conn.close()

        if statement_errors or payroll_errors or unresolved_with_employer_candidate:
            return 1
        return 0


if __name__ == '__main__':
    raise SystemExit(main())
