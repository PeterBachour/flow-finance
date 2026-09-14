from __future__ import annotations

from collections import defaultdict
from datetime import date

from .spending_classification import accepted_recurring_labels, classify_outflow
from .safe_to_spend import calculate_safe_to_spend


HARD_STATEMENT_ISSUES = {
    'missing_statement_balance',
    'statement_arithmetic_mismatch',
    'ledger_mismatch',
    'missing_balance_snapshot',
}
REVIEW_STATEMENT_ISSUES = {
    'import_quality_not_verified',
    'rows_need_review',
}


def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone())


def _statement_audit(conn) -> dict:
    if not (_table_exists(conn, 'imports') and _table_exists(conn, 'transaction_import_meta')):
        return {
            'status': 'unavailable',
            'statements': [],
            'summary': {
                'statement_count': 0,
                'reconciled_count': 0,
                'review_count': 0,
                'warning_count': 0,
                'missing_balance_snapshot_count': 0,
            },
        }

    rows = conn.execute('''
        SELECT i.id,i.account_id,i.filename,i.bank,i.status,i.period_start,i.period_end,
               i.opening_balance_cents,i.closing_balance_cents,
               COALESCE(i.debit_total_cents,0) AS debit_total_cents,
               COALESCE(i.credit_total_cents,0) AS credit_total_cents,
               COALESCE(i.total_rows,0) AS total_rows,
               COALESCE(i.imported_rows,0) AS imported_rows,
               COALESCE(i.duplicate_rows,0) AS duplicate_rows,
               COALESCE(i.review_rows,0) AS review_rows,
               COALESCE(i.quality_status,'unverified') AS quality_status,
               a.name AS account_name
        FROM imports i
        JOIN accounts a ON a.id=i.account_id
        WHERE i.status IN ('completed','duplicate')
          AND i.period_end IS NOT NULL
        ORDER BY i.period_end,i.id
    ''').fetchall()

    statements = []
    for row in rows:
        opening = row['opening_balance_cents']
        closing = row['closing_balance_cents']
        debit = int(row['debit_total_cents'] or 0)
        credit = int(row['credit_total_cents'] or 0)
        statement_net = credit - debit
        metadata_difference = None
        if opening is not None and closing is not None:
            metadata_difference = int(closing) - (int(opening) + statement_net)

        ledger = conn.execute('''
            SELECT COUNT(*) AS row_count,
                   COALESCE(SUM(t.amount_cents),0) AS net_cents,
                   COALESCE(SUM(CASE WHEN t.amount_cents<0 THEN -t.amount_cents ELSE 0 END),0) AS debit_cents,
                   COALESCE(SUM(CASE WHEN t.amount_cents>0 THEN t.amount_cents ELSE 0 END),0) AS credit_cents
            FROM transaction_import_meta m
            JOIN transactions t ON t.id=m.transaction_id
            WHERE m.import_id=?
        ''', (row['id'],)).fetchone()

        snapshot = None
        if closing is not None:
            snapshot = conn.execute('''
                SELECT id,balance_cents,balance_date,source_type,confidence
                FROM account_balance_history
                WHERE account_id=? AND balance_date=? AND source_type='bank_statement'
                ORDER BY id DESC LIMIT 1
            ''', (row['account_id'], row['period_end'])).fetchone()

        duplicate_rows = int(row['duplicate_rows'] or 0)
        ledger_difference = None
        if duplicate_rows == 0 and int(ledger['row_count'] or 0) > 0:
            ledger_difference = int(ledger['net_cents'] or 0) - statement_net

        issues = []
        if opening is None or closing is None:
            issues.append('missing_statement_balance')
        if metadata_difference not in (None, 0):
            issues.append('statement_arithmetic_mismatch')
        if ledger_difference not in (None, 0):
            issues.append('ledger_mismatch')
        if closing is not None and not snapshot:
            issues.append('missing_balance_snapshot')
        if row['quality_status'] not in ('ok', 'verified'):
            issues.append('import_quality_not_verified')
        if int(row['review_rows'] or 0) > 0:
            issues.append('rows_need_review')

        hard_issues = [issue for issue in issues if issue in HARD_STATEMENT_ISSUES]
        review_issues = [issue for issue in issues if issue in REVIEW_STATEMENT_ISSUES]
        documentary_reconciled = (
            metadata_difference == 0
            and closing is not None
            and bool(snapshot)
            and not hard_issues
        )

        if documentary_reconciled:
            integrity_status = 'reconciled_with_review' if review_issues else 'reconciled'
        else:
            integrity_status = 'warning'

        statements.append({
            'import_id': int(row['id']),
            'account_id': int(row['account_id']),
            'account_name': row['account_name'],
            'filename': row['filename'],
            'bank': row['bank'],
            'period_start': row['period_start'],
            'period_end': row['period_end'],
            'opening_balance_cents': opening,
            'closing_balance_cents': closing,
            'statement_debit_cents': debit,
            'statement_credit_cents': credit,
            'statement_net_cents': statement_net,
            'statement_arithmetic_difference_cents': metadata_difference,
            'ledger_imported_rows': int(ledger['row_count'] or 0),
            'ledger_imported_net_cents': int(ledger['net_cents'] or 0),
            'ledger_difference_cents': ledger_difference,
            'duplicate_rows': duplicate_rows,
            'review_rows': int(row['review_rows'] or 0),
            'quality_status': row['quality_status'],
            'balance_snapshot_present': bool(snapshot),
            'documentary_reconciled': documentary_reconciled,
            'integrity_status': integrity_status,
            'hard_issues': hard_issues,
            'review_issues': review_issues,
            'issues': issues,
        })

    missing_snapshots = sum(1 for item in statements if 'missing_balance_snapshot' in item['issues'])
    reconciled = sum(1 for item in statements if item['documentary_reconciled'])
    reviews = sum(1 for item in statements if item['integrity_status'] == 'reconciled_with_review')
    warnings = sum(1 for item in statements if item['integrity_status'] == 'warning')
    arithmetic_errors = sum(1 for item in statements if 'statement_arithmetic_mismatch' in item['issues'])

    return {
        'status': 'ok' if warnings == 0 and reviews == 0 else 'review',
        'summary': {
            'statement_count': len(statements),
            'reconciled_count': reconciled,
            'review_count': reviews,
            'warning_count': warnings,
            'arithmetic_error_count': arithmetic_errors,
            'missing_balance_snapshot_count': missing_snapshots,
        },
        'statements': statements,
    }


