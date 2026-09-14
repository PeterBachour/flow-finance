import sqlite3

from app.v22_migrations import ensure_v22_schema


def test_v22_migration_is_additive_and_idempotent():
    conn = sqlite3.connect(':memory:')
    conn.executescript(
        """
        CREATE TABLE accounts(id INTEGER PRIMARY KEY,name TEXT,kind TEXT,current_balance_cents INTEGER,include_in_wealth INTEGER DEFAULT 1);
        CREATE TABLE financial_goals(id INTEGER PRIMARY KEY,name TEXT,target_cents INTEGER,target_date TEXT,priority INTEGER,is_active INTEGER);
        INSERT INTO accounts(id,name,kind,current_balance_cents) VALUES(1,'Compte courant','checking',100000);
        INSERT INTO financial_goals(id,name,target_cents,priority,is_active) VALUES(1,'Sécurité',300000,100,1);
        """
    )
    ensure_v22_schema(conn)
    ensure_v22_schema(conn)
    assert conn.execute('SELECT name,current_balance_cents FROM accounts WHERE id=1').fetchone() == ('Compte courant', 100000)
    assert conn.execute('SELECT name,target_cents FROM financial_goals WHERE id=1').fetchone() == ('Sécurité', 300000)
    account_columns = {row[1] for row in conn.execute('PRAGMA table_info(accounts)')}
    goal_columns = {row[1] for row in conn.execute('PRAGMA table_info(financial_goals)')}
    assert {'bank','role'} <= account_columns
    assert {'goal_type','monthly_contribution_cents','current_cents'} <= goal_columns
    tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {'wealth_assets','wealth_asset_history'} <= tables
