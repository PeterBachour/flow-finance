from datetime import date
from pathlib import Path
import re

import app.v5_recommendations as recommendations


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _runtime_version() -> str:
    text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert match
    return match.group(1)


def test_v5_recommendations_prioritize_liquidity_and_keep_evidence(monkeypatch):
    monkeypatch.setattr(recommendations, 'build_v5_cockpit', lambda *a, **k: {
        'decision': {'safe_until_income_cents': -5000, 'daily_pace_cents': 0},
        'forecast': {'projected_margin_above_safety_cents': -1000, 'projected_bank_balance_cents': 15000},
        'confidence': {'level': 'high', 'balance_age_days': 1},
        'historical_context': {'signals': []},
    })
    monkeypatch.setattr(recommendations, 'build_v5_plan', lambda *a, **k: {
        'goal_arbitration': {'goals': []}
    })

    result = recommendations.build_v5_recommendations(object(), as_of=date(2026, 9, 11))

    assert result['status'] == 'action_required'
    assert result['primary']['key'] == 'protect_liquidity'
    assert result['primary']['priority'] == 'critical'
    assert result['primary']['evidence']['safe_until_income_cents'] == -5000
    assert result['primary']['read_only'] is True


def test_v5_recommendations_surface_goal_funding_gap(monkeypatch):
    monkeypatch.setattr(recommendations, 'build_v5_cockpit', lambda *a, **k: {
        'decision': {'safe_until_income_cents': 50000, 'daily_pace_cents': 2500},
        'forecast': {'projected_margin_above_safety_cents': 20000, 'projected_bank_balance_cents': 40000},
        'confidence': {'level': 'high', 'balance_age_days': 1},
        'historical_context': {'signals': []},
    })
    monkeypatch.setattr(recommendations, 'build_v5_plan', lambda *a, **k: {
        'goal_arbitration': {'goals': [{
            'goal_id': 7, 'name': 'Projet', 'status': 'off_track', 'mandatory': True,
            'funding_gap_cents': 12000, 'required_monthly_cents': 30000,
            'recommended_monthly_cents': 18000,
        }]}
    })

    result = recommendations.build_v5_recommendations(object(), as_of=date(2026, 9, 11))
    goal = next(item for item in result['recommendations'] if item['kind'] == 'goal')
    assert goal['priority'] == 'high'
    assert goal['impact_cents'] == 12000
    assert goal['evidence']['required_monthly_cents'] == 30000


def test_v5_recommendations_endpoint_and_ui_keep_financial_mutations_out():
    routes = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    js = (STATIC / 'v5-recommendations-ui.js').read_text(encoding='utf-8')
    assert "@router.get('/recommendations')" in routes
    assert "@router.get('/decision-center')" in routes
    assert "@router.get('/home-snapshot')" in routes
    assert "@router.patch('/decision-center/{item_key:path}')" in routes
    assert 'window.FlowV5HomeSnapshot.get' in js
    assert 'snapshot.decision_center' in js
    assert "method:'POST'" not in js
    assert "method:'DELETE'" not in js
    assert "method:'PATCH'" in js
    assert '/api/v5/decision-center/${encodeURIComponent(key)}' in js
    assert '/api/finance/' not in js
    assert '/api/v4.10/goals/' not in js
    assert 'suggested_action' in js
    assert 'explanation' in js


def test_v5_recommendations_assets_are_wired_and_cached():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    version = _runtime_version()
    assert f'v5-recommendations-ui.js?v={version}' in html
    assert f'v5-recommendations-ui.js?v={version}' in sw
