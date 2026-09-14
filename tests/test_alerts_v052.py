from datetime import date

from app.alert_engine import build_actionable_alerts


def dashboard(*, low=50000, safe=30000, as_of='2026-09-08', events=None):
    return {
        'accounts': [{'id': 1, 'name': 'Courant', 'kind': 'checking', 'balance_as_of': as_of}],
        'allocated_cents': 0,
        'projections': {
            'realistic': {
                'low_point': {'date': '2026-09-12', 'balance_cents': low},
                'safe_to_spend_cents': safe,
                'safety_reserve_cents': 5000,
                'allocated_cents': 0,
                'events': events or [],
            }
        },
    }


def prep(status='secured', blockers=None, warnings=None):
    return {'status': status, 'blockers': blockers or [], 'warnings': warnings or []}


def codes(result):
    return {item['code'] for item in result}


def test_negative_low_point_is_critical():
    result = build_actionable_alerts(dashboard=dashboard(low=-12000, safe=0), month_prep=prep(), today=date(2026, 9, 8))
    assert result[0]['code'] == 'negative-low-point'
    assert result[0]['severity'] == 'critical'


def test_stale_snapshot_is_actionable():
    result = build_actionable_alerts(dashboard=dashboard(as_of='2026-09-02'), month_prep=prep(), today=date(2026, 9, 8))
    assert 'snapshot-stale-1' in codes(result)


def test_upcoming_outflows_over_safe_trigger_warning():
    events = [{'date': '2026-09-10', 'amount_cents': -25000, 'label': 'Crédit'}]
    result = build_actionable_alerts(dashboard=dashboard(safe=10000, events=events), month_prep=prep(), today=date(2026, 9, 8))
    assert 'upcoming-over-safe' in codes(result)


def test_unprepared_next_month_exposes_blockers():
    result = build_actionable_alerts(
        dashboard=dashboard(),
        month_prep=prep('attention', blockers=['Aucun revenu structurant récurrent identifié']),
        today=date(2026, 9, 8),
    )
    item = next(x for x in result if x['code'] == 'next-month-unprepared')
    assert 'revenu structurant' in item['message']


def test_healthy_state_has_no_alert():
    result = build_actionable_alerts(dashboard=dashboard(), month_prep=prep(), today=date(2026, 9, 8))
    assert result == []
