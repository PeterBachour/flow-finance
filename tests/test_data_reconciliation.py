import sqlite3

from app.data_reconciliation import reconcile_account_balances


def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    CREATE TABLE accounts(
      id INTEGER PRIMARY KEY,name TEXT,current_balance_cents INTEGER,balance_as_of TEXT,is_active INTEGER DEFAULT 1
    );
    CREATE TABLE transactions(
      id INTEGER PRIMARY KEY,account_id INTEGER,booking_date TEXT,amount_cents INTEGER,status TEXT DEFAULT 'confirmed'
    );
    CREATE TABLE imports(
      id INTEGER PRIMARY KEY,account_id INTEGER,filename TEXT,status TEXT,period_end TEXT,
      closing_balance_cents INTEGER,quality_status TEXT
    );
    ''')
    return conn


def test_reconciles_from_verified_statement_and_post_statement_ledger():
    conn = db()
    conn.execute("INSERT INTO accounts VALUES(1,'Courant',105000,'2026-09-13',1)")
    conn.execute("INSERT INTO imports VALUES(1,1,'aout.pdf','completed','2026-08-31',100000,'verified')")
    conn.executemany(
        'INSERT INTO transactions(id,account_id,booking_date,amount_cents,status) VALUES(?,?,?,?,?)',
        [
            (1, 1, '2026-09-02', 10_000, 'confirmed'),
            (2, 1, '2026-09-05', -5_000, 'confirmed'),
            (3, 1, '2026-09-06', -99_999, 'pending'),
        ],
    )
    result = reconcile_account_balances(conn)
    account = result['accounts'][0]
    assert result['status'] == 'reconciled'
    assert account['ledger_delta_cents'] == 5_000
    assert account['expected_balance_cents'] == 105_000
    assert account['difference_cents'] == 0


def test_reports_mismatch_without_mutating_balance():
    conn = db()
    conn.execute("INSERT INTO accounts VALUES(1,'Courant',106000,'2026-09-13',1)")
    conn.execute("INSERT INTO imports VALUES(1,1,'aout.pdf','completed','2026-08-31',100000,'verified')")
    conn.execute("INSERT INTO transactions VALUES(1,1,'2026-09-02',5000,'confirmed')")
    result = reconcile_account_balances(conn)
    account = result['accounts'][0]
    assert result['status'] == 'mismatch'
    assert account['expected_balance_cents'] == 105_000
    assert account['difference_cents'] == 1_000
    assert conn.execute('SELECT current_balance_cents FROM accounts WHERE id=1').fetchone()[0] == 106_000


def test_requires_valid_balance_date_and_verified_statement():
    conn = db()
    conn.execute("INSERT INTO accounts VALUES(1,'Sans date',50000,NULL,1)")
    conn.execute("INSERT INTO accounts VALUES(2,'Sans relevé',40000,'2026-09-13',1)")
    conn.execute("INSERT INTO imports VALUES(1,2,'draft.pdf','completed','2026-08-31',40000,'review')")
    result = reconcile_account_balances(conn)
    by_id = {row['account_id']: row for row in result['accounts']}
    assert result['status'] == 'incomplete'
    assert by_id[1]['status'] == 'unavailable_no_balance_date'
    assert by_id[2]['status'] == 'unavailable_no_verified_statement'
    assert result['read_only'] is True
