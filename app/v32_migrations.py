from __future__ import annotations

import sqlite3


def ensure_v32_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS forecast_scenarios (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            description TEXT,
            horizon_months INTEGER NOT NULL DEFAULT 6,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS forecast_scenario_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scenario_id INTEGER NOT NULL REFERENCES forecast_scenarios(id) ON DELETE CASCADE,
            event_type TEXT NOT NULL DEFAULT 'one_time',
            label TEXT NOT NULL,
            amount_cents INTEGER NOT NULL,
            due_date TEXT,
            day_of_month INTEGER,
            start_date TEXT,
            end_date TEXT,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE INDEX IF NOT EXISTS idx_forecast_scenario_events_scenario
          ON forecast_scenario_events(scenario_id,id);
        """
    )
