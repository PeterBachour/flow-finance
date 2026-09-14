from __future__ import annotations

import calendar
from datetime import date, timedelta

from .safe_to_spend import RECURRING_STALE_DAYS, recurring_is_fresh


def _normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def _next_month_same_day(value: date, day: int) -> date:
    year = value.year + (1 if value.month == 12 else 0)
    month = 1 if value.month == 12 else value.month + 1
    max_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(max(1, day), max_day))


def _first_occurrence(row, as_of: date) -> date:
    usual_day = int(row['usual_day'] or row['day_of_month'] or 1)
    if row['next_expected_date']:
        try:
            candidate = date.fromisoformat(row['next_expected_date'])
        except ValueError:
            candidate = as_of
    else:
        candidate = date(as_of.year, as_of.month, min(usual_day, calendar.monthrange(as_of.year, as_of.month)[1]))
    while candidate <= as_of:
        candidate = _next_month_same_day(candidate, usual_day)
    return candidate


def _planned_overlap(conn, row, due_date: date, tolerance_days: int = 5) -> dict | None:
    label = _normalize(row['label'])
    if not label:
        return None
    start = (due_date - timedelta(days=tolerance_days)).isoformat()
    end = (due_date + timedelta(days=tolerance_days)).isoformat()
    planned = conn.execute(
        '''SELECT id,label,amount_cents,due_date,certainty,status
           FROM planned_transactions
           WHERE status='planned' AND amount_cents<0 AND due_date>=? AND due_date<=?
           ORDER BY due_date,id''',
        (start, end),
    ).fetchall()
    amount = abs(int(row['amount_cents'] or 0))
    tolerance = max(int(row['tolerance_cents'] or 0), max(100, int(amount * 0.10)))
    for item in planned:
        planned_label = _normalize(item['label'])
        label_match = label in planned_label or planned_label in label
        amount_match = abs(abs(int(item['amount_cents'])) - amount) <= tolerance
        if label_match and amount_match:
            return dict(item)
    return None


def _cycle_overlap(conn, row, due_date: date) -> dict | None:
    if not _table_exists(conn, 'cycle_reserves'):
        return None
    cycle_month = due_date.strftime('%Y-%m')
    reserves = conn.execute(
        '''SELECT id,reserve_key,label,amount_cents,kind,status,source_type,source_status,reason
           FROM cycle_reserves
           WHERE cycle_month=? AND kind='planned_commitment'
             AND status='active' AND source_status='confirmed'
           ORDER BY id''',
        (cycle_month,),
    ).fetchall()
    label = _normalize(row['label'])
    amount = abs(int(row['amount_cents'] or 0))
    tolerance = max(int(row['tolerance_cents'] or 0), max(100, int(amount * 0.10)))
    for item in reserves:
        reserve_label = _normalize(item['label'])
        label_match = label and reserve_label and (label in reserve_label or reserve_label in label)
        amount_match = abs(int(item['amount_cents'] or 0) - amount) <= tolerance
        if label_match and amount_match:
            return dict(item)
    return None


def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone())


def _status_for(row, as_of: date) -> tuple[str, str]:
    detection = (row['detection_status'] or 'accepted').lower()
    source_type = (row['source_type'] or '').lower()
    fresh = recurring_is_fresh(row['last_seen_date'], as_of)
    if detection == 'rejected' or int(row['is_active'] or 0) == 0:
        return 'rejected', 'Rejeté ou inactif'
    if detection != 'accepted':
        return 'probable', 'Détecté mais non validé'
    if source_type in {'history', 'auto', 'detected'} and not fresh:
        return 'stale', f'Non observé depuis plus de {RECURRING_STALE_DAYS} jours'
    return 'confirmed', 'Validé et suffisamment récent'


def _cycle_reserve_items(conn, as_of: date) -> list[dict]:
    if not _table_exists(conn, 'cycle_reserves'):
        return []
    rows = conn.execute(
        '''SELECT id,reserve_key,cycle_month,label,amount_cents,kind,status,source_type,source_status,reason
           FROM cycle_reserves
           WHERE cycle_month=? AND kind='planned_commitment'
           ORDER BY id''',
        (as_of.strftime('%Y-%m'),),
    ).fetchall()
    return [{
        'id': int(row['id']),
        'item_type': 'cycle_reserve',
        'label': row['label'],
        'category': None,
        'amount_cents': int(row['amount_cents'] or 0),
        'status': 'confirmed' if row['status'] == 'active' and row['source_status'] == 'confirmed' else 'rejected',
        'status_reason': row['reason'] or 'Réserve de cycle',
        'detection_status': None,
        'is_active': row['status'] == 'active',
        'confidence': 1.0 if row['source_status'] == 'confirmed' else 0.0,
        'last_seen_date': None,
        'next_expected_date': None,
        'within_horizon': True,
        'protected_in_safe': row['status'] == 'active' and row['source_status'] == 'confirmed',
        'planned_overlap': None,
        'cycle_overlap': None,
        'source_type': row['source_type'],
        'reserve_key': row['reserve_key'],
    } for row in rows]


