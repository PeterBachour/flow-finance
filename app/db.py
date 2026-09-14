import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(os.getenv("FLOW_DB_PATH", "data/flow.db"))

SCHEMA = """
PRAGMA foreign_keys = ON;
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'checking',
    current_balance_cents INTEGER NOT NULL DEFAULT 0,
    balance_as_of TEXT,
    currency TEXT NOT NULL DEFAULT 'EUR',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS categories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    group_name TEXT NOT NULL DEFAULT 'life',
    budget_mode TEXT NOT NULL DEFAULT 'limit',
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    booking_date TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    label TEXT NOT NULL,
    category TEXT,
    transaction_type TEXT NOT NULL DEFAULT 'expense',
    is_internal_transfer INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_transactions_date ON transactions(booking_date);
CREATE TABLE IF NOT EXISTS categorization_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    pattern TEXT NOT NULL,
    category TEXT NOT NULL,
    transaction_type TEXT,
    priority INTEGER NOT NULL DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS planned_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    due_date TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    label TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'commitment',
    certainty TEXT NOT NULL DEFAULT 'confirmed',
    status TEXT NOT NULL DEFAULT 'planned',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_planned_date ON planned_transactions(due_date, status);
CREATE TABLE IF NOT EXISTS recurring_transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id),
    label TEXT NOT NULL,
    amount_cents INTEGER NOT NULL,
    day_of_month INTEGER NOT NULL,
    category TEXT,
    kind TEXT NOT NULL DEFAULT 'commitment',
    certainty TEXT NOT NULL DEFAULT 'expected',
    tolerance_cents INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS budgets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    month TEXT NOT NULL UNIQUE,
    status TEXT NOT NULL DEFAULT 'draft',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS budget_lines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    budget_id INTEGER NOT NULL REFERENCES budgets(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    planned_cents INTEGER NOT NULL DEFAULT 0,
    mode TEXT NOT NULL DEFAULT 'limit',
    UNIQUE(budget_id, category)
);
CREATE TABLE IF NOT EXISTS financial_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_cents INTEGER NOT NULL,
    target_date TEXT,
    priority INTEGER NOT NULL DEFAULT 100,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS goal_allocations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    goal_id INTEGER NOT NULL REFERENCES financial_goals(id) ON DELETE CASCADE,
    account_id INTEGER REFERENCES accounts(id),
    amount_cents INTEGER NOT NULL,
    allocated_on TEXT NOT NULL,
    note TEXT,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS account_balance_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id INTEGER NOT NULL REFERENCES accounts(id) ON DELETE CASCADE,
    balance_cents INTEGER NOT NULL,
    balance_date TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed',
    source_type TEXT,
    source_id TEXT,
    source_url TEXT,
    source_date TEXT,
    source_status TEXT,
    confidence REAL,
    source_key TEXT UNIQUE,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX IF NOT EXISTS idx_balance_history_account_date ON account_balance_history(account_id, balance_date);
CREATE TABLE IF NOT EXISTS financial_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    rule_type TEXT NOT NULL,
    name TEXT NOT NULL,
    value_text TEXT,
    value_cents INTEGER,
    start_date TEXT,
    end_date TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    comment TEXT,
    source_type TEXT,
    source_id TEXT,
    source_url TEXT,
    source_date TEXT,
    source_status TEXT,
    confidence REAL,
    source_key TEXT UNIQUE,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS financial_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_date TEXT NOT NULL,
    title TEXT NOT NULL,
    details TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    supersedes_key TEXT,
    source_type TEXT,
    source_id TEXT,
    source_url TEXT,
    source_date TEXT,
    source_status TEXT,
    confidence REAL,
    source_key TEXT UNIQUE,
    imported_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS notion_import_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mode TEXT NOT NULL,
    status TEXT NOT NULL,
    source_revision TEXT,
    stats_json TEXT,
    conflict_count INTEGER NOT NULL DEFAULT 0,
    ignored_count INTEGER NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at TEXT
);
CREATE TABLE IF NOT EXISTS notion_import_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id INTEGER REFERENCES notion_import_runs(id) ON DELETE CASCADE,
    entity_type TEXT NOT NULL,
    source_key TEXT,
    reason TEXT NOT NULL,
    existing_value TEXT,
    incoming_value TEXT,
    resolution TEXT NOT NULL DEFAULT 'needs_review',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
INSERT OR IGNORE INTO settings(key, value) VALUES ('safety_reserve_cents', '0');
INSERT OR IGNORE INTO settings(key, value) VALUES ('notion_last_sync_at', '');
INSERT OR IGNORE INTO settings(key, value) VALUES ('notion_source_revision', '');
INSERT OR IGNORE INTO categories(name, group_name, budget_mode) VALUES
('Salaire','income','tracking_only'),('Remboursement','off_budget','tracking_only'),
('Logement','obligatory','reserved'),('Transport','obligatory','reserved'),('Télécom','obligatory','reserved'),
('Assurances','obligatory','reserved'),('Crédits','obligatory','reserved'),('Impôts','obligatory','reserved'),
('Alimentation','life','reserved'),('Restaurants','life','limit'),('Shopping','life','limit'),('Loisirs','life','limit'),
('Santé','life','tracking_only'),('Épargne','wealth','tracking_only'),('Investissement','wealth','tracking_only'),
('Transfert interne','off_budget','tracking_only'),('Frais professionnel remboursé','off_budget','tracking_only');
"""

