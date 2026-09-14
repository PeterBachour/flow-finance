from __future__ import annotations

import calendar
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from statistics import median


STALE_BALANCE_DAYS = 7
RECURRING_STALE_DAYS = 45
DEFAULT_HORIZON_DAYS = 30
MIN_RECONCILED_SALARIES = 3
SALARY_LOOKBACK = 8


@dataclass
class SafeToSpendResult:
    as_of: str
    horizon_end: str
    horizon_days: int
    horizon_mode: str
    next_salary_date: str | None
    balance_cents: int
    safety_reserve_cents: int
    planned_commitments_cents: int
    recurring_commitments_cents: int
    goal_contributions_cents: int
    goal_contribution_mode: str
    calculated_safe_to_spend_cents: int
    safe_to_spend_status: str
    included_account_count: int
    balance_age_days: int
    balance_is_stale: bool
    recurring_occurrence_count: int
    recurring_included_count: int
    recurring_stale_excluded_count: int
    planned_occurrence_count: int
    goal_count: int
    cycle_reserve_count: int

    @property
    def safe_to_spend_cents(self) -> int | None:
        if self.safe_to_spend_status != 'available':
            return None
        return self.calculated_safe_to_spend_cents

    def as_dict(self) -> dict:
        payload = asdict(self)
        payload['safe_to_spend_cents'] = self.safe_to_spend_cents
        return payload


def _setting_int(conn, key: str, default: int = 0) -> int:
    row = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    if not row:
        return default
    try:
        return int(row['value'])
    except (TypeError, ValueError):
        return default


