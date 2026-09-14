from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Query

from .db import connection
from .v2_migrations import ensure_v2_schema
from .v22_migrations import ensure_v22_schema
from .v36_routes import decision_inbox

router = APIRouter(prefix='/api/v4.6', tags=['Flow V4.6'])


def _period_start(as_of: date, period: str) -> date:
    days = {'30d': 29, '3m': 91, '6m': 182, '12m': 365}.get(period, 29)
    return as_of - timedelta(days=days)


def _movement_filters(*, start: date, end: date, q: str, category: str | None, account_id: int | None,
                      min_cents: int | None, max_cents: int | None, flow_type: str) -> tuple[str, list[object]]:
    clauses = ['t.booking_date>=?', 't.booking_date<=?', "COALESCE(t.status,'confirmed')='confirmed'"]
    params: list[object] = [start.isoformat(), end.isoformat()]
    if q.strip():
        clauses.append("(t.label LIKE ? OR COALESCE(t.user_label,'') LIKE ? OR COALESCE(t.category,'') LIKE ? OR a.name LIKE ?)")
        pattern = f"%{q.strip()}%"
        params += [pattern, pattern, pattern, pattern]
    if category:
        clauses.append("COALESCE(t.category,'')=?")
        params.append(category)
    if account_id is not None:
        clauses.append('t.account_id=?')
        params.append(account_id)
    if min_cents is not None:
        clauses.append('ABS(t.amount_cents)>=?')
        params.append(abs(min_cents))
    if max_cents is not None:
        clauses.append('ABS(t.amount_cents)<=?')
        params.append(abs(max_cents))
    if flow_type == 'expense':
        clauses += ['t.amount_cents<0', 'COALESCE(t.is_internal_transfer,0)=0', 'COALESCE(t.exclude_from_analytics,0)=0']
    elif flow_type == 'income':
        clauses += ['t.amount_cents>0', 'COALESCE(t.is_internal_transfer,0)=0', 'COALESCE(t.exclude_from_analytics,0)=0']
    elif flow_type == 'transfer':
        clauses.append('COALESCE(t.is_internal_transfer,0)=1')
    elif flow_type == 'exceptional':
        clauses.append('COALESCE(t.is_exceptional,0)=1')
    elif flow_type == 'uncategorized':
        clauses += ["COALESCE(t.category,'')=''", 'COALESCE(t.is_internal_transfer,0)=0']
    return ' AND '.join(clauses), params


def _summary(conn, where: str, params: list[object]) -> dict:
    row = conn.execute(
        f"""SELECT COUNT(*) total,
        COALESCE(SUM(CASE WHEN t.amount_cents<0 AND COALESCE(t.is_internal_transfer,0)=0 AND COALESCE(t.exclude_from_analytics,0)=0 THEN -t.amount_cents ELSE 0 END),0) expenses_cents,
        COALESCE(SUM(CASE WHEN t.amount_cents>0 AND COALESCE(t.is_internal_transfer,0)=0 AND COALESCE(t.exclude_from_analytics,0)=0 THEN t.amount_cents ELSE 0 END),0) income_cents,
        COALESCE(SUM(CASE WHEN COALESCE(t.is_internal_transfer,0)=1 THEN ABS(t.amount_cents) ELSE 0 END),0) transfers_cents,
        COALESCE(SUM(CASE WHEN COALESCE(t.category,'')='' AND COALESCE(t.is_internal_transfer,0)=0 THEN 1 ELSE 0 END),0) uncategorized,
        COALESCE(SUM(CASE WHEN COALESCE(t.is_exceptional,0)=1 THEN 1 ELSE 0 END),0) exceptional
        FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE {where}""",
        params,
    ).fetchone()
    result = dict(row)
    expense_count = int(conn.execute(
        f"SELECT COUNT(*) n FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE {where} AND t.amount_cents<0 AND COALESCE(t.is_internal_transfer,0)=0 AND COALESCE(t.exclude_from_analytics,0)=0",
        params,
    ).fetchone()['n'])
    result['expense_count'] = expense_count
    result['average_expense_cents'] = round(int(result['expenses_cents']) / expense_count) if expense_count else 0
    result['net_cents'] = int(result['income_cents']) - int(result['expenses_cents'])
    return result


