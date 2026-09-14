from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Iterable

from .safe_to_spend import calculate_safe_to_spend, recurring_is_fresh


STRUCTURING_INCOME_KINDS = {'salary', 'structuring_income'}
VARIABLE_CATEGORIES = {'Alimentation', 'Restaurants', 'Shopping', 'Loisirs', 'Santé', 'Transport'}
EXCLUDED_CATEGORIES = {
    'Salaire', 'Remboursement', 'Logement', 'Télécom', 'Assurances', 'Crédits',
    'Impôts', 'Épargne', 'Investissement', 'Transfert interne', 'Frais professionnel remboursé',
}


@dataclass(frozen=True)
class PlannedEvent:
    due_date: date
    amount_cents: int
    label: str
    certainty: str = 'confirmed'
    kind: str = 'commitment'
    source: str = 'planned'


def build_forecast(*, today: date, opening_balance_cents: int, events: Iterable[PlannedEvent], safety_reserve_cents: int = 0, allocated_cents: int = 0, rule_reserved_cents: int = 0) -> dict:
    ordered = sorted((e for e in events if e.due_date >= today), key=lambda e: (e.due_date, e.amount_cents, e.label))
    next_income = next((e for e in ordered if e.amount_cents > 0 and e.kind in STRUCTURING_INCOME_KINDS), None)
    if next_income:
        horizon = next_income.due_date
    else:
        next_month = (today.replace(day=28) + timedelta(days=4)).replace(day=1)
        horizon = next_month - timedelta(days=1)

    relevant = [e for e in ordered if e.due_date <= horizon]
    by_day: dict[date, list[PlannedEvent]] = {}
    for event in relevant:
        by_day.setdefault(event.due_date, []).append(event)

    balance = opening_balance_cents
    low_balance = opening_balance_cents
    low_date = today
    timeline = []
    cursor = today
    while cursor <= horizon:
        for event in by_day.get(cursor, []):
            balance += event.amount_cents
        if balance < low_balance:
            low_balance = balance
            low_date = cursor
        timeline.append({'date': cursor.isoformat(), 'balance_cents': balance})
        cursor += timedelta(days=1)

    commitments = -sum(e.amount_cents for e in relevant if e.amount_cents < 0)
    unavailable = max(0, safety_reserve_cents) + max(0, allocated_cents) + max(0, rule_reserved_cents)
    safe_to_spend = max(0, low_balance - unavailable)
    days = max(1, (horizon - today).days)
    daily_budget = max(0, safe_to_spend // days)

    return {
        'opening_balance_cents': opening_balance_cents,
        'horizon': horizon.isoformat(),
        'next_income': None if next_income is None else {'date': next_income.due_date.isoformat(), 'amount_cents': next_income.amount_cents, 'label': next_income.label, 'kind': next_income.kind},
        'commitments_cents': commitments,
        'safety_reserve_cents': safety_reserve_cents,
        'allocated_cents': allocated_cents,
        'rule_reserved_cents': rule_reserved_cents,
        'safe_to_spend_cents': safe_to_spend,
        'daily_budget_cents': daily_budget,
        'low_point': {'date': low_date.isoformat(), 'balance_cents': low_balance},
        'closing_balance_cents': balance,
        'timeline': timeline,
        'events': [{'date': e.due_date.isoformat(), 'amount_cents': e.amount_cents, 'label': e.label, 'certainty': e.certainty, 'kind': e.kind, 'source': e.source} for e in relevant],
        'explanation': {
            'current_balance_cents': opening_balance_cents,
            'planned_outflows_cents': commitments,
            'allocated_cents': allocated_cents,
            'rule_reserved_cents': rule_reserved_cents,
            'reserve_cents': safety_reserve_cents,
            'low_point_before_reserve_cents': low_balance,
            'available_cents': safe_to_spend,
        },
    }


def _next_month_same_day(value: date, day: int) -> date:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(1, day), max_day))


def _recurring_dates(first: date, usual_day: int, start: date, end: date) -> list[date]:
    current = first
    while current < start:
        current = _next_month_same_day(current, usual_day)
    result: list[date] = []
    while current <= end:
        result.append(current)
        current = _next_month_same_day(current, usual_day)
    return result


def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (name,)).fetchone())


def _normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def _matches_validated_recurrence(label_norm: str, recurring_labels: set[str]) -> bool:
    if not label_norm:
        return False
    if label_norm in recurring_labels:
        return True
    return any(len(recurring) >= 5 and recurring in label_norm for recurring in recurring_labels)


