from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'
def test_v63_assets_are_loaded_after_v5():
    html=(STATIC/'index.html').read_text(encoding='utf-8')
    assert '/static/v63-cockpit.css?v=6.3.0' in html
    assert '/static/v63-cockpit-ui.js?v=6.3.0' in html
    assert html.index('v5-home-ui.js') < html.index('v63-cockpit-ui.js')
def test_v63_uses_canonical_trajectory_contract():
    script=(STATIC/'v63-cockpit-ui.js').read_text(encoding='utf-8')
    assert "fetch('/api/v6/trajectory'" in script
    assert "scenario:'realistic'" in script
    assert "['engaged','realistic','prudent']" in script
    assert "state.range==='week'" in script
    assert 'uncertainty_band' in script
    assert 'spendable_balance_cents' in script
def test_v63_chart_is_accessible_and_versioned():
    script=(STATIC/'v63-cockpit-ui.js').read_text(encoding='utf-8')
    assert 'role="img"' in script
    assert 'role="button" tabindex="0"' in script
    assert "event.key==='Enter'||event.key===' '" in script
    assert "const VERSION='6.3.0'" in script
    assert "const VERSION = '6.3.0'" in (ROOT/'app'/'version.py').read_text(encoding='utf-8')
