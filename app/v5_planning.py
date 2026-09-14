from __future__ import annotations

import calendar
from datetime import date

from .financial_intelligence import build_financial_intelligence
from .v32_routes import _forecast
from .v33_routes import _goal_projection


def _month_add(value: date, offset: int) -> tuple[int, int]:
    idx = value.year * 12 + value.month - 1 + offset
    return idx // 12, idx % 12 + 1


def _scenario_rows(*, today: date, months: int, one_time_expense_cents: int = 0,
                   one_time_date: date | None = None, monthly_spend_delta_cents: int = 0,
                   monthly_income_delta_cents: int = 0) -> list[dict]:
    rows: list[dict] = []
    if one_time_expense_cents > 0:
        due = one_time_date or today
        rows.append({
            'event_type': 'one_time', 'label': 'Scénario · dépense ponctuelle',
            'amount_cents': -abs(int(one_time_expense_cents)), 'due_date': due.isoformat(),
            'day_of_month': None, 'start_date': None, 'end_date': None,
        })
    if monthly_spend_delta_cents > 0:
        rows.append({
            'event_type': 'monthly', 'label': 'Scénario · dépenses mensuelles',
            'amount_cents': -abs(int(monthly_spend_delta_cents)), 'due_date': None,
            'day_of_month': min(today.day, 28), 'start_date': today.isoformat(), 'end_date': None,
        })
    if monthly_income_delta_cents > 0:
        rows.append({
            'event_type': 'monthly', 'label': 'Scénario · revenu mensuel',
            'amount_cents': abs(int(monthly_income_delta_cents)), 'due_date': None,
            'day_of_month': min(today.day, 28), 'start_date': today.isoformat(), 'end_date': None,
        })
    return rows


def _canonical_variable_rate(conn, today: date) -> tuple[int, dict]:
    intelligence = build_financial_intelligence(conn, as_of=today, history_months=12)
    headline = intelligence.get('headline') or {}
    position = intelligence.get('current_position') or {}
    rate = int(headline.get('variable_daily_rate_cents') or 0)
    source = 'validated_daily_forecast'
    if rate <= 0:
        rate = int(position.get('baseline_variable_daily_median_cents') or 0)
        source = 'historical_daily_median'
    return max(0, rate), {
        'source': source,
        'daily_rate_cents': max(0, rate),
        'trend_confidence': headline.get('trend_confidence'),
        'historical_variable_month_median_cents': int(headline.get('historical_variable_month_median_cents') or 0),
    }


def _estimated_projection(known: dict, *, today: date, daily_rate_cents: int, estimate_meta: dict) -> dict:
    protected = int(known.get('protected_cents') or 0)
    opening = int(known.get('opening_balance_cents') or 0)
    cumulative_variable = 0
    estimated_opening = opening
    month_rows: list[dict] = []
    global_low = {'date': today.isoformat(), 'balance_cents': opening}

    for index, row in enumerate(known.get('months') or []):
        year, month = map(int, row['month'].split('-'))
        last_day = calendar.monthrange(year, month)[1]
        if index == 0 and year == today.year and month == today.month:
            variable_days = max(0, last_day - today.day)
        else:
            variable_days = last_day
        variable_estimate = daily_rate_cents * variable_days

        known_opening = int(row.get('opening_balance_cents') or 0)
        known_closing = int(row.get('closing_balance_cents') or 0)
        known_low = int(row.get('low_point_cents') or known_opening)
        known_delta = known_closing - known_opening

        translated_known_low = estimated_opening + (known_low - known_opening)
        estimated_closing = estimated_opening + known_delta - variable_estimate
        estimated_low = min(translated_known_low, estimated_closing)
        estimated_margin = max(0, estimated_low - protected)

        events = []
        for event in row.get('events') or []:
            event_date = date.fromisoformat(str(event['date'])[:10])
            if index == 0 and event_date.year == today.year and event_date.month == today.month:
                days_before_event = max(0, event_date.day - today.day)
                event_variable = daily_rate_cents * days_before_event
            else:
                event_variable = daily_rate_cents * max(0, event_date.day - 1)
            adjusted_balance = int(event.get('balance_after_cents') or 0) - cumulative_variable - event_variable
            events.append({
                **event,
                'known_balance_after_cents': int(event.get('balance_after_cents') or 0),
                'balance_after_cents': adjusted_balance,
                'estimated_variable_spend_before_event_cents': cumulative_variable + event_variable,
                'balance_status': 'estimated',
            })

        low_date = f'{year:04d}-{month:02d}-{last_day:02d}'
        if estimated_low < int(global_low['balance_cents']):
            global_low = {'date': low_date, 'balance_cents': estimated_low}

        month_rows.append({
            **row,
            'known_opening_balance_cents': known_opening,
            'known_closing_balance_cents': known_closing,
            'known_low_point_cents': known_low,
            'opening_balance_cents': estimated_opening,
            'closing_balance_cents': estimated_closing,
            'low_point_cents': estimated_low,
            'safe_margin_cents': estimated_margin,
            'estimated_variable_spend_cents': variable_estimate,
            'estimated_outflows_cents': int(row.get('outflows_cents') or 0) + variable_estimate,
            'variable_estimate_days': variable_days,
            'variable_estimate_status': 'estimated',
            'events': events,
        })
        cumulative_variable += variable_estimate
        estimated_opening = estimated_closing

    closing = month_rows[-1]['closing_balance_cents'] if month_rows else opening
    minimum_margin = min((int(row['safe_margin_cents']) for row in month_rows), default=max(0, opening - protected))
    return {
        'as_of': today.isoformat(),
        'horizon_months': int(known.get('horizon_months') or len(month_rows)),
        'opening_balance_cents': opening,
        'known_closing_balance_cents': int(known.get('closing_balance_cents') or opening),
        'closing_balance_cents': int(closing),
        'protected_cents': protected,
        'protection': known.get('protection') or {},
        'known_low_point': known.get('low_point'),
        'low_point': global_low,
        'minimum_safe_margin_cents': minimum_margin,
        'estimated_variable_spend_cents': cumulative_variable,
        'variable_daily_rate_cents': daily_rate_cents,
        'variable_estimate': {
            **estimate_meta,
            'status': 'estimated',
            'principle': 'Les dépenses variables futures sont estimées avec le rythme journalier canonique de Flow. Elles ne sont pas transformées en transactions.',
        },
        'months': month_rows,
    }


