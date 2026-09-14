import re
from collections import defaultdict
from datetime import date
from statistics import median

from .imports import normalize_label

VARIABLE_TOKEN = re.compile(r'\b(?:\d{2}[/.]\d{2}(?:[/.]\d{2,4})?|\d{4,}|[A-Z0-9]{10,})\b')
PREFIXES = ('CB ', 'PRLV SEPA ', 'PRLV ', 'VIREMENT ', 'VIR SEPA ', 'VIR INST ', 'VIR.PERMANENT ', 'VIR ')


def recurring_key(label: str) -> str:
    value = normalize_label(label)
    for prefix in PREFIXES:
        if value.startswith(prefix):
            value = value[len(prefix):]
            break
    value = VARIABLE_TOKEN.sub('', value)
    value = re.sub(r'\s+', ' ', value).strip(' -./')
    return value


def _months_between(first: str, last: str) -> int:
    a = date.fromisoformat(first)
    b = date.fromisoformat(last)
    return (b.year - a.year) * 12 + b.month - a.month


def detect_recurring_suggestions(conn, min_months: int = 3) -> list[dict]:
    rows = conn.execute(
        """
        SELECT t.account_id,t.booking_date,t.amount_cents,t.label,t.category,t.transaction_type,t.is_internal_transfer,
               a.name account_name
        FROM transactions t JOIN accounts a ON a.id=t.account_id
        WHERE t.amount_cents<>0
        ORDER BY t.booking_date,t.id
        """
    ).fetchall()
    groups = defaultdict(list)
    for row in rows:
        key = recurring_key(row['label'])
        if len(key) < 4:
            continue
        groups[(row['account_id'], key, 1 if row['amount_cents'] > 0 else -1)].append(row)

    suggestions = []
    for (account_id, key, direction), items in groups.items():
        by_month = {}
        for row in items:
            by_month[row['booking_date'][:7]] = row
        if len(by_month) < min_months:
            continue
        samples = list(by_month.values())
        dates = sorted(r['booking_date'] for r in samples)
        span = _months_between(dates[0], dates[-1])
        if span < min_months - 1:
            continue
        amounts = [abs(int(r['amount_cents'])) for r in samples]
        days = [date.fromisoformat(r['booking_date']).day for r in samples]
        amount_med = int(median(amounts))
        day_med = int(round(median(days)))
        tolerance = max(abs(v - amount_med) for v in amounts)
        day_spread = max(abs(v - day_med) for v in days)
        amount_ratio = tolerance / amount_med if amount_med else 1
        if day_spread > 7:
            continue
        if amount_ratio > 0.45 and len(samples) < 5:
            continue
        existing = conn.execute(
            "SELECT 1 FROM recurring_transactions WHERE account_id=? AND is_active=1 AND UPPER(label) LIKE ? LIMIT 1",
            (account_id, f'%{key[:40]}%'),
        ).fetchone()
        if existing:
            continue
        category_counts = defaultdict(int)
        type_counts = defaultdict(int)
        for row in samples:
            if row['category']:
                category_counts[row['category']] += 1
            if row['transaction_type']:
                type_counts[row['transaction_type']] += 1
        category = max(category_counts, key=category_counts.get) if category_counts else None
        tx_type = max(type_counts, key=type_counts.get) if type_counts else ('income' if direction > 0 else 'expense')
        confidence = min(0.99, 0.55 + min(len(samples), 6) * 0.06 + max(0, 0.12 - amount_ratio * 0.2) + max(0, 0.08 - day_spread * 0.01))
        suggestions.append({
            'key': key,
            'account_id': account_id,
            'account_name': samples[-1]['account_name'],
            'label': key.title(),
            'amount_cents': amount_med * direction,
            'day_of_month': day_med,
            'tolerance_cents': tolerance,
            'category': category,
            'transaction_type': tx_type,
            'occurrences': len(samples),
            'first_seen': dates[0],
            'last_seen': dates[-1],
            'confidence': round(confidence, 2),
        })
    suggestions.sort(key=lambda r: (-r['confidence'], -r['occurrences'], r['label']))
    return suggestions
