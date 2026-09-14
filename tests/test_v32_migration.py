import sqlite3

from app.v32_migrations import ensure_v32_schema


def test_v32_migration_is_additive_and_idempotent():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE transactions(id INTEGER PRIMARY KEY, label TEXT)')
    conn.execute("INSERT INTO transactions(id,label) VALUES(1,'existing')")

    ensure_v32_schema(conn)
    ensure_v32_schema(conn)

    assert conn.execute('SELECT label FROM transactions WHERE id=1').fetchone()['label'] == 'existing'
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert 'forecast_scenarios' in tables
    assert 'forecast_scenario_events' in tables

    sid = conn.execute("INSERT INTO forecast_scenarios(name,horizon_months) VALUES('Test',6)").lastrowid
    conn.execute("INSERT INTO forecast_scenario_events(scenario_id,event_type,label,amount_cents,due_date) VALUES(?,?,?,?,?)", (sid,'one_time','Achat',-10000,'2026-10-01'))
    assert conn.execute('SELECT COUNT(*) n FROM forecast_scenario_events WHERE scenario_id=?', (sid,)).fetchone()['n'] == 1
