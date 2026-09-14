from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def test_v55_history_assets_remain_registered_after_release_progression():
    index = (STATIC / 'index.html').read_text(encoding='utf-8')
    service_worker = (STATIC / 'sw.js').read_text(encoding='utf-8')

    assert 'v55-history-ui.js?v=' in index
    assert 'v55-history.css?v=' in index
    assert '/static/v55-history-ui.js?v=' in service_worker
    assert '/static/v55-history.css?v=' in service_worker


def test_v55_release_contains_history_coverage_and_bulk_import_contracts():
    service = (ROOT / 'app' / 'history_coverage.py').read_text(encoding='utf-8')
    routes = (ROOT / 'app' / 'v55_routes.py').read_text(encoding='utf-8')
    ui = (STATIC / 'v55-history-ui.js').read_text(encoding='utf-8')

    assert "'read_only': True" in service
    assert "@router.get('/history-coverage')" in routes
    assert '/api/imports/bulk/analyze' in ui
    assert '/api/imports/bulk/${activeBatch}/commit' in ui


def test_v55_release_notes_remain_available_after_release_progression():
    routes = (ROOT / 'app' / 'v3_routes.py').read_text(encoding='utf-8')
    assert "'version': '5.5.0'" in routes
    assert 'Flow V5.5 — Couverture historique & import multi-documents' in routes
    assert "V55_RELEASE['version']: V55_RELEASE" in routes
