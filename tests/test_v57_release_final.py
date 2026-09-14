from pathlib import Path

from app.v3_routes import changelog
from app.version import VERSION


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def test_v57_release_surfaces_are_synchronized():
    runtime = (STATIC / 'v4-ui.js').read_text(encoding='utf-8')
    index = (STATIC / 'index.html').read_text(encoding='utf-8')
    service_worker = (STATIC / 'sw.js').read_text(encoding='utf-8')
    manifest = (STATIC / 'manifest.webmanifest').read_text(encoding='utf-8')

    assert VERSION == '6.3.0'
    assert "const VERSION='6.3.0';" in runtime
    assert "const VERSION='6.3.0';" in service_worker
    assert '?v=6.3.0' in index
    assert '?v=5.5.0' not in index
    assert '?v=6.3.0' in service_worker
    assert '?v=5.5.0' not in service_worker
    assert '?v=6.3.0' in manifest
    assert '?v=5.5.0' not in manifest


def test_v57_action_center_contract_is_loaded_and_read_only():
    routes = (ROOT / 'app' / 'workspace_routes.py').read_text(encoding='utf-8')
    service = (ROOT / 'app' / 'data_quality_actions.py').read_text(encoding='utf-8')
    ui = (STATIC / 'v57-data-quality-ui.js').read_text(encoding='utf-8')

    assert 'from .v57_routes import router as v57_router' in routes
    assert 'router.include_router(v57_router)' in routes
    assert "'read_only': True" in service
    assert "'requires_confirmation': True" in service
    assert '/api/v5.7/data-quality-actions?months=24' in ui
    assert 'expected_document' in ui
    assert 'unlocks' in ui


def test_v57_release_is_first_in_exposed_changelog():
    data = changelog()
    assert data['releases'][0]['version'] == '6.3.0'
    assert data['releases'][0]['title'] == 'Flow V6.3 — Cockpit prédictif'
    assert data['releases'][0]['highlights']
