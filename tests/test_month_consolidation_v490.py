from pathlib import Path
import sqlite3

from app.v49_routes import _month_status, ensure_v49_schema


def _conn():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
      CREATE TABLE accounts(id INTEGER PRIMARY KEY,name TEXT,kind TEXT,current_balance_cents INTEGER,balance_as_of TEXT,is_active INTEGER DEFAULT 1);
      CREATE TABLE imports(
        id INTEGER PRIMARY KEY,account_id INTEGER,filename TEXT,source_type TEXT,bank TEXT,status TEXT,
        total_rows INTEGER DEFAULT 0,imported_rows INTEGER DEFAULT 0,duplicate_rows INTEGER DEFAULT 0,review_rows INTEGER DEFAULT 0,
        error_message TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,period_start TEXT,period_end TEXT,
        opening_balance_cents INTEGER,closing_balance_cents INTEGER,debit_total_cents INTEGER DEFAULT 0,credit_total_cents INTEGER DEFAULT 0,
        auto_classified_rows INTEGER DEFAULT 0,quality_status TEXT DEFAULT 'unverified',quality_message TEXT,
        statement_fingerprint TEXT,duplicate_of_import_id INTEGER
      );
      CREATE TABLE transaction_import_meta(transaction_id INTEGER PRIMARY KEY,import_id INTEGER,fingerprint TEXT UNIQUE,normalized_label TEXT,review_status TEXT,raw_payload TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
      CREATE TABLE transactions(id INTEGER PRIMARY KEY,account_id INTEGER,booking_date TEXT,amount_cents INTEGER,label TEXT,category TEXT,transaction_type TEXT,is_internal_transfer INTEGER DEFAULT 0);
      INSERT INTO accounts VALUES(1,'LCL','checking',96325,'2026-08-31',1);
    ''')
    ensure_v49_schema(conn)
    return conn


def test_month_without_statement_is_not_consolidated():
    conn=_conn()
    status=_month_status(conn,'2026-08')
    assert status['status']=='statement_missing'
    assert status['closures']==[]


def test_valid_statement_makes_month_ready():
    conn=_conn()
    conn.execute("INSERT INTO imports(id,account_id,filename,source_type,status,period_start,period_end,closing_balance_cents,quality_status,review_rows) VALUES(1,1,'aout.pdf','pdf','completed','2026-08-01','2026-08-31',96325,'ok',0)")
    status=_month_status(conn,'2026-08')
    assert status['status']=='ready'
    assert status['candidates'][0]['closable'] is True


def test_review_rows_block_month_close():
    conn=_conn()
    conn.execute("INSERT INTO imports(id,account_id,filename,source_type,status,period_start,period_end,closing_balance_cents,quality_status,review_rows) VALUES(1,1,'aout.pdf','pdf','completed','2026-08-01','2026-08-31',96325,'ok',2)")
    status=_month_status(conn,'2026-08')
    assert status['status']=='blocked'
    assert 'review_rows' in status['candidates'][0]['blockers']


def test_month_consolidation_ui_requires_explicit_confirmation():
    js=Path('app/static/month-consolidation-ui.js').read_text(encoding='utf-8')
    assert "confirmation:'CLOTURER'" in js
    assert "confirm('Confirmer la clôture" in js
    assert 'Flow n’invente aucune opération' in js
