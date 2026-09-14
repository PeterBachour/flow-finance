import sqlite3
from datetime import date

from app.data_quality_report import build_data_quality_report
from app.db import SCHEMA, _migrate_columns
from app.imports import ensure_import_schema
from app.v2_migrations import ensure_v2_schema


def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _migrate_columns(conn)
    ensure_v2_schema(conn)
    ensure_import_schema(conn)
    return conn


def test_report_exposes_reconciliation_duplicates_categories_and_periods():
    conn = db()
    conn.execute(
        "INSERT INTO accounts(id,name,kind,current_balance_cents,balance_as_of,is_active,include_in_safe_to_spend) VALUES(1,'Courant','checking',110000,'2026-09-13',1,1)"
    )
    conn.execute('''
        INSERT INTO imports(account_id,filename,source_type,status,period_start,period_end,closing_balance_cents,quality_status)
        VALUES(1,'aout.pdf','pdf','completed','2026-08-01','2026-08-31',100000,'verified')
    ''')
    conn.execute('''
        INSERT INTO imports(account_id,filename,source_type,status,period_start,period_end,closing_balance_cents,quality_status)
        VALUES(1,'septembre.pdf','pdf','processing','2026-09-01','2026-09-30',NULL,'unverified')
    ''')
    rows = [
        ('2026-09-02', 10000, 'Salaire partiel', 'Salaire', 'income', 0, 0, 'csv', 'tx:1'),
        ('2026-09-03', -5000, 'Restaurant', 'Restaurants', 'expense', 0, 0, 'csv', 'tx:2'),
        ('2026-09-03', -5000, 'Restaurant', 'Restaurants', 'expense', 0, 0, 'csv', 'tx:3'),
        ('2026-09-04', -3000, 'Mystère', 'Catégorie fantôme', 'expense', 0, 0, 'csv', 'tx:4'),
        ('2026-09-05', -2000, 'Sans catégorie', None, 'expense', 0, 0, 'csv', None),
    ]
    conn.executemany('''
        INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer,exclude_from_analytics,source_type,source_key,status)
        VALUES(1,?,?,?,?,?,?,?,?,?,'confirmed')
    ''', rows)

    report = build_data_quality_report(conn, date(2026, 9, 13))

    assert report['read_only'] is True
    assert report['reconciliation']['status'] == 'mismatch'
    assert report['reconciliation']['mismatch_count'] == 1
    assert report['controls']['duplicates']['exact_duplicate_groups'] == 1
    assert report['controls']['duplicates']['imported_rows_missing_source_key'] == 1
    assert report['controls']['categories']['unknown_category_rows'] == 1
    assert report['controls']['categories']['uncategorized_rows'] == 1
    assert report['controls']['periods']['count'] == 1
    assert report['controls']['periods']['incomplete_periods'][0]['period'] == '2026-09'
    types = {issue['type'] for issue in report['issues']}
    assert 'balance_reconciliation_mismatch' in types
    assert 'duplicates' in types
    assert 'missing_source_key' in types
    assert 'unknown_categories' in types
    assert 'incomplete_periods' in types


def test_refunds_and_internal_transfers_are_not_unknown_category_noise():
    conn = db()
    conn.execute(
        "INSERT INTO accounts(id,name,kind,current_balance_cents,balance_as_of,is_active,include_in_safe_to_spend) VALUES(1,'Courant','checking',0,'2026-09-13',1,1)"
    )
    conn.executemany('''
        INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer,exclude_from_analytics,status)
        VALUES(1,?,?,?,?,?,?,?,'confirmed')
    ''', [
        ('2026-09-01', 3000, 'Refund', 'Whatever', 'refund', 0, 0),
        ('2026-09-02', -5000, 'Transfer', 'Unknown transfer label', 'transfer', 1, 0),
    ])
    report = build_data_quality_report(conn, date(2026, 9, 13))
    assert report['controls']['categories']['unknown_category_rows'] == 0
    assert report['controls']['categories']['uncategorized_rows'] == 0


def test_v2_routes_use_unified_report():
    from app.v2_routes import cockpit, diagnostics, quality

    assert callable(cockpit)
    assert callable(quality)
    assert callable(diagnostics)
