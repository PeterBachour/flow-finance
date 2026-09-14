from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _version() -> str:
    text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert match
    return match.group(1)


def test_v51_scenarios_reuse_existing_forecast_tables_and_engine():
    source = (ROOT / 'app' / 'v51_scenarios.py').read_text(encoding='utf-8')
    assert 'forecast_scenarios' in source
    assert 'forecast_scenario_events' in source
    assert 'ensure_v32_schema' in source
    assert 'from .v32_routes import _forecast' in source
    assert 'CREATE TABLE' not in source


def test_v51_saved_scenarios_never_write_real_transactions():
    source = (ROOT / 'app' / 'v51_scenarios.py').read_text(encoding='utf-8')
    assert 'INSERT INTO transactions' not in source
    assert 'UPDATE transactions' not in source
    assert 'DELETE FROM transactions' not in source
    assert "'affects_real_transactions': False" in source
    assert 'forecast_scenarios' in source
    assert 'forecast_scenario_events' in source
    assert 'ne modifie jamais le ledger bancaire' in source


def test_v51_scenario_routes_expose_save_compare_and_soft_delete():
    routes = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    service = (ROOT / 'app' / 'v51_scenarios.py').read_text(encoding='utf-8')
    assert "@router.get('/scenarios')" in routes
    assert "@router.post('/scenarios'" in routes
    assert "@router.get('/scenarios/{scenario_id}/compare')" in routes
    assert "@router.delete('/scenarios/{scenario_id}'" in routes
    assert 'SET is_active=0' in service


def test_v51_scenario_ui_uses_only_v5_contract_and_is_version_aligned():
    version = _version()
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    js = (STATIC / 'v51-scenarios-ui.js').read_text(encoding='utf-8')
    css = (STATIC / 'v51-scenarios.css').read_text(encoding='utf-8')
    assert f'v51-scenarios-ui.js?v={version}' in html
    assert f'v51-scenarios.css?v={version}' in html
    assert f'v51-scenarios-ui.js?v={version}' in sw
    assert f'v51-scenarios.css?v={version}' in sw
    assert '/api/v5/scenarios' in js
    assert '/api/v3.2/' not in js
    assert 'affectent jamais le ledger bancaire' in js
    assert '.v51-scenarios-card' in css
