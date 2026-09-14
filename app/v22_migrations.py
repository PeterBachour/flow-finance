from __future__ import annotations

import sqlite3


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f'PRAGMA table_info({table})').fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    if name not in _columns(conn, table):
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')


def ensure_v22_schema(conn: sqlite3.Connection) -> None:
    _add_column(conn, 'financial_goals', 'goal_type', "TEXT NOT NULL DEFAULT 'savings'")
    _add_column(conn, 'financial_goals', 'monthly_contribution_cents', 'INTEGER NOT NULL DEFAULT 0')
    _add_column(conn, 'financial_goals', 'current_cents', 'INTEGER NOT NULL DEFAULT 0')
    _add_column(conn, 'accounts', 'bank', 'TEXT')
    _add_column(conn, 'accounts', 'role', "TEXT NOT NULL DEFAULT 'other'")

    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS wealth_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            asset_type TEXT NOT NULL DEFAULT 'other',
            value_cents INTEGER NOT NULL DEFAULT 0,
            debt_cents INTEGER NOT NULL DEFAULT 0,
            valuation_date TEXT,
            include_in_net_worth INTEGER NOT NULL DEFAULT 1,
            note TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS wealth_asset_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            asset_id INTEGER NOT NULL REFERENCES wealth_assets(id) ON DELETE CASCADE,
            valuation_date TEXT NOT NULL,
            value_cents INTEGER NOT NULL,
            debt_cents INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(asset_id, valuation_date)
        );
        CREATE INDEX IF NOT EXISTS idx_wealth_history_date ON wealth_asset_history(valuation_date);
        CREATE INDEX IF NOT EXISTS idx_wealth_assets_type ON wealth_assets(asset_type);
        """
    )
