from datetime import date

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, Form
from pydantic import BaseModel

from .balance_only import enrich_balance_only_position
from .commitment_engine import build_commitment_review
from .current_activity_routes import import_current_activity
from .db import connection
from .financial_integrity import build_financial_integrity
from .financial_intelligence import build_financial_intelligence
from .financial_visualization import build_variable_category_view
from .imports import ensure_import_schema

router = APIRouter(prefix='/api/finance', tags=['finance'])


RECURRING_INTELLIGENCE_COLUMNS = {
    'usual_day': 'INTEGER',
    'next_expected_date': 'TEXT',
    'last_seen_date': 'TEXT',
    "detection_status": "TEXT NOT NULL DEFAULT 'accepted'",
}


class BalanceSnapshotIn(BaseModel):
    current_balance_cents: int
    balance_as_of: date | None = None


class RecurringDecisionIn(BaseModel):
    decision: str


def _ensure_recurring_intelligence_schema(conn) -> None:
    """Apply additive, non-destructive columns required by the intelligence engine."""
    columns = {
        row[1]
        for row in conn.execute('PRAGMA table_info(recurring_transactions)').fetchall()
    }
    for name, sql_type in RECURRING_INTELLIGENCE_COLUMNS.items():
        if name not in columns:
            conn.execute(
                f'ALTER TABLE recurring_transactions ADD COLUMN {name} {sql_type}'
            )


@router.get('/intelligence')
def intelligence(
    as_of: date | None = None,
    history_months: int = Query(default=12, ge=3, le=24),
):
    with connection() as conn:
        _ensure_recurring_intelligence_schema(conn)
        payload = build_financial_intelligence(
            conn,
            as_of=as_of,
            history_months=history_months,
        )
        return enrich_balance_only_position(conn, payload)


@router.get('/visualization')
def visualization(
    as_of: date | None = None,
    months: int = Query(default=6, ge=3, le=12),
):
    """Return read-only aggregates used by financial visualization components."""
    with connection() as conn:
        _ensure_recurring_intelligence_schema(conn)
        return build_variable_category_view(conn, as_of=as_of or date.today(), months=months)


@router.get('/commitments')
def commitments(as_of: date | None = None):
    """Return the explainable commitment review used to validate Safe-to-spend inputs."""
    with connection() as conn:
        _ensure_recurring_intelligence_schema(conn)
        intelligence_payload = build_financial_intelligence(conn, as_of=as_of, history_months=12)
        horizon = date.fromisoformat(intelligence_payload['safe_to_spend']['horizon_end'])
        return build_commitment_review(conn, as_of=as_of, horizon_end=horizon)


@router.patch('/commitments/{recurring_id}')
def decide_commitment(recurring_id: int, payload: RecurringDecisionIn):
    decision = payload.decision.strip().lower()
    if decision not in {'accept', 'reject', 'reactivate'}:
        raise HTTPException(400, 'decision must be accept, reject or reactivate')
    with connection() as conn:
        _ensure_recurring_intelligence_schema(conn)
        row = conn.execute('SELECT * FROM recurring_transactions WHERE id=?', (recurring_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Recurring commitment not found')
        if decision in {'accept', 'reactivate'}:
            conn.execute(
                "UPDATE recurring_transactions SET detection_status='accepted',is_active=1 WHERE id=?",
                (recurring_id,),
            )
        else:
            conn.execute(
                "UPDATE recurring_transactions SET detection_status='rejected',is_active=0 WHERE id=?",
                (recurring_id,),
            )
        updated = conn.execute('SELECT * FROM recurring_transactions WHERE id=?', (recurring_id,)).fetchone()
    return {'commitment': dict(updated), 'decision': decision}


@router.get('/integrity')
def integrity(
    as_of: date | None = None,
    months: int = Query(default=24, ge=1, le=36),
):
    """Return an auditable reconciliation of statements, history and Safe to Spend."""
    with connection() as conn:
        ensure_import_schema(conn)
        _ensure_recurring_intelligence_schema(conn)
        return build_financial_integrity(conn, as_of=as_of, months=months)


@router.post('/activity-import', status_code=201)
async def activity_import(
    account_id: int = Form(...),
    file: UploadFile = File(...),
):
    return await import_current_activity(account_id=account_id, file=file)


@router.put('/accounts/{account_id}/balance')
def update_current_balance(account_id: int, payload: BalanceSnapshotIn):
    """Update the operational balance and keep an auditable manual snapshot.

    This endpoint changes the account balance only. It deliberately does not
    create or infer transactions, so transaction coverage and current-month
    observability remain independent from balance freshness.
    """
    observed = (payload.balance_as_of or date.today()).isoformat()
    with connection() as conn:
        account = conn.execute(
            'SELECT * FROM accounts WHERE id=? AND is_active=1',
            (account_id,),
        ).fetchone()
        if not account:
            raise HTTPException(404, 'Account not found')

        conn.execute(
            'UPDATE accounts SET current_balance_cents=?,balance_as_of=? WHERE id=?',
            (payload.current_balance_cents, observed, account_id),
        )

        source_key = f'manual-balance:{account_id}:{observed}:{payload.current_balance_cents}'
        conn.execute(
            '''INSERT INTO account_balance_history(
                   account_id,balance_cents,balance_date,status,
                   source_type,source_id,source_date,source_status,confidence,source_key
               ) VALUES(?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source_key) DO NOTHING''',
            (
                account_id,
                payload.current_balance_cents,
                observed,
                'confirmed',
                'manual_balance',
                'flow-ui',
                observed,
                'confirmed',
                1.0,
                source_key,
            ),
        )

        row = conn.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()
        history = conn.execute(
            'SELECT id,balance_cents,balance_date,source_type,confidence FROM account_balance_history WHERE source_key=?',
            (source_key,),
        ).fetchone()

    return {
        'account': dict(row),
        'snapshot': dict(history) if history else None,
        'transaction_data_changed': False,
    }


@router.get('/history')
def history(limit: int = Query(default=24, ge=1, le=120)):
    with connection() as conn:
        months = [dict(r) for r in conn.execute('SELECT * FROM monthly_financial_history ORDER BY month DESC LIMIT ?', (limit,)).fetchall()]
        balances = [dict(r) for r in conn.execute('SELECT h.*,a.name account_name FROM account_balance_history h JOIN accounts a ON a.id=h.account_id ORDER BY h.balance_date DESC,h.id DESC LIMIT ?', (limit * 10,)).fetchall()]
    return {'months': months, 'balances': balances}


@router.get('/rules')
def rules(include_inactive: bool = False):
    query = 'SELECT * FROM financial_rules'
    if not include_inactive:
        query += " WHERE status='active'"
    query += ' ORDER BY id DESC'
    with connection() as conn:
        rows = conn.execute(query).fetchall()
    return [dict(r) for r in rows]


@router.get('/decisions')
def decisions(limit: int = Query(default=100, ge=1, le=500)):
    with connection() as conn:
        rows = conn.execute('SELECT * FROM financial_decisions ORDER BY decision_date DESC,id DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in rows]
