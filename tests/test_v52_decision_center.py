from datetime import date
from pathlib import Path

import app.v52_decisions as decisions


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def test_v52_merge_deduplicates_same_financial_key_and_keeps_context():
    recommendation = {
        'key': 'goal:7', 'kind': 'goal', 'priority': 'high', 'title': 'Ajuster objectif',
        'explanation': 'Écart projeté.', 'suggested_action': 'Revoir contribution.',
        'source': 'goal_arbitration', 'impact_cents': 12000, 'evidence': {'gap': 12000},
        'read_only': True,
    }
    financial = {
        'key': 'goal:7', 'type': 'goal_risk', 'priority': 'high', 'title': 'Objectif à risque',
        'detail': 'Contribution insuffisante.', 'amount_cents': None, 'entity_id': 7, 'status': 'open',
    }
    merged = decisions._merge_items([recommendation], [financial])
    assert len(merged) == 1
    assert merged[0]['key'] == 'goal:7'
    assert merged[0]['origin'] == 'financial_decision'
    assert merged[0]['status_editable'] is True
    assert merged[0]['impact_cents'] == 12000
    assert merged[0]['recommendation_context']['source'] == 'goal_arbitration'


def test_v52_decision_center_keeps_quality_reviews_outside_financial_items(monkeypatch):
    monkeypatch.setattr(decisions, 'build_v5_recommendations', lambda *a, **k: {
        'recommendations': [{
            'key': 'keep_daily_pace', 'kind': 'pace', 'priority': 'positive',
            'title': 'Maintenir le rythme', 'explanation': 'Stable',
            'suggested_action': 'Continuer', 'source': 'decision_cockpit',
            'impact_cents': 2500, 'evidence': {}, 'read_only': True,
        }]
    })
    result = decisions.build_v52_decision_center(
        object(),
        as_of=date(2026, 9, 11),
        financial_decisions=[{
            'key': 'overdue:3', 'type': 'missing_expected', 'priority': 'high',
            'title': 'Échéance attendue', 'detail': 'À vérifier', 'amount_cents': -5000,
        }],
        quality_review_count=9,
        months=6,
    )
    assert result['quality_review_count'] == 9
    assert result['financial_choice_count'] == 1
    assert result['recommendation_count'] == 1
    assert result['primary']['key'] == 'overdue:3'
    assert all(item.get('kind') != 'import_review' for item in result['items'])
    recommendation = next(item for item in result['items'] if item['origin'] == 'recommendation')
    assert recommendation['status_editable'] is False


def test_v52_decision_center_service_stays_financially_read_only_and_exposed_by_v5_router():
    service = (ROOT / 'app' / 'v52_decisions.py').read_text(encoding='utf-8')
    routes = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    assert 'INSERT INTO ' not in service
    assert 'UPDATE ' not in service
    assert 'DELETE FROM ' not in service
    assert "@router.get('/decision-center')" in routes
    assert "@router.get('/home-snapshot')" in routes
    assert "@router.patch('/decision-center/{item_key:path}')" in routes
    assert 'build_v52_decision_center' in routes
    assert 'quality_review_count' in routes
    assert "'financial_data_changed': False" in routes


def test_v52_home_uses_unified_decision_contract_and_status_only_for_choices():
    js = (STATIC / 'v5-recommendations-ui.js').read_text(encoding='utf-8')
    assert 'window.FlowV5HomeSnapshot.get' in js
    assert 'snapshot.decision_center' in js
    assert "/api/v5/recommendations?months=6" not in js
    assert 'Choix financier' in js
    assert 'revue(s) de qualité de données' in js
    assert 'data-v52-go' in js
    assert 'status_editable' in js
    assert 'data-v52-status' in js
    assert "method:'POST'" not in js
    assert "method:'PATCH'" in js
    assert "method:'DELETE'" not in js
