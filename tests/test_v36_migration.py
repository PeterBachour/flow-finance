import sqlite3

from app.v36_migrations import ensure_v36_schema


def test_v36_schema_is_idempotent_and_preserves_existing_rows():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE accounts(id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE transactions(id INTEGER PRIMARY KEY, account_id INTEGER, booking_date TEXT, amount_cents INTEGER, label TEXT);
        CREATE TABLE planned_transactions(id INTEGER PRIMARY KEY, account_id INTEGER, due_date TEXT, amount_cents INTEGER, label TEXT, status TEXT);
        INSERT INTO transactions(id,account_id,booking_date,amount_cents,label) VALUES(1,1,'2026-09-01',-1000,'Test');
        """
    )
    ensure_v36_schema(conn)
    ensure_v36_schema(conn)
    assert conn.execute('SELECT COUNT(*) n FROM transactions').fetchone()['n'] == 1
    names = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert {'financial_routine_runs','planned_transaction_matches','decision_inbox_status'} <= names
