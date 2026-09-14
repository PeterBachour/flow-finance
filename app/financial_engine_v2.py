"""Flow 2.0 financial decision engine.

The engine reads the ledger and current balance snapshots. It never mutates
transactions and never presents inferred future events as confirmed facts.
"""
from __future__ import annotations

import calendar
from datetime import date
from statistics import mean

from .forecast import PlannedEvent, build_forecast
from .financial_engine_v1 import financial_rule_summary
from .safe_to_spend import calculate_safe_to_spend

CONFIDENCE_LABELS = (
    (0.90, 'confirmed'),
    (0.72, 'probable'),
    (0.50, 'estimated'),
    (0.00, 'uncertain'),
)
VALID_RECURRING_STATUSES = {'confirmed', 'validated', 'active', 'accepted'}


def confidence_label(score: float | None) -> str:
    value = 0.0 if score is None else max(0.0, min(1.0, float(score)))
    for threshold, label in CONFIDENCE_LABELS:
        if value >= threshold:
            return label
    return 'uncertain'


def safe_status(cents: int, reserve_cents: int, daily_cents: int) -> str:
    if cents <= 0:
        return 'critical'
    floor = max(1, reserve_cents)
    if cents < max(floor // 2, daily_cents * 2):
        return 'tight'
    if cents < max(floor, daily_cents * 7):
        return 'prudent'
    return 'comfortable'


def _month_shift(value: date, offset: int) -> tuple[int, int]:
    index = value.year * 12 + value.month - 1 + offset
    return index // 12, index % 12 + 1


def _month_key(value: date) -> str:
    return value.strftime('%Y-%m')


def _planned_events(conn, today: date, months_ahead: int = 4) -> list[PlannedEvent]:
    upper_year, upper_month = _month_shift(today, months_ahead)
    upper = date(upper_year, upper_month, calendar.monthrange(upper_year, upper_month)[1])
    rows = conn.execute(
        "SELECT due_date,amount_cents,label,certainty,kind FROM planned_transactions "
        "WHERE status='planned' AND due_date BETWEEN ? AND ? ORDER BY due_date,id",
        (today.isoformat(), upper.isoformat()),
    ).fetchall()
    return [
        PlannedEvent(
            date.fromisoformat(row['due_date']), int(row['amount_cents']), row['label'],
            row['certainty'], row['kind'], 'planned'
        )
        for row in rows
    ]


def _recurrence_score(row) -> float:
    explicit = row['confidence_score'] if 'confidence_score' in row.keys() else None
    if explicit is not None:
        return max(0.0, min(1.0, float(explicit)))
    certainty = (row['certainty'] or '').lower()
    return {'confirmed': 0.98, 'expected': 0.78, 'estimated': 0.58}.get(certainty, 0.42)


def _recurring_events(conn, today: date, months_ahead: int = 4) -> list[PlannedEvent]:
    rows = conn.execute("SELECT * FROM recurring_transactions WHERE is_active=1 ORDER BY id").fetchall()
    result: list[PlannedEvent] = []
    for row in rows:
        validation_status = str(
            row['validation_status'] if 'validation_status' in row.keys() else 'confirmed'
        ).strip().lower()
        if validation_status not in VALID_RECURRING_STATUSES:
            continue
        score = _recurrence_score(row)
        certainty = row['certainty'] or confidence_label(score)
        for offset in range(months_ahead + 1):
            year, month = _month_shift(today, offset)
            day = min(int(row['day_of_month']), calendar.monthrange(year, month)[1])
            due = date(year, month, day)
            if due < today:
                continue
            kind = row['kind']
            if (row['category'] or '') == 'Salaire' and int(row['amount_cents']) > 0:
                kind = 'salary'
            result.append(PlannedEvent(due, int(row['amount_cents']), row['label'], certainty, kind, 'recurring'))
    return result


def _normalize_event_label(value: str) -> str:
    return ' '.join((value or '').upper().split())


def _same_commitment(planned: PlannedEvent, recurring: PlannedEvent) -> bool:
    if planned.amount_cents == 0 or recurring.amount_cents == 0:
        return False
    if (planned.amount_cents > 0) != (recurring.amount_cents > 0):
        return False
    if abs((planned.due_date - recurring.due_date).days) > 5:
        return False
    planned_amount = abs(int(planned.amount_cents))
    recurring_amount = abs(int(recurring.amount_cents))
    tolerance = max(100, int(recurring_amount * 0.10))
    if abs(planned_amount - recurring_amount) > tolerance:
        return False
    planned_label = _normalize_event_label(planned.label)
    recurring_label = _normalize_event_label(recurring.label)
    if not planned_label or not recurring_label:
        return False
    return planned_label in recurring_label or recurring_label in planned_label


def _dedupe(events: list[PlannedEvent]) -> list[PlannedEvent]:
    result: list[PlannedEvent] = []
    seen: set[tuple[str, int, str]] = set()
    for event in sorted(events, key=lambda e: (e.due_date, e.source == 'recurring', e.label)):
        if event.source == 'recurring' and any(
            existing.source == 'planned' and _same_commitment(existing, event)
            for existing in result
        ):
            continue
        key = (event.due_date.isoformat(), event.amount_cents, _normalize_event_label(event.label))
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result


def _goal_reserved_cents(conn) -> int:
    return int(conn.execute(
        "SELECT COALESCE(SUM(g.amount_cents),0) total FROM goal_allocations g "
        "JOIN accounts a ON a.id=g.account_id "
        "JOIN financial_goals fg ON fg.id=g.goal_id "
        "WHERE a.include_in_safe_to_spend=1 AND fg.is_active=1 "
        "AND COALESCE(fg.include_in_safe_to_spend,1)=1"
    ).fetchone()['total'])


def _reserve_cents(conn, rules: dict) -> int:
    row = conn.execute("SELECT value FROM settings WHERE key='safety_reserve_cents'").fetchone()
    configured = int(row['value']) if row and str(row['value']).strip() else 0
    return max(configured, int(rules.get('minimum_reserve_cents') or 0))


def _forecast_confidence(events: list[PlannedEvent], snapshot_age_days: int | None) -> float:
    if not events:
        base = 0.55
    else:
        weights = {'confirmed': 1.0, 'expected': 0.80, 'estimated': 0.58, 'uncertain': 0.35}
        base = mean(weights.get(event.certainty, 0.5) for event in events)
    if snapshot_age_days is None:
        return max(0.0, base - 0.25)
    if snapshot_age_days > 14:
        return max(0.0, base - 0.30)
    if snapshot_age_days > 7:
        return max(0.0, base - 0.15)
    if snapshot_age_days > 3:
        return max(0.0, base - 0.06)
    return min(1.0, base)


def build_decision_cockpit(conn, today: date | None = None) -> dict:
    today = today or date.today()
    month = _month_key(today)
    rules = financial_rule_summary(conn, month)
    validated = calculate_safe_to_spend(
        conn,
        as_of=today,
        horizon_days=None,
        stale_reference_date=today,
    )

    allocated = _goal_reserved_cents(conn)
    rule_reserved = max(0, int(rules.get('rule_reserve_cents') or 0))
    reserve = max(_reserve_cents(conn, rules), int(validated.safety_reserve_cents))
    extra_reserve = max(0, reserve - int(validated.safety_reserve_cents))
    opening = int(validated.balance_cents)

    events = _dedupe(_planned_events(conn, today) + _recurring_events(conn, today))
    realistic_events = [e for e in events if e.certainty in {'confirmed', 'expected', 'estimated'}]
    committed_events = [e for e in events if e.certainty == 'confirmed']

    # Funded goal allocations are already reflected in account balances. They
    # remain visible as informational metadata but are not deducted again from
    # either projections or the decision amount.
    realistic = build_forecast(
        today=today,
        opening_balance_cents=opening,
        events=realistic_events,
        safety_reserve_cents=reserve,
        allocated_cents=0,
        rule_reserved_cents=rule_reserved,
    )
    committed = build_forecast(
        today=today,
        opening_balance_cents=opening,
        events=committed_events,
        safety_reserve_cents=reserve,
        allocated_cents=0,
        rule_reserved_cents=rule_reserved,
    )

    is_available = validated.safe_to_spend_status == 'available'
    additional_protection = rule_reserved + extra_reserve
    total_safe = (
        max(0, int(validated.calculated_safe_to_spend_cents) - additional_protection)
        if is_available else None
    )
    days_to_horizon = max(1, int(validated.horizon_days) + 1)
    daily = total_safe // days_to_horizon if total_safe is not None else None
    weekly = (
        min(total_safe, daily * min(7, days_to_horizon))
        if total_safe is not None and daily is not None else None
    )
    status = (
        safe_status(total_safe, reserve, daily or 0)
        if total_safe is not None else validated.safe_to_spend_status
    )
    age = None if validated.balance_age_days >= 999999 else int(validated.balance_age_days)
    confidence = _forecast_confidence(realistic_events, age)

    next_income = realistic['next_income']
    if next_income is None and validated.next_salary_date:
        next_income = {
            'date': validated.next_salary_date,
            'amount_cents': None,
            'label': 'Prochain salaire',
            'kind': 'salary',
            'source': 'validated_payroll_prediction',
        }

    return {
        'as_of': today.isoformat(),
        'opening_balance_cents': opening,
        'safe_to_spend': {
            'today_cents': daily,
            'week_cents': weekly,
            'until_income_cents': total_safe,
            'daily_pacing_cents': daily,
            'status': status,
            'availability_status': validated.safe_to_spend_status,
            'is_available': is_available,
            'explanation': {
                'validated_base_cents': int(validated.calculated_safe_to_spend_cents),
                'planned_commitments_cents': int(validated.planned_commitments_cents),
                'recurring_commitments_cents': int(validated.recurring_commitments_cents),
                'goal_allocations_cents': allocated,
                'goal_allocations_cash_impact_cents': 0,
                'goal_allocation_mode': 'funded_allocation_already_in_balance',
                'rule_reserved_cents': rule_reserved,
                'safety_reserve_cents': reserve,
                'additional_reserve_cents': extra_reserve,
                'days_to_horizon': days_to_horizon,
                'horizon_end': validated.horizon_end,
                'horizon_mode': validated.horizon_mode,
                'balance_age_days': age,
                'formula': 'validated safe to spend - reserved rules - extra reserve',
                'today_formula': (
                    'safe until income / remaining days'
                    if is_available else 'unavailable until balance data is fresh'
                ),
            },
        },
        'validated_safe_to_spend': validated.as_dict(),
        'forecast': realistic,
        'projections': {'realistic': realistic, 'committed': committed},
        'confidence': {
            'score': round(confidence, 3),
            'label': confidence_label(confidence),
            'snapshot_age_days': age,
        },
        'next_income': next_income,
        'next_outflow': next((e for e in realistic['events'] if e['amount_cents'] < 0), None),
        'rules': rules,
    }


def _analytics_where(alias: str = 't') -> str:
    return (
        f"{alias}.is_internal_transfer=0 AND COALESCE({alias}.exclude_from_analytics,0)=0 "
        f"AND COALESCE({alias}.transaction_type,'expense') NOT IN ('refund','reimbursement','transfer') "
        f"AND COALESCE({alias}.category,'')<>'Frais professionnel remboursé'"
    )


def month_totals(conn, month: str) -> dict:
    where = _analytics_where()
    row = conn.execute(
        f"SELECT "
        f"COALESCE(SUM(CASE WHEN amount_cents>0 AND is_internal_transfer=0 AND COALESCE(exclude_from_analytics,0)=0 AND transaction_type NOT IN ('refund','reimbursement','transfer') THEN amount_cents ELSE 0 END),0) income, "
        f"COALESCE(SUM(CASE WHEN amount_cents<0 AND {where} THEN -amount_cents ELSE 0 END),0) spent, "
        f"COALESCE(SUM(CASE WHEN amount_cents<0 AND {where} AND COALESCE(category,'') IN ('Logement','Transport','Télécom','Assurances','Crédits','Impôts') THEN -amount_cents ELSE 0 END),0) fixed, "
        f"COALESCE(SUM(CASE WHEN amount_cents<0 AND {where} AND COALESCE(category,'') NOT IN ('Logement','Transport','Télécom','Assurances','Crédits','Impôts','Épargne','Investissement') THEN -amount_cents ELSE 0 END),0) variable, "
        f"COALESCE(SUM(CASE WHEN amount_cents<0 AND {where} AND COALESCE(category,'') IN ('Épargne','Investissement') THEN -amount_cents ELSE 0 END),0) saving "
        f"FROM transactions t WHERE substr(booking_date,1,7)=?",
        (month,),
    ).fetchone()
    transfers = conn.execute(
        "SELECT COALESCE(SUM(ABS(amount_cents)),0) total FROM transactions "
        "WHERE substr(booking_date,1,7)=? AND is_internal_transfer=1",
        (month,),
    ).fetchone()['total']
    return {
        'income_cents': int(row['income']),
        'spent_cents': int(row['spent']),
        'fixed_cents': int(row['fixed']),
        'variable_cents': int(row['variable']),
        'saving_cents': int(row['saving']),
        'transfers_cents': int(transfers),
        'net_cents': int(row['income']) - int(row['spent']),
    }


def category_spending(conn, month: str) -> dict[str, int]:
    rows = conn.execute(
        f"SELECT COALESCE(category,'Non catégorisé') category, COALESCE(SUM(-amount_cents),0) total "
        f"FROM transactions t WHERE substr(booking_date,1,7)=? AND amount_cents<0 "
        f"AND {_analytics_where()} GROUP BY COALESCE(category,'Non catégorisé')",
        (month,),
    ).fetchall()
    return {row['category']: int(row['total']) for row in rows}


def _previous_month_keys(current: date, count: int) -> list[str]:
    result = []
    for offset in range(1, count + 1):
        year, month = _month_shift(current.replace(day=1), -offset)
        result.append(f'{year:04d}-{month:02d}')
    return result


def trend_summary(conn, today: date | None = None) -> dict:
    today = today or date.today()
    current_key = _month_key(today)
    current = category_spending(conn, current_key)
    prev_keys = _previous_month_keys(today, 6)
    histories = {key: category_spending(conn, key) for key in prev_keys}
    categories = sorted(set(current).union(*(values.keys() for values in histories.values())))
    result = []
    for category in categories:
        current_value = current.get(category, 0)
        values3 = [histories[key].get(category, 0) for key in prev_keys[:3]]
        values6 = [histories[key].get(category, 0) for key in prev_keys[:6]]
        avg3 = round(mean(values3)) if values3 else 0
        avg6 = round(mean(values6)) if values6 else 0
        previous = histories[prev_keys[0]].get(category, 0) if prev_keys else 0
        delta = current_value - avg3
        pct = None if avg3 == 0 else round(delta / avg3 * 100, 1)
        result.append({
            'category': category,
            'current_cents': current_value,
            'average_3m_cents': avg3,
            'average_6m_cents': avg6,
            'previous_month_cents': previous,
            'delta_vs_3m_cents': delta,
            'delta_vs_3m_pct': pct,
            'direction': 'up' if delta > 0 else ('down' if delta < 0 else 'flat'),
        })
    return {'month': current_key, 'categories': sorted(result, key=lambda x: x['current_cents'], reverse=True)}


def monthly_insights(conn, today: date | None = None) -> list[dict]:
    today = today or date.today()
    trend = trend_summary(conn, today)
    insights = []
    for item in trend['categories']:
        avg = item['average_3m_cents']
        delta = item['delta_vs_3m_cents']
        if avg >= 5000 and delta >= max(2500, int(avg * 0.25)):
            insights.append({
                'kind': 'category_increase',
                'category': item['category'],
                'impact_cents': delta,
                'title': f"{item['category']} au-dessus de ta tendance",
                'body': f"{item['current_cents']/100:.0f} € ce mois, soit {delta/100:.0f} € au-dessus de la moyenne 3 mois.",
            })
        elif avg >= 5000 and delta <= -max(2500, int(avg * 0.25)):
            insights.append({
                'kind': 'category_decrease',
                'category': item['category'],
                'impact_cents': delta,
                'title': f"{item['category']} mieux maîtrisé",
                'body': f"{abs(delta)/100:.0f} € sous la moyenne 3 mois sur la période courante.",
            })
    return insights[:6]


def data_quality(conn, today: date | None = None) -> dict:
    today = today or date.today()
    issues: list[dict] = []
    uncategorized = int(conn.execute(
        "SELECT COUNT(*) n FROM transactions WHERE COALESCE(category,'')='' AND is_internal_transfer=0"
    ).fetchone()['n'])
    if uncategorized:
        issues.append({'type': 'uncategorized', 'severity': 'warning', 'count': uncategorized, 'title': 'Mouvements sans catégorie'})

    duplicates = conn.execute(
        "SELECT booking_date,amount_cents,upper(trim(label)) label,COUNT(*) n FROM transactions "
        "GROUP BY booking_date,amount_cents,upper(trim(label)) HAVING COUNT(*)>1 LIMIT 25"
    ).fetchall()
    if duplicates:
        issues.append({'type': 'potential_duplicates', 'severity': 'warning', 'count': len(duplicates), 'title': 'Doublons potentiels'})

    unmatched = int(conn.execute(
        "SELECT COUNT(*) n FROM transactions WHERE is_internal_transfer=1 AND transfer_pair_id IS NULL"
    ).fetchone()['n'])
    if unmatched:
        issues.append({'type': 'unmatched_transfers', 'severity': 'info', 'count': unmatched, 'title': 'Transferts internes non liés'})

    stale = []
    for row in conn.execute(
        "SELECT id,name,balance_as_of FROM accounts WHERE is_active=1 AND include_in_safe_to_spend=1"
    ).fetchall():
        age = None
        if row['balance_as_of']:
            try:
                age = (today - date.fromisoformat(row['balance_as_of'])).days
            except ValueError:
                pass
        if age is None or age > 7:
            stale.append({'account_id': row['id'], 'name': row['name'], 'age_days': age})
    if stale:
        issues.append({
            'type': 'stale_balance',
            'severity': 'critical' if any(x['age_days'] is None or x['age_days'] > 14 for x in stale) else 'warning',
            'count': len(stale),
            'title': 'Solde à rafraîchir',
            'accounts': stale,
        })

    weighted = sum({'critical': 25, 'warning': 10, 'info': 4}.get(issue['severity'], 5) for issue in issues)
    score = max(0, 100 - weighted)
    return {'score': score, 'status': 'good' if score >= 85 else ('watch' if score >= 65 else 'poor'), 'issues': issues}


def simulate_purchase(conn, amount_cents: int, due_date: date, today: date | None = None) -> dict:
    today = today or date.today()
    amount = abs(int(amount_cents))
    baseline = build_decision_cockpit(conn, today)
    if not baseline['safe_to_spend']['is_available']:
        return {
            'amount_cents': amount,
            'due_date': due_date.isoformat(),
            'before': {'safe_to_spend_cents': None},
            'after': {'safe_to_spend_cents': None},
            'impact': {'safe_to_spend_cents': None},
            'recommendation': 'unavailable_stale_or_missing_balance',
        }

    base_forecast = baseline['forecast']
    events = [
        PlannedEvent(
            date.fromisoformat(e['date']), int(e['amount_cents']), e['label'],
            e['certainty'], e['kind'], e['source']
        )
        for e in base_forecast['events']
    ]
    events.append(PlannedEvent(due_date, -amount, 'Simulation', 'confirmed', 'commitment', 'simulation'))
    explanation = baseline['safe_to_spend']['explanation']
    simulated = build_forecast(
        today=today,
        opening_balance_cents=baseline['opening_balance_cents'],
        events=events,
        safety_reserve_cents=int(explanation['safety_reserve_cents']),
        allocated_cents=0,
        rule_reserved_cents=int(explanation['rule_reserved_cents']),
    )
    before = int(baseline['safe_to_spend']['until_income_cents'])
    simulated_forecast_safe = int(simulated['safe_to_spend_cents'])
    after = max(0, min(before - amount, simulated_forecast_safe))
    reserve = int(explanation['safety_reserve_cents'])
    if after <= 0 or simulated['low_point']['balance_cents'] < reserve:
        recommendation = 'compromises_objective' if after <= 0 else 'not_recommended'
    elif amount > before * 0.75:
        recommendation = 'possible_but_prudent'
    else:
        recommendation = 'ok'
    return {
        'amount_cents': amount,
        'due_date': due_date.isoformat(),
        'before': {
            'safe_to_spend_cents': before,
            'low_point_cents': int(base_forecast['low_point']['balance_cents']),
            'closing_balance_cents': int(base_forecast['closing_balance_cents']),
        },
        'after': {
            'safe_to_spend_cents': after,
            'low_point_cents': int(simulated['low_point']['balance_cents']),
            'closing_balance_cents': int(simulated['closing_balance_cents']),
        },
        'impact': {
            'safe_to_spend_cents': after - before,
            'low_point_cents': int(simulated['low_point']['balance_cents']) - int(base_forecast['low_point']['balance_cents']),
            'closing_balance_cents': int(simulated['closing_balance_cents']) - int(base_forecast['closing_balance_cents']),
        },
        'recommendation': recommendation,
    }