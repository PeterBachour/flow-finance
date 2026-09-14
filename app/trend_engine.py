import calendar
from datetime import date
from statistics import median

# Normalised from the LCL statements audited for February-June 2026.
# These figures represent estimated personal consumption after removing identified
# savings/internal transfers. They are deliberately kept separate from raw bank debits.
STATEMENT_NORMALIZED = {
    '2026-02': {'consumption_cents': 151800, 'status': 'statement_audit'},
    '2026-03': {'consumption_cents': 293000, 'status': 'statement_audit_outlier'},
    '2026-04': {'consumption_cents': 149300, 'status': 'statement_audit'},
    '2026-05': {'consumption_cents': 162000, 'status': 'statement_audit'},
    '2026-06': {'consumption_cents': 114800, 'status': 'statement_audit'},
}

# Current-cycle facts explicitly confirmed outside a complete bank statement.
# They are used only as a fallback and are returned with estimated confidence.
CURRENT_CYCLE_SNAPSHOTS = {
    '2026-09': {
        'income_cents': 310400,
        'prepared_transfers_cents': 192000,
        'balance_as_of': '2026-09-07',
        'account_source_key': 'account:lcl-current',
        'source': 'confirmed_balance_reconstruction',
    },
}


def _active_for_month(row, month_key: str) -> bool:
    start = row['start_date'] or '0000-01-01'
    end = row['end_date'] or '9999-12-31'
    return row['status'] == 'active' and start <= f'{month_key}-31' and end >= f'{month_key}-01'


def _pct_delta(value: int, reference: int) -> float | None:
    if not reference:
        return None
    return round(((value - reference) / reference) * 100, 1)


def _target_consumption(conn, month_key: str) -> dict:
    rules = [r for r in conn.execute("SELECT * FROM financial_rules WHERE status='active'").fetchall() if _active_for_month(r, month_key)]
    variable = sum(max(0, int(r['value_cents'] or 0)) for r in rules if r['rule_type'] == 'spending_budget')
    monthly_expenses = sum(max(0, int(r['value_cents'] or 0)) for r in rules if r['rule_type'] == 'monthly_expense')
    monthly_savings = sum(max(0, int(r['value_cents'] or 0)) for r in rules if r['rule_type'] == 'monthly_saving')

    recurring = conn.execute("SELECT amount_cents,kind,category,label FROM recurring_transactions WHERE is_active=1 AND amount_cents<0").fetchall()
    recurring_consumption = 0
    for row in recurring:
        if (row['kind'] or '').lower() == 'transfer':
            continue
        if (row['category'] or '').lower() == 'transfert interne':
            continue
        recurring_consumption += abs(int(row['amount_cents']))

    fixed = monthly_expenses + recurring_consumption
    return {
        'variable_budget_cents': variable,
        'fixed_personal_cents': fixed,
        'monthly_consumption_cents': fixed + variable,
        'monthly_savings_target_cents': monthly_savings,
    }


def _historical_baseline(conn) -> dict:
    rows = conn.execute("SELECT month,salary_cents,status FROM monthly_financial_history WHERE status='confirmed' ORDER BY month DESC LIMIT 12").fetchall()
    available = []
    salary_values = []
    for row in rows:
        month = row['month']
        if month in STATEMENT_NORMALIZED:
            available.append({'month': month, **STATEMENT_NORMALIZED[month]})
        if row['salary_cents']:
            salary_values.append(int(row['salary_cents']))

    values = [x['consumption_cents'] for x in available]
    typical_values = [x['consumption_cents'] for x in available if x['status'] != 'statement_audit_outlier'] or values
    ordered = sorted(typical_values)
    typical_low = ordered[0] if ordered else 0
    typical_high = ordered[-1] if ordered else 0

    return {
        'monthly_consumption_median_cents': int(median(typical_values)) if typical_values else 0,
        'typical_low_cents': typical_low,
        'typical_high_cents': typical_high,
        'salary_median_cents': int(median(salary_values)) if salary_values else 0,
        'months': sorted(available, key=lambda x: x['month']),
        'methodology': 'median_statement_normalized_excluding_identified_outlier',
    }


