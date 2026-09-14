from __future__ import annotations

import sqlite3


def ensure_v34_schema(conn: sqlite3.Connection) -> None:
    """Additive V3.4 schema. Stores only user state for generated plan actions."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS action_plan_status (
            action_key TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'open',
            note TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_action_plan_status_status
            ON action_plan_status(status, updated_at DESC);
        """
    )
