from app import db
from app.notion_import import apply_import


def test_newer_flow_balance_wins_over_older_notion_snapshot(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'flow-test.db')
    db.init_db()
    with db.connection() as conn:
        conn.execute("INSERT INTO accounts(name,kind,current_balance_cents,balance_as_of) VALUES('Compte courant LCL','checking',96000,'2026-09-08')")

    apply_import('test-newer-flow')
    apply_import('test-repeat')

    with db.connection() as conn:
        row = conn.execute("SELECT current_balance_cents,balance_as_of,source_key,source_status FROM accounts WHERE lower(name)=lower('Compte courant LCL')").fetchone()
        conflicts = conn.execute("SELECT COUNT(*) n FROM notion_import_conflicts WHERE entity_type='account' AND source_key='account:lcl-current' AND resolution='needs_review'").fetchone()['n']

    assert row['current_balance_cents'] == 96000
    assert row['balance_as_of'] == '2026-09-08'
    assert row['source_key'] == 'account:lcl-current'
    assert row['source_status'] == 'flow_newer'
    assert conflicts == 0