def _monthly_audit(conn, months: int = 24) -> dict:
    recurring_labels = accepted_recurring_labels(conn)
    rows = conn.execute('''
        SELECT booking_date,amount_cents,label,category,transaction_type,is_internal_transfer,
               COALESCE(status,'confirmed') AS status
        FROM transactions
        WHERE COALESCE(status,'confirmed')='confirmed'
        ORDER BY booking_date,id
    ''').fetchall()

    buckets: dict[str, defaultdict[str, int]] = {}
    counts: dict[str, defaultdict[str, int]] = {}
    for row in rows:
        month = row['booking_date'][:7]
        if month not in buckets:
            buckets[month] = defaultdict(int)
            counts[month] = defaultdict(int)
        amount = int(row['amount_cents'] or 0)
        if amount > 0:
            tx_type = (row['transaction_type'] or '').lower()
            if int(row['is_internal_transfer'] or 0) == 1 or tx_type == 'transfer':
                buckets[month]['internal_in'] += amount
                counts[month]['internal'] += 1
            elif tx_type in {'refund', 'reimbursement'} or (row['category'] or '') in {'Remboursement', 'Frais professionnel remboursé'}:
                buckets[month]['refunds'] += amount
                counts[month]['refunds'] += 1
            else:
                buckets[month]['income'] += amount
                counts[month]['income'] += 1
            continue

        if amount == 0:
            continue
        kind = classify_outflow(row, recurring_labels)
        value = abs(amount)
        buckets[month][kind] += value
        counts[month][kind] += 1

    result = []
    for month in sorted(buckets)[-max(1, months):]:
        b = buckets[month]
        c = counts[month]
        consumption = b['fixed'] + b['variable'] + b['other_classified'] + b['non_routine']
        unknown = b['unknown']
        reviewable = consumption + unknown
        coverage_pct = 100.0 if reviewable == 0 else 100.0 * consumption / reviewable
        net_cash = (
            b['income'] + b['refunds'] + b['internal_in']
            - b['fixed'] - b['variable'] - b['other_classified'] - b['non_routine']
            - b['savings'] - b['unknown'] - b['internal'] - b['excluded']
        )
        result.append({
            'month': month,
            'income_cents': b['income'],
            'refunds_cents': b['refunds'],
            'fixed_cents': b['fixed'],
            'variable_cents': b['variable'],
            'non_routine_cents': b['non_routine'],
            'savings_cents': b['savings'],
            'unknown_cents': b['unknown'],
            'internal_transfer_out_cents': b['internal'],
            'internal_transfer_in_cents': b['internal_in'],
            'consumption_cents': consumption,
            'net_cash_change_cents': net_cash,
            'classification_coverage_pct': round(coverage_pct, 1),
            'transaction_count': sum(c.values()),
        })

    return {'months': result}


