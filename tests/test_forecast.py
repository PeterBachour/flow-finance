from datetime import date

from app.forecast import PlannedEvent, build_forecast


def test_safe_to_spend_uses_low_point_before_next_structuring_income():
    result = build_forecast(
        today=date(2026, 9, 8),
        opening_balance_cents=95300,
        events=[
            PlannedEvent(date(2026, 9, 10), -20700, 'Crédit'),
            PlannedEvent(date(2026, 9, 12), -1000, 'Télécom'),
            PlannedEvent(date(2026, 9, 18), -10000, 'PEA'),
            PlannedEvent(date(2026, 9, 27), 310400, 'Salaire', kind='salary'),
        ],
        safety_reserve_cents=5000,
    )
    assert result['low_point']['balance_cents'] == 63600
    assert result['safe_to_spend_cents'] == 58600
    assert result['horizon'] == '2026-09-27'


def test_refund_does_not_define_forecast_horizon():
    result = build_forecast(
        today=date(2026, 9, 8),
        opening_balance_cents=10000,
        events=[PlannedEvent(date(2026, 9, 12), 5000, 'Remboursement', kind='income')],
    )
    assert result['horizon'] == '2026-09-30'
    assert result['next_income'] is None


def test_allocations_reduce_safe_to_spend_without_changing_cash_timeline():
    result = build_forecast(
        today=date(2026, 9, 8),
        opening_balance_cents=10000,
        events=[],
        safety_reserve_cents=2000,
        allocated_cents=3000,
    )
    assert result['low_point']['balance_cents'] == 10000
    assert result['safe_to_spend_cents'] == 5000
    assert result['allocated_cents'] == 3000


def test_no_income_uses_end_of_month():
    result = build_forecast(today=date(2026, 9, 8), opening_balance_cents=10000, events=[], safety_reserve_cents=2000)
    assert result['horizon'] == '2026-09-30'
    assert result['safe_to_spend_cents'] == 8000
