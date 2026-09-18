from fastapi import HTTPException

from app.main import app
from app.statement_corpus_preflight import StatementRecord, analyze_records


def record(name, start, end, opening, closing, *, staged=False, status='ready', warning=None, source_id=1):
    return StatementRecord(
        source='staged' if staged else 'import',
        source_id=source_id,
        filename=name,
        period_start=start,
        period_end=end,
        opening_balance_cents=opening,
        closing_balance_cents=closing,
        status=status,
        warning=warning,
        staged=staged,
    )


def test_contiguous_chain_is_ready():
    result = analyze_records([
        record('jan.pdf', '2026-01-01', '2026-01-31', 100_00, 150_00),
        record('feb.pdf', '2026-02-01', '2026-02-28', 150_00, 120_00, staged=True, source_id=2),
    ])
    assert result['status'] == 'ready'
    assert result['can_commit'] is True
    assert result['requires_confirmation'] is False
    assert result['issues'] == []


def test_gap_is_warning_but_does_not_block_commit():
    result = analyze_records([
        record('jan.pdf', '2026-01-01', '2026-01-31', 100_00, 150_00),
        record('mar.pdf', '2026-03-01', '2026-03-31', 175_00, 120_00, staged=True, source_id=2),
    ])
    assert result['status'] == 'warning'
    assert result['can_commit'] is True
    assert result['requires_confirmation'] is True
    assert result['issues'][0]['type'] == 'period_gap'
    assert result['issues'][0]['missing_start'] == '2026-02-01'
    assert result['issues'][0]['missing_end'] == '2026-02-28'
    assert not any(issue['type'] == 'balance_discontinuity' for issue in result['issues'])


def test_overlap_blocks_commit():
    result = analyze_records([
        record('jan.pdf', '2026-01-01', '2026-01-31', 100_00, 150_00),
        record('overlap.pdf', '2026-01-31', '2026-02-28', 150_00, 120_00, staged=True, source_id=2),
    ])
    assert result['status'] == 'blocked'
    assert result['can_commit'] is False
    assert result['issues'][0]['type'] == 'period_overlap'


def test_exact_duplicate_with_matching_balances_is_safe():
    result = analyze_records([
        record('already-imported.pdf', '2026-01-01', '2026-01-31', 100_00, 150_00),
        record('renamed-upload.pdf', '2026-01-01', '2026-01-31', 100_00, 150_00, staged=True, source_id=2),
        record('feb.pdf', '2026-02-01', '2026-02-28', 150_00, 120_00, staged=True, source_id=3),
    ])
    assert result['status'] == 'ready'
    assert result['can_commit'] is True
    assert result['issues'] == []
    assert result['duplicate_statement_count'] == 1


def test_same_period_with_conflicting_balances_still_blocks():
    result = analyze_records([
        record('already-imported.pdf', '2026-01-01', '2026-01-31', 100_00, 150_00),
        record('conflicting-upload.pdf', '2026-01-01', '2026-01-31', 100_00, 151_00, staged=True, source_id=2),
    ])
    assert result['status'] == 'blocked'
    assert result['can_commit'] is False
    assert result['issues'][0]['type'] == 'period_overlap'


def test_balance_discontinuity_blocks_commit():
    result = analyze_records([
        record('jan.pdf', '2026-01-01', '2026-01-31', 100_00, 150_00),
        record('feb.pdf', '2026-02-01', '2026-02-28', 149_50, 120_00, staged=True, source_id=2),
    ])
    assert result['status'] == 'blocked'
    assert result['can_commit'] is False
    issue = next(item for item in result['issues'] if item['type'] == 'balance_discontinuity')
    assert issue['difference_cents'] == -50


def test_unparseable_staged_statement_blocks_commit():
    result = analyze_records([
        record('bad.pdf', None, None, None, None, staged=True, status='warning', warning='parse failed'),
    ])
    assert result['status'] == 'blocked'
    assert result['can_commit'] is False
    assert result['issues'][0]['type'] == 'parse_error'


def test_guarded_commit_route_is_registered_before_legacy_commit_route():
    matching = [route for route in app.routes if getattr(route, 'path', None) == '/api/imports/bulk/{batch_id}/commit']
    assert len(matching) >= 2
    assert matching[0].endpoint.__name__ == 'guarded_bulk_commit'


def test_preflight_route_is_exposed():
    paths = {route.path for route in app.routes}
    assert '/api/imports/bulk/{batch_id}/preflight' in paths


def test_guarded_commit_requires_explicit_gap_confirmation(monkeypatch):
    from app import statement_corpus_routes as routes

    class Context:
        def __enter__(self):
            return object()

        def __exit__(self, exc_type, exc, traceback):
            return False

    monkeypatch.setattr(routes, 'connection', lambda: Context())
    monkeypatch.setattr(routes, 'ensure_bulk_schema', lambda conn: None)
    monkeypatch.setattr(
        routes,
        'build_batch_preflight',
        lambda conn, batch_id: {
            'can_commit': True,
            'requires_confirmation': True,
            'issues': [{'type': 'period_gap', 'severity': 'warning'}],
        },
    )
    commit_called = False

    def commit(conn, batch_id):
        nonlocal commit_called
        commit_called = True
        return {}

    monkeypatch.setattr(routes, 'commit_batch', commit)

    try:
        routes.guarded_bulk_commit(12)
    except HTTPException as exc:
        assert exc.status_code == 409
        assert exc.detail['code'] == 'confirmation_required'
    else:
        raise AssertionError('Missing gap confirmation must block the commit')

    assert commit_called is False
    result = routes.guarded_bulk_commit(12, confirm_warnings=True)
    assert result['ok'] is True
    assert commit_called is True