def _safe_breakdown(conn, as_of: date) -> dict:
    safe = calculate_safe_to_spend(conn, as_of=as_of, stale_reference_date=as_of).as_dict()
    components = [
        {'key': 'balance', 'label': 'Solde disponible', 'amount_cents': int(safe['balance_cents'] or 0), 'operator': '+'},
        {'key': 'planned', 'label': 'Échéances planifiées', 'amount_cents': int(safe['planned_commitments_cents'] or 0), 'operator': '-'},
        {'key': 'recurring', 'label': 'Charges récurrentes', 'amount_cents': int(safe['recurring_commitments_cents'] or 0), 'operator': '-'},
        {'key': 'goals', 'label': 'Objectifs explicitement réservés', 'amount_cents': int(safe['goal_contributions_cents'] or 0), 'operator': '-'},
        {'key': 'safety', 'label': 'Marge de sécurité', 'amount_cents': int(safe['safety_reserve_cents'] or 0), 'operator': '-'},
    ]
    reconstructed = components[0]['amount_cents'] - sum(item['amount_cents'] for item in components[1:])
    reconstructed = max(0, reconstructed)
    return {
        'status': safe['safe_to_spend_status'],
        'as_of': safe['as_of'],
        'horizon_end': safe['horizon_end'],
        'horizon_mode': safe['horizon_mode'],
        'next_salary_date': safe['next_salary_date'],
        'components': components,
        'calculated_safe_to_spend_cents': int(safe['calculated_safe_to_spend_cents'] or 0),
        'safe_to_spend_cents': safe['safe_to_spend_cents'],
        'reconstructed_safe_to_spend_cents': reconstructed,
        'arithmetic_consistent': reconstructed == int(safe['calculated_safe_to_spend_cents'] or 0),
        'balance_age_days': int(safe['balance_age_days'] or 0),
        'balance_is_stale': bool(safe['balance_is_stale']),
        'counts': {
            'accounts': int(safe['included_account_count'] or 0),
            'planned_occurrences': int(safe['planned_occurrence_count'] or 0),
            'recurring_occurrences': int(safe['recurring_occurrence_count'] or 0),
            'cycle_reserves': int(safe['cycle_reserve_count'] or 0),
        },
    }


def build_financial_integrity(conn, *, as_of: date | None = None, months: int = 24) -> dict:
    as_of = as_of or date.today()
    statements = _statement_audit(conn)
    monthly = _monthly_audit(conn, months=months)
    safe = _safe_breakdown(conn, as_of)

    current_month = as_of.strftime('%Y-%m')
    current = next((item for item in reversed(monthly['months']) if item['month'] == current_month), None)
    hard_issue_count = int(statements['summary'].get('warning_count') or 0)
    review_issue_count = int(statements['summary'].get('review_count') or 0)
    if not safe['arithmetic_consistent']:
        hard_issue_count += 1
    if safe['balance_is_stale']:
        hard_issue_count += 1
    issue_count = hard_issue_count + review_issue_count

    return {
        'as_of': as_of.isoformat(),
        'status': 'ok' if issue_count == 0 else 'review',
        'issue_count': issue_count,
        'hard_issue_count': hard_issue_count,
        'review_issue_count': review_issue_count,
        'safe_to_spend_breakdown': safe,
        'statement_audit': statements,
        'monthly_audit': monthly,
        'current_month': current,
        'principles': [
            'Solde bancaire et transactions sont deux sources distinctes.',
            'Les transferts internes ne sont ni un revenu ni une dépense de consommation.',
            'Les remboursements sont séparés des revenus structurels.',
            'Les objectifs déjà financés ne sont jamais déduits une seconde fois.',
            'Tout Safe to Spend doit pouvoir être reconstruit par addition et soustraction de composants explicites.',
        ],
    }
