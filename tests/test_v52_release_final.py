from pathlib import Path
import json
import re


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _version() -> str:
    text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert match
    return match.group(1)


def test_v52_is_released_and_decision_contract_is_final():
    version = _version()
    assert tuple(map(int, version.split('.'))) >= (5, 2, 0)
    service = (ROOT / 'app' / 'v52_decisions.py').read_text(encoding='utf-8')
    assert "'schema_version': '5.2'" in service
    assert "'schema_version': '5.2-rc'" not in service


def test_v52_release_keeps_decision_center_and_guarded_lifecycle():
    routes = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    assert "@router.get('/decision-center')" in routes
    assert "@router.patch('/decision-center/{item_key:path}')" in routes
    assert 'financial_decisions(include_closed=True)' in routes
    assert "'financial_data_changed': False" in routes
    assert 'recommandations V5 restent en lecture seule' in routes
    assert 'INSERT INTO transactions' not in routes
    assert 'UPDATE transactions' not in routes


def test_v52_release_ui_exposes_unified_decisions_history_and_reopen():
    js = (STATIC / 'v5-recommendations-ui.js').read_text(encoding='utf-8')
    home = (STATIC / 'v5-home-ui.js').read_text(encoding='utf-8')
    routes = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')

    assert 'FlowV5HomeSnapshot' in js
    assert '/api/v5/decision-center?months=6' not in js
    assert '/api/v5/home-snapshot?months=6' in home
    assert "@router.get('/decision-center')" in routes
    assert '/api/v5/decision-center/${encodeURIComponent(key)}' in js
    assert 'Choix financier' in js
    assert 'Historique récent' in js
    assert 'Rouvrir' in js
    assert 'Note facultative' in js


def test_v52_release_changelog_and_assets_follow_runtime_version():
    version = _version()
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    changelog = json.loads((STATIC / 'changelog.json').read_text(encoding='utf-8'))
    release = next(item for item in changelog['releases'] if item['version'] == '5.2.0')
    assert release['title'].startswith('Flow V5.2')
    assert any('91 tests' in item for item in release['highlights'])
    assert f"const VERSION='{version}'" in sw
    asset_versions = re.findall(r'\?v=([0-9]+\.[0-9]+\.[0-9]+)', html)
    assert asset_versions and set(asset_versions) == {version}
