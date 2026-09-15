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
