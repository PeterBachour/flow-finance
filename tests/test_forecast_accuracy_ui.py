import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def test_home_displays_forecast_accuracy_without_triggering_capture():
    script = (STATIC / 'v4-ui.js').read_text(encoding='utf-8')
    assert "api('/api/v6/forecast-accuracy')" in script
    assert 'forecastAccuracyCard' in script
    assert 'mean_absolute_error_cents' in script
    assert 'mean_error_cents' in script
    assert '/api/v6/forecast-snapshots/capture' not in script


def test_forecast_accuracy_release_assets_are_cache_busted_together():
    version = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    service_worker = (STATIC / 'sw.js').read_text(encoding='utf-8')
    manifest = json.loads((STATIC / 'manifest.webmanifest').read_text(encoding='utf-8'))
    changelog = json.loads((STATIC / 'changelog.json').read_text(encoding='utf-8'))

    assert "VERSION = '6.4.20'" in version
    assert 'v=6.4.20' in html
    assert "const VERSION='6.4.20'" in service_worker
    assert '/static/app.css?v=6.4.20' in service_worker
    assert '/static/v4-ui.js?v=6.4.20' in service_worker
    assert all('v=6.4.20' in icon['src'] for icon in manifest['icons'])
    assert changelog['releases'][0]['version'] == '6.4.20'
