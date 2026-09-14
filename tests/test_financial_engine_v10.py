from app import db
from app.financial_engine_v1 import financial_rule_summary, safe_account_balance_cents
from app.notion_import import apply_import


def test_safe_to_spend_uses_only_explicit_safe_accounts(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'flow-test.db')
    db.init_db()
    apply_import('test')
    with db.connection() as conn:
        assert safe_account_balance_cents(conn) == 95325
        rules = financial_rule_summary(conn, '2026-09')
        names = {r['name']: r for r in rules['obligations']}
        assert names['Versement LCL Vie']['satisfied'] is True
        assert names['Assurance emprunteur']['satisfied'] is True
        assert names['Versement LDDS planifié septembre-décembre 2026']['satisfied'] is True
        assert names['Versement Livret A planifié septembre-décembre 2026']['satisfied'] is True
        assert rules['income_reference_cents'] == 291661
        assert rules['minimum_reserve_cents'] == 20000
        assert rules['variable_budget_cents'] == 48000
        assert rules['rule_reserve_cents'] >= 11300


def test_reimport_does_not_duplicate_source_transactions(tmp_path, monkeypatch):
    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'flow-test.db')
    db.init_db()
    apply_import('test-1')
    apply_import('test-2')
    with db.connection() as conn:
        count = conn.execute("SELECT COUNT(*) n FROM transactions WHERE source_type='notion'").fetchone()['n']
        duplicates = conn.execute("SELECT COUNT(*) n FROM (SELECT source_key,COUNT(*) c FROM transactions WHERE source_key IS NOT NULL GROUP BY source_key HAVING c>1)").fetchone()['n']
    assert count == 5
    assert duplicates == 0
