from datetime import date

from app.v21_routes import _month_close_explanation
from app.financial_routes import _ensure_recurring_intelligence_schema


def test_month_close_reconciles_cash_components_and_stops_at_month_end(tmp_path, monkeypatch):
    import app.db as db

    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'month.db')
    db.init_db()
    with db.connection() as conn:
        _ensure_recurring_intelligence_schema(conn)
        account = conn.execute("""INSERT INTO accounts(name,current_balance_cents,balance_as_of,include_in_safe_to_spend)
            VALUES('Test',100000,'2026-10-04',1)""").lastrowid
        for due, amount, label in [('2026-10-15', 20000, 'Revenu'), ('2026-10-20', -5000, 'Charge'), ('2026-11-01', -90000, 'Après le mois')]:
            conn.execute("""INSERT INTO planned_transactions(account_id,due_date,amount_cents,label,kind,certainty,status)
                VALUES(?,?,?,?,'commitment','confirmed','planned')""", (account,due,amount,label))
        conn.execute("""INSERT INTO transactions(account_id,booking_date,amount_cents,label,category)
            VALUES(?,'2026-10-02',-30000,'Déjà constaté','Loisirs')""", (account,))
        conn.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('safety_reserve_cents','10000')")
        before = conn.total_changes
        result = _month_close_explanation(conn, '2026-10', date(2026,10,4))
        assert conn.total_changes == before
        assert result['status'] == 'available'
        assert result['target_date'] == '2026-10-31'
        assert result['opening_balance_cents'] == 100000
        assert result['expected_income_cents'] == 20000
        assert result['expected_outflows_cents'] == 5000
        assert result['closing_balance_cents'] == (
            100000 + 20000 - 5000 - result['variable_spending_cents'])
        assert result['closing_balance_cents'] == 115000


def test_other_months_and_stale_balances_do_not_expose_a_zero_projection(tmp_path, monkeypatch):
    import app.db as db

    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'missing.db')
    db.init_db()
    with db.connection() as conn:
        _ensure_recurring_intelligence_schema(conn)
        conn.execute("""INSERT INTO accounts(name,current_balance_cents,balance_as_of,include_in_safe_to_spend)
            VALUES('Test',100000,'2026-08-01',1)""")
        for month in ['2026-09','2026-10','2026-11']:
            result = _month_close_explanation(conn, month, date(2026,10,4))
            assert result['status'] == 'unavailable'
            assert result['closing_balance_cents'] is None
            assert result['opening_balance_cents'] is None


def test_month_endpoint_initializes_required_schema_on_a_fresh_database(tmp_path, monkeypatch):
    import app.db as db
    import app.v21_routes as routes

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 10, 4)

    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'fresh.db')
    monkeypatch.setattr(routes, 'date', FixedDate)
    db.init_db()
    with db.connection() as conn:
        conn.execute("""INSERT INTO accounts(name,current_balance_cents,balance_as_of,include_in_safe_to_spend)
            VALUES('Test',100000,'2026-10-04',1)""")
    result = routes.month_dashboard('2026-10')
    assert result['closing_explanation']['status'] == 'available'
    assert result['current']['projected_close_cents'] == result['closing_explanation']['closing_balance_cents']
