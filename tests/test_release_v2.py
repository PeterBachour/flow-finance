from pathlib import Path

from app.version import VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_v2_to_v38_runtime_are_wired_and_legacy_apis_remain_available():
    workspace = (ROOT / 'app' / 'workspace_routes.py').read_text()
    v2 = (ROOT / 'app' / 'v2_routes.py').read_text()
    for name in ('v2_router','v21_router','v22_router','v23_router','v24_router','v3_router','v31_router','v32_router','v33_router','v34_router','v35_router','v36_router','v37_router','v38_router'):
        assert f'router.include_router({name})' in workspace
    for endpoint in ('/cockpit','/months/{month}','/trends','/movements','/wealth','/data-quality','/paychecks','/simulate','/diagnostics'):
        assert endpoint in v2
    assert "prefix='/api/v3.7'" in (ROOT / 'app' / 'v37_routes.py').read_text()
    assert "prefix='/api/v3.8'" in (ROOT / 'app' / 'v38_routes.py').read_text()


def test_v4_frontend_is_single_runtime():
    index = (ROOT / 'app' / 'static' / 'index.html').read_text()
    sw = (ROOT / 'app' / 'static' / 'sw.js').read_text()
    ui = (ROOT / 'app' / 'static' / 'v4-ui.js').read_text()
    assert f'/static/app.css?v={VERSION}' in index
    assert f'/static/v4-ui.js?v={VERSION}' in index
    assert f"const VERSION='{VERSION}'" in ui
    assert "updateViaCache:'none'" in ui
    assert index.count('data-nav="home"') >= 2
    assert index.count('data-nav="month"') == 1
    assert index.count('data-nav="movements"') == 1
    assert index.count('data-nav="wealth"') == 1
    assert 'data-nav="more"' not in index
    for asset in ('v3-ui.js','v31-ui.js','v32-ui.js','v33-ui.js','v34-ui.js','v35-ui.js','v36-ui.js'):
        assert asset not in index
        assert asset not in sw


def test_v37_data_intelligence_is_explainable_and_non_destructive():
    routes = (ROOT / 'app' / 'v37_routes.py').read_text()
    migration = (ROOT / 'app' / 'v37_migrations.py').read_text()
    for value in ('quality_score','merchant_suggestions','large_expense','low_confidence'):
        assert value in routes
    assert 'Les suggestions marchand ne modifient jamais les transactions sans validation explicite' in routes
    assert 'CREATE TABLE IF NOT EXISTS merchant_aliases' in migration
    assert 'DROP TABLE' not in migration
    assert 'DELETE FROM transactions' not in migration
    assert 'UPDATE transactions' not in routes


def test_v38_strategy_is_rule_based_and_non_executing():
    routes = (ROOT / 'app' / 'v38_routes.py').read_text()
    for value in ('protected_cents','mandatory_goal_monthly_cents','strategic_surplus_cents','buckets'):
        assert value in routes
    assert 'réserve et liquidité d’abord' in routes
    assert 'Aucune opération bancaire' in routes
    assert 'INSERT INTO transactions' not in routes
    assert 'UPDATE accounts' not in routes


def test_v36_reconciliation_is_conservative_and_idempotent():
    routes = (ROOT / 'app' / 'v36_routes.py').read_text()
    migration = (ROOT / 'app' / 'v36_migrations.py').read_text()
    assert "best['score'] >= 0.90" in routes
    assert 'unique_margin >= 0.08' in routes
    assert "UPDATE planned_transactions SET status='matched'" in routes
    assert 'INSERT OR IGNORE INTO planned_transaction_matches' in routes
    assert 'UNIQUE(planned_transaction_id)' in migration
    assert 'UNIQUE(transaction_id)' in migration
    assert 'INSERT INTO transactions' not in routes


def test_v36_schema_is_additive_only():
    migration = (ROOT / 'app' / 'v36_migrations.py').read_text()
    for table in ('financial_routine_runs','planned_transaction_matches','decision_inbox_status'):
        assert f'CREATE TABLE IF NOT EXISTS {table}' in migration
    assert 'DROP TABLE' not in migration
    assert 'DELETE FROM transactions' not in migration


def test_v35_adaptive_budget_remains_bounded_and_non_mutating():
    routes = (ROOT / 'app' / 'v35_routes.py').read_text()
    assert 'min(flexible_remaining, max(0, safe_margin))' in routes
    assert 'UPDATE budget_lines' not in routes
    assert 'UPDATE budgets' not in routes


def test_v34_action_plan_remains_non_executing():
    routes = (ROOT / 'app' / 'v34_routes.py').read_text()
    assert 'aucune transaction ni affectation réelle' in routes
    assert 'INSERT INTO transactions' not in routes
    assert 'UPDATE accounts SET current_balance_cents' not in routes


def test_v32_scenarios_remain_persistent_and_non_destructive():
    migration = (ROOT / 'app' / 'v32_migrations.py').read_text()
    assert 'CREATE TABLE IF NOT EXISTS forecast_scenarios' in migration
    assert 'CREATE TABLE IF NOT EXISTS forecast_scenario_events' in migration
    assert 'DROP TABLE' not in migration
    assert 'DELETE FROM transactions' not in migration
