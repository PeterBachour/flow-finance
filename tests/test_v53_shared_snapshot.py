from datetime import date
from pathlib import Path

import app.v5_predictive as predictive
import app.v5_recommendations as recommendations


ROOT = Path(__file__).resolve().parents[1]


def _cockpit():
    return {
        'decision': {'safe_until_income_cents': 50000, 'daily_pace_cents': 2500},
        'forecast': {
            'projected_margin_above_safety_cents': 20000,
            'projected_bank_balance_cents': 40000,
        },
        'confidence': {
            'level': 'high',
            'balance_age_days': 1,
            'current_month_observed': True,
            'historical_coverage_pct': 100,
        },
        'historical_context': {'signals': []},
    }


def _plan():
    return {
        'projection': {
            'opening_balance_cents': 100000,
            'closing_balance_cents': 85000,
            'minimum_safe_margin_cents': 30000,
            'protected_cents': 20000,
            'low_point': {'balance_cents': 50000},
            'months': [{
                'month': '2026-09',
                'closing_balance_cents': 85000,
                'low_point_cents': 50000,
                'safe_margin_cents': 30000,
                'events': [],
            }],
        },
        'goal_arbitration': {
            'monthly_capacity_cents': 20000,
            'unallocated_monthly_capacity_cents': 20000,
            'goals': [],
        },
    }


def test_v53_recommendations_reuse_precomputed_cockpit_and_plan(monkeypatch):
    cockpit = _cockpit()
    plan = _plan()

    def unexpected(*args, **kwargs):
        raise AssertionError('builder must not run when a precomputed snapshot is supplied')

    monkeypatch.setattr(recommendations, 'build_v5_cockpit', unexpected)
    monkeypatch.setattr(recommendations, 'build_v5_plan', unexpected)

    result = recommendations.build_v5_recommendations(
        object(),
        as_of=date(2026, 9, 11),
        months=6,
        cockpit=cockpit,
        plan=plan,
    )

    assert result['primary']['key'] == 'keep_daily_pace'
    assert result['primary']['impact_cents'] == 2500


def test_v53_predictive_builds_cockpit_and_plan_once_then_reuses_same_objects(monkeypatch):
    cockpit = _cockpit()
    plan = _plan()
    calls = {'cockpit': 0, 'plan': 0, 'recommendations': 0}

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
        return {
            'status': 'stable',
            'actionable_count': 0,
            'primary': None,
            'recommendations': [],
        }

    monkeypatch.setattr(predictive, 'build_v5_cockpit', fake_cockpit)
    monkeypatch.setattr(predictive, 'build_v5_plan', fake_plan)
    monkeypatch.setattr(predictive, 'build_v5_recommendations', fake_recommendations)

    result = predictive.build_v5_predictive_pilot(
        object(),
        as_of=date(2026, 9, 11),
        months=6,
    )

    assert calls == {'cockpit': 1, 'plan': 1, 'recommendations': 1}
    assert result['engine_context']['shared_snapshot'] is True
    assert result['engine_context']['cockpit_reused_for_recommendations'] is True
    assert result['engine_context']['plan_reused_for_recommendations'] is True


def test_v53_shared_snapshot_keeps_predictive_financial_contract_unchanged(monkeypatch):
    monkeypatch.setattr(predictive, 'build_v5_cockpit', lambda *a, **k: _cockpit())
    monkeypatch.setattr(predictive, 'build_v5_plan', lambda *a, **k: _plan())
    monkeypatch.setattr(predictive, 'build_v5_recommendations', lambda *a, **k: {
        'status': 'stable', 'actionable_count': 0, 'primary': None, 'recommendations': []
    })

    result = predictive.build_v5_predictive_pilot(object(), as_of=date(2026, 9, 11), months=6)

    assert result['trajectory']['opening_balance_cents'] == 100000
    assert result['trajectory']['closing_balance_cents'] == 85000
    assert result['trajectory']['minimum_safe_margin_cents'] == 30000
    assert result['goals']['monthly_capacity_cents'] == 20000
    assert result['risk']['score'] >= 0
    assert result['risk']['score'] <= 100


def test_v53_snapshot_optimization_remains_read_only_in_later_v5_releases():
    predictive_source = (ROOT / 'app' / 'v5_predictive.py').read_text(encoding='utf-8')
    recommendation_source = (ROOT / 'app' / 'v5_recommendations.py').read_text(encoding='utf-8')

    for source in (predictive_source, recommendation_source):
        assert 'INSERT INTO ' not in source
        assert 'UPDATE ' not in source
        assert 'DELETE FROM ' not in source

    assert "'shared_snapshot': True" in predictive_source
    assert 'cockpit=cockpit' in predictive_source
    assert 'plan=plan' in predictive_source
