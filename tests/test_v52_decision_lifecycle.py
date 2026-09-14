from pathlib import Path

import pytest
from fastapi import HTTPException

import app.v5_routes as routes
import app.v52_decisions as decisions


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def test_v52_only_financial_decisions_expose_editable_status():
    financial = decisions._normalize_financial_decision({
        'key': 'goal:7', 'type': 'goal_risk', 'priority': 'high',
        'title': 'Objectif à ajuster', 'detail': 'Contribution insuffisante.',
        'status': 'open', 'entity_id': 7,
    })
    recommendation = decisions._normalize_recommendation({
        'key': 'keep_daily_pace', 'kind': 'pace', 'priority': 'positive',
        'title': 'Maintenir le rythme', 'explanation': 'Stable.',
        'suggested_action': 'Continuer.', 'source': 'decision_cockpit',
        'read_only': True,
    })
    assert financial['status_editable'] is True
    assert financial['status'] == 'open'
    assert recommendation['status_editable'] is False
    assert recommendation['read_only'] is True


def test_v52_status_update_delegates_to_existing_inbox_for_real_decision(monkeypatch):
    monkeypatch.setattr(routes, 'financial_decisions', lambda include_closed=False: {
        'items': [{'key': 'goal:7', 'type': 'goal_risk', 'status': 'open'}]
    })
    calls = []

    def fake_set(item_key, payload):
        calls.append((item_key, payload.status, payload.note))
        return {'key': item_key, 'status': payload.status, 'note': payload.note}

    monkeypatch.setattr(routes, 'set_inbox_status', fake_set)
    payload = routes.InboxStatusIn(status='done', note='Traité depuis V5.2')
    result = routes.update_decision_center_status('goal:7', payload)

    assert calls == [('goal:7', 'done', 'Traité depuis V5.2')]
    assert result['origin'] == 'financial_decision'
    assert result['financial_data_changed'] is False


def test_v52_status_update_rejects_model_recommendation(monkeypatch):
    monkeypatch.setattr(routes, 'financial_decisions', lambda include_closed=False: {
        'items': [{'key': 'goal:7', 'type': 'goal_risk', 'status': 'open'}]
    })
    with pytest.raises(HTTPException) as exc:
        routes.update_decision_center_status(
            'keep_daily_pace',
            routes.InboxStatusIn(status='dismissed', note=None),
        )
    assert exc.value.status_code == 409
    assert 'recommandations V5 restent en lecture seule' in str(exc.value.detail)


def test_v52_lifecycle_ui_mutates_only_decision_status_contract():
    js = (STATIC / 'v5-recommendations-ui.js').read_text(encoding='utf-8')
    route_source = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    assert 'status_editable?' in js
    assert 'data-v52-status="done"' in js
    assert 'data-v52-status="dismissed"' in js
    assert "method:'PATCH'" in js
    assert '/api/v5/decision-center/${encodeURIComponent(key)}' in js
    assert '/api/finance/' not in js
    assert '/api/v4.10/goals/' not in js
    assert 'financial_decisions(include_closed=True)' in route_source
    assert 'set_inbox_status(item_key, payload)' in route_source
    assert 'INSERT INTO transactions' not in route_source
    assert 'UPDATE transactions' not in route_source
