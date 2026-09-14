from pathlib import Path
import re

from app.v5_predictive import _clamp, _risk_level


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _runtime_version() -> str:
    text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert match
    return match.group(1)


def test_predictive_risk_helpers_are_bounded_and_ordered():
    assert _clamp(-50) == 0
    assert _clamp(140) == 100
    assert _risk_level(10) == 'low'
    assert _risk_level(30) == 'watch'
    assert _risk_level(60) == 'high'
    assert _risk_level(90) == 'critical'


def test_predictive_engine_is_explainable_and_read_only():
    code = (ROOT / 'app' / 'v5_predictive.py').read_text(encoding='utf-8')
    assert "liquidity_score * 0.45" in code
    assert "goal_score * 0.25" in code
    assert "confidence_score * 0.20" in code
    assert "event_score * 0.10" in code
    assert "Pilotage prédictif en lecture seule" in code
    assert 'INSERT INTO ' not in code
    assert 'UPDATE ' not in code
    assert 'DELETE FROM ' not in code


def test_predictive_endpoint_and_assets_are_wired():
    routes = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    version = _runtime_version()
    assert "@router.get('/predictive-pilot')" in routes
    assert "@router.get('/home-snapshot')" in routes
    assert f'v5-predictive.css?v={version}' in html
    assert f'v5-predictive-ui.js?v={version}' in html
    assert f'v5-predictive.css?v={version}' in sw
    assert f'v5-predictive-ui.js?v={version}' in sw


def test_predictive_ui_reads_shared_v5_home_snapshot():
    js = (STATIC / 'v5-predictive-ui.js').read_text(encoding='utf-8')
    assert 'window.FlowV5HomeSnapshot.get' in js
    assert 'snapshot.predictive' in js
    assert '/api/v5/predictive-pilot?months=6' not in js
    assert "method:'POST'" not in js
    assert "method:'PATCH'" not in js
    assert "method:'DELETE'" not in js
    assert '/api/finance/' not in js
    assert '/api/v3' not in js
