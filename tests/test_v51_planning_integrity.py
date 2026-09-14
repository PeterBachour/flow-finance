from datetime import date
from pathlib import Path

from app.v5_planning import _estimated_projection


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _known_projection():
    return {
        'as_of': '2026-09-11',
        'horizon_months': 2,
        'opening_balance_cents': 100000,
        'closing_balance_cents': 130000,
        'protected_cents': 20000,
        'protection': {'safety_reserve_cents': 20000},
        'low_point': {'date': '2026-09-20', 'balance_cents': 80000},
        'months': [
            {
                'month': '2026-09',
                'opening_balance_cents': 100000,
                'inflows_cents': 30000,
                'outflows_cents': 20000,
                'closing_balance_cents': 110000,
                'low_point_cents': 80000,
                'safe_margin_cents': 60000,
                'events': [
                    {
                        'date': '2026-09-20',
                        'amount_cents': -20000,
                        'label': 'Échéance',
                        'source': 'planned',
                        'balance_after_cents': 80000,
                    }
                ],
            },
            {
                'month': '2026-10',
                'opening_balance_cents': 110000,
                'inflows_cents': 30000,
                'outflows_cents': 10000,
                'closing_balance_cents': 130000,
                'low_point_cents': 105000,
                'safe_margin_cents': 85000,
                'events': [],
            },
        ],
    }


def test_estimated_variable_spending_reduces_projected_closing_balance():
    known = _known_projection()
    result = _estimated_projection(
        known,
        today=date(2026, 9, 11),
        daily_rate_cents=1000,
        estimate_meta={'source': 'validated_daily_forecast'},
    )
    assert result['known_closing_balance_cents'] == 130000
    assert result['estimated_variable_spend_cents'] > 0
    assert result['closing_balance_cents'] == 130000 - result['estimated_variable_spend_cents']
    assert result['closing_balance_cents'] < result['known_closing_balance_cents']
    assert result['variable_estimate']['status'] == 'estimated'


def test_current_month_estimate_only_uses_days_remaining_after_as_of():
    result = _estimated_projection(
        _known_projection(),
        today=date(2026, 9, 11),
        daily_rate_cents=1000,
        estimate_meta={'source': 'validated_daily_forecast'},
    )
    september = result['months'][0]
    october = result['months'][1]
    assert september['variable_estimate_days'] == 19
    assert september['estimated_variable_spend_cents'] == 19000
    assert october['variable_estimate_days'] == 31
    assert october['estimated_variable_spend_cents'] == 31000


def test_event_balance_is_adjusted_for_estimated_variable_burn_before_event():
    result = _estimated_projection(
        _known_projection(),
        today=date(2026, 9, 11),
        daily_rate_cents=1000,
        estimate_meta={'source': 'validated_daily_forecast'},
    )
    event = result['months'][0]['events'][0]
    assert event['known_balance_after_cents'] == 80000
    assert event['estimated_variable_spend_before_event_cents'] == 9000
    assert event['balance_after_cents'] == 71000
    assert event['balance_status'] == 'estimated'


def test_v5_planning_ui_explicitly_labels_estimated_projection():
    js = (STATIC / 'v5-planning-ui.js').read_text(encoding='utf-8')
    assert 'Solde projeté estimé' in js
    assert 'Marge minimale estimée' in js
    assert 'dépenses variables estimées' in js
    assert 'variable_daily_rate_cents' in js
    assert 'known_closing_balance_cents' in js
