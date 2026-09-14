from __future__ import annotations

from datetime import date


def _month_key(year: int, month: int) -> str:
    return f'{year:04d}-{month:02d}'


def _shift_month(value: str, delta: int) -> str:
    year, month = (int(part) for part in value.split('-'))
    index = year * 12 + month - 1 + delta
    return _month_key(index // 12, index % 12 + 1)


def expected_months(*, as_of: date | None = None, months: int = 24) -> list[str]:
    if months < 1 or months > 120:
        raise ValueError('months must be between 1 and 120')
    current = (as_of or date.today()).strftime('%Y-%m')
    return [_shift_month(current, offset) for offset in range(-(months - 1), 1)]


def build_history_coverage(conn, *, as_of: date | None = None, months: int = 24) -> dict:
    periods = expected_months(as_of=as_of, months=months)
    period_set = set(periods)

    statements = conn.execute(
        '''SELECT id,filename,status,quality_status,period_start,period_end,review_rows
           FROM imports
           WHERE status IN ('completed','duplicate')
             AND COALESCE(period_end,period_start) IS NOT NULL
           ORDER BY COALESCE(period_end,period_start),id'''
    ).fetchall()
    payrolls = conn.execute(
        '''SELECT id,period,source_status,source_filename,net_paid_cents
           FROM payroll_records
           WHERE period IS NOT NULL
           ORDER BY period,id'''
    ).fetchall()

    statement_by_month: dict[str, list[dict]] = {}
    for row in statements:
        item = dict(row)
        period = (item.get('period_end') or item.get('period_start') or '')[:7]
        if period not in period_set:
            continue
        statement_by_month.setdefault(period, []).append(item)

    payroll_by_month: dict[str, list[dict]] = {}
    for row in payrolls:
        item = dict(row)
        period = str(item.get('period') or '')[:7]
        if period not in period_set:
            continue
        payroll_by_month.setdefault(period, []).append(item)

    rows = []
    missing_statement = []
    missing_payroll = []
    duplicate_statement = []
    duplicate_payroll = []
    review_months = []

    for period in periods:
        month_statements = statement_by_month.get(period, [])
        month_payrolls = payroll_by_month.get(period, [])
        verified_statements = [
            item for item in month_statements
            if item.get('status') == 'completed'
            and item.get('quality_status') == 'verified'
            and int(item.get('review_rows') or 0) == 0
        ]
        statement_reviews = [
            item for item in month_statements
            if item.get('status') == 'completed'
            and (item.get('quality_status') in {'review', 'warning'} or int(item.get('review_rows') or 0) > 0)
        ]
        confirmed_payrolls = [item for item in month_payrolls if item.get('source_status') == 'confirmed']

        if not month_statements:
            missing_statement.append(period)
        if not month_payrolls:
            missing_payroll.append(period)
        if len([item for item in month_statements if item.get('status') == 'completed']) > 1:
            duplicate_statement.append(period)
        if len(confirmed_payrolls) > 1:
            duplicate_payroll.append(period)
        if statement_reviews:
            review_months.append(period)

        rows.append({
            'period': period,
            'statement': {
                'present': bool(month_statements),
                'verified': bool(verified_statements),
                'count': len(month_statements),
                'review_count': len(statement_reviews),
            },
            'payroll': {
                'present': bool(month_payrolls),
                'confirmed': bool(confirmed_payrolls),
                'count': len(month_payrolls),
                'net_paid_cents': sum(int(item.get('net_paid_cents') or 0) for item in confirmed_payrolls),
            },
        })

    statement_covered = months - len(missing_statement)
    payroll_covered = months - len(missing_payroll)
    complete = [row['period'] for row in rows if row['statement']['present'] and row['payroll']['present']]

    actions = []
    if missing_statement:
        actions.append({
            'key': 'missing_statements',
            'priority': 'high',
            'count': len(missing_statement),
            'periods': missing_statement,
            'title': 'Importer les relevés manquants',
        })
    if review_months:
        actions.append({
            'key': 'statement_reviews',
            'priority': 'high',
            'count': len(review_months),
            'periods': review_months,
            'title': 'Traiter les relevés encore à revoir',
        })
    if missing_payroll:
        actions.append({
            'key': 'missing_payrolls',
            'priority': 'medium',
            'count': len(missing_payroll),
            'periods': missing_payroll,
            'title': 'Importer les fiches de paie manquantes',
        })
    if duplicate_statement or duplicate_payroll:
        actions.append({
            'key': 'duplicate_periods',
            'priority': 'medium',
            'count': len(set(duplicate_statement + duplicate_payroll)),
            'periods': sorted(set(duplicate_statement + duplicate_payroll)),
            'title': 'Vérifier les périodes en doublon',
        })

    return {
        'as_of': (as_of or date.today()).isoformat(),
        'window_months': months,
        'period_start': periods[0],
        'period_end': periods[-1],
        'summary': {
            'statement_coverage_pct': round(statement_covered / months * 100, 1),
            'payroll_coverage_pct': round(payroll_covered / months * 100, 1),
            'complete_months': len(complete),
            'missing_statement_months': len(missing_statement),
            'missing_payroll_months': len(missing_payroll),
            'review_months': len(review_months),
            'duplicate_months': len(set(duplicate_statement + duplicate_payroll)),
        },
        'gaps': {
            'statements': missing_statement,
            'payrolls': missing_payroll,
        },
        'duplicates': {
            'statements': duplicate_statement,
            'payrolls': duplicate_payroll,
        },
        'review_periods': review_months,
        'complete_periods': complete,
        'months': rows,
        'actions': actions,
        'read_only': True,
    }
