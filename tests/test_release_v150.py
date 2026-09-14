import json
from pathlib import Path

from app.version import VERSION
from app.v3_routes import changelog

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def test_release_version_is_aligned():
    assert tuple(map(int, VERSION.split('.'))) >= (4, 0, 0)
    sw = (STATIC / 'sw.js').read_text()
    assert f"const VERSION='{VERSION}'" in sw
    assert "flow-v${VERSION}" in sw


def test_manifest_uses_versioned_real_png_icons():
    manifest = json.loads((STATIC / 'manifest.webmanifest').read_text())
    icons = manifest['icons']
    assert any(i['sizes'] == '192x192' and i['type'] == 'image/png' for i in icons)
    assert any(i['sizes'] == '512x512' and i['purpose'] == 'any' for i in icons)
    assert any(i['sizes'] == '512x512' and i['purpose'] == 'maskable' for i in icons)
    assert all(f'v={VERSION}' in i['src'] for i in icons)
    for asset in ('icon-192.png','icon-512.png','icon-maskable-512.png','apple-touch-icon.png'):
        assert (STATIC / asset).read_bytes().startswith(b'\x89PNG\r\n\x1a\n')


def test_v4_runtime_is_consolidated():
    index = (STATIC / 'index.html').read_text()
    sw = (STATIC / 'sw.js').read_text()
    assert f'/static/app.css?v={VERSION}' in index
    assert f'/static/v4-ui.js?v={VERSION}' in index
    assert f'/static/app.css?v={VERSION}' in sw
    assert f'/static/v4-ui.js?v={VERSION}' in sw
    for legacy in ('v3-ui.js','v31-ui.js','v32-ui.js','v33-ui.js','v34-ui.js','v35-ui.js','v36-ui.js','v3.css'):
        assert legacy not in index
        assert legacy not in sw


def test_service_worker_is_network_only_for_apis():
    sw = (STATIC / 'sw.js').read_text()
    assert '/static/changelog.json' in sw
    assert "url.pathname.startsWith('/api/')" in sw
    assert "fetch(event.request,{cache:'no-store'})" in sw
    assert 'skipWaiting()' in sw
    assert 'clients.claim()' in sw


def test_changelog_contains_v4_and_intermediate_releases():
    static_data = json.loads((STATIC / 'changelog.json').read_text())
    assert any(r['version'] == '4.0.0' for r in static_data['releases'])
    assert any(r['version'] == '3.8.0' for r in static_data['releases'])
    assert any(r['version'] == '3.7.0' for r in static_data['releases'])
    assert any(r['version'] == '3.6.0' for r in static_data['releases'])

    exposed = changelog()
    assert exposed['releases'][0]['version'] == VERSION
    assert exposed['releases'][0]['highlights']


def test_update_helper_safety_invariants():
    helper = (ROOT / 'maintenance' / 'update_helper.py').read_text()
    assert "status', '--porcelain'" in helper
    assert "merge', '--ff-only', 'origin/main'" in helper
    assert 'validate_python_ref' in helper
    assert 'smoke_built_image' in helper
    assert 'wait_for_runtime' in helper
    assert 'rollback_runtime' in helper
    assert "'/api/health'" in helper
    assert "'/api/version'" in helper
    assert "'/api/v3/system'" in helper
    assert 'flock' in helper
    assert "'build', 'flow-finance'" in helper
    assert "'--no-deps', 'flow-finance'" in helper
    assert 'reset --hard' not in helper
    assert 'clean -fd' not in helper


def test_docker_build_and_runtime_have_health_barriers():
    compose = (ROOT / 'docker-compose.yml').read_text()
    dockerfile = (ROOT / 'Dockerfile').read_text()
    assert './data:/data' in compose
    assert 'FLOW_DB_PATH: /data/flow.db' in compose
    assert 'healthcheck:' in compose
    assert '/api/health' in compose
    assert 'python -m compileall -q app' in dockerfile
    assert 'HEALTHCHECK' in dockerfile
    assert '/api/health' in dockerfile
    assert 'COPY app ./app' in dockerfile
