from app.history_readiness import build_history_readiness


def _coverage(months, *, statement_pct=100.0, payroll_pct=100.0, review_months=0, duplicate_months=0, actions=None):
    return {
        'window_months': len(months),
        'summary': {
            'statement_coverage_pct': statement_pct,
            'payroll_coverage_pct': payroll_pct,
            'complete_months': sum(1 for row in months if row['statement']['present'] and row['payroll']['present']),
            'review_months': review_months,
            'duplicate_months': duplicate_months,
        },
        'months': months,
        'duplicates': {'statements': [], 'payrolls': []},
        'actions': actions or [],
    }


def _month(period, *, statement=True, verified=True, payroll=True):
    return {
        'period': period,
        'statement': {'present': statement, 'verified': verified},
        'payroll': {'present': payroll},
    }


def test_v56_marks_complete_recent_history_ready():
    months = [_month(f'2026-{month:02d}') for month in range(1, 7)]
    result = build_history_readiness(_coverage(months))

    assert result['score'] == 100
    assert result['status'] == 'ready'
    assert result['trend_ready'] is True
    assert result['payroll_ready'] is True
    assert result['gates']['predictive_models']['ready'] is True
    assert result['blockers'] == []
    assert result['read_only'] is True


def test_v56_recent_statement_gap_blocks_trends_even_with_good_global_score():
    months = [_month(f'2026-{month:02d}') for month in range(1, 7)]
    months[-1] = _month('2026-06', statement=False, verified=False, payroll=True)
    result = build_history_readiness(_coverage(months, statement_pct=83.3, payroll_pct=100.0))

    assert result['trend_ready'] is False
    assert result['gates']['trends']['ready'] is False
    assert result['gates']['predictive_models']['ready'] is False
    assert result['recent_gaps']['statements'] == ['2026-06']
    assert result['blockers'][0]['key'] == 'recent_statement_gap'


def test_v56_review_and_duplicates_reduce_confidence():
    months = [_month(f'2026-{month:02d}') for month in range(1, 7)]
    months[-2] = _month('2026-05', verified=False)
    coverage = _coverage(months, review_months=1, duplicate_months=1)
    coverage['duplicates']['statements'] = ['2026-03']
    result = build_history_readiness(coverage)

    assert result['score'] == 90
    assert result['trend_ready'] is False
    assert {item['key'] for item in result['blockers']} == {'recent_statement_review', 'duplicate_periods'}


def test_v56_prioritizes_statement_remediation_before_payroll():
    months = [_month(f'2026-{month:02d}') for month in range(1, 7)]
    actions = [
        {'key': 'missing_payrolls', 'priority': 'medium', 'count': 4, 'periods': ['2026-01'], 'title': 'Paies'},
        {'key': 'missing_statements', 'priority': 'high', 'count': 1, 'periods': ['2026-02'], 'title': 'Relevés'},
    ]
    result = build_history_readiness(_coverage(months, actions=actions))

    assert result['primary_action']['key'] == 'missing_statements'
    assert 'tendances' in result['primary_action']['why'].lower()
    assert [item['key'] for item in result['actions']] == ['missing_statements', 'missing_payrolls']
