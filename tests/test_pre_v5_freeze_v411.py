from datetime import date
from pathlib import Path
import re

import app.v411_routes as readiness


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _runtime_version() -> str:
    text = (ROOT / 'app' / 'version.py').read_text(encoding='utf-8')
    match = re.search(r"VERSION\s*=\s*['\"]([^'\"]+)['\"]", text)
    assert match
    return match.group(1)


def _diagnostic(*, commit_known=True, uncategorized=0):
    return {
        'version': _runtime_version(),
        'commit': 'abcdef123456' if commit_known else None,
        'commit_status': 'known' if commit_known else 'not_injected',
        'labels': {'commit': 'abcdef1234' if commit_known else 'Non injecté'},
        'database': {'uncategorized': uncategorized},
    }


def _wealth(*, stale=0, undated=0):
    return {'summary': {'stale_accounts': stale, 'undated_accounts': undated}}


def test_previous_month_handles_year_boundary():
    assert readiness._previous_month(date(2026, 1, 5)) == '2025-12'
    assert readiness._previous_month(date(2026, 9, 11)) == '2026-08'


def test_readiness_only_blocks_operational_release_gates(monkeypatch):
    monkeypatch.setattr(readiness, 'system_diagnostic', lambda: _diagnostic(commit_known=False, uncategorized=862))
    monkeypatch.setattr(readiness, 'decision_priorities', lambda: {'open_count': 3})
    monkeypatch.setattr(readiness, 'wealth_readiness', lambda: _wealth(stale=2, undated=1))
    monkeypatch.setattr(readiness, 'month_status', lambda month: {'status': 'blocked'})

    data = readiness.pre_v5_readiness()
    by_key = {gate['key']: gate for gate in data['gates']}

    assert data['release_status'] == 'attention'
    assert data['blocking_count'] == 3
    assert by_key['runtime_identity']['status'] == 'warning'
    assert by_key['previous_month']['status'] == 'warning'
    assert by_key['wealth_freshness']['status'] == 'warning'
    assert by_key['categorization']['status'] == 'info'
    assert by_key['financial_decisions']['status'] == 'info'


def test_readiness_is_ready_when_runtime_month_and_wealth_are_clean(monkeypatch):
    monkeypatch.setattr(readiness, 'system_diagnostic', lambda: _diagnostic(commit_known=True, uncategorized=12))
    monkeypatch.setattr(readiness, 'decision_priorities', lambda: {'open_count': 1})
    monkeypatch.setattr(readiness, 'wealth_readiness', lambda: _wealth(stale=0, undated=0))
    monkeypatch.setattr(readiness, 'month_status', lambda month: {'status': 'consolidated'})

    data = readiness.pre_v5_readiness()

    assert data['release_status'] == 'ready'
    assert data['blocking_count'] == 0
    assert data['summary']['uncategorized_movements'] == 12
    assert data['summary']['open_financial_decisions'] == 1


def test_pre_v5_readiness_ui_is_wired_read_only_and_version_aligned():
    html = (STATIC / 'index.html').read_text(encoding='utf-8')
    sw = (STATIC / 'sw.js').read_text(encoding='utf-8')
    js = (STATIC / 'pre-v5-freeze-ui.js').read_text(encoding='utf-8')
    css = (STATIC / 'pre-v5-freeze.css').read_text(encoding='utf-8')
    workspace = (ROOT / 'app' / 'workspace_routes.py').read_text(encoding='utf-8')
    version = _runtime_version()

    assert f'pre-v5-freeze.css?v={version}' in html
    assert f'pre-v5-freeze-ui.js?v={version}' in html
    assert f'/static/pre-v5-freeze.css?v={version}' in sw
    assert f'/static/pre-v5-freeze-ui.js?v={version}' in sw
    assert f"const VERSION='{version}'" in sw
    assert 'v411_router' in workspace
    assert '/api/v4.11/pre-v5-readiness' in js
    assert 'method:' not in js
    assert '.pre-v5-readiness' in css
