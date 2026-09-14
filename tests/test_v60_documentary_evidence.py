import json
import sqlite3
from datetime import date

from app.documentary_evidence import build_documentary_evidence, transaction_evidence


def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    CREATE TABLE imports(
        id INTEGER PRIMARY KEY, account_id INTEGER, filename TEXT, source_type TEXT, bank TEXT,
        status TEXT, quality_status TEXT, quality_message TEXT, period_start TEXT, period_end TEXT,
        opening_balance_cents INTEGER, closing_balance_cents INTEGER, debit_total_cents INTEGER,
        credit_total_cents INTEGER, total_rows INTEGER, imported_rows INTEGER, duplicate_rows INTEGER,
        review_rows INTEGER, statement_fingerprint TEXT, created_at TEXT
    );
    CREATE TABLE payroll_records(
        id INTEGER PRIMARY KEY, period TEXT, employer TEXT, gross_cents INTEGER,
        net_before_tax_cents INTEGER, net_paid_cents INTEGER, taxable_net_cents INTEGER,
        withholding_tax_cents INTEGER, reimbursements_cents INTEGER, bonuses_cents INTEGER,
        source_filename TEXT, source_hash TEXT, source_status TEXT, created_at TEXT
    );
    CREATE TABLE transactions(
        id INTEGER PRIMARY KEY, account_id INTEGER, booking_date TEXT, amount_cents INTEGER,
        label TEXT, category TEXT, transaction_type TEXT, source_type TEXT, source_id TEXT,
        source_url TEXT, source_date TEXT, source_status TEXT, confidence REAL,
        source_key TEXT, imported_at TEXT
    );
    CREATE TABLE transaction_import_meta(
        transaction_id INTEGER PRIMARY KEY, import_id INTEGER, fingerprint TEXT,
        row_signature TEXT, occurrence_index INTEGER, normalized_label TEXT,
        review_status TEXT, raw_payload TEXT
    );
    ''')
    return conn


def seed(conn):
    conn.execute(
        '''INSERT INTO imports VALUES(1,1,'june.pdf','pdf','LCL','completed','verified','OK',
           '2026-06-01','2026-06-30',10000,12000,1000,3000,2,1,0,0,'statement-sha','2026-07-01')'''
    )
    conn.execute(
        '''INSERT INTO payroll_records VALUES(1,'2026-06','Kardham Digital',400000,320000,300000,
           330000,20000,0,0,'pay-june.pdf','pay-sha','confirmed','2026-07-01')'''
    )
    conn.execute(
        '''INSERT INTO transactions VALUES(10,1,'2026-06-12',-1000,'CB TEST','Loisirs','expense',
           NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)'''
    )
    conn.execute(
        '''INSERT INTO transaction_import_meta VALUES(10,1,'row-fingerprint','row-signature',1,
           'CB TEST','accepted',?)''',
        (json.dumps({'line': 'CB TEST 10,00'}),),
    )


def test_documentary_evidence_builds_month_matrix_and_proofs():
    conn = db()
    seed(conn)
    result = build_documentary_evidence(conn, as_of=date(2026, 6, 30), months=1)

    assert result['summary']['documents'] == 2
    assert result['summary']['verified_statements'] == 1
    assert result['summary']['verified_payrolls'] == 1
    assert result['summary']['linked_transactions'] == 1
    assert result['summary']['transaction_evidence_pct'] == 100.0
    assert result['months'][0]['status'] == 'complete'
    assert result['documents']['statements'][0]['proof']['source_identity'] is True
    assert result['read_only'] is True


def test_transaction_evidence_reconstructs_source_without_mutation():
    conn = db()
    seed(conn)
    before = conn.total_changes

    result = transaction_evidence(conn, 10)

    assert result['source']['filename'] == 'june.pdf'
    assert result['source']['document_identity'] == 'statement-sha'
    assert result['source']['transaction_identity'] == 'row-fingerprint'
    assert result['quality']['has_document_proof'] is True
    assert result['raw'] == {'line': 'CB TEST 10,00'}
    assert result['read_only'] is True
    assert conn.total_changes == before


def test_transaction_evidence_returns_none_for_unknown_transaction():
    conn = db()
    assert transaction_evidence(conn, 999) is None
