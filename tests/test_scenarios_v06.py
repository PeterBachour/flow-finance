from datetime import date

from app import scenario_routes


def _dashboard(safe=50000, low=60000):
    forecast = {
        'safe_to_spend_cents': safe,
        'low_point': {'date': '2026-09-20', 'balance_cents': low},
        'closing_balance_cents': low,
    }
    return {'as_of': '2026-09-08', 'projections': {'realistic': forecast}}


def test_decision_never_persists(monkeypatch):
    calls = []
    monkeypatch.setattr(scenario_routes, 'dashboard_v2_data', lambda events=None: calls.append(events or []) or _dashboard())
    result = scenario_routes.evaluate_decision(scenario_routes.DecisionIn(amount_cents=10000, due_date=date(2026, 9, 20), label='Test'))
    assert result['persisted'] is False
    assert [s['name'] for s in result['scenarios']] == ['Normal', 'Prudent', 'Exceptionnel']
    assert len(calls) == 4


def test_prudent_adds_minimum_100_euro_margin(monkeypatch):
    captured = []
    monkeypatch.setattr(scenario_routes, 'dashboard_v2_data', lambda events=None: captured.append(events or []) or _dashboard())
    scenario_routes.evaluate_decision(scenario_routes.DecisionIn(amount_cents=5000, due_date=date(2026, 9, 20), label='Petit achat'))
    prudent_events = captured[2]
    assert any(e.label == 'Marge prudente' and e.amount_cents == -10000 for e in prudent_events)


def test_exceptional_uses_requested_buffer(monkeypatch):
    captured = []
    monkeypatch.setattr(scenario_routes, 'dashboard_v2_data', lambda events=None: captured.append(events or []) or _dashboard())
    scenario_routes.evaluate_decision(scenario_routes.DecisionIn(amount_cents=20000, due_date=date(2026, 9, 20), exceptional_buffer_cents=45000))
    exceptional_events = captured[3]
    assert any(e.label == 'Imprévu exceptionnel' and e.amount_cents == -45000 for e in exceptional_events)