def _table_exists(conn, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return bool(row)


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


def _shift_weekend_back(value: date) -> date:
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def _salary_candidate_for_month(year: int, month: int, usual_day: int) -> date:
    day = min(max(1, usual_day), calendar.monthrange(year, month)[1])
    return _shift_weekend_back(date(year, month, day))


def predict_next_salary_date(conn, as_of: date, lookback: int = SALARY_LOOKBACK) -> tuple[date | None, str]:
    if not (_table_exists(conn, 'payroll_transaction_matches') and _table_exists(conn, 'payroll_records')):
        return None, 'fallback_missing_payroll_schema'

    rows = conn.execute('''
        SELECT t.booking_date,m.confidence
        FROM payroll_transaction_matches m
        JOIN payroll_records p ON p.id=m.payroll_record_id
        JOIN transactions t ON t.id=m.transaction_id
        WHERE t.amount_cents > 0
          AND t.booking_date <= ?
        ORDER BY t.booking_date DESC,t.id DESC
        LIMIT ?
    ''', (as_of.isoformat(), max(MIN_RECONCILED_SALARIES, lookback))).fetchall()

    if len(rows) < MIN_RECONCILED_SALARIES:
        return None, 'fallback_insufficient_reconciled_salary_history'

    dates = [date.fromisoformat(row['booking_date']) for row in reversed(rows)]
    recent_days = [d.day for d in dates[-min(6, len(dates)):]]
    usual_day = int(round(median(recent_days)))

    year, month = as_of.year, as_of.month
    candidate = _salary_candidate_for_month(year, month, usual_day)
    if candidate <= as_of:
        if month == 12:
            year, month = year + 1, 1
        else:
            month += 1
        candidate = _salary_candidate_for_month(year, month, usual_day)

    return candidate, 'next_salary_reconciled_history'


def recurring_is_fresh(last_seen_date: str | None, as_of: date) -> bool:
    if not last_seen_date:
        return False
    try:
        last_seen = date.fromisoformat(last_seen_date)
    except ValueError:
        return False
    return (as_of - last_seen).days <= RECURRING_STALE_DAYS


def _normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def _planned_overlaps_recurring(planned_rows, recurring_row, occurrence: date) -> bool:
    recurring_label = _normalize(recurring_row['label'])
    if not recurring_label:
        return False
    recurring_amount = abs(int(recurring_row['amount_cents'] or 0))
    tolerance = max(int(recurring_row['tolerance_cents'] or 0), max(100, int(recurring_amount * 0.10)))
    for planned in planned_rows:
        try:
            planned_date = date.fromisoformat(planned['due_date'])
        except (TypeError, ValueError):
            continue
        if abs((planned_date - occurrence).days) > 5:
            continue
        planned_label = _normalize(planned['label'])
        label_match = recurring_label in planned_label or planned_label in recurring_label
        amount_match = abs(abs(int(planned['amount_cents'])) - recurring_amount) <= tolerance
        if label_match and amount_match:
            return True
    return False


def _cycle_overlaps_recurring(cycle_rows, recurring_row, occurrence: date, cycle_month: str) -> bool:
    if occurrence.strftime('%Y-%m') != cycle_month:
        return False
    recurring_label = _normalize(recurring_row['label'])
    if not recurring_label:
        return False
    recurring_amount = abs(int(recurring_row['amount_cents'] or 0))
    tolerance = max(int(recurring_row['tolerance_cents'] or 0), max(100, int(recurring_amount * 0.10)))
    for reserve in cycle_rows:
        if reserve['kind'] != 'planned_commitment':
            continue
        reserve_label = _normalize(reserve['label'])
        label_match = reserve_label and (recurring_label in reserve_label or reserve_label in recurring_label)
        amount_match = abs(int(reserve['amount_cents'] or 0) - recurring_amount) <= tolerance
        if label_match and amount_match:
            return True
    return False


def _goal_cash_impact_for_cycle(conn, cycle_month: str, as_of: date) -> tuple[int, str]:
    if not _table_exists(conn, 'financial_goals'):
        return 0, 'no_goal_schema'

    goal_count = conn.execute(
        'SELECT COUNT(*) FROM financial_goals WHERE is_active=1 AND monthly_contribution_cents>0'
    ).fetchone()[0]
    if not goal_count:
        return 0, 'no_active_monthly_goals'

    if not _table_exists(conn, 'goal_allocations'):
        return 0, 'planning_targets_not_cash_reserved'

    conn.execute('''
        SELECT COUNT(*)
        FROM goal_allocations ga
        WHERE ga.allocated_on<=?
          AND (
              ga.allocated_on>=?
              OR ga.note LIKE ?
          )
    ''', (as_of.isoformat(), f'{cycle_month}-01', f'cycle={cycle_month};%')).fetchone()

    return 0, 'allocation_driven_no_unfunded_cash_reservation'


def _balance_dates(account_rows) -> tuple[list[date], bool]:
    parsed: list[date] = []
    incomplete = False
    for row in account_rows:
        raw = row['balance_as_of']
        if not raw:
            incomplete = True
            continue
        try:
            parsed.append(date.fromisoformat(raw))
        except (TypeError, ValueError):
            incomplete = True
    return parsed, incomplete


def calculate_safe_to_spend(
    conn,
    *,
    as_of: date | None = None,
    horizon_days: int | None = None,
    stale_reference_date: date | None = None,
) -> SafeToSpendResult:
    account_rows = conn.execute('''
        SELECT id,current_balance_cents,balance_as_of
        FROM accounts
        WHERE is_active=1 AND include_in_safe_to_spend=1
    ''').fetchall()

    included_account_count = len(account_rows)
    balance_cents = sum(int(row['current_balance_cents'] or 0) for row in account_rows)
    known_dates, incomplete_balance_dates = _balance_dates(account_rows)
    oldest_balance_date = min(known_dates) if known_dates else None

    if as_of is None:
        as_of = oldest_balance_date or date.today()

    next_salary_date: date | None = None
    if horizon_days is None:
        next_salary_date, prediction_mode = predict_next_salary_date(conn, as_of)
        if next_salary_date:
            horizon_end = max(as_of, next_salary_date - timedelta(days=1))
            effective_horizon_days = max(0, (horizon_end - as_of).days)
            horizon_mode = prediction_mode
        else:
            effective_horizon_days = DEFAULT_HORIZON_DAYS
            horizon_end = as_of + timedelta(days=effective_horizon_days)
            horizon_mode = prediction_mode
    else:
        effective_horizon_days = max(0, horizon_days)
        horizon_end = as_of + timedelta(days=effective_horizon_days)
        horizon_mode = 'manual_days'

    cycle_month = as_of.strftime('%Y-%m')
    cycle_rows = []
    if _table_exists(conn, 'cycle_reserves'):
        cycle_rows = conn.execute('''
            SELECT label,amount_cents,kind
            FROM cycle_reserves
            WHERE cycle_month=?
              AND status='active'
              AND source_status='confirmed'
        ''', (cycle_month,)).fetchall()

    cycle_reserve_count = len(cycle_rows)
    cycle_safety = sum(max(0, int(row['amount_cents'] or 0)) for row in cycle_rows if row['kind'] == 'safety_reserve')
    cycle_planned = sum(max(0, int(row['amount_cents'] or 0)) for row in cycle_rows if row['kind'] == 'planned_commitment')
    safety_reserve = cycle_safety if cycle_safety > 0 else max(0, _setting_int(conn, 'safety_reserve_cents', 0))

    planned_rows = conn.execute('''
        SELECT id,label,amount_cents,due_date
        FROM planned_transactions
        WHERE status='planned'
          AND kind='commitment'
          AND amount_cents<0
          AND due_date>? AND due_date<=?
    ''', (as_of.isoformat(), horizon_end.isoformat())).fetchall()
    planned_commitments = sum(abs(int(row['amount_cents'])) for row in planned_rows) + cycle_planned

    recurring_rows = conn.execute('''
        SELECT id,label,amount_cents,usual_day,day_of_month,next_expected_date,last_seen_date,
               source_type,tolerance_cents,category,kind
        FROM recurring_transactions
        WHERE is_active=1
          AND detection_status='accepted'
          AND amount_cents<0
          AND COALESCE(kind,'commitment')='commitment'
          AND COALESCE(category,'')<>'Transfert interne'
    ''').fetchall()
    recurring_commitments = 0
    recurring_occurrence_count = 0
    recurring_included_count = 0
    recurring_stale_excluded_count = 0
    for row in recurring_rows:
        source_type = (row['source_type'] or '').lower()
        auto_detected = source_type in {'history', 'auto', 'detected'}
        if auto_detected and not recurring_is_fresh(row['last_seen_date'], as_of):
            recurring_stale_excluded_count += 1
            continue

        usual_day = int(row['usual_day'] or row['day_of_month'] or 1)
        if row['next_expected_date']:
            first = date.fromisoformat(row['next_expected_date'])
        else:
            max_day = calendar.monthrange(as_of.year, as_of.month)[1]
            first = date(as_of.year, as_of.month, min(max(1, usual_day), max_day))
        dates = _recurring_dates(first, usual_day, as_of + timedelta(days=1), horizon_end)
        effective_dates = [
            d for d in dates
            if not _planned_overlaps_recurring(planned_rows, row, d)
            and not _cycle_overlaps_recurring(cycle_rows, row, d, cycle_month)
        ]
        if not effective_dates:
            continue
        recurring_included_count += 1
        recurring_occurrence_count += len(effective_dates)
        recurring_commitments += abs(int(row['amount_cents'])) * len(effective_dates)

    if _table_exists(conn, 'financial_goals'):
        goal_rows = conn.execute('''
            SELECT monthly_contribution_cents
            FROM financial_goals
            WHERE is_active=1 AND monthly_contribution_cents>0
        ''').fetchall()
    else:
        goal_rows = []
    goal_contributions, goal_contribution_mode = _goal_cash_impact_for_cycle(conn, cycle_month, as_of)

    reserved = safety_reserve + planned_commitments + recurring_commitments + goal_contributions
    calculated_safe_to_spend = max(0, balance_cents - reserved)

    reference = stale_reference_date or date.today()
    if oldest_balance_date and not incomplete_balance_dates:
        balance_age_days = max(0, (reference - oldest_balance_date).days)
    else:
        balance_age_days = 999999
    balance_is_stale = balance_age_days > STALE_BALANCE_DAYS

    if included_account_count == 0:
        safe_to_spend_status = 'unavailable_no_account'
    elif incomplete_balance_dates or oldest_balance_date is None:
        safe_to_spend_status = 'unavailable_no_balance_date'
    elif balance_is_stale:
        safe_to_spend_status = 'unavailable_stale_balance'
    else:
        safe_to_spend_status = 'available'

    return SafeToSpendResult(
        as_of=as_of.isoformat(),
        horizon_end=horizon_end.isoformat(),
        horizon_days=effective_horizon_days,
        horizon_mode=horizon_mode,
        next_salary_date=next_salary_date.isoformat() if next_salary_date else None,
        balance_cents=balance_cents,
        safety_reserve_cents=safety_reserve,
        planned_commitments_cents=planned_commitments,
        recurring_commitments_cents=recurring_commitments,
        goal_contributions_cents=goal_contributions,
        goal_contribution_mode=goal_contribution_mode,
        calculated_safe_to_spend_cents=calculated_safe_to_spend,
        safe_to_spend_status=safe_to_spend_status,
        included_account_count=included_account_count,
        balance_age_days=balance_age_days,
        balance_is_stale=balance_is_stale,
        recurring_occurrence_count=recurring_occurrence_count,
        recurring_included_count=recurring_included_count,
        recurring_stale_excluded_count=recurring_stale_excluded_count,
        planned_occurrence_count=len(planned_rows) + sum(1 for row in cycle_rows if row['kind'] == 'planned_commitment'),
        goal_count=len(goal_rows),
        cycle_reserve_count=cycle_reserve_count,
    )