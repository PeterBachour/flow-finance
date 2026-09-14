from datetime import date
from pathlib import Path

import app.v53_home_snapshot as home_snapshot


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def test_v53_home_snapshot_builds_each_financial_layer_once_and_reuses_identity(monkeypatch):
    cockpit = {'decision': {'safe_until_income_cents': 50000}}
    plan = {'projection': {'months': []}}
    recommendations = {'recommendations': [], 'status': 'stable', 'actionable_count': 0, 'primary': None}
    predictive = {'risk': {'score': 12}, 'recommendations': {'items': []}}
    decision_center = {'items': [], 'recent_closed': [], 'primary': None}
    calls = {'cockpit': 0, 'plan': 0, 'recommendations': 0, 'predictive': 0, 'decision_center': 0}

    def fake_cockpit(*args, **kwargs):
        calls['cockpit'] += 1
        return cockpit

    def fake_plan(*args, **kwargs):
        calls['plan'] += 1
        return plan

    def fake_recommendations(*args, **kwargs):
        calls['recommendations'] += 1
        assert kwargs['cockpit'] is cockpit
        assert kwargs['plan'] is plan
        return recommendations

    def fake_predictive(*args, **kwargs):
        calls['predictive'] += 1
        assert kwargs['cockpit'] is cockpit
        assert kwargs['plan'] is plan
        assert kwargs['recommendations'] is recommendations
        return predictive

    def fake_decision_center(*args, **kwargs):
        calls['decision_center'] += 1
        assert kwargs['recommendations'] is recommendations
        return decision_center

    monkeypatch.setattr(home_snapshot, 'build_v5_cockpit', fake_cockpit)
    monkeypatch.setattr(home_snapshot, 'build_v5_plan', fake_plan)
    monkeypatch.setattr(home_snapshot, 'build_v5_recommendations', fake_recommendations)
    monkeypatch.setattr(home_snapshot, 'build_v5_predictive_pilot', fake_predictive)
    monkeypatch.setattr(home_snapshot, 'build_v52_decision_center', fake_decision_center)

    result = home_snapshot.build_v53_home_snapshot(
        object(),
        as_of=date(2026, 9, 11),
        all_financial_decisions=[],
        quality_review_count=3,
        months=6,
    )

    assert calls == {'cockpit': 1, 'plan': 1, 'recommendations': 1, 'predictive': 1, 'decision_center': 1}
    assert result['cockpit']['decision'] is cockpit['decision']
    assert result['predictive'] is predictive
    assert result['decision_center'] is decision_center
    assert result['engine_context']['shared_home_snapshot'] is True


def test_v53_home_snapshot_selects_open_financial_decisions_like_v47_priority_order():
    items = [
        {'key': 'z', 'type': 'goal_risk', 'priority': 'medium', 'status': 'open'},
        {'key': 'b', 'type': 'missing_expected', 'priority': 'high', 'status': 'open'},
        {'key': 'a', 'type': 'missing_expected', 'priority': 'high', 'status': 'open'},
        {'key': 'closed', 'type': 'goal_risk', 'priority': 'high', 'status': 'done'},
        {'key': 'low', 'type': 'stale_balance', 'priority': 'low', 'status': 'open'},
    ]

    selected = home_snapshot.select_open_financial_decisions(items)

    assert [item['key'] for item in selected] == ['a', 'b', 'z', 'low']
    assert all(item['status'] == 'open' for item in selected)


def test_v53_home_frontend_uses_one_shared_get_contract_for_three_overlays():
    home_js = (STATIC / 'v5-home-ui.js').read_text(encoding='utf-8')
    decision_js = (STATIC / 'v5-recommendations-ui.js').read_text(encoding='utf-8')
    predictive_js = (STATIC / 'v5-predictive-ui.js').read_text(encoding='utf-8')

    assert home_js.count("fetch('/api/v5/home-snapshot?months=6'") == 1
    assert 'window.FlowV5HomeSnapshot' in home_js
    assert 'snapshot.cockpit' in home_js
    assert 'window.FlowV5HomeSnapshot.get' in decision_js
    assert 'snapshot.decision_center' in decision_js
    assert 'window.FlowV5HomeSnapshot.get' in predictive_js
    assert 'snapshot.predictive' in predictive_js
    assert '/api/v5/decision-center?months=6' not in decision_js
    assert '/api/v5/predictive-pilot?months=6' not in predictive_js
    assert 'FlowV5HomeSnapshot.invalidate' in decision_js


def test_v53_home_snapshot_remains_read_only_in_later_v5_releases():
    service = (ROOT / 'app' / 'v53_home_snapshot.py').read_text(encoding='utf-8')
    routes = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')

    assert "@router.get('/home-snapshot')" in routes
    assert "'schema_version': '5.3'" in service
    assert "'schema_version': '5.3-rc'" not in service
    assert "'cockpit_builds': 1" in service
    assert "'plan_builds': 1" in service
    assert 'INSERT INTO ' not in service
    assert 'UPDATE ' not in service
    assert 'DELETE FROM ' not in service
