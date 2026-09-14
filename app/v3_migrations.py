from __future__ import annotations

import sqlite3


def ensure_v3_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS activity_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_type TEXT NOT NULL,
            title TEXT NOT NULL,
            details TEXT,
            entity_type TEXT,
            entity_id TEXT,
            metadata_json TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_activity_log_created_at ON activity_log(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_activity_log_event_type ON activity_log(event_type);

        CREATE TABLE IF NOT EXISTS feature_flags (
            key TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0,
            description TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO feature_flags(key,enabled,description) VALUES
            ('advanced_notifications',0,'Notifications financières expérimentales'),
            ('experimental_forecast',0,'Moteur de prévision expérimental'),
            ('beta_import_parser',0,'Parseur d’import expérimental');
        """
    )


def log_activity(conn: sqlite3.Connection, event_type: str, title: str, details: str | None = None,
                 entity_type: str | None = None, entity_id: str | None = None, metadata_json: str | None = None) -> None:
    ensure_v3_schema(conn)
    conn.execute(
        'INSERT INTO activity_log(event_type,title,details,entity_type,entity_id,metadata_json) VALUES(?,?,?,?,?,?)',
        (event_type, title, details, entity_type, entity_id, metadata_json),
    )
