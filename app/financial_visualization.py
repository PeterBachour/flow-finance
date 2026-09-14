from __future__ import annotations

import calendar
from collections import defaultdict
from datetime import date

from .spending_classification import accepted_recurring_labels, classify_outflow


def _shift_month(year: int, month: int, delta: int) -> tuple[int, int]:
    index = year * 12 + (month - 1) + delta
    return index // 12, index % 12 + 1


def build_variable_category_view(conn, *, as_of: date, months: int = 6) -> dict:
    """Aggregate validated variable consumption by category over closed months.

    This is a presentation view only. It reuses the canonical spending classifier
    and never changes transaction categories or source records.
    """
    recurring_labels = accepted_recurring_labels(conn)
    start_year, start_month = _shift_month(as_of.year, as_of.month, -max(1, months))
    start = date(start_year, start_month, 1)
    current_month_start = as_of.replace(day=1)

    rows = conn.execute(
        '''SELECT booking_date,amount_cents,label,category,transaction_type,is_internal_transfer
           FROM transactions
           WHERE booking_date>=? AND booking_date<?
             AND amount_cents<0
             AND COALESCE(status,'confirmed')='confirmed'
           ORDER BY booking_date,label,amount_cents''',
        (start.isoformat(), current_month_start.isoformat()),
    ).fetchall()

    totals: defaultdict[str, int] = defaultdict(int)
    month_totals: defaultdict[str, int] = defaultdict(int)
    for row in rows:
        if classify_outflow(row, recurring_labels) != 'variable':
            continue
        category = (row['category'] or 'À qualifier').strip() or 'À qualifier'
        amount = abs(int(row['amount_cents'] or 0))
        totals[category] += amount
        month_totals[row['booking_date'][:7]] += amount

    total = sum(totals.values())
    categories = [
        {
            'category': category,
            'amount_cents': amount,
            'share_pct': round(100.0 * amount / total, 1) if total else 0.0,
        }
        for category, amount in sorted(totals.items(), key=lambda item: (-item[1], item[0]))
    ]

    months_view = []
    for offset in range(-max(1, months), 0):
        year, month = _shift_month(as_of.year, as_of.month, offset)
        key = f'{year:04d}-{month:02d}'
        months_view.append({
            'month': key,
            'variable_cents': int(month_totals.get(key, 0)),
            'days': calendar.monthrange(year, month)[1],
        })

    return {
        'period_start': start.isoformat(),
        'period_end': current_month_start.isoformat(),
        'months': max(1, months),
        'total_variable_cents': total,
        'categories': categories,
        'monthly_variable': months_view,
        'principle': 'Dépenses variables des mois clôturés uniquement, classées avec le moteur canonique.',
    }
