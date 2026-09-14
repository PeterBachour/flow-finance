from __future__ import annotations

import re
from collections import defaultdict
from statistics import median

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .db import connection
from .imports import normalize_label
from .recurring_detection import detect_recurring_suggestions, recurring_key
from .v2_migrations import ensure_v2_schema
from .v37_migrations import ensure_v37_schema

router = APIRouter(prefix='/api/v3.7', tags=['Flow V3.7'])


class MerchantAliasIn(BaseModel):
    normalized_key: str = Field(min_length=2, max_length=120)
    canonical_name: str = Field(min_length=2, max_length=120)


def _merchant_key(label: str) -> str:
    value = recurring_key(label or '') or normalize_label(label or '')
    value = re.sub(r'\b(?:CARTE|CB|PAIEMENT|PRLV|SEPA|VIREMENT|VIR)\b', ' ', value, flags=re.I)
    value = re.sub(r'\s+', ' ', value).strip(' -./')
    return value[:120]


def _quality_score(total: int, uncategorized: int, excluded: int, stale_source: int, anomaly_count: int) -> int:
    if total <= 0:
        return 0
    penalty = (
        uncategorized / total * 35
        + excluded / total * 10
        + stale_source / total * 10
        + min(anomaly_count / max(total, 1), 0.2) * 100 * 0.45
    )
    return max(0, min(100, round(100 - penalty)))


@router.get('/data-intelligence')
def data_intelligence(limit: int = 250):
    limit = min(max(limit, 50), 1000)
    with connection() as conn:
        ensure_v2_schema(conn)
        ensure_v37_schema(conn)
        rows = conn.execute(
            """
            SELECT id,booking_date,amount_cents,label,user_label,merchant,category,transaction_type,
                   is_internal_transfer,exclude_from_analytics,source_type,source_status,confidence
            FROM transactions
            ORDER BY booking_date DESC,id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()
        aliases = {r['normalized_key']: dict(r) for r in conn.execute('SELECT * FROM merchant_aliases').fetchall()}
        recurring = detect_recurring_suggestions(conn)

    items = [dict(r) for r in rows]
    expense_amounts = [abs(int(x['amount_cents'])) for x in items if int(x['amount_cents']) < 0 and not x['is_internal_transfer'] and not x['exclude_from_analytics']]
    med = int(median(expense_amounts)) if expense_amounts else 0
    large_threshold = max(med * 4, 15000) if med else 15000

    merchant_groups: dict[str, list[dict]] = defaultdict(list)
    for item in items:
        key = _merchant_key(item.get('user_label') or item.get('label') or '')
        if key:
            merchant_groups[key].append(item)

    merchant_suggestions = []
    for key, group in merchant_groups.items():
        if len(group) < 2:
            continue
        alias = aliases.get(key)
        canonical = alias['canonical_name'] if alias else key.title()
        merchant_suggestions.append({
            'normalized_key': key,
            'canonical_name': canonical,
            'occurrences': len(group),
            'confirmed': bool(alias),
            'confidence': 1.0 if alias else min(0.95, 0.55 + len(group) * 0.07),
        })
    merchant_suggestions.sort(key=lambda x: (-x['occurrences'], x['canonical_name']))

    anomalies = []
    for item in items:
        amount = int(item['amount_cents'])
        if amount < 0 and abs(amount) >= large_threshold and not item['is_internal_transfer'] and not item['exclude_from_analytics']:
            anomalies.append({
                'type': 'large_expense', 'severity': 'warning', 'transaction_id': item['id'],
                'title': 'Dépense nettement supérieure au niveau habituel',
                'detail': item.get('user_label') or item['label'], 'amount_cents': amount,
            })
        if not item.get('category') and not item['is_internal_transfer']:
            anomalies.append({
                'type': 'uncategorized', 'severity': 'info', 'transaction_id': item['id'],
                'title': 'Mouvement non catégorisé', 'detail': item.get('user_label') or item['label'],
                'amount_cents': amount,
            })
        if item.get('confidence') is not None and float(item['confidence']) < 0.6:
            anomalies.append({
                'type': 'low_confidence', 'severity': 'info', 'transaction_id': item['id'],
                'title': 'Source à faible confiance', 'detail': item.get('user_label') or item['label'],
                'amount_cents': amount,
            })

    total = len(items)
    uncategorized = sum(1 for x in items if not x.get('category') and not x['is_internal_transfer'])
    excluded = sum(1 for x in items if x['exclude_from_analytics'])
    stale_source = sum(1 for x in items if x.get('source_status') in {'needs_review', 'stale', 'unknown'})
    score = _quality_score(total, uncategorized, excluded, stale_source, len([a for a in anomalies if a['type'] == 'large_expense']))

    return {
        'sample_size': total,
        'quality_score': score,
        'metrics': {
            'uncategorized': uncategorized,
            'excluded': excluded,
            'source_review': stale_source,
            'large_expenses': sum(1 for a in anomalies if a['type'] == 'large_expense'),
            'recurring_suggestions': len([r for r in recurring if float(r.get('confidence') or 0) >= 0.75]),
        },
        'large_expense_threshold_cents': large_threshold,
        'merchant_suggestions': merchant_suggestions[:30],
        'anomalies': anomalies[:100],
        'method': 'Score heuristique et explicable basé sur catégorisation, exclusions, qualité de source et anomalies de montant. Les suggestions marchand ne modifient jamais les transactions sans validation explicite.',
    }


@router.post('/merchant-aliases', status_code=201)
def save_merchant_alias(payload: MerchantAliasIn):
    key = _merchant_key(payload.normalized_key)
    with connection() as conn:
        ensure_v37_schema(conn)
        conn.execute(
            """
            INSERT INTO merchant_aliases(normalized_key,canonical_name,confidence,source)
            VALUES(?,?,1.0,'user')
            ON CONFLICT(normalized_key) DO UPDATE SET
              canonical_name=excluded.canonical_name,confidence=1.0,source='user',updated_at=CURRENT_TIMESTAMP
            """,
            (key, payload.canonical_name.strip()),
        )
        row = conn.execute('SELECT * FROM merchant_aliases WHERE normalized_key=?', (key,)).fetchone()
    return dict(row)
