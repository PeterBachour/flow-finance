import sqlite3

from app.import_identity import (
    ensure_identity_schema,
    find_duplicate_statement,
    import_rows_occurrence_safe,
    statement_fingerprint,
)
from app.imports import ensure_import_schema


def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript("""
    PRAGMA foreign_keys=ON;
    CREATE TABLE accounts(id INTEGER PRIMARY KEY,name TEXT,is_active INTEGER DEFAULT 1);
    CREATE TABLE transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,account_id INTEGER,booking_date TEXT,amount_cents INTEGER,label TEXT,category TEXT,transaction_type TEXT,is_internal_transfer INTEGER DEFAULT 0);
    CREATE TABLE categorization_rules(id INTEGER PRIMARY KEY AUTOINCREMENT,pattern TEXT,category TEXT,transaction_type TEXT,priority INTEGER DEFAULT 100,is_active INTEGER DEFAULT 1);
    INSERT INTO accounts(id,name) VALUES(1,'Courant');
    """)
    ensure_import_schema(conn)
    ensure_identity_schema(conn)
    return conn


def make_import(conn, import_id=1, filename='statement.csv', statement_id=None, status='processing'):
    conn.execute(
        'INSERT INTO imports(id,account_id,filename,source_type,status,total_rows,statement_fingerprint) VALUES(?,?,?,?,?,?,?)',
        (import_id, 1, filename, 'csv', status, 2, statement_id),
    )


def test_two_identical_purchases_in_same_statement_are_preserved():
    conn = db()
    make_import(conn)
    rows = [
        {'booking_date':'2026-09-08','amount_cents':-1234,'label':'CB MONOPRIX','raw':{'line':1}},
        {'booking_date':'2026-09-08','amount_cents':-1234,'label':'CB MONOPRIX','raw':{'line':2}},
    ]
    result = import_rows_occurrence_safe(conn, 1, 1, rows)
    assert result['imported'] == 2
    assert result['duplicates'] == 0
    occurrences = [r['occurrence_index'] for r in conn.execute('SELECT occurrence_index FROM transaction_import_meta ORDER BY transaction_id').fetchall()]
    assert occurrences == [1, 2]


def test_one_existing_manual_row_consumes_only_one_occurrence():
    conn = db()
    make_import(conn)
    conn.execute("INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type) VALUES(1,'2026-09-08',-1234,'CB MONOPRIX','Alimentation','expense')")
    rows = [
        {'booking_date':'2026-09-08','amount_cents':-1234,'label':'CB MONOPRIX','raw':{'line':1}},
        {'booking_date':'2026-09-08','amount_cents':-1234,'label':'CB MONOPRIX','raw':{'line':2}},
    ]
    result = import_rows_occurrence_safe(conn, 1, 1, rows)
    assert result['duplicates'] == 1
    assert result['imported'] == 1
    assert conn.execute('SELECT COUNT(*) n FROM transactions').fetchone()['n'] == 2


def test_statement_identity_ignores_filename_and_detects_same_content():
    conn = db()
    rows = [
        {'booking_date':'2026-09-08','amount_cents':-1234,'label':'CB MONOPRIX','raw':{}},
        {'booking_date':'2026-09-09','amount_cents':310400,'label':'VIREMENT KARDHAM DIGITAL','raw':{}},
    ]
    metadata = {
        'period_start':'2026-09-08','period_end':'2026-09-09',
        'opening_balance_cents':100000,'closing_balance_cents':409166,
    }
    fingerprint = statement_fingerprint(1, 'LCL', metadata, rows)
    make_import(conn, 1, 'original.pdf', fingerprint, 'completed')
    duplicate = find_duplicate_statement(conn, 1, fingerprint)
    assert duplicate is not None
    assert duplicate['filename'] == 'original.pdf'


def test_statement_identity_changes_when_an_occurrence_is_added():
    rows = [{'booking_date':'2026-09-08','amount_cents':-1234,'label':'CB MONOPRIX','raw':{}}]
    metadata = {'period_start':'2026-09-08','period_end':'2026-09-08','opening_balance_cents':None,'closing_balance_cents':None}
    first = statement_fingerprint(1, 'LCL', metadata, rows)
    second = statement_fingerprint(1, 'LCL', metadata, rows + [dict(rows[0])])
    assert first != second
