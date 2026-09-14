from app.data_quality_actions import build_data_quality_actions
from app.main import app


def _coverage():
    periods = [f'2026-{month:02d}' for month in range(1, 10)]
    return {
        'window_months': 9,
        'months': [
            {
                'period': period,
                'statement': {'present': period not in {'2026-08'}, 'verified': period not in {'2026-07', '2026-08'}},
                'payroll': {'present': period not in {'2026-09'}},
            }
            for period in periods
        ],
        'gaps': {'statements': ['2026-08'], 'payrolls': ['2026-09']},
        'duplicates': {'statements': ['2026-04'], 'payrolls': []},
        'review_periods': ['2026-07'],
    }


def test_recent_statement_gaps_are_prioritized_before_payroll():
    result = build_data_quality_actions(_coverage(), {'score': 61, 'status': 'limited'})

    assert result['open_count'] == 4
    assert result['blocking_count'] == 3
    assert result['primary_action']['key'] == 'missing_statement'
    assert result['primary_action']['period'] == '2026-08'
    assert result['primary_action']['priority'] == 'critical'
    assert result['primary_action']['requires_confirmation'] is True
    assert result['primary_action']['expected_document'] == 'Relevé bancaire 2026-08'
    assert result['primary_action']['evidence'] == 'Couverture relevé 2026-08 : absente.'
    assert result['primary_action']['unlocks'] == ['trends', 'predictive_models']
    assert result['actions'][-1]['key'] == 'missing_payroll'


def test_action_center_is_read_only_and_exposes_traceable_targets():
    result = build_data_quality_actions(_coverage(), {'score': 61, 'status': 'limited'})

    assert result['read_only'] is True
    assert all(item['status'] == 'open' for item in result['actions'])
    assert all(item['requires_confirmation'] is True for item in result['actions'])
    assert all(item['evidence'] for item in result['actions'])
    assert all(item['unlocks'] for item in result['actions'])
    assert all(item['target'] in {'bulk_import', 'statement_review', 'history_details'} for item in result['actions'])
    assert len({item['id'] for item in result['actions']}) == len(result['actions'])


def test_review_duplicate_and_payroll_actions_explain_their_effect():
    result = build_data_quality_actions(_coverage(), {'score': 61, 'status': 'limited'})
    by_key = {item['key']: item for item in result['actions']}

    assert by_key['review_statement']['expected_document'] is None
    assert 'predictive_models' in by_key['review_statement']['unlocks']
    assert by_key['duplicate_period']['expected_document'] is None
    assert set(by_key['duplicate_period']['unlocks']) == {'trends', 'predictive_models', 'income_analysis'}
    assert by_key['missing_payroll']['expected_document'] == 'Fiche de paie 2026-09'
    assert by_key['missing_payroll']['unlocks'] == ['income_analysis']


def test_empty_history_queue_returns_no_primary_action():
    coverage = {
        'window_months': 6,
        'months': [
            {'period': f'2026-{month:02d}', 'statement': {'present': True, 'verified': True}, 'payroll': {'present': True}}
            for month in range(4, 10)
        ],
        'gaps': {'statements': [], 'payrolls': []},
        'duplicates': {'statements': [], 'payrolls': []},
        'review_periods': [],
    }
    result = build_data_quality_actions(coverage, {'score': 100, 'status': 'ready'})

    assert result['open_count'] == 0
    assert result['blocking_count'] == 0
    assert result['primary_action'] is None
    assert result['counts'] == {'critical': 0, 'high': 0, 'medium': 0, 'low': 0}


def test_v57_action_center_route_is_registered():
    paths = {route.path for route in app.routes}
    assert '/api/v5.7/data-quality-actions' in paths