PROVENANCE_COLUMNS = {
    'accounts': {
        'include_in_wealth': "INTEGER NOT NULL DEFAULT 1",
        'include_in_liquidity': "INTEGER NOT NULL DEFAULT 1",
        'include_in_safe_to_spend': "INTEGER NOT NULL DEFAULT 0",
        'source_type': 'TEXT', 'source_id': 'TEXT', 'source_url': 'TEXT', 'source_date': 'TEXT',
        'source_status': 'TEXT', 'confidence': 'REAL', 'source_key': 'TEXT', 'imported_at': 'TEXT'
    },
    'transactions': {
        'destination_account_id': 'INTEGER', 'status': "TEXT NOT NULL DEFAULT 'confirmed'",
        'source_type': 'TEXT', 'source_id': 'TEXT', 'source_url': 'TEXT', 'source_date': 'TEXT',
        'source_status': 'TEXT', 'confidence': 'REAL', 'source_key': 'TEXT', 'imported_at': 'TEXT'
    },
    'planned_transactions': {
        'source_type': 'TEXT', 'source_id': 'TEXT', 'source_url': 'TEXT', 'source_date': 'TEXT',
        'source_status': 'TEXT', 'confidence': 'REAL', 'source_key': 'TEXT', 'imported_at': 'TEXT'
    },
    'recurring_transactions': {
        'source_type': 'TEXT', 'source_id': 'TEXT', 'source_url': 'TEXT', 'source_date': 'TEXT',
        'source_status': 'TEXT', 'confidence': 'REAL', 'source_key': 'TEXT', 'imported_at': 'TEXT'
    },
    'financial_goals': {
        'current_cents': "INTEGER NOT NULL DEFAULT 0", 'monthly_contribution_cents': "INTEGER NOT NULL DEFAULT 0",
        'source_type': 'TEXT', 'source_id': 'TEXT', 'source_url': 'TEXT', 'source_date': 'TEXT',
        'source_status': 'TEXT', 'confidence': 'REAL', 'source_key': 'TEXT', 'imported_at': 'TEXT'
    },
}


def _migrate_columns(conn: sqlite3.Connection) -> None:
    for table, definitions in PROVENANCE_COLUMNS.items():
        columns = {row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}
        for name, sql_type in definitions.items():
            if name not in columns:
                conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {sql_type}')
    source_key_indexes = {
        'idx_accounts_source_key': 'accounts',
        'idx_transactions_source_key': 'transactions',
        'idx_planned_source_key': 'planned_transactions',
        'idx_recurring_source_key': 'recurring_transactions',
        'idx_goals_source_key': 'financial_goals',
    }
    for index_name, table in source_key_indexes.items():
        existing = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND name=?",
            (index_name,),
        ).fetchone()
        if existing and existing[0] and ' WHERE ' in existing[0].upper():
            conn.execute(f'DROP INDEX {index_name}')
        conn.execute(
            f'CREATE UNIQUE INDEX IF NOT EXISTS {index_name} ON {table}(source_key)'
        )


def init_db() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        conn.executescript(SCHEMA)
        columns = {row[1] for row in conn.execute('PRAGMA table_info(accounts)').fetchall()}
        if 'balance_as_of' not in columns:
            conn.execute('ALTER TABLE accounts ADD COLUMN balance_as_of TEXT')
        _migrate_columns(conn)


@contextmanager
def connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys = ON')
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()
