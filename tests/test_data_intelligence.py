import sqlite3
from pathlib import Path

from app.bulk_import import ensure_bulk_schema
from app.data_intelligence import detect_recurring_transactions, ensure_intelligence_schema, reconcile_payroll
from app.db import SCHEMA, _migrate_columns


def make_conn(tmp_path: Path):
    conn = sqlite3.connect(tmp_path / 'test.db')
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    ensure_bulk_schema(conn)
    ensure_intelligence_schema(conn)
    return conn


def test_payroll_matches_single_bank_income(tmp_path: Path):
    conn = make_conn(tmp_path)
    account = conn.execute("INSERT INTO accounts(name) VALUES('LCL')").lastrowid
    tx = conn.execute("INSERT INTO transactions(account_id,booking_date,amount_cents,label,transaction_type) VALUES(?,?,?,?,?)",
                      (account, '2026-02-26', 310400, 'VIREMENT KARDHAM DIGITAL', 'income')).lastrowid
    payroll = conn.execute("INSERT INTO payroll_records(period,employer,net_paid_cents,source_hash) VALUES(?,?,?,?)",
                           ('2026-02', 'Kardham Digital', 310400, 'hash-payroll')).lastrowid
    result = reconcile_payroll(conn)
    assert result['matched'] == 1
    match = conn.execute('SELECT * FROM payroll_transaction_matches WHERE payroll_record_id=?', (payroll,)).fetchone()
    assert match['transaction_id'] == tx
    assert match['confidence'] >= 0.72
    assert conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 1
    conn.close()


def test_payroll_falls_back_to_unique_employer_period_income(tmp_path: Path):
    conn = make_conn(tmp_path)
    account = conn.execute("INSERT INTO accounts(name) VALUES('LCL')").lastrowid
    tx = conn.execute("INSERT INTO transactions(account_id,booking_date,amount_cents,label,transaction_type) VALUES(?,?,?,?,?)",
                      (account, '2025-04-29', 248775, 'VIREMENT KARDHAM DIGITAL', 'income')).lastrowid
    conn.execute("INSERT INTO transactions(account_id,booking_date,amount_cents,label,transaction_type) VALUES(?,?,?,?,?)",
                 (account, '2025-04-07', 160200, 'AUTRE VIREMENT', 'income'))
    payroll = conn.execute("INSERT INTO payroll_records(period,employer,net_paid_cents,source_hash) VALUES(?,?,?,?)",
                           ('2025-04', 'Kardham Digital', 271517, 'hash-payroll-fallback')).lastrowid
    result = reconcile_payroll(conn)
    assert result['matched'] == 1
    assert result['unresolved'] == 0
    match = conn.execute('SELECT * FROM payroll_transaction_matches WHERE payroll_record_id=?', (payroll,)).fetchone()
    assert match['transaction_id'] == tx
    assert match['confidence'] >= 0.84
    assert 'fallback' in match['match_reason']
    assert conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0] == 2
    conn.close()


def test_detects_monthly_recurring_payment_with_date_tolerance(tmp_path: Path):
    conn = make_conn(tmp_path)
    account = conn.execute("INSERT INTO accounts(name) VALUES('LCL')").lastrowid
    for booking_date, amount in [
        ('2026-01-05', -9080), ('2026-02-02', -9080), ('2026-03-02', -9080),
        ('2026-04-02', -9080), ('2026-05-04', -9080), ('2026-06-02', -9080),
    ]:
        conn.execute("INSERT INTO transactions(account_id,booking_date,amount_cents,label,category) VALUES(?,?,?,?,?)",
                     (account, booking_date, amount, 'PRLV SEPA Navigo Annuel - COMUTITRES SAS', 'Transport'))
    result = detect_recurring_transactions(conn, account)
    assert result['detected'] == 1
    assert result['accepted'] == 1
    recurring = conn.execute('SELECT * FROM recurring_transactions').fetchone()
    assert recurring['occurrence_count'] == 6
    assert recurring['usual_day'] in (2, 3)
    assert recurring['day_tolerance'] >= 2
    assert recurring['confidence'] >= 0.52
    assert recurring['next_expected_date'].startswith('2026-07-')
    assert recurring['detection_status'] == 'accepted'
    assert recurring['is_active'] == 1
    assert conn.execute('SELECT COUNT(*) FROM recurring_occurrences').fetchone()[0] == 6
    conn.close()


def test_large_amount_spread_requires_review_and_is_inactive(tmp_path: Path):
    conn = make_conn(tmp_path)
    account = conn.execute("INSERT INTO accounts(name) VALUES('LCL')").lastrowid
    for booking_date, amount in [
        ('2026-01-18', -200), ('2026-02-18', -4799), ('2026-03-18', -4799),
        ('2026-04-18', -4799), ('2026-05-18', -4799),
    ]:
        conn.execute("INSERT INTO transactions(account_id,booking_date,amount_cents,label) VALUES(?,?,?,?)",
                     (account, booking_date, amount, 'CB CANAL PLUS FR'))
    result = detect_recurring_transactions(conn, account)
    assert result['review_amount'] == 1
    recurring = conn.execute('SELECT * FROM recurring_transactions').fetchone()
    assert recurring['detection_status'] == 'review_amount'
    assert recurring['is_active'] == 0
    conn.close()


def test_large_day_tolerance_requires_review_and_is_inactive(tmp_path: Path):
    conn = make_conn(tmp_path)
    account = conn.execute("INSERT INTO accounts(name) VALUES('LCL')").lastrowid
    for booking_date in ('2026-01-01', '2026-02-20', '2026-03-20', '2026-04-20'):
        conn.execute("INSERT INTO transactions(account_id,booking_date,amount_cents,label) VALUES(?,?,?,?)",
                     (account, booking_date, -2285, 'PRLV SEPA CACI NON LIFE LIMITED'))
    result = detect_recurring_transactions(conn, account)
    assert result['review_date'] == 1
    recurring = conn.execute('SELECT * FROM recurring_transactions').fetchone()
    assert recurring['detection_status'] == 'review_date'
    assert recurring['is_active'] == 0
    conn.close()


def test_bank_aggregate_is_excluded_from_recurring_profiles(tmp_path: Path):
    conn = make_conn(tmp_path)
    account = conn.execute("INSERT INTO accounts(name) VALUES('LCL')").lastrowid
    for month in (1, 2, 3, 4):
        conn.execute("INSERT INTO transactions(account_id,booking_date,amount_cents,label) VALUES(?,?,?,?)",
                     (account, f'2026-{month:02d}-24', -800, 'TOTAL INCIDENTS FONCTIONNEMENT'))
    result = detect_recurring_transactions(conn, account)
    assert result['excluded'] == 1
    assert conn.execute('SELECT COUNT(*) FROM recurring_transactions').fetchone()[0] == 0
    conn.close()


def test_internal_transfer_is_not_detected_as_expense_recurrence(tmp_path: Path):
    conn = make_conn(tmp_path)
    account = conn.execute("INSERT INTO accounts(name) VALUES('LCL')").lastrowid
    for month in (1, 2, 3, 4):
        conn.execute("INSERT INTO transactions(account_id,booking_date,amount_cents,label,transaction_type,is_internal_transfer) VALUES(?,?,?,?,?,1)",
                     (account, f'2026-{month:02d}-01', -140000, 'VIR.PERMANENT Compte Joint', 'transfer'))
    result = detect_recurring_transactions(conn, account)
    assert result['detected'] == 0
    assert conn.execute('SELECT COUNT(*) FROM recurring_transactions').fetchone()[0] == 0
    conn.close()
