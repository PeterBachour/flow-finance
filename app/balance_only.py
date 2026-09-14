from __future__ import annotations

import calendar
from datetime import date


def _statement_reference(conn, account_id: int, coverage_end: str):
    """Return the latest confirmed statement balance for an account.

    Mid-cycle estimation is anchored to a documentary bank balance, never to
    another manual snapshot. This prevents Flow from inventing transaction
    detail from two user-entered balances.
    """
    return conn.execute(
        '''SELECT balance_cents,balance_date,source_type
           FROM account_balance_history
           WHERE account_id=?
             AND balance_date<=?
             AND COALESCE(status,'confirmed')='confirmed'
             AND COALESCE(source_status,'confirmed')='confirmed'
             AND source_type='bank_statement'
           ORDER BY balance_date DESC,id DESC
           LIMIT 1''',
        (account_id, coverage_end),
    ).fetchone()


def enrich_balance_only_position(conn, payload: dict) -> dict:
    """Add the normal in-month estimated operating mode.

    Flow's source model is monthly: detailed bank transactions are consolidated
    when the statement becomes available at month end. During the open month,
    decision support therefore uses the current operational balance, known
    commitments and the validated historical variable-spend pace.

    This is a normal estimated mode, not a data-quality incident. The balance
    delta is exposed only as a net cash-flow estimate; Flow never fabricates
    transaction categories from it.
    """
    quality = payload.get('data_quality') or {}
    position = payload.get('current_position') or {}

    if quality.get('current_month_observed'):
        quality.update({
            'decision_mode': 'month_consolidated',
            'cycle_status': 'consolidated',
            'freshness_status': 'current',
            'transaction_freshness_status': 'current',
            'transaction_detail_pending': False,
        })
        headline = payload.get('headline') or {}
        headline.update({'decision_mode': 'month_consolidated', 'cycle_status': 'consolidated', 'source_freshness': 'current'})
        payload['headline'] = headline
        return payload

    if quality.get('balance_freshness_status') != 'current':
        quality.update({'decision_mode': 'insufficient_freshness', 'cycle_status': 'estimated'})
        return payload

    coverage_end = quality.get('transaction_coverage_end') or quality.get('bank_coverage_end')
    balance_as_of = quality.get('balance_as_of')
    if not coverage_end or not balance_as_of or balance_as_of <= coverage_end:
        quality.update({'decision_mode': 'insufficient_reference', 'cycle_status': 'estimated'})
        return payload

    accounts = conn.execute(
        '''SELECT id,name,current_balance_cents,balance_as_of
           FROM accounts
           WHERE is_active=1 AND include_in_safe_to_spend=1
           ORDER BY id'''
    ).fetchall()
    if not accounts:
        quality.update({'decision_mode': 'insufficient_reference', 'cycle_status': 'estimated'})
        return payload

    reference_rows = []
    for account in accounts:
        reference = _statement_reference(conn, int(account['id']), coverage_end)
        if not reference:
            quality.update({
                'decision_mode': 'insufficient_statement_balance_reference',
                'cycle_status': 'estimated',
            })
            return payload
        reference_rows.append((account, reference))

    reference_balance = sum(int(reference['balance_cents'] or 0) for _, reference in reference_rows)
    current_balance = sum(int(account['current_balance_cents'] or 0) for account, _ in reference_rows)
    net_change = current_balance - reference_balance
    estimated_net_outflow = max(0, -net_change)
    estimated_net_inflow = max(0, net_change)

    balance_date = date.fromisoformat(balance_as_of)
    coverage_date = date.fromisoformat(coverage_end)
    current_month_start = balance_date.replace(day=1)
    observed_start = max(current_month_start, coverage_date)
    elapsed_days = max(0, (balance_date - observed_start).days)
    if coverage_date < current_month_start:
        elapsed_days = balance_date.day

    baseline_daily = int(position.get('baseline_variable_daily_median_cents') or 0)
    expected_to_date = baseline_daily * elapsed_days
    month_days = calendar.monthrange(balance_date.year, balance_date.month)[1]
    remaining_month_days = max(0, month_days - balance_date.day)
    projected_net_outflow = estimated_net_outflow + baseline_daily * remaining_month_days

    forecast = payload.get('forecast') or {}
    horizon_end_raw = forecast.get('horizon_end')
    if horizon_end_raw:
        horizon_end = date.fromisoformat(horizon_end_raw)
        days_to_horizon = max(1, (horizon_end - balance_date).days)
    else:
        days_to_horizon = max(1, remaining_month_days)
    safe_cents = int((payload.get('safe_to_spend') or {}).get('safe_to_spend_cents') or 0)
    envelope_daily = max(0, safe_cents // days_to_horizon)
    if baseline_daily > 0:
        recommended_daily = min(baseline_daily, envelope_daily)
    else:
        recommended_daily = envelope_daily

    statement_dates = sorted({reference['balance_date'] for _, reference in reference_rows})
    exact_reference = len(statement_dates) == 1 and statement_dates[0] == coverage_end
    confidence = 'high' if exact_reference and baseline_daily > 0 else 'medium'

    position.update({
        'status': 'month_estimated',
        'mode': 'estimated_current_cycle',
        'cycle_status': 'estimated',
        'confidence': confidence,
        'current_month_observed': False,
        'observed_through': balance_as_of,
        'estimated_net_outflow_mtd_cents': int(estimated_net_outflow),
        'estimated_net_inflow_mtd_cents': int(estimated_net_inflow),
        'net_balance_change_cents': int(net_change),
        'reference_balance_cents': int(reference_balance),
        'current_balance_cents': int(current_balance),
        'reference_balance_date': min(statement_dates) if statement_dates else coverage_end,
        'expected_to_date_cents': int(expected_to_date),
        'projected_full_month_cents': int(projected_net_outflow),
        'variable_mtd_cents': None,
        'elapsed_balance_only_days': int(elapsed_days),
        'remaining_days': int(remaining_month_days),
        'days_to_horizon': int(days_to_horizon),
        'envelope_daily_cents': int(envelope_daily),
        'historical_daily_cents': int(baseline_daily),
        'recommended_daily_spend_cents': int(recommended_daily),
        'estimation_basis': 'current_balance_known_commitments_and_historical_variable_pace',
    })

    quality.update({
        'decision_mode': 'month_estimated',
        'cycle_status': 'estimated',
        'balance_only_available': True,
        'balance_only_reference_date': position['reference_balance_date'],
        'balance_only_confidence': confidence,
        'transaction_detail_pending': True,
        'transaction_detail_expected_at_month_close': True,
        'freshness_status': 'monthly_statement_pending',
        'transaction_freshness_status': 'monthly_statement_pending',
    })
    payload['current_position'] = position
    payload['data_quality'] = quality

    headline = payload.get('headline') or {}
    headline.update({
        'source_freshness': 'current_balance_monthly_statement_pending',
        'decision_mode': 'month_estimated',
        'cycle_status': 'estimated',
        'recommended_daily_spend_cents': int(recommended_daily),
    })
    payload['headline'] = headline
    return payload
