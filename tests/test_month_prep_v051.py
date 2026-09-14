import sqlite3
from datetime import date

from app.month_prep import build_month_preparation, next_month_key


def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    CREATE TABLE accounts(id INTEGER PRIMARY KEY,name TEXT,is_active INTEGER DEFAULT 1);
    CREATE TABLE recurring_transactions(id INTEGER PRIMARY KEY,account_id INTEGER,label TEXT,amount_cents INTEGER,day_of_month INTEGER,category TEXT,kind TEXT,certainty TEXT,tolerance_cents INTEGER,is_active INTEGER DEFAULT 1);
    CREATE TABLE planned_transactions(id INTEGER PRIMARY KEY,account_id INTEGER,due_date TEXT,amount_cents INTEGER,label TEXT,kind TEXT,certainty TEXT,status TEXT DEFAULT 'planned');
    CREATE TABLE budgets(id INTEGER PRIMARY KEY,month TEXT,status TEXT);
    CREATE TABLE budget_lines(id INTEGER PRIMARY KEY,budget_id INTEGER,category TEXT,planned_cents INTEGER,mode TEXT);
    CREATE TABLE transactions(id INTEGER PRIMARY KEY,account_id INTEGER,booking_date TEXT,amount_cents INTEGER,label TEXT,category TEXT,transaction_type TEXT,is_internal_transfer INTEGER DEFAULT 0);
    CREATE TABLE financial_rules(id INTEGER PRIMARY KEY,rule_type TEXT,name TEXT,value_text TEXT,value_cents INTEGER,start_date TEXT,end_date TEXT,status TEXT,source_key TEXT);
    ''')
    conn.execute("INSERT INTO accounts VALUES(1,'Courant',1)")
    return conn


def test_next_month_handles_year_change():
    assert next_month_key(date(2026, 12, 20)) == '2027-01'


def test_month_is_secured_when_structural_items_are_ready():
    conn = db()
    conn.execute("INSERT INTO recurring_transactions VALUES(1,1,'Salaire',310400,29,'Salaire','income','expected',0,1)")
    conn.execute("INSERT INTO recurring_transactions VALUES(2,1,'Crédit',-20720,10,'Crédits','commitment','expected',0,1)")
    conn.execute("INSERT INTO budgets VALUES(1,'2026-10','ready')")
    conn.execute("INSERT INTO budget_lines VALUES(1,1,'Crédits',20720,'reserved')")
    result = build_month_preparation(conn, '2026-10', date(2026, 9, 8))
    assert result['status'] == 'secured'
    assert result['structural_income']['amount_cents'] == 310400
    assert result['recurring_outflows_cents'] == 20720


def test_month_requires_salary_and_validated_charges():
    conn = db()
    result = build_month_preparation(conn, '2026-10', date(2026, 9, 8))
    assert result['status'] == 'attention'
    assert len(result['blockers']) == 2
