from __future__ import annotations

from datetime import date

from .safe_to_spend import calculate_safe_to_spend


def _confidence(result) -> dict:
    reasons: list[str] = []
    if result.safe_to_spend_status != 'available':
        return {
            'score': 0,
            'level': 'unavailable',
            'reasons': [result.safe_to_spend_status],
        }

    score = 92 if result.next_salary_date else 78
    if not result.next_salary_date:
        reasons.append('Date du prochain salaire non confirmée par l’historique rapproché')
    if result.recurring_stale_excluded_count:
        penalty = min(18, result.recurring_stale_excluded_count * 4)
        score -= penalty
        reasons.append(
            f'{result.recurring_stale_excluded_count} récurrence(s) ancienne(s) exclue(s)'
        )
    if result.horizon_mode.startswith('fallback_'):
        reasons.append('Horizon calculé avec une durée de repli')
    if not reasons:
        reasons.append('Solde récent et horizon salarial rapproché')

    if score >= 90:
        level = 'confirmed'
    elif score >= 72:
        level = 'probable'
    elif score >= 50:
        level = 'estimated'
    else:
        level = 'uncertain'
    return {'score': max(0, min(100, score)), 'level': level, 'reasons': reasons}


def _confirmed_timeline(conn, *, as_of: date, horizon_end: date, opening_cents: int) -> dict:
    rows = conn.execute(
        '''SELECT due_date,amount_cents,label,certainty
           FROM planned_transactions
           WHERE status='planned'
             AND due_date>?
             AND due_date<=?
             AND certainty='confirmed'
           ORDER BY due_date,id''',
        (as_of.isoformat(), horizon_end.isoformat()),
    ).fetchall()
    balance = opening_cents
    low_balance = opening_cents
    low_date = as_of
    events = []
    for row in rows:
        amount = int(row['amount_cents'] or 0)
        balance += amount
        event_date = date.fromisoformat(row['due_date'])
        if balance < low_balance:
            low_balance = balance
            low_date = event_date
        events.append({
            'date': row['due_date'],
            'label': row['label'],
            'amount_cents': amount,
            'certainty': 'confirmed',
        })
    return {
        'events': events,
        'closing_cents': balance,
        'low_point_cents': low_balance,
        'low_point_date': low_date.isoformat(),
    }


def build_certified_safe_to_spend(
    conn,
    *,
    as_of: date | None = None,
    horizon_days: int | None = None,
    stale_reference_date: date | None = None,
) -> dict:
    result = calculate_safe_to_spend(
        conn,
        as_of=as_of,
        horizon_days=horizon_days,
        stale_reference_date=stale_reference_date,
    )
    observed = date.fromisoformat(result.as_of)
    horizon_end = date.fromisoformat(result.horizon_end)
    timeline = _confirmed_timeline(
        conn,
        as_of=observed,
        horizon_end=horizon_end,
        opening_cents=result.balance_cents,
    )

    available = result.safe_to_spend_status == 'available'
    total = result.safe_to_spend_cents if available else None
    inclusive_days = max(1, (horizon_end - observed).days + 1)
    today_cents = total // inclusive_days if total is not None else None
    confidence = _confidence(result)

    engaged_balance = result.balance_cents - result.planned_commitments_cents
    realistic_balance = engaged_balance - result.recurring_commitments_cents
    prudent_balance = (
        realistic_balance
        - result.goal_contributions_cents
        - result.safety_reserve_cents
    )

    breakdown = [
        {
            'key': 'confirmed_balance',
            'label': 'Solde confirmé',
            'operator': 'base',
            'amount_cents': result.balance_cents,
            'certainty': 'confirmed',
            'included': True,
        },
        {
            'key': 'planned_commitments',
            'label': 'Échéances confirmées',
            'operator': 'subtract',
            'amount_cents': result.planned_commitments_cents,
            'certainty': 'confirmed',
            'included': True,
        },
        {
            'key': 'recurring_commitments',
            'label': 'Charges récurrentes validées',
            'operator': 'subtract',
            'amount_cents': result.recurring_commitments_cents,
            'certainty': 'probable',
            'included': True,
        },
        {
            'key': 'goal_reservations',
            'label': 'Objectifs avec impact de trésorerie',
            'operator': 'subtract',
            'amount_cents': result.goal_contributions_cents,
            'certainty': 'confirmed',
            'included': True,
            'mode': result.goal_contribution_mode,
        },
        {
            'key': 'safety_reserve',
            'label': 'Marge de sécurité',
            'operator': 'subtract',
            'amount_cents': result.safety_reserve_cents,
            'certainty': 'confirmed',
            'included': True,
        },
    ]

    return {
        'schema_version': '6.1',
        'as_of': result.as_of,
        'horizon': {
            'end': result.horizon_end,
            'days': result.horizon_days,
            'mode': result.horizon_mode,
            'next_salary_date': result.next_salary_date,
        },
        'availability': {
            'status': result.safe_to_spend_status,
            'available': available,
            'balance_age_days': result.balance_age_days,
            'balance_is_stale': result.balance_is_stale,
            'included_account_count': result.included_account_count,
        },
        'safe_to_spend': {
            'total_cents': total,
            'today_cents': today_cents,
            'calculated_cents': result.calculated_safe_to_spend_cents,
            'formula': 'balance - planned - recurring - goal_cash_impact - safety_reserve',
        },
        'components': {
            'current_balance_cents': result.balance_cents,
            'confirmed_commitments_cents': result.planned_commitments_cents,
            'probable_recurring_cents': result.recurring_commitments_cents,
            'goal_reservations_cents': result.goal_contributions_cents,
            'safety_reserve_cents': result.safety_reserve_cents,
        },
        'breakdown': breakdown,
        'projections': {
            'engaged': {
                'balance_cents': engaged_balance,
                'low_point_cents': timeline['low_point_cents'],
                'low_point_date': timeline['low_point_date'],
                'definition': 'Solde et échéances confirmées uniquement',
            },
            'realistic': {
                'balance_cents': realistic_balance,
                'low_point_cents': realistic_balance,
                'low_point_date': result.horizon_end,
                'definition': 'Projection engagée et charges récurrentes validées',
            },
            'prudent': {
                'balance_cents': prudent_balance,
                'low_point_cents': prudent_balance,
                'low_point_date': result.horizon_end,
                'definition': 'Projection réaliste, objectifs engagés et marge de sécurité',
            },
        },
        'confirmed_timeline': timeline['events'],
        'confidence': confidence,
        'controls': {
            'goals_not_double_counted': True,
            'stale_recurrences_excluded': result.recurring_stale_excluded_count,
            'planned_occurrences': result.planned_occurrence_count,
            'recurring_occurrences': result.recurring_occurrence_count,
            'read_only': True,
        },
    }
