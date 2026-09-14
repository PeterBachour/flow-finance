from app import db
from app.notion_import import SOURCE_REVISION, apply_import


def test_notion_import_is_idempotent_and_keeps_confirmed_balances(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'flow-test.db')
    db.init_db()

    first = apply_import('test')
    second = apply_import('test-repeat')

    assert first['source_revision'] == SOURCE_REVISION
    assert second['source_revision'] == SOURCE_REVISION

    with db.connection() as conn:
        accounts = conn.execute("SELECT name,current_balance_cents,balance_as_of FROM accounts WHERE source_type='notion' ORDER BY name").fetchall()
        transactions = conn.execute("SELECT COUNT(*) n FROM transactions WHERE source_type='notion'").fetchone()['n']
        transfers = conn.execute("SELECT COUNT(*) n FROM transactions WHERE source_type='notion' AND is_internal_transfer=1").fetchone()['n']
        histories = conn.execute("SELECT COUNT(*) n FROM monthly_financial_history WHERE source_type='notion'").fetchone()['n']
        duplicate_keys = conn.execute("SELECT COUNT(*) n FROM (SELECT source_key,COUNT(*) c FROM transactions WHERE source_key IS NOT NULL GROUP BY source_key HAVING c>1)").fetchone()['n']
        lcl = conn.execute("SELECT current_balance_cents,balance_as_of FROM accounts WHERE source_key='account:lcl-current'").fetchone()
        ldds = conn.execute("SELECT current_balance_cents FROM accounts WHERE source_key='account:ldds'").fetchone()

    assert len(accounts) == 6
    assert transactions == 5
    assert transfers == 4
    assert histories == 5
    assert duplicate_keys == 0
    assert lcl['current_balance_cents'] == 95325
    assert lcl['balance_as_of'] == '2026-09-07'
    assert ldds['current_balance_cents'] == 59651
