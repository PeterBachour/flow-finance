from __future__ import annotations

from fastapi import APIRouter, Query

from .db import connection
from .bulk_import import ensure_bulk_schema
from .imports import ensure_import_schema
from .v22_migrations import ensure_v22_schema

router = APIRouter(prefix='/api/v2.4', tags=['Flow V2.4'])


def _like(value: str) -> str:
    return f"%{value.strip()}%"


@router.get('/search')
def global_search(q: str = Query(min_length=2, max_length=120), limit: int = Query(default=8, ge=1, le=25)):
    term = q.strip()
    pattern = _like(term)
    results: list[dict] = []
    with connection() as conn:
        ensure_v22_schema(conn)
        ensure_import_schema(conn)
        ensure_bulk_schema(conn)

        for row in conn.execute(
            "SELECT t.id,t.booking_date,t.amount_cents,t.label,COALESCE(t.user_label,'') user_label,COALESCE(t.category,'') category,a.name account_name "
            "FROM transactions t JOIN accounts a ON a.id=t.account_id "
            "WHERE t.label LIKE ? OR COALESCE(t.user_label,'') LIKE ? OR COALESCE(t.category,'') LIKE ? OR a.name LIKE ? "
            "ORDER BY t.booking_date DESC,t.id DESC LIMIT ?",
            (pattern, pattern, pattern, pattern, limit),
        ).fetchall():
            results.append({'type':'movement','id':row['id'],'title':row['user_label'] or row['label'],'subtitle':f"{row['booking_date']} · {row['category'] or 'Non catégorisé'} · {row['account_name']}",'amount_cents':row['amount_cents'],'date':row['booking_date']})

        for row in conn.execute(
            "SELECT id,name,kind,current_balance_cents,balance_as_of FROM accounts WHERE is_active=1 AND (name LIKE ? OR COALESCE(bank,'') LIKE ?) ORDER BY id LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall():
            results.append({'type':'account','id':row['id'],'title':row['name'],'subtitle':f"{row['kind']} · solde au {row['balance_as_of'] or 'jour inconnu'}",'amount_cents':row['current_balance_cents']})

        for row in conn.execute(
            "SELECT id,due_date,amount_cents,label,kind,certainty FROM planned_transactions WHERE status='planned' AND (label LIKE ? OR kind LIKE ?) ORDER BY due_date LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall():
            results.append({'type':'planned','id':row['id'],'title':row['label'],'subtitle':f"Prévu le {row['due_date']} · {row['certainty']}",'amount_cents':row['amount_cents'],'date':row['due_date']})

        for row in conn.execute(
            "SELECT id,name,goal_type,target_cents,current_cents,target_date FROM financial_goals WHERE is_active=1 AND (name LIKE ? OR COALESCE(goal_type,'') LIKE ?) ORDER BY priority,id LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall():
            results.append({'type':'goal','id':row['id'],'title':row['name'],'subtitle':f"Objectif · {row['goal_type'] or 'épargne'} · cible {row['target_date'] or 'sans date'}",'amount_cents':row['target_cents']})

        for row in conn.execute(
            "SELECT id,name,asset_type,value_cents,debt_cents,valuation_date FROM wealth_assets WHERE name LIKE ? OR asset_type LIKE ? ORDER BY id DESC LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall():
            results.append({'type':'asset','id':row['id'],'title':row['name'],'subtitle':f"{row['asset_type']} · valorisé le {row['valuation_date']}",'amount_cents':row['value_cents']-row['debt_cents']})

        for row in conn.execute(
            "SELECT id,filename,bank,status,period_start,period_end,imported_rows,duplicate_rows FROM imports WHERE filename LIKE ? OR COALESCE(bank,'') LIKE ? ORDER BY id DESC LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall():
            results.append({'type':'import','id':row['id'],'title':row['filename'],'subtitle':f"Import {row['bank'] or ''} · {row['status']} · {row['period_start'] or '?'} → {row['period_end'] or '?'}",'meta':{'imported':row['imported_rows'],'duplicates':row['duplicate_rows']}})

        for row in conn.execute(
            "SELECT id,period,employer,net_paid_cents,gross_cents FROM payroll_records WHERE COALESCE(employer,'') LIKE ? OR COALESCE(period,'') LIKE ? ORDER BY period DESC,id DESC LIMIT ?",
            (pattern, pattern, limit),
        ).fetchall():
            results.append({'type':'payroll','id':row['id'],'title':row['employer'] or 'Fiche de paie','subtitle':f"Paie · {row['period'] or 'période inconnue'}",'amount_cents':row['net_paid_cents']})

    order = {'movement':0,'planned':1,'account':2,'goal':3,'asset':4,'payroll':5,'import':6}
    results.sort(key=lambda item:(order.get(item['type'],99), str(item.get('date') or '')), reverse=False)
    return {'query': term, 'count': len(results), 'results': results[:limit * 3]}


@router.get('/imports/summary')
def import_summary():
    with connection() as conn:
        ensure_import_schema(conn)
        ensure_bulk_schema(conn)
        imports = conn.execute(
            "SELECT COUNT(*) total,COALESCE(SUM(imported_rows),0) imported,COALESCE(SUM(duplicate_rows),0) duplicates,COALESCE(SUM(review_rows),0) review FROM imports"
        ).fetchone()
        payrolls = conn.execute('SELECT COUNT(*) total FROM payroll_records').fetchone()['total']
        batches = conn.execute("SELECT COUNT(*) total FROM bulk_import_batches WHERE status='staging'").fetchone()['total']
        latest = conn.execute('SELECT id,filename,status,quality_status,created_at FROM imports ORDER BY id DESC LIMIT 1').fetchone()
    return {
        'imports': dict(imports),
        'payrolls': int(payrolls),
        'staging_batches': int(batches),
        'latest': dict(latest) if latest else None,
    }
