from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date
from statistics import mean, median

from .forecast import build_validated_daily_forecast
from .safe_to_spend import calculate_safe_to_spend
from .spending_classification import accepted_recurring_labels, classify_outflow


def _previous_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _complete_months_before(as_of: date, count: int) -> list[str]:
    year, month = _previous_month(as_of.year, as_of.month)
    result: list[str] = []
    for _ in range(max(3, count)):
        result.append(f'{year:04d}-{month:02d}')
        year, month = _previous_month(year, month)
    return list(reversed(result))


def _historical_trends(conn, as_of: date, history_months: int) -> dict:
    months = _complete_months_before(as_of, history_months)
    start = f'{months[0]}-01'
    year, month = map(int, months[-1].split('-'))
    end = date(year, month, calendar.monthrange(year, month)[1]).isoformat()
    recurring_labels = accepted_recurring_labels(conn)

    rows = conn.execute(
        '''SELECT booking_date,amount_cents,label,category,transaction_type,is_internal_transfer
           FROM transactions
           WHERE booking_date>=? AND booking_date<=?
             AND amount_cents<0
             AND COALESCE(status,'confirmed')='confirmed'
           ORDER BY booking_date,id''',
        (start, end),
    ).fetchall()

    by_month = {key: defaultdict(int) for key in months}
    for row in rows:
        key = row['booking_date'][:7]
        if key not in by_month:
            continue
        kind = classify_outflow(row, recurring_labels)
        by_month[key][kind] += abs(int(row['amount_cents']))

    monthly = []
    for key in months:
        data = by_month[key]
        known = data['fixed'] + data['variable'] + data['other_classified']
        reviewable = known + data['unknown']
        coverage = (100.0 * known / reviewable) if reviewable else 100.0
        monthly.append({
            'month': key,
            'fixed_cents': data['fixed'],
            'variable_cents': data['variable'],
            'non_routine_cents': data['non_routine'],
            'savings_cents': data['savings'],
            'unknown_cents': data['unknown'],
            'known_consumption_cents': known,
            'coverage_pct': round(coverage, 1),
        })

    def _window(size: int) -> dict:
        sample = monthly[-min(size, len(monthly)):]
        variables = [item['variable_cents'] for item in sample]
        known = [item['known_consumption_cents'] for item in sample]
        unknown = [item['unknown_cents'] for item in sample]
        return {
            'months': len(sample),
            'variable_avg_cents': int(round(mean(variables))) if variables else 0,
            'variable_median_cents': int(round(median(variables))) if variables else 0,
            'known_consumption_avg_cents': int(round(mean(known))) if known else 0,
            'unknown_avg_cents': int(round(mean(unknown))) if unknown else 0,
            'coverage_avg_pct': round(mean([item['coverage_pct'] for item in sample]), 1) if sample else 0.0,
        }

    known_total = sum(item['known_consumption_cents'] for item in monthly)
    unknown_total = sum(item['unknown_cents'] for item in monthly)
    aggregate_coverage = (100.0 * known_total / (known_total + unknown_total)) if (known_total + unknown_total) else 100.0
    trend_confidence = 'high' if aggregate_coverage >= 90 else ('medium' if aggregate_coverage >= 65 else 'low')

    return {
        'months': monthly,
        'windows': {'3m': _window(3), '6m': _window(6), '12m': _window(12)},
        'aggregate': {
            'known_consumption_cents': known_total,
            'unknown_cents': unknown_total,
            'coverage_pct': round(aggregate_coverage, 1),
            'confidence': trend_confidence,
        },
    }


def _max_booking_date(conn, source_type: str) -> str | None:
    row = conn.execute(
        'SELECT MAX(booking_date) AS coverage_end FROM transactions WHERE source_type=?',
        (source_type,),
    ).fetchone()
    return row['coverage_end'] if row else None


def _latest_date(*values: str | None) -> str | None:
    present = [value for value in values if value]
    return max(present) if present else None