def _planned_items(conn, as_of: date, horizon_end: date) -> list[dict]:
    rows = conn.execute(
        '''SELECT id,label,amount_cents,due_date,certainty,status,source_type
           FROM planned_transactions
           WHERE amount_cents<0 AND due_date>? AND due_date<=?
           ORDER BY due_date,id''',
        (as_of.isoformat(), horizon_end.isoformat()),
    ).fetchall()
    return [{
        'id': int(row['id']),
        'item_type': 'planned_transaction',
        'label': row['label'],
        'category': None,
        'amount_cents': int(row['amount_cents']),
        'status': 'confirmed' if row['status'] == 'planned' else 'rejected',
        'status_reason': 'Échéance planifiée confirmée' if row['status'] == 'planned' else 'Échéance non active',
        'detection_status': None,
        'is_active': row['status'] == 'planned',
        'confidence': 1.0 if row['certainty'] == 'confirmed' else 0.8,
        'last_seen_date': None,
        'next_expected_date': row['due_date'],
        'within_horizon': True,
        'protected_in_safe': row['status'] == 'planned',
        'planned_overlap': None,
        'cycle_overlap': None,
        'source_type': row['source_type'],
    } for row in rows]


def build_commitment_review(conn, *, as_of: date | None = None, horizon_end: date | None = None) -> dict:
    as_of = as_of or date.today()
    horizon_end = horizon_end or (as_of + timedelta(days=45))
    rows = conn.execute(
        '''SELECT id,account_id,label,amount_cents,day_of_month,category,kind,certainty,
                  tolerance_cents,is_active,source_type,source_id,source_date,source_status,
                  confidence,usual_day,next_expected_date,last_seen_date,detection_status
           FROM recurring_transactions
           ORDER BY ABS(amount_cents) DESC,id'''
    ).fetchall()

    recurring_items = []
    counts = {'confirmed': 0, 'probable': 0, 'stale': 0, 'rejected': 0, 'overlap': 0}
    totals = {'confirmed_cents': 0, 'probable_cents': 0, 'stale_cents': 0, 'overlap_cents': 0}

    for row in rows:
        status, reason = _status_for(row, as_of)
        due = _first_occurrence(row, as_of)
        planned_overlap = _planned_overlap(conn, row, due) if status != 'rejected' else None
        cycle_overlap = _cycle_overlap(conn, row, due) if status != 'rejected' and not planned_overlap else None
        overlap = planned_overlap or cycle_overlap
        amount = abs(int(row['amount_cents'] or 0))
        within_horizon = due <= horizon_end
        protected = status == 'confirmed' and within_horizon and not overlap

        counts[status] = counts.get(status, 0) + 1
        if overlap:
            counts['overlap'] += 1
            totals['overlap_cents'] += amount
        if within_horizon and status in {'confirmed', 'probable', 'stale'}:
            totals[f'{status}_cents'] += amount

        recurring_items.append({
            'id': int(row['id']),
            'item_type': 'recurring',
            'label': row['label'],
            'category': row['category'],
            'amount_cents': int(row['amount_cents']),
            'status': status,
            'status_reason': reason,
            'detection_status': row['detection_status'],
            'is_active': bool(row['is_active']),
            'confidence': float(row['confidence'] or 0),
            'last_seen_date': row['last_seen_date'],
            'next_expected_date': due.isoformat(),
            'within_horizon': within_horizon,
            'protected_in_safe': protected,
            'planned_overlap': planned_overlap,
            'cycle_overlap': cycle_overlap,
            'source_type': row['source_type'],
        })

    cycle_items = _cycle_reserve_items(conn, as_of)
    planned_items = _planned_items(conn, as_of, horizon_end)
    all_items = cycle_items + planned_items + recurring_items
    protected_cycle_cents = sum(abs(i['amount_cents']) for i in cycle_items if i['protected_in_safe'])
    protected_planned_cents = sum(abs(i['amount_cents']) for i in planned_items if i['protected_in_safe'])
    protected_recurring_cents = sum(abs(i['amount_cents']) for i in recurring_items if i['protected_in_safe'])
    review_needed = counts['probable'] + counts['stale'] + counts['overlap']

    return {
        'as_of': as_of.isoformat(),
        'horizon_end': horizon_end.isoformat(),
        'summary': {
            **counts,
            **totals,
            'review_needed': review_needed,
            'cycle_reserve_cents': protected_cycle_cents,
            'planned_transaction_cents': protected_planned_cents,
            'protected_recurring_cents': protected_recurring_cents,
            'protected_confirmed_cents': protected_cycle_cents + protected_planned_cents + protected_recurring_cents,
        },
        'items': all_items,
        'principles': [
            'Les réserves de cycle confirmées, les échéances planifiées actives et les récurrents validés composent les engagements protégés.',
            'Les récurrents probables ou anciens restent visibles mais ne réduisent pas automatiquement le Safe to Spend.',
            'Un récurrent couvert par une échéance planifiée ou une réserve de cycle équivalente n’est jamais compté deux fois.',
        ],
    }