def _ledger_current(conn, month_key: str) -> tuple[int, int, str | None]:
    rows = conn.execute(
        """SELECT booking_date,amount_cents FROM transactions
           WHERE substr(booking_date,1,7)=? AND amount_cents<0
             AND is_internal_transfer=0
             AND COALESCE(category,'')<>'Frais professionnel remboursé'
             AND COALESCE(status,'confirmed')='confirmed'
           ORDER BY booking_date""",
        (month_key,),
    ).fetchall()
    return sum(abs(int(r['amount_cents'])) for r in rows), len(rows), (rows[-1]['booking_date'] if rows else None)


def _reconstructed_current(conn, month_key: str) -> dict | None:
    snapshot = CURRENT_CYCLE_SNAPSHOTS.get(month_key)
    if not snapshot:
        return None
    account = conn.execute(
        "SELECT current_balance_cents,balance_as_of FROM accounts WHERE source_key=? AND is_active=1 LIMIT 1",
        (snapshot['account_source_key'],),
    ).fetchone()
    if not account:
        return None
    as_of = account['balance_as_of'] or snapshot['balance_as_of']
    if as_of < snapshot['balance_as_of']:
        return None
    consumed = max(0, snapshot['income_cents'] - snapshot['prepared_transfers_cents'] - int(account['current_balance_cents']))
    return {
        'spent_cents': consumed,
        'as_of': as_of,
        'source': snapshot['source'],
        'confidence': 'estimated',
        'note': 'Reconstruction depuis revenu du cycle, transferts de préparation et dernier solde confirmé.',
    }


def spending_trend(conn, today: date) -> dict:
    month_key = today.strftime('%Y-%m')
    baseline = _historical_baseline(conn)
    target = _target_consumption(conn, month_key)
    ledger_spend, ledger_count, ledger_last_date = _ledger_current(conn, month_key)

    # A reasonably populated current ledger is preferred. Otherwise use the
    # confirmed-balance reconstruction when one is available for this cycle.
    current = None
    if ledger_count >= 8:
        current = {
            'spent_cents': ledger_spend,
            'as_of': ledger_last_date or today.isoformat(),
            'source': 'transaction_ledger',
            'confidence': 'high',
            'note': 'Calculé depuis les transactions confirmées, hors transferts internes et frais remboursés.',
        }
    else:
        current = _reconstructed_current(conn, month_key)
        if current is None:
            current = {
                'spent_cents': ledger_spend,
                'as_of': ledger_last_date or today.isoformat(),
                'source': 'partial_transaction_ledger',
                'confidence': 'low' if ledger_count < 3 else 'medium',
                'note': 'Historique du mois incomplet : le rythme est indicatif jusqu’au prochain relevé/import.',
            }

    as_of_date = date.fromisoformat(current['as_of'])
    elapsed_days = max(1, as_of_date.day)
    days_in_month = calendar.monthrange(as_of_date.year, as_of_date.month)[1]
    projected = round(current['spent_cents'] / elapsed_days * days_in_month)
    current['elapsed_days'] = elapsed_days
    current['days_in_month'] = days_in_month
    current['projected_month_cents'] = projected

    trend_ref = baseline['monthly_consumption_median_cents']
    target_ref = target['monthly_consumption_cents']
    vs_trend = _pct_delta(projected, trend_ref)
    vs_target = _pct_delta(projected, target_ref)

    if vs_target is None:
        status = 'unknown'
    elif vs_target <= 0:
        status = 'on_target'
    elif vs_target <= 10:
        status = 'slightly_above_target'
    else:
        status = 'above_target'

    return {
        'baseline': baseline,
        'target': target,
        'current': current,
        'comparison': {
            'vs_trend_pct': vs_trend,
            'vs_target_pct': vs_target,
            'status': status,
        },
    }
