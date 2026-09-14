import sqlite3
from pathlib import Path

from app.imports import (
    accept_categorized_import_reviews,
    ensure_import_schema,
    refresh_review_counts,
)


ROOT = Path(__file__).resolve().parents[1]


def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE accounts(id INTEGER PRIMARY KEY, name TEXT, is_active INTEGER DEFAULT 1)')
    conn.execute(
        """CREATE TABLE transactions(
            id INTEGER PRIMARY KEY,
            account_id INTEGER,
            booking_date TEXT,
            amount_cents INTEGER,
            label TEXT,
            category TEXT,
            transaction_type TEXT,
            is_internal_transfer INTEGER DEFAULT 0
        )"""
    )
    conn.execute("INSERT INTO accounts(id,name) VALUES(1,'Compte')")
    ensure_import_schema(conn)
    return conn


def add_review(conn, *, import_id=1, transaction_id=1, category='Restaurants',
               opening=1000, closing=900, debit=100, credit=0, quality='review'):
    conn.execute(
        """INSERT INTO imports(
            id,account_id,filename,source_type,status,total_rows,imported_rows,review_rows,
            opening_balance_cents,closing_balance_cents,debit_total_cents,credit_total_cents,
            quality_status
        ) VALUES(?,1,?,'pdf','completed',1,1,1,?,?,?,?,?)""",
        (import_id, f'{import_id}.pdf', opening, closing, debit, credit, quality),
    )
    conn.execute(
        """INSERT INTO transactions(
            id,account_id,booking_date,amount_cents,label,category,transaction_type
        ) VALUES(?,1,'2026-08-01',-100,'CB TEST',?,'expense')""",
        (transaction_id, category),
    )
    conn.execute(
        """INSERT INTO transaction_import_meta(
            transaction_id,import_id,fingerprint,normalized_label,review_status
        ) VALUES(?,?,?,'CB TEST','needs_review')""",
        (transaction_id, import_id, f'fp-{transaction_id}'),
    )


def test_explicitly_categorized_row_closes_review_and_verifies_reconciled_statement():
    conn = db()
    add_review(conn)

    accepted = accept_categorized_import_reviews(conn, {1})

    assert accepted == 1
    assert conn.execute(
        'SELECT review_status FROM transaction_import_meta WHERE transaction_id=1'
    ).fetchone()['review_status'] == 'accepted'
    statement = conn.execute(
        'SELECT review_rows,quality_status FROM imports WHERE id=1'
    ).fetchone()
    assert statement['review_rows'] == 0
    assert statement['quality_status'] == 'verified'


def test_uncategorized_row_remains_pending():
    conn = db()
    add_review(conn, category=None)

    accepted = accept_categorized_import_reviews(conn, {1})

    assert accepted == 0
    assert conn.execute(
        'SELECT review_status FROM transaction_import_meta WHERE transaction_id=1'
    ).fetchone()['review_status'] == 'needs_review'


def test_arithmetic_mismatch_is_never_promoted_to_verified():
    conn = db()
    add_review(conn, closing=800)

    accepted = accept_categorized_import_reviews(conn, {1})

    assert accepted == 1
    statement = conn.execute(
        'SELECT review_rows,quality_status FROM imports WHERE id=1'
    ).fetchone()
    assert statement['review_rows'] == 0
    assert statement['quality_status'] == 'review'


def test_warning_statement_is_never_promoted_to_verified():
    conn = db()
    add_review(conn, quality='warning')

    accept_categorized_import_reviews(conn, {1})
    refresh_review_counts(conn, {1})

    statement = conn.execute(
        'SELECT review_rows,quality_status FROM imports WHERE id=1'
    ).fetchone()
    assert statement['review_rows'] == 0
    assert statement['quality_status'] == 'warning'


def test_v31_movement_edit_closes_import_review_only_after_explicit_category():
    source = (ROOT / 'app' / 'v31_routes.py').read_text(encoding='utf-8')
    assert 'accept_categorized_import_reviews' in source
    assert "if updates.get('category')" in source
    assert "'import_review_accepted': bool(review_accepted)" in source


def test_reconciliation_tool_is_dry_run_by_default():
    source = (ROOT / 'maintenance' / 'reconcile_import_reviews.py').read_text(encoding='utf-8')
    assert "parser.add_argument('--apply', action='store_true')" in source
    assert "mode = 'apply' if args.apply else 'dry-run'" in source
    assert 'conn.rollback()' in source


def test_reconciled_legacy_unverified_statement_is_promoted_after_review():
    conn = db()
    add_review(conn, quality='unverified')

    accepted = accept_categorized_import_reviews(conn, {1})

    assert accepted == 1
    statement = conn.execute(
        'SELECT review_rows,quality_status FROM imports WHERE id=1'
    ).fetchone()
    assert statement['review_rows'] == 0
    assert statement['quality_status'] == 'verified'