def _historical_variable_daily_rate(conn, as_of: date, months: int = 6) -> tuple[int, str, int]:
    recurring_labels = {
        _normalize(row['label'])
        for row in conn.execute("SELECT label FROM recurring_transactions WHERE detection_status='accepted' AND amount_cents<0").fetchall()
        if row['label']
    }
    fixed_markers = ('NAVIGO', 'COMUTITRES', 'VELIB')
    monthly_rates: list[float] = []
    classified_rows = 0
    year, month = as_of.year, as_of.month
    if month == 1:
        year, month = year - 1, 12
    else:
        month -= 1
    month_keys: list[tuple[int, int]] = []
    for _ in range(max(1, months)):
        month_keys.append((year, month))
        if month == 1:
            year, month = year - 1, 12
        else:
            month -= 1
    month_keys.reverse()
    for year, month in month_keys:
        start = date(year, month, 1)
        end = date(year, month, calendar.monthrange(year, month)[1])
        rows = conn.execute('''
            SELECT amount_cents,label,category,transaction_type,is_internal_transfer
            FROM transactions
            WHERE booking_date>=? AND booking_date<=?
              AND amount_cents<0
              AND COALESCE(status,'confirmed')='confirmed'
        ''', (start.isoformat(), end.isoformat())).fetchall()
        total = 0
        for row in rows:
            category = row['category'] or ''
            label_norm = _normalize(row['label'])
            tx_type = _normalize(row['transaction_type'])
            if int(row['is_internal_transfer'] or 0) == 1:
                continue
            if category in EXCLUDED_CATEGORIES:
                continue
            if tx_type in {'INCOME', 'REFUND', 'TRANSFER', 'SAVING', 'INVESTMENT'}:
                continue
            recurring = _matches_validated_recurrence(label_norm, recurring_labels) or any(marker in label_norm for marker in fixed_markers)
            if recurring:
                continue
            if category in VARIABLE_CATEGORIES:
                total += abs(int(row['amount_cents']))
                classified_rows += 1
        monthly_rates.append(total / calendar.monthrange(year, month)[1])
    if not monthly_rates:
        return 0, 'low', classified_rows
    daily = int(round(median(monthly_rates)))
    confidence = 'medium' if months >= 4 and classified_rows > 0 else 'low'
    return daily, confidence, classified_rows


