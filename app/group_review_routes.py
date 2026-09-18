from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import connection
from .imports import apply_rule_to_inbox, ensure_import_schema, normalize_label, refresh_review_counts

router = APIRouter()


class GroupReviewIn(BaseModel):
    normalized_label: str = Field(min_length=1, max_length=180)
    category: str = Field(min_length=1, max_length=80)
    transaction_type: str | None = Field(default=None, max_length=40)
    confirm: bool = False
    create_rule: bool = False


def _group_preview(conn, normalized_label: str) -> dict:
    rows = conn.execute(
        """
        SELECT t.id,t.booking_date,t.amount_cents,t.label,t.category,
               t.transaction_type,t.is_internal_transfer,m.import_id
        FROM transaction_import_meta m
        JOIN transactions t ON t.id=m.transaction_id
        WHERE m.review_status='needs_review' AND m.normalized_label=?
        ORDER BY t.booking_date DESC,t.id DESC
        """,
        (normalized_label,),
    ).fetchall()
    movements = [dict(row) for row in rows]
    return {
        'normalized_label': normalized_label,
        'pending_count': len(movements),
        'net_amount_cents': sum(int(row['amount_cents']) for row in movements),
        'debit_count': sum(1 for row in movements if int(row['amount_cents']) < 0),
        'credit_count': sum(1 for row in movements if int(row['amount_cents']) > 0),
        'first_seen': min((row['booking_date'] for row in movements), default=None),
        'last_seen': max((row['booking_date'] for row in movements), default=None),
        'import_ids': sorted({int(row['import_id']) for row in movements if row['import_id'] is not None}),
        'movements': movements,
    }


@router.post('/api/imports/inbox/group-review')
def review_import_group(payload: GroupReviewIn):
    category = payload.category.strip()
    normalized_label = payload.normalized_label.strip()
    if not category or not normalized_label:
        raise HTTPException(400, 'Le libellé et la catégorie sont obligatoires')

    with connection() as conn:
        ensure_import_schema(conn)
        preview = _group_preview(conn, normalized_label)
        if preview['pending_count'] == 0:
            raise HTTPException(404, 'Aucun mouvement en revue pour ce groupe')

        if not payload.confirm:
            return {
                'ok': False,
                'requires_confirmation': True,
                'preview': preview,
                'applied': 0,
                'read_only': True,
            }

        transaction_type = payload.transaction_type or (
            'income' if preview['credit_count'] and not preview['debit_count'] else 'expense'
        )
        internal = int(transaction_type == 'transfer' or category == 'Transfert interne')
        conn.execute(
            """
            UPDATE transactions
            SET category=?,transaction_type=?,is_internal_transfer=?
            WHERE id IN (
                SELECT t.id
                FROM transaction_import_meta m
                JOIN transactions t ON t.id=m.transaction_id
                WHERE m.review_status='needs_review' AND m.normalized_label=?
            )
            """,
            (category, transaction_type, internal, normalized_label),
        )
        conn.execute(
            """
            UPDATE transaction_import_meta
            SET review_status='accepted'
            WHERE review_status='needs_review' AND normalized_label=?
            """,
            (normalized_label,),
        )

        rule_applied = 0
        if payload.create_rule:
            pattern = normalize_label(normalized_label)
            existing = conn.execute(
                'SELECT 1 FROM categorization_rules WHERE pattern=? AND category=? AND is_active=1',
                (pattern, category),
            ).fetchone()
            if not existing:
                conn.execute(
                    'INSERT INTO categorization_rules(pattern,category,transaction_type,priority) VALUES(?,?,?,?)',
                    (pattern, category, transaction_type, 50),
                )
            rule_applied = apply_rule_to_inbox(conn, pattern, category, transaction_type)

        refresh_review_counts(conn)
        preview_after = _group_preview(conn, normalized_label)
        return {
            'ok': True,
            'requires_confirmation': False,
            'preview': preview,
            'applied': preview['pending_count'],
            'remaining_pending': preview_after['pending_count'],
            'category': category,
            'transaction_type': transaction_type,
            'is_internal_transfer': bool(internal),
            'rule_applied': rule_applied,
            'read_only': False,
        }
