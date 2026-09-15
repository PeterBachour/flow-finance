from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi import HTTPException

from app import import_routes


@contextmanager
def fake_connection():
    yield object()


def test_bulk_commit_blocks_accounting_discontinuity(monkeypatch):
    monkeypatch.setattr(import_routes, 'connection', fake_connection)
    monkeypatch.setattr(import_routes, 'ensure_bulk_schema', lambda conn: None)
    monkeypatch.setattr(
        import_routes,
        'build_batch_preflight',
        lambda conn, batch_id: {
            'can_commit': False,
            'blocking_count': 1,
            'issues': [{'type': 'balance_discontinuity', 'severity': 'blocking'}],
        },
    )
    commit_called = False

    def commit_batch(conn, batch_id):
        nonlocal commit_called
        commit_called = True
        return {}

    monkeypatch.setattr(import_routes, 'commit_batch', commit_batch)

    with pytest.raises(HTTPException) as caught:
        import_routes.bulk_commit(42)

    assert caught.value.status_code == 409
    assert caught.value.detail['preflight']['blocking_count'] == 1
    assert commit_called is False


def test_bulk_commit_runs_after_clean_preflight(monkeypatch):
    monkeypatch.setattr(import_routes, 'connection', fake_connection)
    monkeypatch.setattr(import_routes, 'ensure_bulk_schema', lambda conn: None)
    monkeypatch.setattr(
        import_routes,
        'build_batch_preflight',
        lambda conn, batch_id: {
            'can_commit': True,
            'blocking_count': 0,
            'issues': [],
        },
    )
    monkeypatch.setattr(
        import_routes,
        'commit_batch',
        lambda conn, batch_id: {
            'statements': 2,
            'payrolls': 0,
            'transactions': 25,
            'duplicates': 0,
        },
    )

    result = import_routes.bulk_commit(7)

    assert result['ok'] is True
    assert result['batch_id'] == 7
    assert result['transactions'] == 25


def test_bulk_import_ui_exposes_continuity_and_blocks_invalid_commit():
    script = (
        Path(__file__).resolve().parents[1]
        / 'app'
        / 'static'
        / 'bulk-import-ui.js'
    ).read_text(encoding='utf-8')

    assert 'Contrôle de continuité' in script
    assert 'Validation bloquée' in script
    assert "preflight?.can_commit!==false" in script


def test_bulk_commit_reports_review_workload_in_api_and_ui():
    root = Path(__file__).resolve().parents[1]
    service = (root / 'app' / 'bulk_import.py').read_text(encoding='utf-8')
    script = (root / 'app' / 'static' / 'bulk-import-ui.js').read_text(encoding='utf-8')

    assert "'review': 0" in service
    assert "'auto_classified': 0" in service
    assert "result['review'] += imported['review']" in service
    assert "result['auto_classified'] += imported['auto_classified']" in service
    assert 'classée(s) automatiquement' in script
    assert 'à revoir' in script
