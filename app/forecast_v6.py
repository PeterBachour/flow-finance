from __future__ import annotations

import calendar
from datetime import date, timedelta
from statistics import median

from .certified_safe_to_spend import build_certified_safe_to_spend
from .forecast import _historical_variable_daily_rate
from .safe_to_spend import (
    _cycle_overlaps_recurring,
    _planned_overlaps_recurring,
    _recurring_dates,
    _table_exists,
    recurring_is_fresh,
)


def _next_salary_event(conn, *, salary_date: date) -> dict | None:
    if not (_table_exists(conn, 'payroll_transaction_matches') and _table_exists(conn, 'payroll_records')):
        return None
    rows = conn.execute(
        '''SELECT t.amount_cents
           FROM payroll_transaction_matches m
           JOIN payroll_records p ON p.id=m.payroll_record_id
           JOIN transactions t ON t.id=m.transaction_id
           WHERE t.amount_cents>0
           ORDER BY t.booking_date DESC,t.id DESC
           LIMIT 6'''
    ).fetchall()
    amounts = [int(row['amount_cents'] or 0) for row in rows if int(row['amount_cents'] or 0) > 0]
    if len(amounts) < 3:
        return None
    amount = int(round(median(amounts)))
    return {
        'date': salary_date.isoformat(),
        'amount_cents': amount,
        'label': 'Salaire attendu',
        'kind': 'structuring_income',
        'certainty': 'expected',
        'source': 'historical_salary_pattern',
    }


def _scenario(
    *,
    name: str,
    as_of: date,
    horizon_end: date,
    opening_cents: int,
    events: list[dict],
    variable_daily_cents: int,
    protected_cents: int,
) -> dict:
    by_day: dict[str, list[dict]] = {}
    for event in events:
        by_day.setdefault(event['date'], []).append(event)

    cursor = as_of
    balance = opening_cents
    low_balance = opening_cents
    low_date = as_of
    points = []
    elapsed_days = 0
    while cursor <= horizon_end:
        key = cursor.isoformat()
        day_events = by_day.get(key, [])
        event_delta = sum(int(item['amount_cents']) for item in day_events)
        if cursor > as_of:
            elapsed_days += 1
        variable_delta = -variable_daily_cents if cursor > as_of else 0
        balance += event_delta + variable_delta
        if balance < low_balance:
            low_balance = balance
            low_date = cursor
        points.append({
            'date': key,
            'balance_cents': balance,
            'spendable_balance_cents': max(0, balance - protected_cents),
            'event_delta_cents': event_delta,
            'variable_delta_cents': variable_delta,
            'events': day_events,
        })
        cursor += timedelta(days=1)

    return {
        'name': name,
        'opening_balance_cents': opening_cents,
        'closing_balance_cents': balance,
        'low_point': {'date': low_date.isoformat(), 'balance_cents': low_balance},
        'variable_daily_cents': variable_daily_cents,
        'variable_total_cents': variable_daily_cents * elapsed_days,
        'protected_cents': protected_cents,
        'timeline': points,
    }


def _dated_events(conn, *, as_of: date, horizon_end: date) -> tuple[list[dict], list[dict]]:
    planned_rows = conn.execute(
        '''SELECT id,due_date,amount_cents,label,kind,certainty
           FROM planned_transactions
           WHERE status='planned' AND due_date>? AND due_date<=?
           ORDER BY due_date,id''',
        (as_of.isoformat(), horizon_end.isoformat()),
    ).fetchall()

    confirmed = []
    realistic = []
    for row in planned_rows:
        event = {
            'date': row['due_date'],
            'amount_cents': int(row['amount_cents'] or 0),
            'label': row['label'],
            'kind': row['kind'],
            'certainty': row['certainty'],
            'source': 'planned',
        }
        realistic.append(event)
        if row['certainty'] == 'confirmed':
            confirmed.append(event)

    cycle_month = as_of.strftime('%Y-%m')
    cycle_rows = []
    if _table_exists(conn, 'cycle_reserves'):
        cycle_rows = conn.execute(
            "SELECT label,amount_cents,kind FROM cycle_reserves WHERE cycle_month=? AND status='active' AND source_status='confirmed'",
            (cycle_month,),
        ).fetchall()

    # Cycle reserves are confirmed monthly commitments without an exact due date.
    # Keep them in the trajectory at the next horizon day and mark the date as estimated.
    for row in cycle_rows:
        if row['kind'] != 'planned_commitment':
            continue
        event = {
            'date': (as_of + timedelta(days=1)).isoformat(),
            'amount_cents': -abs(int(row['amount_cents'] or 0)),
            'label': row['label'],
            'kind': row['kind'],
            'certainty': 'confirmed',
            'source': 'cycle_reserve',
            'date_precision': 'month',
        }
        confirmed.append(event)
        realistic.append(event)

    recurring_rows = conn.execute(
        '''SELECT id,label,amount_cents,usual_day,day_of_month,next_expected_date,last_seen_date,
                  source_type,tolerance_cents,category,kind,certainty,validation_status
           FROM recurring_transactions
           WHERE is_active=1
             AND (detection_status='accepted' OR validation_status='confirmed')
             AND amount_cents<0
             AND COALESCE(kind,'commitment') IN ('commitment','transfer')
           ORDER BY id'''
    ).fetchall()
    for row in recurring_rows:
        source_type = (row['source_type'] or '').lower()
        if source_type in {'history', 'auto', 'detected'} and not recurring_is_fresh(row['last_seen_date'], as_of):
            continue
        usual_day = int(row['usual_day'] or row['day_of_month'] or 1)
        if row['next_expected_date']:
            first = date.fromisoformat(row['next_expected_date'])
        else:
            first = date(
                as_of.year,
                as_of.month,
                min(max(1, usual_day), calendar.monthrange(as_of.year, as_of.month)[1]),
            )
        for occurrence in _recurring_dates(first, usual_day, as_of + timedelta(days=1), horizon_end):
            if _planned_overlaps_recurring(planned_rows, row, occurrence):
                continue
            if _cycle_overlaps_recurring(cycle_rows, row, occurrence, cycle_month):
                continue
            event = {
                'date': occurrence.isoformat(),
                'amount_cents': int(row['amount_cents'] or 0),
                'label': row['label'],
                'kind': row['kind'],
                'certainty': row['certainty'] or 'expected',
                'source': 'recurring',
            }
            realistic.append(event)
            if row['kind'] == 'transfer' and row['certainty'] == 'confirmed':
                confirmed.append(event)
    return confirmed, realistic


