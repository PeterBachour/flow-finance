from __future__ import annotations

import os
from collections import defaultdict
from datetime import date
from statistics import median

from fastapi import APIRouter

from .db import connection
from .imports import ensure_import_schema
from .spending_classification import accepted_recurring_labels, classify_outflow
from .v2_migrations import ensure_v2_schema
from .v22_migrations import ensure_v22_schema
from .v46_routes import financial_decisions
from .version import VERSION

router = APIRouter(prefix='/api/v4.7', tags=['Flow V4.7'])


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + month - 1 + delta
    return index // 12, index % 12 + 1


def _closed_months(as_of: date, count: int) -> list[str]:
    result = []
    for offset in range(-count, 0):
        year, month = _shift_month(as_of.year, as_of.month, offset)
        result.append(f'{year:04d}-{month:02d}')
    return result


def _average(values: list[int]) -> int:
    return round(sum(values) / len(values)) if values else 0


def _pct_delta(current: int, reference: int) -> float | None:
    if reference <= 0:
        return None
    return round((current - reference) / reference * 100, 1)


def build_advanced_analysis(conn, *, as_of: date) -> dict:
    months = _closed_months(as_of, 12)
    start = f'{months[0]}-01'
    end = as_of.replace(day=1).isoformat()
    recurring_labels = accepted_recurring_labels(conn)

    rows = conn.execute(
        '''SELECT id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer
           FROM transactions
           WHERE booking_date>=? AND booking_date<?
             AND amount_cents<0
             AND COALESCE(status,'confirmed')='confirmed'
           ORDER BY booking_date,label,amount_cents''',
        (start, end),
    ).fetchall()

    monthly: defaultdict[str, int] = defaultdict(int)
    category_month: defaultdict[str, defaultdict[str, int]] = defaultdict(lambda: defaultdict(int))
    variable_rows = []
    for row in rows:
        if classify_outflow(row, recurring_labels) != 'variable':
            continue
        month = row['booking_date'][:7]
        category = (row['category'] or 'À qualifier').strip() or 'À qualifier'
        amount = abs(int(row['amount_cents'] or 0))
        monthly[month] += amount
        category_month[category][month] += amount
        variable_rows.append({**dict(row), 'variable_amount_cents': amount})

    monthly_rows = [{'month': month, 'variable_cents': int(monthly.get(month, 0))} for month in months]
    windows = {}
    for size in (3, 6, 12):
        values = [int(monthly.get(month, 0)) for month in months[-size:]]
        windows[f'{size}m'] = {
            'months': size,
            'average_monthly_cents': _average(values),
            'median_monthly_cents': round(median(values)) if values else 0,
            'observed_months': sum(1 for value in values if value > 0),
        }

    latest_month = months[-1]
    latest_total = int(monthly.get(latest_month, 0))
    prior_values = [int(monthly.get(month, 0)) for month in months[-7:-1]]
    prior_nonzero = [value for value in prior_values if value > 0]
    prior_reference = round(median(prior_nonzero)) if prior_nonzero else 0

    trends = []
    anomalies = []
    for category, by_month in category_month.items():
        recent = [int(by_month.get(month, 0)) for month in months[-3:]]
        previous = [int(by_month.get(month, 0)) for month in months[-6:-3]]
        recent_average = _average(recent)
        previous_average = _average(previous)
        delta_pct = _pct_delta(recent_average, previous_average)
        if recent_average > 0 or previous_average > 0:
            trends.append({
                'category': category,
                'recent_3m_average_cents': recent_average,
                'previous_3m_average_cents': previous_average,
                'delta_cents': recent_average - previous_average,
                'delta_pct': delta_pct,
            })

        latest = int(by_month.get(latest_month, 0))
        history = [int(by_month.get(month, 0)) for month in months[-7:-1]]
        observed = [value for value in history if value > 0]
        if latest <= 0 or len(observed) < 3:
            continue
        reference = round(median(observed))
        difference = latest - reference
        anomaly_pct = _pct_delta(latest, reference)
        if reference > 0 and difference >= 3000 and anomaly_pct is not None and anomaly_pct >= 50:
            anomalies.append({
                'kind': 'category_anomaly',
                'severity': 'high' if anomaly_pct >= 100 and difference >= 5000 else 'watch',
                'category': category,
                'month': latest_month,
                'amount_cents': latest,
                'reference_median_cents': reference,
                'delta_cents': difference,
                'delta_pct': anomaly_pct,
                'title': f'{category} inhabituel',
                'detail': f'{anomaly_pct:.1f} % au-dessus de sa médiane historique sur le dernier mois clôturé.',
            })

    trends.sort(key=lambda item: abs(int(item['delta_cents'])), reverse=True)
    anomalies.sort(key=lambda item: (-int(item['delta_cents']), item['category']))

    latest_variable_rows = [row for row in variable_rows if row['booking_date'][:7] == latest_month]
    historical_amounts = [row['variable_amount_cents'] for row in variable_rows if row['booking_date'][:7] != latest_month]
    large_expenses = []
    if len(historical_amounts) >= 10:
        transaction_median = round(median(historical_amounts))
        threshold = max(10000, transaction_median * 4)
        for row in sorted(latest_variable_rows, key=lambda item: -item['variable_amount_cents']):
            if row['variable_amount_cents'] < threshold:
                continue
            large_expenses.append({
                'kind': 'large_variable_expense',
                'severity': 'watch',
                'transaction_id': row['id'],
                'date': row['booking_date'],
                'label': row['label'],
                'category': row['category'],
                'amount_cents': row['variable_amount_cents'],
                'reference_median_cents': transaction_median,
                'title': 'Dépense variable nettement supérieure au niveau habituel',
                'detail': f"{row['label']} · {row['booking_date']}",
            })

    overall_pct = _pct_delta(latest_total, prior_reference)
    signals = []
    if prior_reference > 0 and overall_pct is not None and abs(overall_pct) >= 15:
        direction = 'au-dessus' if latest_total > prior_reference else 'en dessous'
        signals.append({
            'kind': 'overall_variable_trend',
            'severity': 'watch' if latest_total > prior_reference else 'positive',
            'title': f'Dépenses variables {direction} de la référence',
            'detail': f'{latest_month} : {abs(overall_pct):.1f} % {direction} de la médiane des 6 mois précédents disponibles.',
            'amount_cents': latest_total,
            'reference_cents': prior_reference,
        })
    signals.extend(anomalies[:5])
    signals.extend(large_expenses[:5])

    return {
        'as_of': as_of.isoformat(),
        'latest_closed_month': latest_month,
        'latest_closed_variable_cents': latest_total,
        'prior_reference_median_cents': prior_reference,
        'latest_vs_reference_pct': overall_pct,
        'windows': windows,
        'monthly_variable': monthly_rows,
        'category_trends': trends[:12],
        'anomalies': anomalies[:12],
        'signals': signals[:10],
        'signal_count': len(signals),
        'method': (
            'Analyse déterministe des dépenses variables confirmées sur mois clôturés avec le classifieur canonique. '
            'Une anomalie de catégorie nécessite au moins 3 mois observés, +50 % et +30 € au-dessus de la médiane. '
            'Aucune saisonnalité n’est affirmée sans historique multi-annuel.'
        ),
    }