def _goal_arbitration(conn, *, today: date, months: int, minimum_safe_margin_cents: int) -> dict:
    goals = [dict(row) for row in conn.execute(
        'SELECT * FROM financial_goals WHERE is_active=1 ORDER BY priority,id'
    ).fetchall()]
    allocations = {
        int(row['goal_id']): int(row['total'] or 0)
        for row in conn.execute(
            'SELECT goal_id,COALESCE(SUM(amount_cents),0) total FROM goal_allocations GROUP BY goal_id'
        ).fetchall()
    }
    projected = [_goal_projection(goal, allocations.get(int(goal['id']), 0), today, minimum_safe_margin_cents) for goal in goals]

    # The minimum estimated margin is the cumulative buffer left after known events and
    # estimated variable spending. Dividing it across the horizon yields a conservative
    # recurring envelope without treating the whole one-time buffer as monthly income.
    monthly_capacity = max(0, int(minimum_safe_margin_cents) // max(1, months))
    remaining_capacity = monthly_capacity

    status_rank = {'late': 0, 'off_track': 1, 'at_risk': 2, 'on_track': 3, 'no_deadline': 4, 'achieved': 5}
    ordered = sorted(
        projected,
        key=lambda goal: (
            0 if int(goal.get('is_mandatory') or 0) else 1,
            status_rank.get(goal.get('status'), 9),
            int(goal.get('priority') or 999),
            goal.get('months_remaining') if goal.get('months_remaining') is not None else 9999,
            int(goal.get('id') or 0),
        ),
    )

    recommendations = []
    for goal in ordered:
        required = goal.get('required_monthly_cents')
        configured = max(0, int(goal.get('monthly_contribution_cents') or 0))
        if goal.get('status') == 'achieved':
            recommended = 0
            reason = 'Objectif déjà atteint.'
        elif required is None:
            recommended = min(configured, remaining_capacity)
            reason = 'Pas de date cible : maintien de la contribution configurée dans la capacité prudente.'
        else:
            required = max(0, int(required))
            recommended = min(required, remaining_capacity)
            reason = 'Priorité calculée selon caractère obligatoire, retard, priorité et échéance.'
        remaining_capacity = max(0, remaining_capacity - recommended)
        recommendations.append({
            'goal_id': int(goal['id']), 'name': goal['name'], 'status': goal.get('status'),
            'mandatory': bool(goal.get('is_mandatory')), 'priority': int(goal.get('priority') or 999),
            'target_date': goal.get('target_date'), 'months_remaining': goal.get('months_remaining'),
            'current_cents': int(goal.get('effective_current_cents') or 0),
            'target_cents': int(goal.get('target_cents') or 0),
            'remaining_cents': int(goal.get('remaining_cents') or 0),
            'configured_monthly_cents': configured,
            'required_monthly_cents': goal.get('required_monthly_cents'),
            'recommended_monthly_cents': recommended,
            'funding_gap_cents': max(0, (int(goal.get('required_monthly_cents') or 0) - recommended)),
            'reason': reason,
        })

    return {
        'monthly_capacity_cents': monthly_capacity,
        'unallocated_monthly_capacity_cents': remaining_capacity,
        'goals': recommendations,
        'method': 'Arbitrage déterministe et prudent : capacité calculée sur la marge minimale estimée après événements connus et dépenses variables estimées, répartie sur l’horizon. Objectifs obligatoires d’abord, puis objectifs en retard/à risque, priorité et échéance. Aucun virement ni réservation n’est exécuté.',
    }


def build_v5_plan(conn, *, months: int = 6, today: date | None = None) -> dict:
    today = today or date.today()
    months = max(1, min(12, int(months)))
    known = _forecast(conn, months, today=today)
    daily_rate, estimate_meta = _canonical_variable_rate(conn, today)
    projection = _estimated_projection(known, today=today, daily_rate_cents=daily_rate, estimate_meta=estimate_meta)
    minimum_safe_margin = int(projection['minimum_safe_margin_cents'])
    arbitration = _goal_arbitration(conn, today=today, months=months, minimum_safe_margin_cents=minimum_safe_margin)

    return {
        'as_of': today.isoformat(),
        'horizon_months': months,
        'projection': projection,
        'goal_arbitration': arbitration,
        'principle': 'Projection multi-mois à deux niveaux : événements connus séparés des dépenses variables estimées. Le pilotage V5 utilise la trajectoire estimée et n’invente aucune transaction.',
    }


def build_v5_scenario(conn, *, months: int = 6, today: date | None = None,
                      one_time_expense_cents: int = 0, one_time_date: date | None = None,
                      monthly_spend_delta_cents: int = 0, monthly_income_delta_cents: int = 0) -> dict:
    today = today or date.today()
    months = max(1, min(12, int(months)))
    daily_rate, estimate_meta = _canonical_variable_rate(conn, today)
    known_baseline = _forecast(conn, months, today=today)
    baseline = _estimated_projection(known_baseline, today=today, daily_rate_cents=daily_rate, estimate_meta=estimate_meta)
    rows = _scenario_rows(
        today=today, months=months,
        one_time_expense_cents=one_time_expense_cents, one_time_date=one_time_date,
        monthly_spend_delta_cents=monthly_spend_delta_cents,
        monthly_income_delta_cents=monthly_income_delta_cents,
    )
    known_simulated = _forecast(conn, months, rows, today=today)
    simulated = _estimated_projection(known_simulated, today=today, daily_rate_cents=daily_rate, estimate_meta=estimate_meta)
    base_margin = int(baseline['minimum_safe_margin_cents'])
    sim_margin = int(simulated['minimum_safe_margin_cents'])
    sim_low = int(simulated['low_point']['balance_cents'])
    protected = int(simulated['protected_cents'])
    if sim_low < 0:
        verdict = 'not_recommended'
        label = 'Risque de découvert'
    elif sim_low < protected:
        verdict = 'caution'
        label = 'Possible mais sous la protection cible'
    else:
        verdict = 'compatible'
        label = 'Compatible avec la protection actuelle'

    return {
        'as_of': today.isoformat(), 'horizon_months': months,
        'persisted': False,
        'assumptions': {
            'one_time_expense_cents': int(one_time_expense_cents),
            'one_time_date': one_time_date.isoformat() if one_time_date else None,
            'monthly_spend_delta_cents': int(monthly_spend_delta_cents),
            'monthly_income_delta_cents': int(monthly_income_delta_cents),
        },
        'baseline': {
            'known_closing_balance_cents': int(baseline['known_closing_balance_cents']),
            'closing_balance_cents': int(baseline['closing_balance_cents']),
            'estimated_variable_spend_cents': int(baseline['estimated_variable_spend_cents']),
            'minimum_safe_margin_cents': base_margin,
            'low_point': baseline['low_point'],
        },
        'simulated': {
            'known_closing_balance_cents': int(simulated['known_closing_balance_cents']),
            'closing_balance_cents': int(simulated['closing_balance_cents']),
            'estimated_variable_spend_cents': int(simulated['estimated_variable_spend_cents']),
            'minimum_safe_margin_cents': sim_margin,
            'low_point': simulated['low_point'],
            'months': simulated['months'],
        },
        'impact': {
            'closing_balance_delta_cents': int(simulated['closing_balance_cents']) - int(baseline['closing_balance_cents']),
            'minimum_safe_margin_delta_cents': sim_margin - base_margin,
            'low_point_delta_cents': int(simulated['low_point']['balance_cents']) - int(baseline['low_point']['balance_cents']),
        },
        'verdict': verdict, 'verdict_label': label,
        'variable_estimate': baseline['variable_estimate'],
        'principle': 'Simulation en lecture seule sur une trajectoire qui distingue événements connus et dépenses variables estimées. Aucune hypothèse n’est enregistrée ni transformée en transaction.',
    }
