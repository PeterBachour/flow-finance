import sqlite3

from app.v3_migrations import ensure_v3_schema


def test_v3_migration_is_additive_and_idempotent(tmp_path):
    db = tmp_path / 'flow.db'
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE transactions(id INTEGER PRIMARY KEY, label TEXT)')
    conn.execute("INSERT INTO transactions(label) VALUES('historique')")

    ensure_v3_schema(conn)
    ensure_v3_schema(conn)

    assert conn.execute('SELECT label FROM transactions').fetchone()['label'] == 'historique'
    tables = {r['name'] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
    assert 'activity_log' in tables
    assert 'feature_flags' in tables
    flags = conn.execute('SELECT COUNT(*) n FROM feature_flags').fetchone()['n']
    assert flags == 3
    conn.close()