def build_v6_daily_trajectory(
    conn,
    *,
    as_of: date | None = None,
    horizon_days: int | None = None,
    stale_reference_date: date | None = None,
) -> dict:
    certified = build_certified_safe_to_spend(
        conn,
        as_of=as_of,
        horizon_days=horizon_days,
        stale_reference_date=stale_reference_date,
    )
    observed = date.fromisoformat(certified['as_of'])
    horizon_end = date.fromisoformat(certified['horizon']['end'])
    trajectory_horizon_end = horizon_end
    next_salary_date = certified['horizon'].get('next_salary_date')
    salary_event = None
    if next_salary_date:
        salary_date = date.fromisoformat(next_salary_date)
        trajectory_horizon_end = max(horizon_end, salary_date + timedelta(days=7))
        salary_event = _next_salary_event(conn, salary_date=salary_date)
    opening = int(certified['components']['current_balance_cents'])
    confirmed, realistic_events = _dated_events(conn, as_of=observed, horizon_end=trajectory_horizon_end)
    if salary_event:
        realistic_events.append(salary_event)

    variable_daily, variable_confidence, history_rows = _historical_variable_daily_rate(conn, observed, 6)
    uncertainty_rate = 15 if variable_confidence == 'medium' else 30
    prudent_daily = variable_daily + (variable_daily * uncertainty_rate + 99) // 100

    safety = int(certified['components']['safety_reserve_cents'])
    goals = int(certified['components']['goal_reservations_cents'])
    protected = safety + goals

    engaged = _scenario(
        name='engaged', as_of=observed, horizon_end=trajectory_horizon_end, opening_cents=opening,
        events=confirmed, variable_daily_cents=0, protected_cents=protected,
    )
    realistic = _scenario(
        name='realistic', as_of=observed, horizon_end=trajectory_horizon_end, opening_cents=opening,
        events=realistic_events, variable_daily_cents=variable_daily, protected_cents=protected,
    )
    prudent = _scenario(
        name='prudent', as_of=observed, horizon_end=trajectory_horizon_end, opening_cents=opening,
        events=realistic_events, variable_daily_cents=prudent_daily, protected_cents=protected,
    )

    return {
        'schema_version': '6.2',
        'as_of': certified['as_of'],
        'horizon': certified['horizon'],
        'availability': certified['availability'],
        'confidence': certified['confidence'],
        'safe_to_spend': certified['safe_to_spend'],
        'variable_spending': {
            'realistic_daily_cents': variable_daily,
            'prudent_daily_cents': prudent_daily,
            'uncertainty_rate_pct': uncertainty_rate,
            'confidence': variable_confidence,
            'history_rows': history_rows,
            'method': 'Médiane quotidienne des six mois précédents, hors transferts, récurrences et catégories non consommées',
        },
        'scenarios': {
            'engaged': engaged,
            'realistic': realistic,
            'prudent': prudent,
        },
        'uncertainty_band': [
            {
                'date': realistic['timeline'][index]['date'],
                'optimistic_cents': engaged['timeline'][index]['balance_cents'],
                'realistic_cents': realistic['timeline'][index]['balance_cents'],
                'prudent_cents': prudent['timeline'][index]['balance_cents'],
            }
            for index in range(len(realistic['timeline']))
        ],
        'controls': {
            'planned_recurring_deduplicated': True,
            'internal_transfers_excluded_from_analytics': True,
            'internal_transfers_in_cash_trajectory': True,
            'stale_recurrences_excluded': True,
            'safety_reserve_is_not_an_outflow': True,
            'read_only': True,
        },
    }
