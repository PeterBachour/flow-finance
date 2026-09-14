from pathlib import Path
import re

from app.v3_routes import changelog


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _runtime_version() -> str:
    text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert match, 'app/version.py must expose VERSION'
    return match.group(1)


def test_flow_v5_runtime_version_is_aligned_across_backend_frontend_and_pwa():
    version = _runtime_version()
    runtime = (STATIC / 'v4-ui.js').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    html = (STATIC / 'index.html').read_text(encoding='utf-8')

    assert f"const VERSION='{version}'" in runtime
    assert f"const VERSION='{version}'" in sw

    asset_versions = re.findall(r'\?v=([0-9]+\.[0-9]+\.[0-9]+)', html)
    assert asset_versions
    assert set(asset_versions) == {version}
    assert f'flow-v${{VERSION}}' in sw


def test_current_runtime_is_first_release_exposed_by_changelog_api():
    version = _runtime_version()
    data = changelog()
    assert data['releases'][0]['version'] == version
    assert data['releases'][0]['title'].startswith(f'Flow V{version.split(".")[0]}')
    assert data['releases'][0]['highlights']


def test_flow_v5_runtime_keeps_single_home_overlay_and_v51_assets():
    version = _runtime_version()
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')

    assert html.count(f'v5-home-ui.js?v={version}') == 1
    assert f'v51-events-ui.js?v={version}' in html
    assert f'v51-scenarios-ui.js?v={version}' in html
    assert f'/static/v51-events-ui.js?v={version}' in sw
    assert f'/static/v51-scenarios-ui.js?v={version}' in sw
    assert 'home-canonical-ui.js' not in html
    assert 'home-canonical-ui.js' not in sw