def build_financial_intelligence(conn, *, as_of: date | None = None, history_months: int = 12) -> dict:
    as_of = as_of or date.today()
    history_months = min(max(history_months, 3), 24)

    safe = calculate_safe_to_spend(conn, as_of=as_of, stale_reference_date=as_of).as_dict()
    forecast = build_validated_daily_forecast(conn, as_of=as_of)
    trends = _historical_trends(conn, as_of, history_months)

    statement_coverage_end = _max_booking_date(conn, 'bank_statement')
    activity_coverage_end = _max_booking_date(conn, 'bank_activity')
    transaction_coverage_end = _latest_date(statement_coverage_end, activity_coverage_end)

    current_month = as_of.strftime('%Y-%m')
    current_month_observed = bool(
        transaction_coverage_end and transaction_coverage_end[:7] == current_month
    )
    transaction_freshness_status = 'current' if current_month_observed else 'source_not_current'

    balance_rows = conn.execute(
        '''SELECT id,name,current_balance_cents,balance_as_of
           FROM accounts
           WHERE is_active=1 AND include_in_safe_to_spend=1
           ORDER BY id'''
    ).fetchall()
    balance_dates = [row['balance_as_of'] for row in balance_rows if row['balance_as_of']]
    balance_as_of = min(balance_dates) if balance_dates else None
    balance_freshness_status = (
        'current' if balance_as_of and int(safe.get('balance_age_days') or 0) <= 7
        else 'stale_or_unknown'
    )

    six_month = trends['windows']['6m']
    baseline_month_median = six_month['variable_median_cents']
    baseline_daily = 0
    recent = trends['months'][-min(6, len(trends['months'])):]
    daily_rates = []
    for item in recent:
        year, month = map(int, item['month'].split('-'))
        days = calendar.monthrange(year, month)[1]
        daily_rates.append(item['variable_cents'] / days if days else 0)
    if daily_rates:
        baseline_daily = int(round(median(daily_rates)))

    current_position = {
        'status': 'unavailable',
        'confidence': 'unavailable',
        'current_month_observed': current_month_observed,
        'observed_through': transaction_coverage_end if current_month_observed else None,
        'variable_mtd_cents': None,
        'expected_to_date_cents': None,
        'projected_full_month_cents': None,
        'baseline_variable_month_median_cents': baseline_month_median,
        'baseline_variable_daily_median_cents': baseline_daily,
    }

    if current_month_observed:
        recurring_labels = accepted_recurring_labels(conn)
        current_rows = conn.execute(
            '''SELECT booking_date,amount_cents,label,category,transaction_type,is_internal_transfer
               FROM transactions
               WHERE booking_date>=? AND booking_date<=?
                 AND amount_cents<0
                 AND COALESCE(status,'confirmed')='confirmed' ''',
            (as_of.replace(day=1).isoformat(), transaction_coverage_end),
        ).fetchall()
        buckets = defaultdict(int)
        for row in current_rows:
            buckets[classify_outflow(row, recurring_labels)] += abs(int(row['amount_cents']))
        known = buckets['fixed'] + buckets['variable'] + buckets['other_classified']
        reviewable = known + buckets['unknown']
        coverage_pct = (100.0 * known / reviewable) if reviewable else 100.0
        confidence = 'high' if coverage_pct >= 90 else ('medium' if coverage_pct >= 65 else 'low')
        observed_day = date.fromisoformat(transaction_coverage_end).day
        expected_to_date = baseline_daily * observed_day
        remaining_days = calendar.monthrange(as_of.year, as_of.month)[1] - observed_day
        projected = buckets['variable'] + baseline_daily * max(0, remaining_days)
        current_position.update({
            'status': 'observed',
            'confidence': confidence,
            'variable_mtd_cents': buckets['variable'],
            'expected_to_date_cents': expected_to_date,
            'projected_full_month_cents': projected,
            'coverage_pct': round(coverage_pct, 1),
        })

    expected_remaining = forecast.get('expected_remaining_after_variable_spend_cents')
    headline = {
        'safe_to_spend_cents': safe.get('safe_to_spend_cents'),
        'expected_remaining_at_horizon_cents': expected_remaining,
        'next_salary_date': safe.get('next_salary_date') or forecast.get('next_salary_date'),
        'variable_daily_rate_cents': forecast.get('variable_daily_rate_cents'),
        'historical_variable_month_median_cents': baseline_month_median,
        'source_freshness': transaction_freshness_status,
        'trend_confidence': trends['aggregate']['confidence'],
    }

    return {
        'as_of': as_of.isoformat(),
        'headline': headline,
        'safe_to_spend': safe,
        'forecast': forecast,
        'trends': trends,
        'current_position': current_position,
        'data_quality': {
            'statement_coverage_end': statement_coverage_end,
            'activity_coverage_end': activity_coverage_end,
            'transaction_coverage_end': transaction_coverage_end,
            'bank_coverage_end': transaction_coverage_end,
            'current_month_observed': current_month_observed,
            'freshness_status': transaction_freshness_status,
            'transaction_freshness_status': transaction_freshness_status,
            'balance_as_of': balance_as_of,
            'balance_age_days': safe.get('balance_age_days'),
            'balance_freshness_status': balance_freshness_status,
            'historical_coverage_pct': trends['aggregate']['coverage_pct'],
            'trend_confidence': trends['aggregate']['confidence'],
        },
    }
