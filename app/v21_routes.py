from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import connection
from .financial_engine_v2 import build_decision_cockpit, category_spending, data_quality, monthly_insights
from .monthly_finance import month_totals
from .v2_migrations import ensure_v2_schema

router = APIRouter(prefix='/api/v2.1', tags=['Flow V2.1'])


class CategorizationRuleIn(BaseModel):
    pattern: str = Field(min_length=2, max_length=120)
    category: str = Field(min_length=1, max_length=80)
    transaction_type: str | None = None
    priority: int = Field(default=100, ge=1, le=999)
    apply_existing: bool = True


def _month_shift(month: str, delta: int) -> str:
    try:
        y, m = map(int, month.split('-'))
        if m < 1 or m > 12:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(400, 'Invalid month, expected YYYY-MM') from exc
    idx = y * 12 + (m - 1) + delta
    return f'{idx // 12:04d}-{idx % 12 + 1:02d}'


def _avg_months(conn, month: str, count: int) -> dict[str, int | float]:
    keys = [_month_shift(month, -i) for i in range(1, count + 1)]
    rows = [month_totals(conn, key) for key in keys]
    amount_fields = (
        'income_cents', 'salary_cents', 'other_income_cents', 'spent_cents',
        'consumption_cents', 'routine_consumption_cents', 'fixed_cents',
        'variable_cents', 'saving_cents', 'exceptional_cents', 'transfers_cents',
        'unknown_cents', 'other_classified_cents', 'excluded_cents',
        'cash_outflow_cents', 'net_cents', 'cash_net_cents',
    )
    result: dict[str, int | float] = {
        field: round(sum(int(row.get(field, 0)) for row in rows) / count) if rows else 0
        for field in amount_fields
    }
    result['semantic_coverage_pct'] = (
        round(sum(float(row.get('semantic_coverage_pct', 0)) for row in rows) / count, 1)
        if rows else 0.0
    )
    return result


def _calendar(conn, today: date, horizon_days: int = 45) -> list[dict]:
    end = today + timedelta(days=horizon_days)
    events: list[dict] = []
    for row in conn.execute(
        "SELECT id,due_date,amount_cents,label,kind,certainty,'planned' source FROM planned_transactions "
        "WHERE status='planned' AND due_date BETWEEN ? AND ? ORDER BY due_date,id",
        (today.isoformat(), end.isoformat()),
    ).fetchall():
        events.append(dict(row))

    recurring = conn.execute(
        "SELECT id,label,amount_cents,day_of_month,category,kind,certainty,COALESCE(confidence_score,confidence,0.75) confidence "
        "FROM recurring_transactions WHERE is_active=1 AND COALESCE(validation_status,'confirmed')<>'rejected'"
    ).fetchall()
    cursor = date(today.year, today.month, 1)
    for _ in range(3):
        last_day = monthrange(cursor.year, cursor.month)[1]
        for row in recurring:
            due = date(cursor.year, cursor.month, min(int(row['day_of_month']), last_day))
            if today <= due <= end:
                events.append({
                    'id': row['id'], 'due_date': due.isoformat(), 'amount_cents': int(row['amount_cents']),
                    'label': row['label'], 'kind': row['kind'], 'certainty': row['certainty'],
                    'source': 'recurring', 'confidence': float(row['confidence'] or 0),
                })
        cursor = date(cursor.year + (cursor.month == 12), 1 if cursor.month == 12 else cursor.month + 1, 1)

    unique: list[dict] = []
    for event in sorted(events, key=lambda x: (x['due_date'], 0 if x['source'] == 'planned' else 1)):
        duplicate = any(
            item['due_date'] == event['due_date']
            and item['label'].strip().upper() == event['label'].strip().upper()
            and abs(int(item['amount_cents']) - int(event['amount_cents'])) <= 100
            for item in unique
        )
        if not duplicate:
            unique.append(event)
    return unique


def _running_balances(conn, events: list[dict]) -> list[dict]:
    balance = int(conn.execute(
        "SELECT COALESCE(SUM(current_balance_cents),0) total FROM accounts WHERE is_active=1 AND COALESCE(include_in_safe_to_spend,0)=1"
    ).fetchone()['total'])
    result = []
    for event in events:
        balance += int(event['amount_cents'])
        result.append({**event, 'balance_after_cents': balance})
    return result


@router.get('/cockpit')
def cockpit():
    with connection() as conn:
        ensure_v2_schema(conn)
        decision = build_decision_cockpit(conn)
        quality = data_quality(conn)
        insights = monthly_insights(conn)
        events = _running_balances(conn, _calendar(conn, date.today()))
        next_outflow = next((event for event in events if int(event['amount_cents']) < 0), None)
        structural = decision.get('next_income')
        next_income = None
        if structural:
            next_income = next((event for event in events if event['due_date'] == structural['date'] and int(event['amount_cents']) > 0), None)
            if next_income is None:
                next_income = {**structural, 'due_date': structural['date'], 'source': 'forecast'}
    return {
        'decision': decision,
        'calendar': events,
        'next_outflow': next_outflow,
        'next_income': next_income,
        'quality': quality,
        'insights': insights,
        'generated_for': date.today().isoformat(),
    }


@router.get('/months/{month}')
def month_dashboard(month: str):
    _month_shift(month, 0)
    today = date.today()
    current_key = today.strftime('%Y-%m')
    with connection() as conn:
        ensure_v2_schema(conn)
        current = month_totals(conn, month)
        previous = month_totals(conn, _month_shift(month, -1))
        average_3m = _avg_months(conn, month, 3)
        average_6m = _avg_months(conn, month, 6)
        categories = category_spending(conn, month)
        projected = None
        if month == current_key:
            projected = int(build_decision_cockpit(conn, today)['forecast']['closing_balance_cents'])
    return {
        'month': month,
        'current': {**current, 'projected_close_cents': projected},
        'previous': previous,
        'average_3m': average_3m,
        'average_6m': average_6m,
        'categories': categories,
    }


@router.get('/quality')
def quality():
    with connection() as conn:
        ensure_v2_schema(conn)
        return data_quality(conn)


@router.get('/categorization-rules')
def categorization_rules():
    with connection() as conn:
        rows = conn.execute('SELECT * FROM categorization_rules ORDER BY priority,id').fetchall()
    return [dict(row) for row in rows]


@router.post('/categorization-rules', status_code=201)
def create_categorization_rule(payload: CategorizationRuleIn):
    pattern = payload.pattern.strip().upper()
    with connection() as conn:
        category = conn.execute('SELECT name FROM categories WHERE name=? AND is_active=1', (payload.category,)).fetchone()
        if not category:
            raise HTTPException(400, 'Unknown category')
        cursor = conn.execute(
            'INSERT INTO categorization_rules(pattern,category,transaction_type,priority,is_active) VALUES(?,?,?,?,1)',
            (pattern, payload.category, payload.transaction_type, payload.priority),
        )
        updated = 0
        if payload.apply_existing:
            params: list[object] = [payload.category]
            sql = "UPDATE transactions SET category=?"
            if payload.transaction_type:
                sql += ',transaction_type=?'; params.append(payload.transaction_type)
            sql += " WHERE UPPER(label) LIKE ? AND COALESCE(is_internal_transfer,0)=0"
            params.append(f'%{pattern}%')
            updated = conn.execute(sql, params).rowcount
        row = conn.execute('SELECT * FROM categorization_rules WHERE id=?', (cursor.lastrowid,)).fetchone()
    return {**dict(row), 'updated_transactions': updated}
