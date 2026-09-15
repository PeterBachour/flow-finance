import sqlite3

from app.imports import apply_rule_to_inbox, ensure_import_schema, import_review_groups, import_rows, make_fingerprint, normalize_label, parse_csv_bytes


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
    conn.execute("INSERT INTO imports(id,account_id,filename,source_type,status,total_rows) VALUES(1,1,'x.csv','csv','processing',1)")
    return conn


def test_csv_signed_amount_and_normalization():
    rows = parse_csv_bytes('Date;Libellé;Montant\n08/09/2026;CB MONOPRIX 07/09/26;-12,34\n'.encode())
    assert rows[0]['booking_date'] == '2026-09-08'
    assert rows[0]['amount_cents'] == -1234
    assert normalize_label(rows[0]['label']) == 'CB MONOPRIX'


def test_import_does_not_duplicate_existing_manual_transaction():
    conn = db()
    conn.execute("INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type) VALUES(1,'2026-09-08',-1234,'CB MONOPRIX','Alimentation','expense')")
    result = import_rows(conn, 1, 1, [{'booking_date':'2026-09-08','amount_cents':-1234,'label':'CB MONOPRIX','raw':{}}])
    assert result == {'imported': 0, 'duplicates': 1, 'review': 0, 'auto_classified': 0}


def test_rule_reclassifies_other_inbox_rows():
    conn = db()
    rows = [
        {'booking_date':'2026-09-08','amount_cents':-1234,'label':'CB MONOPRIX','raw':{}},
        {'booking_date':'2026-09-09','amount_cents':-2200,'label':'CB MONOPRIX PARIS','raw':{}},
    ]
    result = import_rows(conn, 1, 1, rows)
    assert result['review'] == 2
    count = apply_rule_to_inbox(conn, 'CB MONOPRIX', 'Alimentation', 'expense')
    assert count == 2
    remaining = conn.execute("SELECT COUNT(*) n FROM transaction_import_meta WHERE review_status='needs_review'").fetchone()['n']
    assert remaining == 0


def test_fingerprint_ignores_card_execution_date_suffix():
    a = make_fingerprint(1,'2026-09-08',-1000,'CB TEST 07/09/26')
    b = make_fingerprint(1,'2026-09-08',-1000,'CB TEST')
    assert a == b


def test_review_groups_expose_total_and_repeated_labels():
    conn = db()
    rows = [
        {'booking_date':'2026-09-08','amount_cents':-1234,'label':'CB MONOPRIX','raw':{}},
        {'booking_date':'2026-09-09','amount_cents':-2200,'label':'CB MONOPRIX PARIS','raw':{}},
        {'booking_date':'2026-09-10','amount_cents':-600,'label':'COTISATION CARTE','raw':{}},
    ]
    result = import_rows(conn, 1, 1, rows)
    assert result['review'] == 3

    summary = import_review_groups(conn)

    assert summary['total_pending'] == 3
    assert summary['grouped_pending'] == 2
    assert len(summary['groups']) == 1
    group = summary['groups'][0]
    assert group['normalized_label'] == 'CB MONOPRIX'
    assert group['occurrence_count'] == 2
    assert group['volume_cents'] == 3434
    assert group['first_seen'] == '2026-09-08'
    assert group['last_seen'] == '2026-09-09'