def build_validated_daily_forecast(conn, *, as_of: date | None = None) -> dict:
    sts = calculate_safe_to_spend(conn, as_of=as_of, horizon_days=None, stale_reference_date=date.today())
    as_of_date = date.fromisoformat(sts.as_of)
    horizon_end = date.fromisoformat(sts.horizon_end)
    events_by_date: dict[str, list[dict]] = {}

    planned_rows = conn.execute('''
        SELECT due_date,amount_cents,label,kind,certainty
        FROM planned_transactions
        WHERE status='planned' AND amount_cents<0 AND due_date>? AND due_date<=?
        ORDER BY due_date,id
    ''', (as_of_date.isoformat(), horizon_end.isoformat())).fetchall()
    for row in planned_rows:
        events_by_date.setdefault(row['due_date'], []).append({'type': 'planned_commitment', 'label': row['label'], 'amount_cents': int(row['amount_cents']), 'certainty': row['certainty']})

    recurring_rows = conn.execute('''
        SELECT label,amount_cents,usual_day,day_of_month,next_expected_date,last_seen_date,confidence,source_type
        FROM recurring_transactions
        WHERE is_active=1 AND detection_status='accepted' AND amount_cents<0
        ORDER BY label
    ''').fetchall()
    for row in recurring_rows:
        source_type = (row['source_type'] or '').lower()
        auto_detected = source_type in {'history', 'auto', 'detected'}
        if auto_detected and not recurring_is_fresh(row['last_seen_date'], as_of_date):
            continue
        usual_day = int(row['usual_day'] or row['day_of_month'] or 1)
        if row['next_expected_date']:
            first = date.fromisoformat(row['next_expected_date'])
        else:
            max_day = calendar.monthrange(as_of_date.year, as_of_date.month)[1]
            first = date(as_of_date.year, as_of_date.month, min(max(1, usual_day), max_day))
        for occurrence in _recurring_dates(first, usual_day, as_of_date + timedelta(days=1), horizon_end):
            events_by_date.setdefault(occurrence.isoformat(), []).append({'type': 'recurring_commitment', 'label': row['label'], 'amount_cents': int(row['amount_cents']), 'confidence': float(row['confidence'] or 0)})

    protected_static = int(sts.safety_reserve_cents) + int(sts.planned_commitments_cents)
    protected_static -= sum(abs(int(row['amount_cents'])) for row in planned_rows)
    protected_static = max(0, protected_static)
    total_dated_commitments = sum(abs(int(event['amount_cents'])) for events in events_by_date.values() for event in events if int(event['amount_cents']) < 0)
    remaining_committed = total_dated_commitments

    variable_daily_rate, variable_confidence, variable_rows = _historical_variable_daily_rate(conn, as_of_date, 6)
    baseline_safe = int(sts.safe_to_spend_cents or 0)

    timeline = []
    projected_balance = int(sts.balance_cents)
    low_balance = projected_balance
    low_date = as_of_date
    cursor = as_of_date
    elapsed_prediction_days = 0
    while cursor <= horizon_end:
        key = cursor.isoformat()
        opening = projected_balance
        events = events_by_date.get(key, [])
        movement = sum(int(event['amount_cents']) for event in events)
        projected_balance += movement
        paid_commitments = sum(abs(int(event['amount_cents'])) for event in events if int(event['amount_cents']) < 0)
        remaining_committed = max(0, remaining_committed - paid_commitments)
        if projected_balance < low_balance:
            low_balance = projected_balance
            low_date = cursor
        safe_remaining = max(0, projected_balance - protected_static - remaining_committed)
        if cursor > as_of_date:
            elapsed_prediction_days += 1
        expected_variable_spend = variable_daily_rate * elapsed_prediction_days
        expected_safe_after_variable = max(0, safe_remaining - expected_variable_spend)
        timeline.append({
            'date': key,
            'opening_balance_cents': opening,
            'movement_cents': movement,
            'closing_balance_cents': projected_balance,
            'protected_static_cents': protected_static,
            'remaining_committed_cents': remaining_committed,
            'safe_to_spend_remaining_cents': safe_remaining,
            'safe_to_spend_cents': safe_remaining,
            'expected_variable_spend_cents': expected_variable_spend,
            'expected_safe_after_variable_cents': expected_safe_after_variable,
            'events': events,
        })
        cursor += timedelta(days=1)

    days_remaining = max(1, (horizon_end - as_of_date).days)
    daily_budget = baseline_safe // days_remaining
    projected_variable_to_horizon = variable_daily_rate * days_remaining
    expected_remaining_at_horizon = max(0, baseline_safe - projected_variable_to_horizon)

    # True bank balance projected at the horizon: current balance minus all
    # protected cash commitments that still have to leave the account, minus
    # the expected variable spend. The safety reserve is NOT an outflow; it is
    # the portion of the projected bank balance that Flow intends to preserve.
    projected_bank_balance_at_horizon = max(
        0,
        int(sts.balance_cents)
        - int(sts.planned_commitments_cents)
        - int(sts.recurring_commitments_cents)
        - projected_variable_to_horizon,
    )
    projected_margin_above_safety = max(
        0,
        projected_bank_balance_at_horizon - int(sts.safety_reserve_cents),
    )

    return {
        'as_of': sts.as_of,
        'horizon_end': sts.horizon_end,
        'horizon_days': sts.horizon_days,
        'horizon_mode': sts.horizon_mode,
        'next_salary_date': sts.next_salary_date,
        'starting_balance_cents': sts.balance_cents,
        'baseline_safe_to_spend_cents': sts.safe_to_spend_cents,
        'safety_reserve_cents': sts.safety_reserve_cents,
        'planned_commitments_cents': sts.planned_commitments_cents,
        'recurring_commitments_cents': sts.recurring_commitments_cents,
        'protected_commitments_cents': int(sts.planned_commitments_cents) + int(sts.recurring_commitments_cents),
        'protected_static_cents': protected_static,
        'dated_commitments_cents': total_dated_commitments,
        'daily_budget_cents': daily_budget,
        'variable_daily_rate_cents': variable_daily_rate,
        'variable_projection_confidence': variable_confidence,
        'variable_history_rows': variable_rows,
        'projected_variable_to_horizon_cents': projected_variable_to_horizon,
        'expected_remaining_after_variable_spend_cents': expected_remaining_at_horizon,
        'projected_bank_balance_at_horizon_cents': projected_bank_balance_at_horizon,
        'projected_margin_above_safety_cents': projected_margin_above_safety,
        'projection_semantics': {
            'bank_balance': 'projected_after_known_commitments_and_variable_spend',
            'safe_to_spend': 'current_decision_envelope_after_reserve_and_commitments',
            'margin': 'projected_bank_balance_minus_safety_reserve',
            'legacy_closing_balance': 'dated_commitments_only_excludes_static_cycle_reserves_and_variable_spend',
        },
        'low_point': {'date': low_date.isoformat(), 'balance_cents': low_balance},
        'closing_balance_cents': projected_balance,
        'legacy_dated_closing_balance_cents': projected_balance,
        'timeline': timeline,
    }
