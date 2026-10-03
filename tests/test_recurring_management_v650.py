from fastapi.testclient import TestClient

from app.main import app


def test_recurring_management_contract(tmp_path, monkeypatch):
    import app.db as db

    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'flow.db')
    db.init_db()
    with db.connection() as conn:
        account_id = conn.execute(
            "INSERT INTO accounts(name,current_balance_cents) VALUES('Compte test',100000)"
        ).lastrowid

    with TestClient(app) as client:
        created = client.post('/api/recurring', json={
            'account_id': account_id,
            'label': 'Abonnement test',
            'amount_cents': -1999,
            'day_of_month': 12,
            'category': 'Loisirs',
            'frequency': 'monthly',
            'next_occurrence': '2026-10-12',
        })
        assert created.status_code == 201
        recurring_id = created.json()['id']

        updated = client.patch(f'/api/recurring/{recurring_id}', json={
            'amount_cents': -2499,
            'day_of_month': 14,
            'next_occurrence': '2026-10-14',
        })
        assert updated.status_code == 200
        assert updated.json()['amount_cents'] == -2499
        assert updated.json()['day_of_month'] == 14
        assert updated.json()['next_occurrence'] == '2026-10-14'

        disabled = client.delete(f'/api/recurring/{recurring_id}')
        assert disabled.status_code == 204


def test_recurring_frequency_drives_forecasts_and_safe_to_spend(tmp_path, monkeypatch):
    from datetime import date

    import app.db as db
    from app.financial_engine_v2 import _recurring_events
    from app.main import _recurring_forecast_events
    from app.safe_to_spend import calculate_safe_to_spend

    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'flow-frequency.db')
    db.init_db()
    with db.connection() as conn:
        account_id = conn.execute(
            """INSERT INTO accounts(
                name,current_balance_cents,balance_as_of,include_in_safe_to_spend
            ) VALUES('Compte fréquence',100000,'2026-10-03',1)"""
        ).lastrowid
        fixtures = [
            ('Hebdo', -1000, 5, 'weekly', '2026-10-05'),
            ('Mensuel', -2000, 20, 'monthly', '2026-10-20'),
            ('Trimestriel', -3000, 10, 'quarterly', '2026-10-10'),
            ('Annuel', -12000, 15, 'yearly', '2026-10-15'),
        ]
        for label, amount, day, frequency, next_occurrence in fixtures:
            conn.execute(
                """INSERT INTO recurring_transactions(
                    account_id,label,amount_cents,day_of_month,frequency,next_occurrence,
                    category,kind,certainty,is_active
                ) VALUES(?,?,?,?,?,?,?,'commitment','expected',1)""",
                (account_id, label, amount, day, frequency, next_occurrence, 'Loisirs'),
            )

        dashboard_events = _recurring_forecast_events(conn, date(2026, 10, 3))
        weekly_dashboard_dates = [
            event.due_date.isoformat()
            for event in dashboard_events
            if event.label == 'Hebdo'
        ]
        assert weekly_dashboard_dates[:5] == [
            '2026-10-05', '2026-10-12', '2026-10-19', '2026-10-26', '2026-11-02'
        ]
        assert [event.due_date.isoformat() for event in dashboard_events if event.label == 'Trimestriel'] == [
            '2026-10-10'
        ]

        v2_events = _recurring_events(conn, date(2026, 10, 3), months_ahead=1)
        weekly_v2_dates = [event.due_date.isoformat() for event in v2_events if event.label == 'Hebdo']
        assert weekly_v2_dates[:5] == [
            '2026-10-05', '2026-10-12', '2026-10-19', '2026-10-26', '2026-11-02'
        ]

        safe = calculate_safe_to_spend(
            conn,
            as_of=date(2026, 10, 3),
            horizon_days=30,
            stale_reference_date=date(2026, 10, 3),
        )
        assert safe.recurring_occurrence_count == 8
        assert safe.recurring_commitments_cents == 22000
        assert safe.calculated_safe_to_spend_cents == 78000


def test_recurring_month_status_matches_paid_and_remaining(tmp_path, monkeypatch):
    import app.db as db

    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'flow-status.db')
    db.init_db()
    with db.connection() as conn:
        account_id = conn.execute(
            "INSERT INTO accounts(name,current_balance_cents,balance_as_of) VALUES('Compte statut',100000,'2026-10-03')"
        ).lastrowid
        conn.execute(
            """INSERT INTO recurring_transactions(
                account_id,label,amount_cents,day_of_month,category,frequency,next_occurrence,is_active
            ) VALUES(?,?,?,?,?,?,?,1)""",
            (account_id, 'ABONNEMENT TEST', -1999, 2, 'Loisirs', 'monthly', '2026-10-02'),
        )
        conn.execute(
            """INSERT INTO recurring_transactions(
                account_id,label,amount_cents,day_of_month,category,frequency,next_occurrence,is_active
            ) VALUES(?,?,?,?,?,?,?,1)""",
            (account_id, 'NAVIGO TEST', -8880, 8, 'Transport', 'monthly', '2026-10-08'),
        )
        conn.execute(
            """INSERT INTO transactions(
                account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer
            ) VALUES(?,?,?,?,?,'expense',0)""",
            (account_id, '2026-10-02', -1999, 'PRLV ABONNEMENT TEST', 'Loisirs'),
        )

    with TestClient(app) as client:
        response = client.get('/api/recurring/status?month=2026-10')
        assert response.status_code == 200
        payload = response.json()
        assert payload['summary']['expected_cents'] == 10879
        assert payload['summary']['paid_cents'] == 1999
        assert payload['summary']['remaining_cents'] == 8880
        assert payload['summary']['paid_count'] == 1
        assert payload['summary']['remaining_count'] == 1
        statuses = {item['label']: item['status'] for item in payload['items']}
        assert statuses['ABONNEMENT TEST'] == 'paid'
        assert statuses['NAVIGO TEST'] in {'upcoming', 'overdue'}


def test_recurring_can_be_paused_and_reactivated(tmp_path, monkeypatch):
    import app.db as db

    monkeypatch.setattr(db, 'DB_PATH', tmp_path / 'flow-pause.db')
    db.init_db()
    with db.connection() as conn:
        account_id = conn.execute(
            "INSERT INTO accounts(name,current_balance_cents) VALUES('Compte pause',100000)"
        ).lastrowid

    with TestClient(app) as client:
        created = client.post('/api/recurring', json={
            'account_id': account_id,
            'label': 'Pause test',
            'amount_cents': -5000,
            'day_of_month': 15,
            'frequency': 'monthly',
        })
        recurring_id = created.json()['id']

        paused = client.patch(f'/api/recurring/{recurring_id}', json={'is_active': False})
        assert paused.status_code == 200
        assert paused.json()['is_active'] == 0

        active_rows = client.get('/api/recurring').json()
        assert all(item['id'] != recurring_id for item in active_rows)

        reactivated = client.patch(f'/api/recurring/{recurring_id}', json={'is_active': True})
        assert reactivated.status_code == 200
        assert reactivated.json()['is_active'] == 1
