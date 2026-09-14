import sqlite3

from app.v2_migrations import ensure_v2_schema


def test_v2_migration_is_additive_and_preserves_existing_rows():
    db = sqlite3.connect(':memory:')
    db.executescript('''
    CREATE TABLE accounts(id INTEGER PRIMARY KEY,name TEXT,kind TEXT,current_balance_cents INTEGER);
    CREATE TABLE transactions(id INTEGER PRIMARY KEY,account_id INTEGER,booking_date TEXT,amount_cents INTEGER,label TEXT,category TEXT,transaction_type TEXT,is_internal_transfer INTEGER);
    CREATE TABLE recurring_transactions(id INTEGER PRIMARY KEY,account_id INTEGER,label TEXT,amount_cents INTEGER,day_of_month INTEGER,category TEXT,kind TEXT,certainty TEXT,is_active INTEGER);
    CREATE TABLE financial_goals(id INTEGER PRIMARY KEY,name TEXT,target_cents INTEGER,is_active INTEGER);
    INSERT INTO accounts VALUES(1,'Compte courant','checking',95325);
    INSERT INTO transactions VALUES(1,1,'2026-09-01',-1000,'Test','Courses','expense',0);
    ''')
    ensure_v2_schema(db)
    ensure_v2_schema(db)
    assert db.execute('SELECT current_balance_cents FROM accounts WHERE id=1').fetchone()[0] == 95325
    assert db.execute('SELECT label FROM transactions WHERE id=1').fetchone()[0] == 'Test'
    columns = {row[1] for row in db.execute('PRAGMA table_info(transactions)')}
    assert {'user_label','exclude_from_analytics','is_exceptional','transfer_pair_id'} <= columns
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'paychecks','transaction_tags','data_quality_issues','forecast_snapshots','insights'} <= tables
