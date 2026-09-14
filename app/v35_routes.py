from __future__ import annotations

from calendar import monthrange
from datetime import date

from fastapi import APIRouter, HTTPException, Query

from .db import connection
from .v32_routes import _forecast

router = APIRouter(prefix='/api/v3.5', tags=['Flow V3.5'])


def _validate_month(month: str) -> tuple[int, int]:
    try:
        y, m = map(int, month.split('-'))
        if m < 1 or m > 12:
            raise ValueError
        return y, m
    except ValueError as exc:
        raise HTTPException(400, 'Invalid month, expected YYYY-MM') from exc


def _spent_by_category(conn, month: str) -> dict[str, int]:
    rows = conn.execute(
        "SELECT COALESCE(category,'Non catégorisé') category,COALESCE(SUM(-amount_cents),0) spent "
        "FROM transactions WHERE substr(booking_date,1,7)=? AND amount_cents<0 "
        "AND COALESCE(is_internal_transfer,0)=0 AND COALESCE(exclude_from_analytics,0)=0 "
        "AND COALESCE(category,'')<>'Frais professionnel remboursé' GROUP BY COALESCE(category,'Non catégorisé')",
        (month,),
    ).fetchall()
    return {str(r['category']): int(r['spent']) for r in rows}


def _budget(conn, month: str):
    budget = conn.execute('SELECT * FROM budgets WHERE month=?', (month,)).fetchone()
    if not budget:
        return None, []
    rows = conn.execute(
        'SELECT bl.*,COALESCE(c.group_name,\'life\') group_name,COALESCE(c.budget_mode,bl.mode) category_mode '
        'FROM budget_lines bl LEFT JOIN categories c ON c.name=bl.category '
        'WHERE bl.budget_id=? ORDER BY bl.category',
        (budget['id'],),
    ).fetchall()
    return dict(budget), [dict(r) for r in rows]


@router.get('/adaptive-budget')
def adaptive_budget(month: str | None = Query(default=None, pattern=r'^\d{4}-\d{2}$')):
    today = date.today()
    month = month or today.strftime('%Y-%m')
    y, m = _validate_month(month)
    last_day = monthrange(y, m)[1]
    days_left = max(0, last_day - today.day + 1) if month == today.strftime('%Y-%m') else 0

    with connection() as conn:
        budget, lines = _budget(conn, month)
        spent = _spent_by_category(conn, month)
        forecast = _forecast(conn, 1) if month == today.strftime('%Y-%m') else None

    planned_total = sum(int(x['planned_cents']) for x in lines)
    spent_total = sum(spent.values())
    raw_remaining = max(0, planned_total - spent_total)
    safe_margin = int(forecast['months'][0]['safe_margin_cents']) if forecast and forecast['months'] else raw_remaining

    flexible = [x for x in lines if (x.get('category_mode') or x.get('mode')) == 'limit']
    flexible_remaining = sum(max(0, int(x['planned_cents']) - spent.get(x['category'], 0)) for x in flexible)
    adaptive_pool = min(flexible_remaining, max(0, safe_margin))

    out = []
    for line in lines:
        category = line['category']
        planned = int(line['planned_cents'])
        actual = int(spent.get(category, 0))
        remaining = max(0, planned - actual)
        mode = line.get('category_mode') or line.get('mode') or 'limit'
        if mode == 'limit' and flexible_remaining > 0:
            recommended = round(adaptive_pool * remaining / flexible_remaining)
        else:
            recommended = remaining
        out.append({
            'category': category,
            'mode': mode,
            'planned_cents': planned,
            'spent_cents': actual,
            'remaining_cents': remaining,
            'recommended_remaining_cents': max(0, recommended),
            'daily_allowance_cents': round(max(0, recommended) / days_left) if days_left else None,
            'status': 'over' if actual > planned and planned > 0 else ('warning' if planned > 0 and actual >= planned * .8 else 'ok'),
        })

    return {
        'month': month,
        'budget': budget,
        'days_left': days_left,
        'planned_total_cents': planned_total,
        'spent_total_cents': spent_total,
        'raw_remaining_cents': raw_remaining,
        'safe_margin_cents': safe_margin,
        'adaptive_pool_cents': adaptive_pool,
        'lines': out,
        'method': 'Le budget adaptatif conserve les montants réservés et redistribue uniquement l’enveloppe des catégories en mode limite. L’enveloppe flexible est plafonnée par la marge Safe to Spend du forecast courant.',
    }


@router.get('/closeout')
def closeout(month: str | None = Query(default=None, pattern=r'^\d{4}-\d{2}$')):
    month = month or date.today().strftime('%Y-%m')
    _validate_month(month)
    with connection() as conn:
        budget, lines = _budget(conn, month)
        spent = _spent_by_category(conn, month)
        income = int(conn.execute(
            "SELECT COALESCE(SUM(amount_cents),0) total FROM transactions WHERE substr(booking_date,1,7)=? "
            "AND amount_cents>0 AND COALESCE(is_internal_transfer,0)=0 AND transaction_type NOT IN ('refund','reimbursement')",
            (month,),
        ).fetchone()['total'])
    planned = sum(int(x['planned_cents']) for x in lines)
    actual = sum(spent.values())
    variance = planned - actual
    return {
        'month': month,
        'budget_status': budget['status'] if budget else 'missing',
        'income_cents': income,
        'planned_spend_cents': planned,
        'actual_spend_cents': actual,
        'variance_cents': variance,
        'savings_rate_pct': round(max(0, income - actual) / income * 100, 1) if income > 0 else None,
        'categories_over_budget': [
            {'category': x['category'], 'over_cents': spent.get(x['category'], 0) - int(x['planned_cents'])}
            for x in lines if spent.get(x['category'], 0) > int(x['planned_cents'])
        ],
        'method': 'Clôture analytique uniquement : aucune écriture comptable ni modification de budget n’est effectuée.',
    }
