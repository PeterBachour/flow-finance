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
