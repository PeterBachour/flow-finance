from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .data_quality_report import build_data_quality_report
from .db import DB_PATH, connection
from .financial_engine_v2 import (
    build_decision_cockpit,
    category_spending,
    month_totals,
    monthly_insights,
    simulate_purchase,
    trend_summary,
)
from .v2_migrations import ensure_v2_schema
from .version import VERSION

router = APIRouter(prefix='/api/v2', tags=['Flow V2'])


class MovementPatch(BaseModel):
    category: str | None = None
    user_label: str | None = Field(default=None, max_length=180)
    transaction_type: str | None = None
    is_internal_transfer: bool | None = None
    is_exceptional: bool | None = None
    exclude_from_analytics: bool | None = None


class SimulationIn(BaseModel):
    amount_cents: int = Field(gt=0)
    due_date: date | None = None


class PaycheckIn(BaseModel):
    account_id: int | None = None
    pay_date: date
    employer: str | None = Field(default=None, max_length=160)
    net_cents: int = Field(gt=0)
    gross_cents: int | None = Field(default=None, gt=0)
    taxable_net_cents: int | None = Field(default=None, gt=0)
    withholding_tax_cents: int | None = Field(default=None, ge=0)
    bonuses_cents: int | None = Field(default=None, ge=0)
    benefits_cents: int | None = Field(default=None, ge=0)


def _ready(conn) -> None:
    ensure_v2_schema(conn)


def _valid_month(value: str) -> str:
    try:
        date.fromisoformat(f'{value}-01')
    except ValueError as exc:
        raise HTTPException(400, 'Invalid month, expected YYYY-MM') from exc
    return value


@router.get('/cockpit')
def cockpit():
    with connection() as conn:
        _ready(conn)
        result = build_decision_cockpit(conn)
        result['trends'] = trend_summary(conn)
        result['insights'] = monthly_insights(conn)
        result['data_quality'] = build_data_quality_report(conn)
    return result


@router.get('/months/{month}')
def month(month: str):
    month = _valid_month(month)
    with connection() as conn:
        _ready(conn)
        totals = month_totals(conn, month)
        categories = category_spending(conn, month)
        budget = conn.execute('SELECT id,status FROM budgets WHERE month=?', (month,)).fetchone()
        lines = []
        if budget:
            for row in conn.execute('SELECT category,planned_cents,mode FROM budget_lines WHERE budget_id=? ORDER BY category', (budget['id'],)).fetchall():
                spent = categories.get(row['category'], 0)
                projected = spent
                lines.append({
                    **dict(row), 'spent_cents': spent,
                    'remaining_cents': max(0, int(row['planned_cents']) - spent),
                    'projected_cents': projected,
                    'status': 'over' if spent > int(row['planned_cents']) else 'ok',
                })
        current = date.fromisoformat(f'{month}-01')
        previous_index = current.year * 12 + current.month - 2
        previous = f'{previous_index // 12:04d}-{previous_index % 12 + 1:02d}'
        previous_totals = month_totals(conn, previous)
    return {
        'month': month,
        **totals,
        'categories': categories,
        'budget_status': budget['status'] if budget else 'draft',
        'budget_lines': lines,
        'comparison': {
            'previous_month': previous,
            'spent_delta_cents': totals['spent_cents'] - previous_totals['spent_cents'],
            'income_delta_cents': totals['income_cents'] - previous_totals['income_cents'],
            'saving_delta_cents': totals['saving_cents'] - previous_totals['saving_cents'],
        },
    }


@router.get('/trends')
def trends():
    with connection() as conn:
        _ready(conn)
        return {'trends': trend_summary(conn), 'insights': monthly_insights(conn)}


