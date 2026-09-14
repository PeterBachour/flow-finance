from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _runtime_version() -> str:
    text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert match, 'app/version.py must expose VERSION'
    return match.group(1)


def test_release_candidate_version_is_aligned_across_runtime_and_assets():
    version = _runtime_version()
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    runtime = (STATIC / 'v4-ui.js').read_text(encoding='utf-8')

    assert f"const VERSION='{version}'" in sw
    assert f"const VERSION='{version}'" in runtime

    asset_versions = set(re.findall(r'\?v=([0-9]+\.[0-9]+\.[0-9]+)', html))
    assert asset_versions == {version}


def test_v5_home_has_one_decision_overlay_and_legacy_overlay_is_not_loaded():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')

    assert 'home-canonical-ui.js' not in html
    assert 'home-canonical-ui.js' not in sw
    assert html.count('v5-home-ui.js') == 1
    assert 'v5-planning-ui.js' in html
    assert 'v5-recommendations-ui.js' in html
    assert 'v5-predictive-ui.js' in html


def test_v5_frontend_contracts_do_not_read_legacy_financial_endpoints():
    files = [
        'v5-home-ui.js',
        'v5-planning-ui.js',
        'v5-recommendations-ui.js',
        'v5-predictive-ui.js',
    ]
    for filename in files:
        text = (STATIC / filename).read_text(encoding='utf-8')
        assert '/api/v3' not in text, filename
        assert '/api/v4' not in text, filename
        assert '/api/finance/' not in text, filename
        assert '/api/v5/' in text or 'FlowV5HomeSnapshot' in text, filename

    home = (STATIC / 'v5-home-ui.js').read_text(encoding='utf-8')
    predictive = (STATIC / 'v5-predictive-ui.js').read_text(encoding='utf-8')
    assert '/api/v5/home-snapshot?months=6' in home
    assert 'FlowV5HomeSnapshot' in predictive
    assert '/api/v5/predictive-pilot?months=6' not in predictive


def test_v5_backend_exposes_complete_release_candidate_contract():
    routes = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    workspace = (ROOT / 'app' / 'workspace_routes.py').read_text(encoding='utf-8')

    for endpoint in ("'/cockpit'", "'/plan'", "'/scenario'", "'/recommendations'", "'/predictive-pilot'"):
        assert endpoint in routes
    assert "'/home-snapshot'" in routes
    assert 'v5_router' in workspace
