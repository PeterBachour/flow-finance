from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def test_v55_router_is_registered_and_read_only_contract_is_exposed():
    workspace = (ROOT / 'app' / 'workspace_routes.py').read_text(encoding='utf-8')
    routes = (ROOT / 'app' / 'v55_routes.py').read_text(encoding='utf-8')
    service = (ROOT / 'app' / 'history_coverage.py').read_text(encoding='utf-8')

    assert 'from .v55_routes import router as v55_router' in workspace
    assert 'router.include_router(v55_router)' in workspace
    assert "router = APIRouter(prefix='/api/v5.5'" in routes
    assert "@router.get('/history-coverage')" in routes
    assert "'read_only': True" in service
    assert 'INSERT INTO ' not in service
    assert 'UPDATE ' not in service
    assert 'DELETE FROM ' not in service


def test_v55_history_assets_are_loaded_and_cached():
    index = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    ui = (STATIC / 'v55-history-ui.js').read_text(encoding='utf-8')

    assert '/static/v55-history.css?v=' in index
    assert '/static/v55-history-ui.js?v=' in index
    assert '/static/v55-history.css?v=' in sw
    assert '/static/v55-history-ui.js?v=' in sw
    assert '/api/v5.5/history-coverage?months=24' in ui
    assert '/api/imports/bulk/analyze' in ui
    assert '/api/imports/bulk/${activeBatch}/commit' in ui
    assert "method:'DELETE'" in ui
