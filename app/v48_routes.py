from __future__ import annotations

import hashlib
from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import connection
from .recurring_detection import detect_recurring_suggestions, recurring_key
from .v2_migrations import ensure_v2_schema
from .v3_migrations import ensure_v3_schema, log_activity

router = APIRouter(prefix='/api/v4.8', tags=['Flow V4.8'])


class BulkCategoryIn(BaseModel):
    pattern: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    account_id: int | None = None
    only_uncategorized: bool = True
    transaction_type: str | None = Field(default=None, max_length=40)
    create_rule: bool = True


class RecurringDecisionIn(BaseModel):
    key: str = Field(min_length=2, max_length=180)
    action: str = Field(pattern='^(accept|reject)$')


def ensure_v48_schema(conn) -> None:
    conn.execute('''CREATE TABLE IF NOT EXISTS recurring_review_state (
        suggestion_key TEXT PRIMARY KEY,
        status TEXT NOT NULL CHECK(status IN ('accepted','rejected')),
        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    )''')


def _rule_key(pattern: str) -> str:
    return 'bulk:' + hashlib.sha1(pattern.strip().upper().encode('utf-8')).hexdigest()[:16]


def _bulk_where(payload: BulkCategoryIn) -> tuple[str, list[object]]:
    clauses = ["UPPER(COALESCE(t.user_label,t.label)) LIKE ?", "COALESCE(t.is_internal_transfer,0)=0"]
    params: list[object] = [f"%{payload.pattern.strip().upper()}%"]
    if payload.account_id is not None:
        clauses.append('t.account_id=?')
        params.append(payload.account_id)
    if payload.only_uncategorized:
        clauses.append("COALESCE(t.category,'')=''")
    return ' AND '.join(clauses), params


def _validate_bulk(conn, payload: BulkCategoryIn) -> None:
    if not conn.execute('SELECT 1 FROM categories WHERE name=? AND is_active=1', (payload.category,)).fetchone():
        raise HTTPException(400, 'Catégorie inconnue')
    if payload.account_id is not None and not conn.execute('SELECT 1 FROM accounts WHERE id=? AND is_active=1', (payload.account_id,)).fetchone():
        raise HTTPException(404, 'Compte introuvable')


@router.post('/bulk-category/preview')
def bulk_category_preview(payload: BulkCategoryIn):
    with connection() as conn:
        ensure_v2_schema(conn)
        _validate_bulk(conn, payload)
        where, params = _bulk_where(payload)
        count = int(conn.execute(f'SELECT COUNT(*) n FROM transactions t WHERE {where}', params).fetchone()['n'])
        rows = conn.execute(
            f'''SELECT t.id,t.booking_date,t.amount_cents,t.label,t.user_label,t.category,a.name account_name
                FROM transactions t JOIN accounts a ON a.id=t.account_id
                WHERE {where} ORDER BY t.booking_date DESC,t.id DESC LIMIT 12''',
            params,
        ).fetchall()
    return {
        'pattern': payload.pattern.strip().upper(), 'category': payload.category,
        'affected_count': count, 'sample': [dict(r) for r in rows],
        'will_create_rule': bool(payload.create_rule),
        'principle': 'Aucune modification n’est effectuée pendant la prévisualisation.',
    }


@router.post('/bulk-category/apply')
def bulk_category_apply(payload: BulkCategoryIn):
    with connection() as conn:
        ensure_v2_schema(conn)
        ensure_v3_schema(conn)
        _validate_bulk(conn, payload)
        where, params = _bulk_where(payload)
        ids = [r['id'] for r in conn.execute(f'SELECT t.id FROM transactions t WHERE {where}', params).fetchall()]
        if not ids:
            return {'updated_count': 0, 'rule_id': None}
        set_sql = 'category=?'
        set_params: list[object] = [payload.category]
        if payload.transaction_type:
            set_sql += ',transaction_type=?'
            set_params.append(payload.transaction_type)
        placeholders = ','.join('?' for _ in ids)
        conn.execute(f'UPDATE transactions SET {set_sql} WHERE id IN ({placeholders})', set_params + ids)
        rule_id = None
        if payload.create_rule:
            pattern = payload.pattern.strip().upper()
            existing = conn.execute(
                'SELECT id FROM categorization_rules WHERE pattern=? AND category=? AND is_active=1',
                (pattern, payload.category),
            ).fetchone()
            if existing:
                rule_id = existing['id']
            else:
                cur = conn.execute(
                    'INSERT INTO categorization_rules(pattern,category,transaction_type,priority,is_active) VALUES(?,?,?,?,1)',
                    (pattern, payload.category, payload.transaction_type, 50),
                )
                rule_id = cur.lastrowid
        log_activity(conn, 'bulk_categorization', 'Catégorisation groupée appliquée',
                     f'{payload.pattern.strip().upper()} → {payload.category} · {len(ids)} mouvement(s)',
                     'categorization_rule', str(rule_id or _rule_key(payload.pattern)))
    return {'updated_count': len(ids), 'rule_id': rule_id}


