import sqlite3

from app.imports import ensure_import_schema, evaluate_import_quality, statement_metadata


def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE accounts(id INTEGER PRIMARY KEY, name TEXT, is_active INTEGER DEFAULT 1)')
    conn.execute("CREATE TABLE transactions(id INTEGER PRIMARY KEY, account_id INTEGER, booking_date TEXT, amount_cents INTEGER, label TEXT, category TEXT, transaction_type TEXT, is_internal_transfer INTEGER DEFAULT 0)")
    conn.execute('INSERT INTO accounts(id,name) VALUES(1,\'Compte\')')
    ensure_import_schema(conn)
    return conn


def test_csv_metadata_totals_and_period():
    rows=[
        {'booking_date':'2026-04-01','amount_cents':-1250,'label':'A'},
        {'booking_date':'2026-04-30','amount_cents':3000,'label':'B'},
    ]
    meta=statement_metadata(b'',None,rows)
    assert meta['period_start']=='2026-04-01'
    assert meta['period_end']=='2026-04-30'
    assert meta['debit_total_cents']==1250
    assert meta['credit_total_cents']==3000


def test_continuity_with_previous_statement_is_ok():
    conn=db()
    conn.execute("INSERT INTO imports(id,account_id,filename,source_type,status,total_rows,period_start,period_end,closing_balance_cents) VALUES(1,1,'apr.pdf','pdf','completed',1,'2026-04-01','2026-04-30',315774)")
    conn.execute("INSERT INTO imports(id,account_id,filename,source_type,status,total_rows,period_start,period_end) VALUES(2,1,'may.pdf','pdf','processing',1,'2026-05-01','2026-05-31')")
    meta={'period_start':'2026-05-01','period_end':'2026-05-31','opening_balance_cents':315774,'closing_balance_cents':325774,'debit_total_cents':0,'credit_total_cents':10000}
    quality=evaluate_import_quality(conn,1,2,meta,{'review':0})
    assert quality['status']=='ok'
    assert 'Continuité' in quality['message']


def test_balance_mismatch_is_warning():
    conn=db()
    conn.execute("INSERT INTO imports(id,account_id,filename,source_type,status,total_rows,period_start,period_end) VALUES(2,1,'may.pdf','pdf','processing',1,'2026-05-01','2026-05-31')")
    meta={'period_start':'2026-05-01','period_end':'2026-05-31','opening_balance_cents':10000,'closing_balance_cents':12000,'debit_total_cents':0,'credit_total_cents':1000}
    quality=evaluate_import_quality(conn,1,2,meta,{'review':0})
    assert quality['status']=='warning'
