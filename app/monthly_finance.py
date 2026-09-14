from __future__ import annotations


FIXED_CATEGORIES = {'Logement', 'Télécom', 'Assurances', 'Crédits', 'Impôts', 'Frais bancaires'}
VARIABLE_CATEGORIES = {
    'Alimentation',
    'Restaurants',
    'Shopping',
    'Loisirs',
    'Santé',
    'Transport',
    'Services numériques',
    'Remboursement',
}
SAVINGS_CATEGORIES = {'Épargne', 'Investissement'}
EXCEPTIONAL_CATEGORIES = {'Voyage', 'Dépense exceptionnelle'}


def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone())


def _next_month_key(period: str | None) -> str | None:
    if not period:
        return None
    try:
        year, month = (int(value) for value in period.split('-', 1))
    except (TypeError, ValueError):
        return None
    if not 1 <= month <= 12:
        return None
    if month == 12:
        return f'{year + 1:04d}-01'
    return f'{year:04d}-{month + 1:02d}'


def _normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def _accepted_recurring_labels(conn) -> set[str]:
    if not _table_exists(conn, 'recurring_transactions'):
        return set()
    columns = {row['name'] for row in conn.execute('PRAGMA table_info(recurring_transactions)').fetchall()}
    if 'detection_status' in columns:
        rows = conn.execute(
            "SELECT label FROM recurring_transactions WHERE is_active=1 AND detection_status='accepted' AND amount_cents<0"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT label FROM recurring_transactions WHERE is_active=1 AND amount_cents<0"
        ).fetchall()
    return {_normalize(row['label']) for row in rows if row['label']}


def _matches_recurrence(label: str | None, accepted: set[str]) -> bool:
    normalized = _normalize(label)
    if not normalized:
        return False
    if normalized in accepted:
        return True
    return any(len(candidate) >= 5 and candidate in normalized for candidate in accepted)


def _salary_income_for_budget_month(conn, month: str) -> tuple[int, set[int], str]:
    """Return reconciled salary assigned to its budget month.

    Payroll period N funds budget month N+1. A salary transaction therefore does
    not belong to a month merely because its bank booking date falls inside that
    calendar month.
    """
    if not (_table_exists(conn, 'payroll_transaction_matches') and _table_exists(conn, 'payroll_records')):
        return 0, set(), 'fallback_no_payroll_reconciliation'

    rows = conn.execute('''
        SELECT t.id AS transaction_id,t.amount_cents,p.period AS payroll_period
        FROM payroll_transaction_matches m
        JOIN payroll_records p ON p.id=m.payroll_record_id
        JOIN transactions t ON t.id=m.transaction_id
        WHERE t.amount_cents>0
          AND COALESCE(t.status,'confirmed')='confirmed'
    ''').fetchall()

    all_matched_ids = {int(row['transaction_id']) for row in rows}
    salary_cents = sum(
        int(row['amount_cents'])
        for row in rows
        if _next_month_key(row['payroll_period']) == month
    )
    return salary_cents, all_matched_ids, 'payroll_period_plus_one_month'


def _classify_outflow(row, recurring_labels: set[str]) -> str:
    category = (row['category'] or '').strip()
    tx_type = (row['transaction_type'] or '').lower()

    # A transfer to another owned account may still be semantically savings.
    # Savings intent wins over the transport mechanism so monthly reporting can
    # distinguish wealth funding from operating transfers while preserving the
    # original is_internal_transfer flag.
    if category in SAVINGS_CATEGORIES or tx_type in {'saving', 'investment'}:
        return 'savings'
    if int(row['is_internal_transfer'] or 0) == 1 or category == 'Transfert interne' or tx_type == 'transfer':
        return 'transfer'
    if int(row['exclude_from_analytics'] or 0) == 1 or category == 'Frais professionnel remboursé':
        return 'excluded'
    if int(row['is_exceptional'] or 0) == 1 or category in EXCEPTIONAL_CATEGORIES:
        return 'exceptional'
    if _matches_recurrence(row['label'], recurring_labels) or category in FIXED_CATEGORIES:
        return 'fixed'
    if category in VARIABLE_CATEGORIES:
        return 'variable'
    if not category:
        return 'unknown'
    return 'other'