def _suggestion_key(item: dict) -> str:
    raw = f"{item['account_id']}|{item.get('key') or item['label']}|{1 if item['amount_cents'] > 0 else -1}"
    return 'recurring:' + hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


@router.get('/recurring-review')
def recurring_review():
    with connection() as conn:
        ensure_v2_schema(conn)
        ensure_v48_schema(conn)
        states = {r['suggestion_key']: r['status'] for r in conn.execute('SELECT suggestion_key,status FROM recurring_review_state').fetchall()}
        items = []
        for item in detect_recurring_suggestions(conn):
            key = _suggestion_key(item)
            if states.get(key) == 'rejected':
                continue
            items.append({**item, 'review_key': key, 'review_status': states.get(key, 'pending')})
    return {'count': len(items), 'items': items, 'principle': 'Une récurrence détectée reste inactive tant qu’elle n’est pas acceptée explicitement.'}


@router.post('/recurring-review/decision')
def recurring_review_decision(payload: RecurringDecisionIn):
    with connection() as conn:
        ensure_v2_schema(conn)
        ensure_v3_schema(conn)
        ensure_v48_schema(conn)
        suggestions = detect_recurring_suggestions(conn)
        suggestion = next((item for item in suggestions if _suggestion_key(item) == payload.key), None)
        if not suggestion:
            raise HTTPException(404, 'Suggestion de récurrence introuvable ou déjà traitée')
        if payload.action == 'reject':
            conn.execute(
                "INSERT INTO recurring_review_state(suggestion_key,status) VALUES(?,'rejected') ON CONFLICT(suggestion_key) DO UPDATE SET status='rejected',updated_at=CURRENT_TIMESTAMP",
                (payload.key,),
            )
            log_activity(conn, 'recurring_review', 'Récurrence rejetée', suggestion['label'], 'recurring_suggestion', payload.key)
            return {'key': payload.key, 'status': 'rejected'}
        existing = conn.execute(
            'SELECT id FROM recurring_transactions WHERE account_id=? AND is_active=1 AND UPPER(label)=UPPER(?)',
            (suggestion['account_id'], suggestion['label']),
        ).fetchone()
        if existing:
            recurring_id = existing['id']
        else:
            kind = 'salary' if suggestion['amount_cents'] > 0 and suggestion.get('category') == 'Salaire' else ('income' if suggestion['amount_cents'] > 0 else 'commitment')
            cur = conn.execute(
                '''INSERT INTO recurring_transactions(account_id,label,amount_cents,day_of_month,category,kind,certainty,tolerance_cents,is_active)
                   VALUES(?,?,?,?,?,?,?, ?,1)''',
                (suggestion['account_id'], suggestion['label'], suggestion['amount_cents'], suggestion['day_of_month'],
                 suggestion.get('category'), kind, 'expected', suggestion.get('tolerance_cents') or 0),
            )
            recurring_id = cur.lastrowid
        conn.execute(
            "INSERT INTO recurring_review_state(suggestion_key,status) VALUES(?,'accepted') ON CONFLICT(suggestion_key) DO UPDATE SET status='accepted',updated_at=CURRENT_TIMESTAMP",
            (payload.key,),
        )
        log_activity(conn, 'recurring_review', 'Récurrence acceptée', suggestion['label'], 'recurring_transaction', str(recurring_id))
    return {'key': payload.key, 'status': 'accepted', 'recurring_id': recurring_id}


@router.get('/quality-workbench')
def quality_workbench():
    with connection() as conn:
        ensure_v2_schema(conn)
        ensure_v48_schema(conn)
        uncategorized = int(conn.execute("SELECT COUNT(*) n FROM transactions WHERE COALESCE(category,'')='' AND COALESCE(is_internal_transfer,0)=0").fetchone()['n'])
        unmatched = int(conn.execute('SELECT COUNT(*) n FROM transactions WHERE COALESCE(is_internal_transfer,0)=1 AND transfer_pair_id IS NULL').fetchone()['n'])
        excluded = int(conn.execute('SELECT COUNT(*) n FROM transactions WHERE COALESCE(exclude_from_analytics,0)=1').fetchone()['n'])
        rejected_recurring = int(conn.execute("SELECT COUNT(*) n FROM recurring_review_state WHERE status='rejected'").fetchone()['n'])
        pending_recurring = len([i for i in detect_recurring_suggestions(conn) if _suggestion_key(i) not in {
            r['suggestion_key'] for r in conn.execute("SELECT suggestion_key FROM recurring_review_state WHERE status='rejected'").fetchall()
        }])
    return {
        'uncategorized': uncategorized, 'unmatched_transfers': unmatched, 'excluded_from_analysis': excluded,
        'pending_recurring': pending_recurring, 'rejected_recurring': rejected_recurring,
        'principle': 'Ces éléments relèvent de la qualité des données et ne sont pas comptés comme décisions financières.'
    }
