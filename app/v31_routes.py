from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .db import connection
from .financial_engine_v2 import build_decision_cockpit, data_quality
from .imports import accept_categorized_import_reviews, ensure_import_schema
from .v2_migrations import ensure_v2_schema
from .v31_migrations import ensure_v31_schema
from .v3_migrations import ensure_v3_schema, log_activity

router = APIRouter(prefix='/api/v3.1', tags=['Flow V3.1'])


class MovementPatch(BaseModel):
    user_label: str | None = Field(default=None, max_length=180)
    category: str | None = Field(default=None, max_length=80)
    transaction_type: str | None = Field(default=None, max_length=40)
    is_internal_transfer: bool | None = None
    is_exceptional: bool | None = None
    exclude_from_analytics: bool | None = None


class RuleFromMovementIn(BaseModel):
    pattern: str | None = Field(default=None, min_length=2, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    transaction_type: str | None = Field(default=None, max_length=40)
    apply_existing: bool = True
    priority: int = Field(default=50, ge=1, le=999)


class NotificationPreferencePatch(BaseModel):
    enabled: bool | None = None
    threshold_cents: int | None = Field(default=None, ge=0)


def _movement_view(row) -> dict:
    item = dict(row)
    item['quality_flags'] = []
    if not item.get('category'):
        item['quality_flags'].append('uncategorized')
    if item.get('is_internal_transfer') and not item.get('transfer_pair_id'):
        item['quality_flags'].append('unmatched_transfer')
    if item.get('exclude_from_analytics'):
        item['quality_flags'].append('excluded')
    if item.get('is_exceptional'):
        item['quality_flags'].append('exceptional')
    return item


@router.get('/movements')
def movements(
    q: str = '',
    month: str | None = None,
    category: str | None = None,
    quality: str | None = None,
    limit: int = Query(default=120, ge=1, le=500),
):
    with connection() as conn:
        ensure_v2_schema(conn)
        clauses = ['1=1']
        params: list[object] = []
        if q.strip():
            clauses.append("(t.label LIKE ? OR COALESCE(t.user_label,'') LIKE ? OR COALESCE(t.category,'') LIKE ? OR a.name LIKE ?)")
            pattern = f"%{q.strip()}%"
            params += [pattern, pattern, pattern, pattern]
        if month:
            clauses.append('substr(t.booking_date,1,7)=?')
            params.append(month)
        if category:
            clauses.append("COALESCE(t.category,'')=?")
            params.append(category)
        if quality == 'uncategorized':
            clauses.append("COALESCE(t.category,'')=''")
        elif quality == 'unmatched_transfer':
            clauses.append('COALESCE(t.is_internal_transfer,0)=1 AND t.transfer_pair_id IS NULL')
        elif quality == 'exceptional':
            clauses.append('COALESCE(t.is_exceptional,0)=1')
        elif quality == 'excluded':
            clauses.append('COALESCE(t.exclude_from_analytics,0)=1')
        params.append(limit)
        rows = conn.execute(
            f"SELECT t.*,a.name account_name FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE {' AND '.join(clauses)} ORDER BY t.booking_date DESC,t.id DESC LIMIT ?",
            params,
        ).fetchall()
    return [_movement_view(row) for row in rows]


@router.patch('/movements/{transaction_id}')
def update_movement(transaction_id: int, payload: MovementPatch):
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, 'Aucune modification demandée')
    bool_fields = {'is_internal_transfer', 'is_exceptional', 'exclude_from_analytics'}
    with connection() as conn:
        ensure_v2_schema(conn)
        ensure_v3_schema(conn)
        before = conn.execute('SELECT * FROM transactions WHERE id=?', (transaction_id,)).fetchone()
        if not before:
            raise HTTPException(404, 'Mouvement introuvable')
        if 'category' in updates and updates['category']:
            if not conn.execute('SELECT 1 FROM categories WHERE name=? AND is_active=1', (updates['category'],)).fetchone():
                raise HTTPException(400, 'Catégorie inconnue')
        fields = []
        values = []
        for key, value in updates.items():
            fields.append(f'{key}=?')
            values.append(int(value) if key in bool_fields and value is not None else value)
        values.append(transaction_id)
        conn.execute(f"UPDATE transactions SET {','.join(fields)} WHERE id=?", values)
        review_accepted = 0
        if updates.get('category'):
            ensure_import_schema(conn)
            review_accepted = accept_categorized_import_reviews(conn, {transaction_id})
        after = conn.execute('SELECT * FROM transactions WHERE id=?', (transaction_id,)).fetchone()
        changed = [key for key in updates if before[key] != after[key]]
        if changed:
            log_activity(conn, 'movement_edit', 'Mouvement corrigé', ', '.join(changed), 'transaction', str(transaction_id))
    return {**_movement_view(after), 'import_review_accepted': bool(review_accepted)}


