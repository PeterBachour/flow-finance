import sqlite3

from app.recurring_detection import detect_recurring_suggestions, recurring_key


def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    CREATE TABLE accounts(id INTEGER PRIMARY KEY,name TEXT,is_active INTEGER DEFAULT 1);
    CREATE TABLE transactions(id INTEGER PRIMARY KEY,account_id INTEGER,booking_date TEXT,amount_cents INTEGER,label TEXT,category TEXT,transaction_type TEXT,is_internal_transfer INTEGER DEFAULT 0);
    CREATE TABLE recurring_transactions(id INTEGER PRIMARY KEY,account_id INTEGER,label TEXT,is_active INTEGER DEFAULT 1);
    INSERT INTO accounts(id,name) VALUES(1,'Courant');
    ''')
    return conn


def add(conn, day, amount, label='PRLV SEPA NETFLIX 1234567890'):
    conn.execute('INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type) VALUES(1,?,?,?,?,?)', (day, amount, label, 'Loisirs', 'expense'))


def test_recurring_key_removes_transaction_noise():
    assert recurring_key('PRLV SEPA NETFLIX 1234567890') == 'NETFLIX'


def test_three_months_generate_suggestion():
    conn = db()
    add(conn, '2026-04-12', -1399)
    add(conn, '2026-05-12', -1399)
    add(conn, '2026-06-13', -1399)
    rows = detect_recurring_suggestions(conn)
    assert len(rows) == 1
    assert rows[0]['amount_cents'] == -1399
    assert rows[0]['day_of_month'] == 12
    assert rows[0]['occurrences'] == 3


def test_two_months_are_not_enough():
    conn = db()
    add(conn, '2026-05-12', -1399)
    add(conn, '2026-06-12', -1399)
    assert detect_recurring_suggestions(conn) == []


def test_large_day_spread_is_rejected():
    conn = db()
    add(conn, '2026-04-01', -1000)
    add(conn, '2026-05-15', -1000)
    add(conn, '2026-06-28', -1000)
    assert detect_recurring_suggestions(conn) == []
