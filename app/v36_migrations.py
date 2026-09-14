from __future__ import annotations

import sqlite3


def ensure_v36_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS financial_routine_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            routine_key TEXT NOT NULL,
            period_key TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'completed',
            summary_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(routine_key, period_key)
        );
        CREATE INDEX IF NOT EXISTS idx_financial_routine_runs_period
            ON financial_routine_runs(period_key, created_at DESC);

        CREATE TABLE IF NOT EXISTS planned_transaction_matches (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            planned_transaction_id INTEGER NOT NULL REFERENCES planned_transactions(id) ON DELETE CASCADE,
            transaction_id INTEGER NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
            amount_delta_cents INTEGER NOT NULL DEFAULT 0,
            day_delta INTEGER NOT NULL DEFAULT 0,
            confidence REAL NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(planned_transaction_id),
            UNIQUE(transaction_id)
        );

        CREATE TABLE IF NOT EXISTS decision_inbox_status (
            item_key TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'open',
            note TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
