#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.bulk_import import ensure_bulk_schema, parse_payroll
from app.data_intelligence import ensure_intelligence_schema, detect_recurring_transactions
from app.import_identity import ensure_identity_schema, import_rows_occurrence_safe
from app.imports import ensure_import_schema, parse_statement, statement_metadata
from app.notion_dataset import SOURCE_REVISION
from app.payroll_reconciliation import credible_employer_candidates, period_has_bank_coverage, reconcile_payroll
from app.transfer_intelligence import detect_internal_transfers, ensure_transfer_schema


def _pdfs(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.glob('*.pdf'))
    return [path] if path.suffix.lower() == '.pdf' else []


def _init_db(path: Path) -> None:
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


def _integrity(conn: sqlite3.Connection) -> None:
    result = conn.execute('PRAGMA integrity_check').fetchone()[0]
    if result != 'ok':
        raise RuntimeError(f'integrity_check failed: {result}')


def main() -> int:
    parser = argparse.ArgumentParser(description='Build a persistent clean Flow staging DB from bank statements and payroll PDFs')
    parser.add_argument('--statements', type=Path, required=True)
    parser.add_argument('--payroll', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=PROJECT_ROOT / 'data' / 'flow-staging.db')
    parser.add_argument('--overwrite', action='store_true')
    args = parser.parse_args()

    statements = _pdfs(args.statements)
    payroll_files = _pdfs(args.payroll)
    if not statements:
        print('error=no bank statement PDFs found')
        return 2
    if not payroll_files:
        print('error=no payroll PDFs found')
        return 3

    output = args.output.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if output == production:
        print('error=refusing to build directly over production flow.db')
        return 4
    if output.exists():
        if not args.overwrite:
            print(f'error=output already exists: {output}; use --overwrite')
            return 5
        output.unlink()
    output.parent.mkdir(parents=True, exist_ok=True)

    _init_db(output)
    conn = sqlite3.connect(output)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    ensure_import_schema(conn)
    ensure_identity_schema(conn)
    ensure_bulk_schema(conn)
    ensure_intelligence_schema(conn)
    ensure_transfer_schema(conn)

    account_id = conn.execute(
        "INSERT INTO accounts(name,kind,is_active,include_in_wealth,include_in_liquidity,include_in_safe_to_spend,source_type,source_status) "
        "VALUES('LCL Compte courant','checking',1,1,1,1,'bank_rebuild','confirmed')"
    ).lastrowid

    imported_transactions = 0
    statement_errors = 0
    latest_closing_date = None
    latest_closing_balance = None
    coverage_start = None
    coverage_end = None

    for path in statements:
        try:
            data = path.read_bytes()
            source_type, bank, rows = parse_statement(path.name, data)
            metadata = statement_metadata(data, bank, rows)
            cur = conn.execute(
                '''INSERT INTO imports(account_id,filename,source_type,bank,status,total_rows,period_start,period_end,
                   opening_balance_cents,closing_balance_cents,debit_total_cents,credit_total_cents)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                (account_id, path.name, source_type, bank, 'processing', len(rows), metadata.get('period_start'),
                 metadata.get('period_end'), metadata.get('opening_balance_cents'), metadata.get('closing_balance_cents'),
                 metadata.get('debit_total_cents') or 0, metadata.get('credit_total_cents') or 0),
            )
            import_id = cur.lastrowid
            result = import_rows_occurrence_safe(conn, import_id, account_id, rows)
            conn.execute(
                "UPDATE imports SET status='completed',imported_rows=?,duplicate_rows=?,review_rows=? WHERE id=?",
                (result['imported'], result['duplicates'], result['review'], import_id),
            )
            conn.execute(
                '''UPDATE transactions
                   SET source_type='bank_statement',
                       source_id=?,
                       source_date=booking_date,
                       source_status='confirmed',
                       confidence=1.0,
                       source_key=(SELECT 'bank:' || m.fingerprint
                                   FROM transaction_import_meta m
                                   WHERE m.transaction_id=transactions.id),
                       imported_at=CURRENT_TIMESTAMP
                   WHERE id IN (SELECT transaction_id FROM transaction_import_meta WHERE import_id=?)''',
                (path.name, import_id),
            )
            imported_transactions += result['imported']
            period_start = metadata.get('period_start')
            period_end = metadata.get('period_end')
            if period_start and (coverage_start is None or period_start < coverage_start):
                coverage_start = period_start
            if period_end and (coverage_end is None or period_end > coverage_end):
                coverage_end = period_end
            closing = metadata.get('closing_balance_cents')
            if period_end and closing is not None and (latest_closing_date is None or period_end > latest_closing_date):
                latest_closing_date = period_end
                latest_closing_balance = int(closing)
        except Exception as exc:
            statement_errors += 1
            print(f'statement_error={path.name}: {exc}')

    payroll_errors = 0
    for path in payroll_files:
        try:
            data = path.read_bytes()
            payload, warnings = parse_payroll(path.name, data)
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

    if latest_closing_date is not None and latest_closing_balance is not None:
        conn.execute(
            'UPDATE accounts SET current_balance_cents=?,balance_as_of=? WHERE id=?',
            (latest_closing_balance, latest_closing_date, account_id),
        )
        conn.execute(
            '''INSERT INTO account_balance_history(account_id,balance_cents,balance_date,status,source_type,source_status,confidence,source_key)
               VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source_key) DO NOTHING''',
            (account_id, latest_closing_balance, latest_closing_date, 'confirmed', 'bank_rebuild', 'confirmed', 1.0,
             f'bank-rebuild:closing:{latest_closing_date}'),
        )

    conn.execute(
        "INSERT INTO settings(key,value) VALUES('notion_source_revision',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (SOURCE_REVISION,),
    )
    conn.execute(
        "INSERT INTO settings(key,value) VALUES('rebuild_source','bank_payroll_clean') ON CONFLICT(key) DO UPDATE SET value=excluded.value"
    )

    # Order matters: payroll truth first, then owner/internal transfers, then
    # recurring detection so transfers cannot be mistaken for commitments.
    payroll_result = reconcile_payroll(conn)
    transfer_result = detect_internal_transfers(conn)
    recurring_result = detect_recurring_transactions(conn, account_id)
    conn.commit()
    _integrity(conn)

    tx_count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    payroll_count = conn.execute('SELECT COUNT(*) FROM payroll_records').fetchone()[0]
    match_count = conn.execute('SELECT COUNT(*) FROM payroll_transaction_matches').fetchone()[0]
    internal_count = conn.execute('SELECT COUNT(*) FROM transactions WHERE is_internal_transfer=1').fetchone()[0]
    identity_count = conn.execute("SELECT COUNT(*) FROM internal_transfer_candidates WHERE status='confirmed_identity'").fetchone()[0]
    transfer_review_count = conn.execute("SELECT COUNT(*) FROM internal_transfer_candidates WHERE status='review'").fetchone()[0]
    active_recurring = conn.execute("SELECT COUNT(*) FROM recurring_transactions WHERE is_active=1 AND detection_status='accepted'").fetchone()[0]
    review_recurring = conn.execute("SELECT COUNT(*) FROM recurring_transactions WHERE is_active=0 AND detection_status IN ('review_date','review_amount')").fetchone()[0]
    source_types = conn.execute("SELECT source_type,COUNT(*) c FROM transactions GROUP BY source_type ORDER BY source_type").fetchall()

    matched_payroll_ids = {
        row['payroll_record_id'] for row in conn.execute('SELECT payroll_record_id FROM payroll_transaction_matches').fetchall()
    }
    unresolved_no_bank_coverage = 0
    salary_not_observed = 0
    unresolved_with_employer_candidate = 0
    for row in conn.execute('SELECT id,period,employer FROM payroll_records ORDER BY period,id').fetchall():
        if row['id'] in matched_payroll_ids:
            continue
        if not period_has_bank_coverage(row['period'], coverage_start, coverage_end):
            unresolved_no_bank_coverage += 1
        elif credible_employer_candidates(conn, row['period'], row['employer']):
            unresolved_with_employer_candidate += 1
        else:
            salary_not_observed += 1

    print(f'output={output}')
    print(f'account_balance={latest_closing_balance} balance_as_of={latest_closing_date}')
    print(f'bank_coverage={coverage_start}->{coverage_end}')
    print('transaction_sources=' + str({row['source_type']: row['c'] for row in source_types}))
    print(
        f'summary statements={len(statements)} statement_errors={statement_errors} transactions={tx_count} '
        f'payroll_files={len(payroll_files)} payroll_records={payroll_count} payroll_errors={payroll_errors} '
        f'payroll_matched={match_count} unresolved_no_bank_coverage={unresolved_no_bank_coverage} '
        f'salary_not_observed_on_account={salary_not_observed} '
        f'unresolved_with_employer_candidate={unresolved_with_employer_candidate} '
        f'internal_transfer_rows={internal_count} internal_identity={identity_count} '
        f'internal_pairs={transfer_result["confirmed_pairs"]} internal_review={transfer_review_count} '
        f'recurring_accepted={active_recurring} recurring_review={review_recurring} '
        f'recurring_detected={recurring_result["detected"]} integrity=ok notion_bootstrap_revision={SOURCE_REVISION}'
    )
    conn.close()

    return 1 if statement_errors or payroll_errors or unresolved_with_employer_candidate or transfer_review_count else 0


if __name__ == '__main__':
    raise SystemExit(main())
