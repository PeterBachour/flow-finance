import sqlite3
from datetime import date

import pytest

from app.history_coverage import build_history_coverage, expected_months


def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('''CREATE TABLE imports(
        id INTEGER PRIMARY KEY,
        filename TEXT,
        status TEXT,
        quality_status TEXT,
        period_start TEXT,
        period_end TEXT,
        review_rows INTEGER DEFAULT 0
    )''')
    conn.execute('''CREATE TABLE payroll_records(
        id INTEGER PRIMARY KEY,
        period TEXT,
        source_status TEXT,
        source_filename TEXT,
        net_paid_cents INTEGER
    )''')
    return conn


def test_expected_months_is_contiguous_and_bounded():
    assert expected_months(as_of=date(2026, 9, 12), months=4) == [
        '2026-06', '2026-07', '2026-08', '2026-09'
    ]
    with pytest.raises(ValueError):
        expected_months(as_of=date(2026, 9, 12), months=0)


def test_history_coverage_reports_gaps_reviews_and_complete_months():
    conn = db()
    conn.executemany(
        '''INSERT INTO imports(id,filename,status,quality_status,period_start,period_end,review_rows)
           VALUES(?,?,?,?,?,?,?)''',
        [
            (1, 'june.pdf', 'completed', 'verified', '2026-06-01', '2026-06-30', 0),
            (2, 'july.pdf', 'completed', 'review', '2026-07-01', '2026-07-31', 2),
            (3, 'sept.pdf', 'completed', 'verified', '2026-09-01', '2026-09-30', 0),
        ],
    )
    conn.executemany(
        '''INSERT INTO payroll_records(id,period,source_status,source_filename,net_paid_cents)
           VALUES(?,?,?,?,?)''',
        [
            (1, '2026-06', 'confirmed', 'june-pay.pdf', 300000),
            (2, '2026-08', 'confirmed', 'aug-pay.pdf', 310000),
            (3, '2026-09', 'confirmed', 'sept-pay.pdf', 310000),
        ],
    )

    report = build_history_coverage(conn, as_of=date(2026, 9, 12), months=4)

    assert report['gaps']['statements'] == ['2026-08']
    assert report['gaps']['payrolls'] == ['2026-07']
    assert report['review_periods'] == ['2026-07']
    assert report['complete_periods'] == ['2026-06', '2026-09']
    assert report['summary']['statement_coverage_pct'] == 75.0
    assert report['summary']['payroll_coverage_pct'] == 75.0
    assert report['summary']['complete_months'] == 2
    assert report['read_only'] is True


def test_duplicate_periods_are_reported_without_mutation():
    conn = db()
    conn.executemany(
        '''INSERT INTO imports(id,filename,status,quality_status,period_start,period_end,review_rows)
           VALUES(?,?,?,?,?,?,?)''',
        [
            (1, 'a.pdf', 'completed', 'verified', '2026-09-01', '2026-09-30', 0),
            (2, 'b.pdf', 'completed', 'verified', '2026-09-01', '2026-09-30', 0),
        ],
    )
    conn.executemany(
        '''INSERT INTO payroll_records(id,period,source_status,source_filename,net_paid_cents)
           VALUES(?,?,?,?,?)''',
        [
            (1, '2026-09', 'confirmed', 'a-pay.pdf', 300000),
            (2, '2026-09', 'confirmed', 'b-pay.pdf', 300000),
        ],
    )
    before_imports = conn.execute('SELECT COUNT(*) n FROM imports').fetchone()['n']
    before_payrolls = conn.execute('SELECT COUNT(*) n FROM payroll_records').fetchone()['n']

    report = build_history_coverage(conn, as_of=date(2026, 9, 12), months=1)

    assert report['duplicates']['statements'] == ['2026-09']
    assert report['duplicates']['payrolls'] == ['2026-09']
    assert report['summary']['duplicate_months'] == 1
    assert conn.execute('SELECT COUNT(*) n FROM imports').fetchone()['n'] == before_imports
    assert conn.execute('SELECT COUNT(*) n FROM payroll_records').fetchone()['n'] == before_payrolls