@router.get('/analysis')
def advanced_analysis(as_of: date | None = None):
    with connection() as conn:
        ensure_v2_schema(conn)
        return build_advanced_analysis(conn, as_of=as_of or date.today())


@router.get('/decision-priorities')
def decision_priorities():
    decisions = financial_decisions(include_closed=False)
    rank = {'high': 0, 'medium': 1, 'low': 2}
    items = sorted(
        decisions.get('items', []),
        key=lambda item: (rank.get(item.get('priority'), 9), item.get('type', ''), item.get('key', '')),
    )
    return {
        'open_count': len(items),
        'primary': items[0] if items else None,
        'items': items[:8],
        'quality_review_count': int(decisions.get('quality_review_count') or 0),
        'principle': 'Une priorité correspond à un choix financier réel. Les tâches de qualité de données restent hors de cette file.',
    }


@router.get('/system-diagnostic')
def system_diagnostic():
    commit = (os.getenv('FLOW_GIT_COMMIT') or '').strip()
    commit_known = bool(commit and commit.lower() != 'unknown')
    with connection() as conn:
        ensure_v2_schema(conn)
        ensure_v22_schema(conn)
        ensure_import_schema(conn)
        counts = {}
        for table in ('transactions', 'imports', 'financial_goals'):
            counts[table] = int(conn.execute(f'SELECT COUNT(*) n FROM {table}').fetchone()['n'])
        last_import = conn.execute('SELECT MAX(created_at) value FROM imports').fetchone()['value']
        latest_balance = conn.execute('SELECT MAX(balance_as_of) value FROM accounts WHERE is_active=1').fetchone()['value']
        uncategorized = int(conn.execute(
            "SELECT COUNT(*) n FROM transactions WHERE COALESCE(category,'')='' AND COALESCE(is_internal_transfer,0)=0"
        ).fetchone()['n'])
    return {
        'version': VERSION,
        'commit': commit if commit_known else None,
        'commit_status': 'known' if commit_known else 'not_injected',
        'database': {'connected': True, 'counts': counts, 'uncategorized': uncategorized},
        'last_import_at': last_import,
        'latest_balance_as_of': latest_balance,
        'labels': {
            'commit': commit[:10] if commit_known else 'Non injecté',
            'update_reliability': 'fiable' if commit_known else 'limitée sans commit injecté',
        },
    }
