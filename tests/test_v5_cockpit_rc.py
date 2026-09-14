from pathlib import Path
import re

from app.v5_engine import _decision_status, _primary_recommendation


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _runtime_version() -> str:
    text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert match
    return match.group(1)


def test_v5_decision_status_uses_only_canonical_outputs():
    assert _decision_status(safe_cents=0, projected_margin_cents=10000, confidence='high') == 'critical'
    assert _decision_status(safe_cents=10000, projected_margin_cents=-1, confidence='high') == 'critical'
    assert _decision_status(safe_cents=10000, projected_margin_cents=10000, confidence='low') == 'watch'
    assert _decision_status(safe_cents=10000, projected_margin_cents=10000, confidence='medium') == 'prudent'
    assert _decision_status(safe_cents=10000, projected_margin_cents=10000, confidence='high') == 'comfortable'


def test_v5_recommendation_prioritizes_liquidity_before_optional_signals():
    decision = {'type': 'goal', 'priority': 'medium', 'title': 'Objectif', 'detail': 'À ajuster', 'key': 'g1'}
    signal = {'kind': 'category_anomaly', 'severity': 'watch', 'title': 'Restaurants inhabituel', 'detail': '+50 %'}
    result = _primary_recommendation(
        safe_cents=0,
        projected_margin_cents=50000,
        confidence='high',
        financial_decision=decision,
        signal=signal,
    )
    assert result['kind'] == 'liquidity'
    assert result['severity'] == 'critical'
    assert result['source'] == 'safe_to_spend'


def test_v5_recommendation_uses_financial_decision_before_historical_signal():
    decision = {'type': 'goal', 'priority': 'high', 'title': 'Objectif', 'detail': 'À ajuster', 'key': 'g1'}
    signal = {'kind': 'category_anomaly', 'severity': 'watch', 'title': 'Restaurants inhabituel', 'detail': '+50 %'}
    result = _primary_recommendation(
        safe_cents=50000,
        projected_margin_cents=30000,
        confidence='high',
        financial_decision=decision,
        signal=signal,
    )
    assert result['kind'] == 'goal'
    assert result['title'] == 'Objectif'
    assert result['source'] == 'financial_decisions'


def test_v5_router_and_home_are_wired_as_single_decision_contract():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    js = (STATIC / 'v5-home-ui.js').read_text(encoding='utf-8')
    workspace = (ROOT / 'app' / 'workspace_routes.py').read_text(encoding='utf-8')
    route = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    engine = (ROOT / 'app' / 'v5_engine.py').read_text(encoding='utf-8')
    version = _runtime_version()

    assert f'/static/v5-home-ui.js?v={version}' in html
    assert f'/static/v5-home-ui.js?v={version}' in sw
    assert "fetch('/api/v5/home-snapshot?months=6'" in js
    assert 'snapshot.cockpit' in js
    assert '/api/finance/intelligence' not in js
    assert '/api/finance/commitments' not in js
    assert 'v5_router' in workspace
    assert "router = APIRouter(prefix='/api/v5'" in route
    assert "@router.get('/home-snapshot')" in route
    assert "'schema_version': '5.0'" in engine
    assert 'build_financial_intelligence' in engine
    assert 'build_commitment_review' in engine
    assert 'build_advanced_analysis' in engine
    assert 'il ne recalcule aucun montant dans le frontend' in engine