@router.get('/movements/analysis')
def movement_analysis(
    period: str = Query(default='30d', pattern='^(30d|3m|6m|12m)$'),
    as_of: date | None = None,
    q: str = '',
    category: str | None = None,
    account_id: int | None = None,
    min_cents: int | None = None,
    max_cents: int | None = None,
    flow_type: str = Query(default='all', pattern='^(all|expense|income|transfer|exceptional|uncategorized)$'),
    sort: str = Query(default='date_desc', pattern='^(date_desc|date_asc|amount_desc|amount_asc)$'),
    limit: int = Query(default=200, ge=1, le=500),
):
    end = as_of or date.today()
    start = _period_start(end, period)
    where, params = _movement_filters(start=start, end=end, q=q, category=category, account_id=account_id,
                                      min_cents=min_cents, max_cents=max_cents, flow_type=flow_type)
    order = {
        'date_desc': 't.booking_date DESC,t.id DESC', 'date_asc': 't.booking_date,t.id',
        'amount_desc': 'ABS(t.amount_cents) DESC,t.booking_date DESC',
        'amount_asc': 'ABS(t.amount_cents),t.booking_date DESC',
    }[sort]
    with connection() as conn:
        ensure_v2_schema(conn)
        summary = _summary(conn, where, params)
        category_rows = conn.execute(
            f"""SELECT COALESCE(NULLIF(t.category,''),'À catégoriser') category,
            SUM(-t.amount_cents) amount_cents,COUNT(*) count
            FROM transactions t JOIN accounts a ON a.id=t.account_id
            WHERE {where} AND t.amount_cents<0 AND COALESCE(t.is_internal_transfer,0)=0 AND COALESCE(t.exclude_from_analytics,0)=0
            GROUP BY COALESCE(NULLIF(t.category,''),'À catégoriser') ORDER BY amount_cents DESC LIMIT 12""",
            params,
        ).fetchall()
        rows = conn.execute(
            f"SELECT t.*,a.name account_name FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE {where} ORDER BY {order} LIMIT ?",
            params + [limit],
        ).fetchall()
        accounts = [dict(r) for r in conn.execute('SELECT id,name,kind FROM accounts WHERE is_active=1 ORDER BY name').fetchall()]
        categories = [r['name'] for r in conn.execute('SELECT name FROM categories WHERE is_active=1 ORDER BY name').fetchall()]

        span = (end - start).days + 1
        previous_end = start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=span - 1)
        prev_where, prev_params = _movement_filters(start=previous_start, end=previous_end, q=q, category=category,
                                                     account_id=account_id, min_cents=min_cents, max_cents=max_cents,
                                                     flow_type=flow_type)
        previous = _summary(conn, prev_where, prev_params)

    expenses = int(summary['expenses_cents'])
    previous_expenses = int(previous['expenses_cents'])
    delta_pct = None if previous_expenses == 0 else round((expenses - previous_expenses) / previous_expenses * 100, 1)
    cats = [dict(r) for r in category_rows]
    return {
        'period': period, 'date_from': start.isoformat(), 'date_to': end.isoformat(),
        'summary': summary,
        'comparison': {'previous_date_from': previous_start.isoformat(), 'previous_date_to': previous_end.isoformat(),
                       'previous_expenses_cents': previous_expenses, 'expense_delta_cents': expenses - previous_expenses,
                       'expense_delta_pct': delta_pct},
        'top_category': cats[0] if cats else None,
        'categories': cats, 'rows': [dict(r) for r in rows],
        'filters': {'accounts': accounts, 'categories': categories},
    }


@router.get('/wealth/quality')
def wealth_quality(as_of: date | None = None):
    today = as_of or date.today()
    with connection() as conn:
        ensure_v22_schema(conn)
        accounts = [dict(r) for r in conn.execute(
            'SELECT id,name,kind,current_balance_cents,balance_as_of,include_in_wealth FROM accounts WHERE is_active=1 ORDER BY name'
        ).fetchall()]
    included = [a for a in accounts if int(a.get('include_in_wealth', 1))]
    stale = []
    undated = []
    for account in included:
        if not account.get('balance_as_of'):
            undated.append(account)
            continue
        try:
            age = (today - date.fromisoformat(account['balance_as_of'])).days
        except ValueError:
            undated.append(account)
            continue
        if age > 31:
            stale.append({**account, 'age_days': age})
    return {
        'as_of': today.isoformat(), 'included_accounts': len(included),
        'stale_accounts': stale, 'undated_accounts': undated,
        'fresh_accounts': len(included) - len(stale) - len(undated),
        'status': 'fresh' if not stale and not undated else 'review',
    }


@router.get('/decisions')
def financial_decisions(include_closed: bool = False):
    """Expose only decisions that can change a financial choice.

    Import/categorisation reviews stay in data-quality workflows and are counted
    separately instead of flooding the decision center.
    """
    inbox = decision_inbox(include_closed=include_closed)
    excluded_types = {'import_review'}
    items = [item for item in inbox.get('items', []) if item.get('type') not in excluded_types]
    with connection() as conn:
        try:
            quality_reviews = int(conn.execute(
                "SELECT COUNT(*) n FROM transaction_import_meta WHERE review_status='needs_review'"
            ).fetchone()['n'])
        except Exception:
            quality_reviews = 0
    return {
        'items': items,
        'open_count': sum(1 for item in items if item.get('status') == 'open'),
        'quality_review_count': quality_reviews,
        'method': 'Les décisions financières sont séparées des tâches de qualité de données. Les mouvements à catégoriser restent dans Mouvements.',
    }