@router.get('/movements')
def movements(
    q: str = '',
    account_id: int | None = None,
    category: str | None = None,
    transaction_type: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    exceptional: bool | None = None,
    excluded: bool | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    min_cents: int | None = None,
    max_cents: int | None = None,
    limit: int = Query(default=100, ge=1, le=500),
):
    clauses = ['1=1']
    params: list[object] = []
    if q.strip():
        clauses.append("(t.label LIKE ? OR COALESCE(t.user_label,'') LIKE ? OR COALESCE(t.category,'') LIKE ? OR COALESCE(t.merchant,'') LIKE ?)")
        pattern = f'%{q.strip()}%'
        params.extend([pattern] * 4)
    if account_id is not None:
        clauses.append('t.account_id=?'); params.append(account_id)
    if category:
        clauses.append('t.category=?'); params.append(category)
    if transaction_type:
        clauses.append('t.transaction_type=?'); params.append(transaction_type)
    if status:
        clauses.append("COALESCE(t.status,'confirmed')=?"); params.append(status)
    if source_type:
        clauses.append("COALESCE(t.source_type,'')=?"); params.append(source_type)
    if exceptional is not None:
        clauses.append('COALESCE(t.is_exceptional,0)=?'); params.append(int(exceptional))
    if excluded is not None:
        clauses.append('COALESCE(t.exclude_from_analytics,0)=?'); params.append(int(excluded))
    if date_from:
        clauses.append('t.booking_date>=?'); params.append(date_from.isoformat())
    if date_to:
        clauses.append('t.booking_date<=?'); params.append(date_to.isoformat())
    if min_cents is not None:
        clauses.append('ABS(t.amount_cents)>=?'); params.append(abs(min_cents))
    if max_cents is not None:
        clauses.append('ABS(t.amount_cents)<=?'); params.append(abs(max_cents))
    params.append(limit)
    sql = (
        "SELECT t.*,a.name account_name FROM transactions t JOIN accounts a ON a.id=t.account_id "
        f"WHERE {' AND '.join(clauses)} ORDER BY t.booking_date DESC,t.id DESC LIMIT ?"
    )
    with connection() as conn:
        _ready(conn)
        rows = conn.execute(sql, params).fetchall()
        tags = conn.execute(
            f"SELECT transaction_id,tag FROM transaction_tags WHERE transaction_id IN ({','.join('?' for _ in rows)}) ORDER BY tag",
            [row['id'] for row in rows],
        ).fetchall() if rows else []
    tag_map: dict[int, list[str]] = {}
    for tag in tags:
        tag_map.setdefault(tag['transaction_id'], []).append(tag['tag'])
    return [{**dict(row), 'tags': tag_map.get(row['id'], [])} for row in rows]


@router.patch('/movements/{transaction_id}')
def update_movement(transaction_id: int, payload: MovementPatch):
    updates = []
    params: list[object] = []
    for field in ('category', 'user_label', 'transaction_type'):
        value = getattr(payload, field)
        if value is not None:
            updates.append(f'{field}=?'); params.append(value.strip() if isinstance(value, str) else value)
    for field in ('is_internal_transfer', 'is_exceptional', 'exclude_from_analytics'):
        value = getattr(payload, field)
        if value is not None:
            updates.append(f'{field}=?'); params.append(int(value))
    if not updates:
        raise HTTPException(400, 'No changes supplied')
    params.append(transaction_id)
    with connection() as conn:
        _ready(conn)
        if not conn.execute('SELECT 1 FROM transactions WHERE id=?', (transaction_id,)).fetchone():
            raise HTTPException(404, 'Transaction not found')
        conn.execute(f"UPDATE transactions SET {', '.join(updates)} WHERE id=?", params)
        row = conn.execute('SELECT * FROM transactions WHERE id=?', (transaction_id,)).fetchone()
    return dict(row)


