import sqlite3
from datetime import date
from pathlib import Path

from app.db import SCHEMA, _migrate_columns
from app.financial_integrity import build_financial_integrity
from app.imports import ensure_import_schema


def make_conn(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / 'integrity.db')
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    ensure_import_schema(conn)
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(recurring_transactions)').fetchall()}
    for name, sql_type in {
        'usual_day': 'INTEGER',
        'next_expected_date': 'TEXT',
        'last_seen_date': 'TEXT',
        "detection_status": "TEXT NOT NULL DEFAULT 'accepted'",
    }.items():
        if name not in columns:
            conn.execute(f'ALTER TABLE recurring_transactions ADD COLUMN {name} {sql_type}')
    return conn


def _insert_reconciled_statement(conn, account_id: int, *, quality_status='ok', review_rows=0):
    import_id = conn.execute('''
        INSERT INTO imports(
            account_id,filename,source_type,bank,status,total_rows,imported_rows,duplicate_rows,review_rows,
            period_start,period_end,opening_balance_cents,closing_balance_cents,debit_total_cents,credit_total_cents,quality_status
        ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    ''', (
        account_id,'statement.pdf','pdf','LCL','completed',2,2,0,review_rows,
        '2026-08-01','2026-08-31',100000,120000,10000,30000,quality_status
    )).lastrowid
    tx1 = conn.execute(
        "INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,source_type) VALUES(?,?,?,?,?,?)",
        (account_id,'2026-08-10',30000,'SALAIRE TEST','Salaire','bank_statement')
    ).lastrowid
    tx2 = conn.execute(
        "INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,source_type) VALUES(?,?,?,?,?,?)",
        (account_id,'2026-08-15',-10000,'ACHAT TEST','Alimentation','bank_statement')
    ).lastrowid
    for tx_id, fingerprint in ((tx1,'f1'),(tx2,'f2')):
        conn.execute(
            "INSERT INTO transaction_import_meta(transaction_id,import_id,fingerprint,normalized_label,review_status) VALUES(?,?,?,?,?)",
            (tx_id,import_id,fingerprint,'TEST','needs_review' if review_rows else 'accepted')
        )
    conn.execute('''
        INSERT INTO account_balance_history(
            account_id,balance_cents,balance_date,status,source_type,source_status,confidence,source_key
        ) VALUES(?,?,?,?,?,?,?,?)
    ''', (account_id,120000,'2026-08-31','confirmed','bank_statement','confirmed',1.0,'statement:aug'))
    return import_id


def test_statement_arithmetic_and_snapshot_are_reconciled(tmp_path: Path):
    conn = make_conn(tmp_path)
    account_id = conn.execute(
        "INSERT INTO accounts(name,current_balance_cents,balance_as_of,include_in_safe_to_spend) VALUES('LCL',120000,'2026-09-10',1)"
    ).lastrowid
    _insert_reconciled_statement(conn, account_id)

    result = build_financial_integrity(conn, as_of=date(2026,9,10), months=6)
    audit = result['statement_audit']
    assert audit['summary']['statement_count'] == 1
    assert audit['summary']['reconciled_count'] == 1
    assert audit['summary']['review_count'] == 0
    assert audit['summary']['warning_count'] == 0
    assert audit['statements'][0]['statement_arithmetic_difference_cents'] == 0
    assert audit['statements'][0]['ledger_difference_cents'] == 0
    assert audit['statements'][0]['balance_snapshot_present'] is True
    assert audit['statements'][0]['documentary_reconciled'] is True
    conn.close()


def test_reconciled_statement_can_still_need_analytical_review(tmp_path: Path):
    conn = make_conn(tmp_path)
    account_id = conn.execute(
        "INSERT INTO accounts(name,current_balance_cents,balance_as_of,include_in_safe_to_spend) VALUES('LCL',120000,'2026-09-10',1)"
    ).lastrowid
    _insert_reconciled_statement(conn, account_id, quality_status='unverified', review_rows=2)

    result = build_financial_integrity(conn, as_of=date(2026,9,10), months=6)
    audit = result['statement_audit']
    statement = audit['statements'][0]
    assert audit['summary']['reconciled_count'] == 1
    assert audit['summary']['review_count'] == 1
    assert audit['summary']['warning_count'] == 0
    assert statement['documentary_reconciled'] is True
    assert statement['integrity_status'] == 'reconciled_with_review'
    assert statement['hard_issues'] == []
    assert set(statement['review_issues']) == {'import_quality_not_verified', 'rows_need_review'}
    assert result['hard_issue_count'] == 0
    assert result['review_issue_count'] == 1
    assert result['status'] == 'review'
    conn.close()


def test_safe_to_spend_breakdown_is_reconstructable(tmp_path: Path):
    conn = make_conn(tmp_path)
    account_id = conn.execute(
        "INSERT INTO accounts(name,current_balance_cents,balance_as_of,include_in_safe_to_spend) VALUES('LCL',100000,'2026-09-10',1)"
    ).lastrowid
    conn.execute("UPDATE settings SET value='10000' WHERE key='safety_reserve_cents'")
    conn.execute(
        "INSERT INTO planned_transactions(account_id,due_date,amount_cents,label,kind,certainty,status) VALUES(?,?,?,?,?,?,?)",
        (account_id,'2026-09-20',-20000,'Facture','commitment','confirmed','planned')
    )

    result = build_financial_integrity(conn, as_of=date(2026,9,10), months=3)
    safe = result['safe_to_spend_breakdown']
    assert safe['arithmetic_consistent'] is True
    assert safe['calculated_safe_to_spend_cents'] == 70000
    assert safe['safe_to_spend_cents'] == 70000
    assert safe['reconstructed_safe_to_spend_cents'] == 70000
    conn.close()


def test_internal_transfers_are_not_consumption(tmp_path: Path):
    conn = make_conn(tmp_path)
    account_id = conn.execute("INSERT INTO accounts(name) VALUES('LCL')").lastrowid
    conn.execute(
        "INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer) VALUES(?,?,?,?,?,?,1)",
        (account_id,'2026-08-01',-140000,'VIR.PERMANENT Compte Joint','Transfert interne','transfer')
    )
    conn.execute(
        "INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer) VALUES(?,?,?,?,?,?,0)",
        (account_id,'2026-08-02',-5000,'CARREFOUR','Alimentation','expense')
    )

    result = build_financial_integrity(conn, as_of=date(2026,9,10), months=3)
    august = next(item for item in result['monthly_audit']['months'] if item['month']=='2026-08')
    assert august['internal_transfer_out_cents'] == 140000
    assert august['consumption_cents'] == 5000
    conn.close()