@router.post('/movements/{transaction_id}/rule', status_code=201)
def create_rule_from_movement(transaction_id: int, payload: RuleFromMovementIn):
    with connection() as conn:
        ensure_v2_schema(conn)
        ensure_v3_schema(conn)
        row = conn.execute('SELECT id,label,user_label FROM transactions WHERE id=?', (transaction_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Mouvement introuvable')
        if not conn.execute('SELECT 1 FROM categories WHERE name=? AND is_active=1', (payload.category,)).fetchone():
            raise HTTPException(400, 'Catégorie inconnue')
        pattern = (payload.pattern or row['user_label'] or row['label']).strip().upper()
        if len(pattern) < 2:
            raise HTTPException(400, 'Motif trop court')
        existing = conn.execute(
            'SELECT * FROM categorization_rules WHERE pattern=? AND category=? AND is_active=1',
            (pattern, payload.category),
        ).fetchone()
        if existing:
            rule_id = existing['id']
        else:
            cur = conn.execute(
                'INSERT INTO categorization_rules(pattern,category,transaction_type,priority,is_active) VALUES(?,?,?,?,1)',
                (pattern, payload.category, payload.transaction_type, payload.priority),
            )
            rule_id = cur.lastrowid
        updated = 0
        if payload.apply_existing:
            params: list[object] = [payload.category]
            sql = 'UPDATE transactions SET category=?'
            if payload.transaction_type:
                sql += ',transaction_type=?'
                params.append(payload.transaction_type)
            sql += " WHERE UPPER(COALESCE(user_label,label)) LIKE ? AND COALESCE(is_internal_transfer,0)=0"
            params.append(f'%{pattern}%')
            updated = conn.execute(sql, params).rowcount
        conn.execute('UPDATE transactions SET category=? WHERE id=?', (payload.category, transaction_id))
        log_activity(conn, 'categorization_rule', 'Règle de catégorisation créée', f'{pattern} → {payload.category} · {updated} mouvement(s)', 'categorization_rule', str(rule_id))
        rule = conn.execute('SELECT * FROM categorization_rules WHERE id=?', (rule_id,)).fetchone()
    return {**dict(rule), 'updated_transactions': updated}


@router.get('/movement-summary')
def movement_summary(month: str | None = None):
    month = month or date.today().strftime('%Y-%m')
    with connection() as conn:
        ensure_v2_schema(conn)
        row = conn.execute(
            """SELECT COUNT(*) total,
               COALESCE(SUM(CASE WHEN amount_cents<0 AND is_internal_transfer=0 AND exclude_from_analytics=0 THEN -amount_cents ELSE 0 END),0) spent,
               COALESCE(SUM(CASE WHEN amount_cents>0 AND is_internal_transfer=0 AND exclude_from_analytics=0 THEN amount_cents ELSE 0 END),0) income,
               COALESCE(SUM(CASE WHEN is_exceptional=1 THEN 1 ELSE 0 END),0) exceptional,
               COALESCE(SUM(CASE WHEN COALESCE(category,'')='' THEN 1 ELSE 0 END),0) uncategorized,
               COALESCE(SUM(CASE WHEN is_internal_transfer=1 AND transfer_pair_id IS NULL THEN 1 ELSE 0 END),0) unmatched_transfers
               FROM transactions WHERE substr(booking_date,1,7)=?""",
            (month,),
        ).fetchone()
    return {'month': month, **dict(row)}


@router.get('/notifications')
def notifications():
    today = date.today()
    with connection() as conn:
        ensure_v2_schema(conn)
        ensure_v31_schema(conn)
        ensure_import_schema(conn)
        prefs = {r['key']: dict(r) for r in conn.execute('SELECT * FROM notification_preferences').fetchall()}
        cockpit = build_decision_cockpit(conn, today)
        quality = data_quality(conn, today)
        items: list[dict] = []
        safe = cockpit['safe_to_spend']
        if prefs['safe_to_spend_risk']['enabled'] and safe.get('status') in {'prudent','tight','critical'}:
            items.append({'key':'safe_to_spend_risk','severity':'critical' if safe.get('status') == 'critical' else 'warning','title':'Safe to Spend sous tension','detail':f"Disponible sécurisé : {int(safe.get('until_income_cents') or 0)/100:.2f} €",'due_date':today.isoformat()})
        threshold = int(prefs['large_upcoming_outflow']['threshold_cents'] or 30000)
        if prefs['large_upcoming_outflow']['enabled']:
            end = (today + timedelta(days=7)).isoformat()
            rows = conn.execute("SELECT id,due_date,amount_cents,label FROM planned_transactions WHERE status='planned' AND due_date BETWEEN ? AND ? AND amount_cents<=? ORDER BY due_date", (today.isoformat(), end, -threshold)).fetchall()
            for row in rows:
                items.append({'key':'large_upcoming_outflow','severity':'warning','title':row['label'],'detail':f"Sortie prévue de {abs(row['amount_cents'])/100:.2f} €",'due_date':row['due_date'],'entity_id':row['id']})
        if prefs['stale_balance']['enabled']:
            for issue in quality.get('issues', []):
                if issue.get('type') == 'stale_balance':
                    items.append({'key':'stale_balance','severity':issue.get('severity','warning'),'title':'Solde bancaire à rafraîchir','detail':f"{issue.get('count',1)} compte(s) concerné(s)",'due_date':today.isoformat()})
        if prefs['import_review']['enabled']:
            review = int(conn.execute("SELECT COUNT(*) n FROM transaction_import_meta WHERE review_status='needs_review'").fetchone()['n'])
            if review:
                items.append({'key':'import_review','severity':'info','title':'Imports à vérifier','detail':f'{review} mouvement(s) attendent une validation','due_date':today.isoformat()})
    items.sort(key=lambda item: (0 if item['severity']=='critical' else 1 if item['severity']=='warning' else 2, item.get('due_date') or ''))
    return {'count': len(items), 'items': items}


@router.get('/notification-preferences')
def notification_preferences():
    with connection() as conn:
        ensure_v31_schema(conn)
        rows = conn.execute('SELECT key,enabled,threshold_cents,description,updated_at FROM notification_preferences ORDER BY key').fetchall()
    return [dict(row) for row in rows]


@router.patch('/notification-preferences/{key}')
def update_notification_preference(key: str, payload: NotificationPreferencePatch):
    updates = payload.model_dump(exclude_unset=True)
    if not updates:
        raise HTTPException(400, 'Aucune modification demandée')
    with connection() as conn:
        ensure_v31_schema(conn)
        ensure_v3_schema(conn)
        if not conn.execute('SELECT 1 FROM notification_preferences WHERE key=?', (key,)).fetchone():
            raise HTTPException(404, 'Préférence introuvable')
        fields = []
        values = []
        for name, value in updates.items():
            fields.append(f'{name}=?')
            values.append(int(value) if name == 'enabled' and value is not None else value)
        fields.append('updated_at=CURRENT_TIMESTAMP')
        values.append(key)
        conn.execute(f"UPDATE notification_preferences SET {','.join(fields)} WHERE key=?", values)
        log_activity(conn, 'notification_setting', 'Préférence de notification modifiée', key, 'notification_preference', key)
        row = conn.execute('SELECT key,enabled,threshold_cents,description,updated_at FROM notification_preferences WHERE key=?', (key,)).fetchone()
    return dict(row)
