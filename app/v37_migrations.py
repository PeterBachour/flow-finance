from __future__ import annotations

import sqlite3


def ensure_v37_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS merchant_aliases (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            normalized_key TEXT NOT NULL UNIQUE,
            canonical_name TEXT NOT NULL,
            confidence REAL NOT NULL DEFAULT 1.0,
            source TEXT NOT NULL DEFAULT 'user',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_merchant_aliases_name ON merchant_aliases(canonical_name);
        """
    )
