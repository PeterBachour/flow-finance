from pathlib import Path

from app.version import VERSION

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def test_active_shell_loads_only_canonical_ui():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    assert f'/static/v4-ui.js?v={VERSION}' in html
    assert 'v63-cockpit-ui.js' not in html
    assert 'v63-cockpit.css' not in html


def test_canonical_ui_contains_decision_screens():
    script = (STATIC / 'v4-ui.js').read_text(encoding='utf-8')
    assert 'renderHome' in script
    assert 'renderMovements' in script
    assert 'renderMonth' in script
    assert 'renderWealth' in script
    assert 'openSimulation' in script
    assert '/api/dashboard' in script
    assert '/api/simulations' in script


def test_active_version_is_consistent():
    assert f"VERSION = '{VERSION}'" in (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
