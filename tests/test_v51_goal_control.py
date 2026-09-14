from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def test_v51_goal_engine_reuses_existing_projection_and_plan_without_mutation():
    code = (ROOT / 'app' / 'v51_goals.py').read_text(encoding='utf-8')
    assert 'from .v33_routes import _goal_projection' in code
    assert 'from .v5_planning import build_v5_plan' in code
    assert 'INSERT INTO financial_goals' not in code
    assert 'UPDATE financial_goals' not in code
    assert 'DELETE FROM financial_goals' not in code
    assert "'persisted': False" in code


def test_v51_goal_control_exposes_required_recommended_and_capacity_values():
    code = (ROOT / 'app' / 'v51_goals.py').read_text(encoding='utf-8')
    for field in (
        'required_monthly_cents',
        'recommended_monthly_cents',
        'funding_gap_cents',
        'monthly_capacity_cents',
        'unallocated_monthly_capacity_cents',
        'projected_gap_cents',
    ):
        assert field in code
    assert 'goal_progress_history' in code


def test_v51_goal_routes_are_v5_and_simulation_is_separate_from_real_update():
    routes = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    assert "@router.get('/goals-control')" in routes
    assert "@router.post('/goals/{goal_id}/simulate-contribution')" in routes
    assert 'simulate_goal_contribution' in routes
    assert '/api/v4.10/goals/' not in routes


def test_v51_goal_ui_is_wired_through_existing_v51_assets():
    js = (STATIC / 'v51-scenarios-ui.js').read_text(encoding='utf-8')
    css = (STATIC / 'v51-scenarios.css').read_text(encoding='utf-8')
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    version_text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    version = version_text.split("'")[1]

    assert '/api/v5/goals-control?months=12' in js
    assert '/api/v5/goals/${card.dataset.goalId}/simulate-contribution' in js
    assert '/api/v4.10/goals/' not in js
    assert 'aucune modification enregistrée' in js
    assert '.v51-goals-card' in css
    assert f'v51-scenarios-ui.js?v={version}' in html
    assert f'v51-scenarios.css?v={version}' in html
    assert f'/static/v51-scenarios-ui.js?v={version}' in sw
    assert f'/static/v51-scenarios.css?v={version}' in sw
