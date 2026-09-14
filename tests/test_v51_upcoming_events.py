from datetime import date
from pathlib import Path
import re

import app.v51_events as events


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _version() -> str:
    text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert match
    return match.group(1)


def test_event_status_is_driven_by_balance_after_and_protection():
    assert events._event_status(amount_cents=10000, balance_after_cents=1000, protected_cents=20000) == 'income'
    assert events._event_status(amount_cents=-1000, balance_after_cents=-1, protected_cents=20000) == 'critical'
    assert events._event_status(amount_cents=-1000, balance_after_cents=15000, protected_cents=20000) == 'high'
    assert events._event_status(amount_cents=-1000, balance_after_cents=24000, protected_cents=20000) == 'watch'
    assert events._event_status(amount_cents=-1000, balance_after_cents=30000, protected_cents=20000) == 'safe'


def test_upcoming_events_are_chronological_filtered_and_read_only(monkeypatch):
    monkeypatch.setattr(events, 'build_v5_plan', lambda *a, **k: {
        'projection': {
            'protected_cents': 20000,
            'months': [
                {'events': [
                    {'date': '2026-09-20', 'label': 'Revenu', 'amount_cents': 100000, 'balance_after_cents': 120000, 'source': 'known'},
                    {'date': '2026-09-13', 'label': 'Charge', 'amount_cents': -5000, 'balance_after_cents': 19000, 'source': 'known'},
                    {'date': '2026-11-15', 'label': 'Hors fenêtre', 'amount_cents': -1000, 'balance_after_cents': 50000, 'source': 'known'},
                    {'date': '2026-09-01', 'label': 'Passé', 'amount_cents': -1000, 'balance_after_cents': 50000, 'source': 'known'},
                ]}
            ],
        }
    })

    result = events.build_upcoming_events(object(), as_of=date(2026, 9, 11), days=45)

    assert [item['label'] for item in result['events']] == ['Charge', 'Revenu']
    assert result['events'][0]['days_away'] == 2
    assert result['events'][0]['status'] == 'high'
    assert result['summary']['sensitive_count'] == 1
    assert result['summary']['next_outflow']['label'] == 'Charge'
    assert result['summary']['next_income']['label'] == 'Revenu'
    assert result['principle'].startswith('Agenda financier en lecture seule')


def test_upcoming_events_engine_does_not_mutate_financial_data():
    source = (ROOT / 'app' / 'v51_events.py').read_text(encoding='utf-8')
    assert 'INSERT INTO' not in source
    assert 'UPDATE ' not in source
    assert 'DELETE FROM' not in source
    assert 'build_v5_plan' in source


def test_v51_upcoming_events_endpoint_and_assets_are_wired_on_current_runtime():
    version = _version()
    routes = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    js = (STATIC / 'v51-events-ui.js').read_text(encoding='utf-8')

    assert "@router.get('/upcoming-events')" in routes
    assert f'v51-events.css?v={version}' in html
    assert f'v51-events-ui.js?v={version}' in html
    assert f'/static/v51-events.css?v={version}' in sw
    assert f'/static/v51-events-ui.js?v={version}' in sw
    assert '/api/v5/upcoming-events?days=45' in js
    assert "method:'POST'" not in js
    assert "method:'PATCH'" not in js
    assert "method:'DELETE'" not in js