def month_totals(conn, month: str) -> dict:
    """Return reconciled monthly income and mutually-exclusive outflow buckets.

    `consumption_cents` is deliberately routine consumption only: fixed + variable
    + other classified routine outflows. Exceptional and unknown outflows remain
    explicit separate buckets. `cash_outflow_cents` still represents every
    confirmed negative cash movement, including savings, transfers and exclusions.
    Internal transfers tagged with transaction_type=saving/investment are reported
    as savings without losing their internal-transfer identity in the ledger.
    """
    salary_cents, matched_salary_ids, salary_method = _salary_income_for_budget_month(conn, month)

    income_rows = conn.execute('''
        SELECT id,amount_cents,category,transaction_type,is_internal_transfer,exclude_from_analytics
        FROM transactions
        WHERE substr(booking_date,1,7)=?
          AND amount_cents>0
          AND COALESCE(status,'confirmed')='confirmed'
    ''', (month,)).fetchall()

    other_income_cents = 0
    fallback_salary_cents = 0
    for income in income_rows:
        transaction_id = int(income['id'])
        if transaction_id in matched_salary_ids:
            continue
        if int(income['is_internal_transfer'] or 0) == 1 or int(income['exclude_from_analytics'] or 0) == 1:
            continue
        tx_type = (income['transaction_type'] or '').lower()
        if tx_type in {'refund', 'reimbursement', 'transfer'}:
            continue
        category = (income['category'] or '').strip()
        if salary_method == 'fallback_no_payroll_reconciliation' and category == 'Salaire':
            fallback_salary_cents += int(income['amount_cents'])
        else:
            other_income_cents += int(income['amount_cents'])

    if salary_method == 'fallback_no_payroll_reconciliation':
        salary_cents = fallback_salary_cents

    recurring_labels = _accepted_recurring_labels(conn)
    outflow_rows = conn.execute('''
        SELECT id,amount_cents,label,category,transaction_type,is_internal_transfer,
               COALESCE(exclude_from_analytics,0) AS exclude_from_analytics,
               COALESCE(is_exceptional,0) AS is_exceptional
        FROM transactions
        WHERE substr(booking_date,1,7)=?
          AND amount_cents<0
          AND COALESCE(status,'confirmed')='confirmed'
    ''', (month,)).fetchall()

    buckets = {
        'fixed': 0,
        'variable': 0,
        'savings': 0,
        'exceptional': 0,
        'transfer': 0,
        'unknown': 0,
        'other': 0,
        'excluded': 0,
    }
    counts = {key: 0 for key in buckets}
    for row in outflow_rows:
        kind = _classify_outflow(row, recurring_labels)
        buckets[kind] += abs(int(row['amount_cents']))
        counts[kind] += 1

    routine_consumption_cents = buckets['fixed'] + buckets['variable'] + buckets['other']
    consumption_cents = routine_consumption_cents
    cash_outflow_cents = sum(buckets.values())
    reviewable_cents = routine_consumption_cents + buckets['exceptional'] + buckets['unknown']
    classified_reviewable_cents = routine_consumption_cents + buckets['exceptional']
    semantic_coverage_pct = (
        round(100.0 * classified_reviewable_cents / reviewable_cents, 1)
        if reviewable_cents else 100.0
    )

    total_income = int(salary_cents) + int(other_income_cents)
    return {
        'income_cents': total_income,
        'salary_cents': int(salary_cents),
        'other_income_cents': int(other_income_cents),
        'salary_attribution_method': salary_method,
        'spent_cents': int(consumption_cents),
        'consumption_cents': int(consumption_cents),
        'routine_consumption_cents': int(routine_consumption_cents),
        'fixed_cents': int(buckets['fixed']),
        'variable_cents': int(buckets['variable']),
        'saving_cents': int(buckets['savings']),
        'exceptional_cents': int(buckets['exceptional']),
        'transfers_cents': int(buckets['transfer']),
        'unknown_cents': int(buckets['unknown']),
        'other_classified_cents': int(buckets['other']),
        'excluded_cents': int(buckets['excluded']),
        'cash_outflow_cents': int(cash_outflow_cents),
        'semantic_coverage_pct': semantic_coverage_pct,
        'outflow_counts': counts,
        'net_cents': total_income - int(consumption_cents),
        'cash_net_cents': total_income - int(cash_outflow_cents),
        'outflow_semantics': 'mutually_exclusive_v3_savings_transfer_aware',
    }
