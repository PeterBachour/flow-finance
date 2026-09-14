from __future__ import annotations

import sqlite3


def ensure_v31_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS notification_preferences (
            key TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 1,
            threshold_cents INTEGER,
            description TEXT,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        INSERT OR IGNORE INTO notification_preferences(key,enabled,threshold_cents,description) VALUES
            ('large_upcoming_outflow',1,30000,'Alerte lorsqu’une sortie importante approche'),
            ('safe_to_spend_risk',1,NULL,'Alerte lorsque le Safe to Spend passe en vigilance ou critique'),
            ('stale_balance',1,NULL,'Alerte lorsqu’un compte utilisé par le cockpit n’est plus à jour'),
            ('import_review',1,NULL,'Alerte lorsqu’un import nécessite une validation'),
            ('missing_expected_debit',0,NULL,'Alerte expérimentale lorsqu’un prélèvement attendu semble absent');
        """
    )
