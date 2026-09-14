"""Additive Flow 2.0 schema migration.

This module never drops, truncates, recreates or rewrites user data.  It only
adds columns, indexes and V2 tables when they are missing.
"""
from __future__ import annotations

import sqlite3

V2_COLUMNS: dict[str, dict[str, str]] = {
    'accounts': {
        'bank': 'TEXT',
        'role': "TEXT NOT NULL DEFAULT 'other'",
    },
    'transactions': {
        'user_label': 'TEXT',
        'merchant': 'TEXT',
        'exclude_from_analytics': "INTEGER NOT NULL DEFAULT 0",
        'is_exceptional': "INTEGER NOT NULL DEFAULT 0",
        'transfer_pair_id': 'INTEGER',
    },
    'recurring_transactions': {
        'frequency': "TEXT NOT NULL DEFAULT 'monthly'",
        'variance_cents': "INTEGER NOT NULL DEFAULT 0",
        'last_occurrence': 'TEXT',
        'next_occurrence': 'TEXT',
        'confidence_score': 'REAL',
        'validation_status': "TEXT NOT NULL DEFAULT 'confirmed'",
    },
    'financial_goals': {
        'goal_type': "TEXT NOT NULL DEFAULT 'savings'",
        'is_mandatory': "INTEGER NOT NULL DEFAULT 0",
        'include_in_safe_to_spend': "INTEGER NOT NULL DEFAULT 1",
    },
}

V2_SCHEMA = """
CREATE TABLE IF NOT EXISTS paychecks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER REFERENCES accounts(id),
    pay_date TEXT NOT NULL,
    employer TEXT,
    gross_cents INTEGER,
    net_cents INTEGER NOT NULL,
    taxable_net_cents INTEGER,
    withholding_tax_cents INTEGER,
    bonuses_cents INTEGER,
    benefits_cents INTEGER,
    source_type TEXT,
    source_id TEXT,
    source_key TEXT UNIQUE,
    confidence REAL,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_paychecks_date ON paychecks(pay_date DESC);

CREATE TABLE IF NOT EXISTS transaction_tags (
    transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    tag TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(transaction_id, tag)
);
CREATE INDEX IF NOT EXISTS idx_transaction_tags_tag ON transaction_tags(tag);

CREATE TABLE IF NOT EXISTS data_quality_issues (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    issue_key TEXT NOT NULL UNIQUE,
    issue_type TEXT NOT NULL,
    severity TEXT NOT NULL DEFAULT 'warning',
    entity_type TEXT,
    entity_id INTEGER,
    title TEXT NOT NULL,
    details TEXT,
    status TEXT NOT NULL DEFAULT 'open',
    detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    resolved_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_quality_status ON data_quality_issues(status, severity);

CREATE TABLE IF NOT EXISTS forecast_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of TEXT NOT NULL,
    horizon TEXT NOT NULL,
    mode TEXT NOT NULL,
    safe_to_spend_cents INTEGER NOT NULL,
    low_point_cents INTEGER NOT NULL,
    low_point_date TEXT NOT NULL,
    confidence_score REAL,
    payload_json TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(as_of, horizon, mode)
);
CREATE INDEX IF NOT EXISTS idx_forecast_snapshots_asof ON forecast_snapshots(as_of DESC);

CREATE TABLE IF NOT EXISTS insights (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    insight_key TEXT NOT NULL UNIQUE,
    period TEXT NOT NULL,
    insight_type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    impact_cents INTEGER,
    confidence REAL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_insights_period ON insights(period, created_at DESC);
"""

INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_transactions_account_date ON transactions(account_id, booking_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_category_date ON transactions(category, booking_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_type_date ON transactions(transaction_type, booking_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_transactions_analytics ON transactions(exclude_from_analytics, is_internal_transfer, booking_date DESC)",
    "CREATE INDEX IF NOT EXISTS idx_recurring_active_day ON recurring_transactions(is_active, day_of_month)",
)


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}


def ensure_v2_schema(conn: sqlite3.Connection) -> None:
    """Apply V2 changes in-place. Safe to call repeatedly."""
    for table, definitions in V2_COLUMNS.items():
        existing = _columns(conn, table)
        if not existing:
            # Base schema is owned by db.init_db(); never invent a replacement.
            continue
        for name, sql_type in definitions.items():
            if name not in existing:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {sql_type}')
    conn.executescript(V2_SCHEMA)
    for statement in INDEXES:
        try:
            conn.execute(statement)
        except sqlite3.OperationalError as exc:
            # An old database can be opened briefly before base migrations have
            # completed.  Do not mutate destructively; the next request retries.
            if 'no such column' not in str(exc).lower():
                raise