@router.get('/wealth')
def wealth():
    with connection() as conn:
        _ready(conn)
        accounts = [dict(row) for row in conn.execute('SELECT * FROM accounts WHERE is_active=1 ORDER BY id').fetchall()]
        goals = [dict(row) for row in conn.execute('SELECT * FROM financial_goals WHERE is_active=1 ORDER BY priority,id').fetchall()]
        allocations = {row['goal_id']: int(row['total']) for row in conn.execute('SELECT goal_id,COALESCE(SUM(amount_cents),0) total FROM goal_allocations GROUP BY goal_id').fetchall()}
        history = [dict(row) for row in conn.execute(
            "SELECT balance_date,COALESCE(SUM(balance_cents),0) total FROM account_balance_history "
            "GROUP BY balance_date ORDER BY balance_date DESC LIMIT 24"
        ).fetchall()]
    groups = {'cash_cents': 0, 'available_savings_cents': 0, 'locked_savings_cents': 0, 'investments_cents': 0, 'liabilities_cents': 0}
    for account in accounts:
        if not int(account.get('include_in_wealth', 1)):
            continue
        value = int(account['current_balance_cents'])
        kind = account['kind']
        if kind in {'checking', 'cash', 'joint'}:
            groups['cash_cents'] += value
        elif kind in {'savings', 'livret', 'ldds'}:
            groups['available_savings_cents'] += value
        elif kind in {'investment', 'pea', 'cto', 'life_insurance'}:
            groups['investments_cents'] += value
        elif kind in {'locked_savings'}:
            groups['locked_savings_cents'] += value
        elif kind in {'loan', 'debt'}:
            groups['liabilities_cents'] += abs(value)
    gross = groups['cash_cents'] + groups['available_savings_cents'] + groups['locked_savings_cents'] + groups['investments_cents']
    enriched_goals = []
    today = date.today()
    for goal in goals:
        current = max(int(goal.get('current_cents') or 0), allocations.get(goal['id'], 0))
        remaining = max(0, int(goal['target_cents']) - current)
        months = None
        required = None
        if goal.get('target_date'):
            target = date.fromisoformat(goal['target_date'])
            months = max(1, (target.year - today.year) * 12 + target.month - today.month)
            required = (remaining + months - 1) // months
        enriched_goals.append({**goal, 'effective_current_cents': current, 'remaining_cents': remaining, 'required_monthly_cents': required})
    return {'accounts': accounts, 'goals': enriched_goals, 'history': history, **groups, 'gross_financial_cents': gross, 'net_financial_cents': gross - groups['liabilities_cents']}


@router.get('/data-quality')
def quality():
    with connection() as conn:
        _ready(conn)
        return build_data_quality_report(conn)


@router.get('/paychecks')
def paychecks():
    with connection() as conn:
        _ready(conn)
        rows = conn.execute('SELECT p.*,a.name account_name FROM paychecks p LEFT JOIN accounts a ON a.id=p.account_id ORDER BY pay_date DESC,id DESC').fetchall()
    return [dict(row) for row in rows]


@router.post('/paychecks', status_code=201)
def create_paycheck(payload: PaycheckIn):
    with connection() as conn:
        _ready(conn)
        if payload.account_id and not conn.execute('SELECT 1 FROM accounts WHERE id=?', (payload.account_id,)).fetchone():
            raise HTTPException(404, 'Account not found')
        cursor = conn.execute(
            "INSERT INTO paychecks(account_id,pay_date,employer,gross_cents,net_cents,taxable_net_cents,withholding_tax_cents,bonuses_cents,benefits_cents,source_type,confidence) "
            "VALUES(?,?,?,?,?,?,?,?,?,'manual',1.0)",
            (payload.account_id, payload.pay_date.isoformat(), payload.employer, payload.gross_cents, payload.net_cents, payload.taxable_net_cents, payload.withholding_tax_cents, payload.bonuses_cents, payload.benefits_cents),
        )
        row = conn.execute('SELECT * FROM paychecks WHERE id=?', (cursor.lastrowid,)).fetchone()
    return dict(row)


@router.post('/simulate')
def simulate(payload: SimulationIn):
    with connection() as conn:
        _ready(conn)
        return simulate_purchase(conn, payload.amount_cents, payload.due_date or date.today())


@router.get('/diagnostics')
def diagnostics():
    with connection() as conn:
        _ready(conn)
        tx_count = int(conn.execute('SELECT COUNT(*) n FROM transactions').fetchone()['n'])
        account_count = int(conn.execute('SELECT COUNT(*) n FROM accounts WHERE is_active=1').fetchone()['n'])
        last_tx = conn.execute('SELECT MAX(booking_date) value FROM transactions').fetchone()['value']
        last_import = conn.execute('SELECT MAX(imported_at) value FROM transactions WHERE imported_at IS NOT NULL').fetchone()['value']
        quality = build_data_quality_report(conn)
    db_size = DB_PATH.stat().st_size if DB_PATH.exists() else 0
    commit = os.getenv('FLOW_GIT_COMMIT', '')[:12] or None
    return {
        'version': VERSION,
        'commit': commit,
        'database': {'path': str(DB_PATH), 'size_bytes': db_size, 'transactions': tx_count, 'accounts': account_count},
        'freshness': {'last_transaction': last_tx, 'last_import': last_import},
        'data_quality': quality,
        'backend': 'ok',
        'storage': 'persistent' if str(DB_PATH).startswith('/data') or 'data/' in str(DB_PATH) else 'configured',
    }
