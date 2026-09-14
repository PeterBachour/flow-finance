from pathlib import Path
import re

from app.v5_planning import _scenario_rows


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _runtime_version() -> str:
    text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert match
    return match.group(1)


def test_v5_scenario_rows_preserve_cashflow_signs_and_are_ephemeral():
    from datetime import date

    rows = _scenario_rows(
        today=date(2026, 9, 11), months=6,
        one_time_expense_cents=25000,
        one_time_date=date(2026, 10, 5),
        monthly_spend_delta_cents=5000,
        monthly_income_delta_cents=10000,
    )
    assert len(rows) == 3
    assert rows[0]['amount_cents'] == -25000
    assert rows[1]['amount_cents'] == -5000
    assert rows[2]['amount_cents'] == 10000
    assert all(row.get('source_key') is None for row in rows)


def test_v5_planning_engine_is_read_only_and_reuses_existing_forecast():
    source = (ROOT / 'app' / 'v5_planning.py').read_text(encoding='utf-8')
    assert 'from .v32_routes import _forecast' in source
    assert '_goal_projection' in source
    assert 'INSERT INTO' not in source
    assert 'UPDATE ' not in source
    assert 'DELETE FROM' not in source
    assert "'persisted': False" in source
    assert 'Aucun virement ni réservation n’est exécuté' in source


def test_v5_routes_expose_plan_and_non_persistent_scenario():
    source = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    workspace = (ROOT / 'app' / 'workspace_routes.py').read_text(encoding='utf-8')
    assert "@router.get('/plan')" in source
    assert "@router.post('/scenario')" in source
    assert 'build_v5_plan' in source
    assert 'build_v5_scenario' in source
    assert 'v5_router' in workspace


def test_v5_planning_ui_uses_only_v5_planning_contracts_and_is_wired():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    js = (STATIC / 'v5-planning-ui.js').read_text(encoding='utf-8')
    css = (STATIC / 'v5-planning.css').read_text(encoding='utf-8')
    version = _runtime_version()

    assert f'v5-planning-ui.js?v={version}' in html
    assert f'v5-planning.css?v={version}' in html
    assert f'v5-planning-ui.js?v={version}' in sw
    assert f'v5-planning.css?v={version}' in sw
    assert '/api/v5/plan?months=6' in js
    assert '/api/v5/scenario' in js
    assert '/api/v3.2/' not in js
    assert '/api/v3.3/' not in js
    assert '/api/v3.8/' not in js
    assert 'v5-plan-chart' in css
