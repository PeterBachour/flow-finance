from __future__ import annotations

from datetime import date
from math import ceil

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import connection
from .v22_migrations import ensure_v22_schema

router = APIRouter(prefix='/api/v2.2', tags=['Flow V2.2'])


class WealthAssetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    asset_type: str = Field(default='other', max_length=40)
    value_cents: int = Field(ge=0)
    debt_cents: int = Field(default=0, ge=0)
    valuation_date: date | None = None
    include_in_net_worth: bool = True
    note: str | None = Field(default=None, max_length=300)


class WealthAssetPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    asset_type: str | None = Field(default=None, max_length=40)
    value_cents: int | None = Field(default=None, ge=0)
    debt_cents: int | None = Field(default=None, ge=0)
    valuation_date: date | None = None
    include_in_net_worth: bool | None = None
    note: str | None = Field(default=None, max_length=300)


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    goal_type: str = Field(default='savings', max_length=40)
    target_cents: int = Field(gt=0)
    current_cents: int = Field(default=0, ge=0)
    target_date: date | None = None
    monthly_contribution_cents: int = Field(default=0, ge=0)
    priority: int = Field(default=100, ge=1, le=999)


class GoalPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    goal_type: str | None = Field(default=None, max_length=40)
    target_cents: int | None = Field(default=None, gt=0)
    current_cents: int | None = Field(default=None, ge=0)
    target_date: date | None = None
    monthly_contribution_cents: int | None = Field(default=None, ge=0)
    priority: int | None = Field(default=None, ge=1, le=999)
    is_active: bool | None = None


def _months_until(target: date | None, today: date) -> int | None:
    if not target:
        return None
    if target <= today:
        return 0
    return max(1, (target.year - today.year) * 12 + target.month - today.month + (1 if target.day > today.day else 0))


def _goal_view(goal: dict, allocated: int, today: date) -> dict:
    current = max(int(goal.get('current_cents') or 0), int(allocated or 0))
    target = int(goal['target_cents'])
    remaining = max(0, target - current)
    target_date = date.fromisoformat(goal['target_date']) if goal.get('target_date') else None
    months = _months_until(target_date, today)
    required = None if months is None else (remaining if months == 0 else ceil(remaining / months))
    contribution = int(goal.get('monthly_contribution_cents') or 0)
    projected = current + (contribution * months if months else 0)
    progress = 100 if target <= 0 else min(100, round(current / target * 100, 1))
    if remaining <= 0:
        probability, status = 1.0, 'achieved'
    elif months == 0:
        probability, status = 0.0, 'late'
    elif required is None:
        probability, status = None, 'no_deadline'
    elif required <= 0:
        probability, status = 1.0, 'on_track'
    else:
        ratio = contribution / required if required else 1.0
        probability = max(0.0, min(1.0, ratio))
        status = 'on_track' if ratio >= 1 else ('at_risk' if ratio >= .6 else 'off_track')
    return {
        **goal,
        'effective_current_cents': current,
        'remaining_cents': remaining,
        'months_remaining': months,
        'required_monthly_cents': required,
        'projected_at_target_cents': projected,
        'progress_pct': progress,
        'probability': None if probability is None else round(probability, 3),
        'status': status,
    }


def _account_groups(accounts: list[dict]) -> dict[str, int]:
    groups = {'cash_cents': 0, 'savings_cents': 0, 'investments_cents': 0, 'liabilities_cents': 0}
    for account in accounts:
        if not int(account.get('include_in_wealth', 1)):
            continue
        value = int(account.get('current_balance_cents') or 0)
        kind = (account.get('kind') or '').lower()
        if kind in {'checking', 'cash', 'joint'}:
            groups['cash_cents'] += value
        elif kind in {'savings', 'livret', 'ldds', 'locked_savings'}:
            groups['savings_cents'] += value
        elif kind in {'investment', 'pea', 'cto', 'life_insurance'}:
            groups['investments_cents'] += value
        elif kind in {'loan', 'debt'}:
            groups['liabilities_cents'] += abs(value)
    return groups


def _history(conn, accounts: list[dict], assets: list[dict]) -> list[dict]:
    dates = [row['d'] for row in conn.execute(
        "SELECT d FROM (SELECT DISTINCT balance_date d FROM account_balance_history UNION SELECT DISTINCT valuation_date d FROM wealth_asset_history) "
        "WHERE d IS NOT NULL ORDER BY d DESC LIMIT 60"
    ).fetchall()]
    result = []
    wealth_accounts = [a for a in accounts if int(a.get('include_in_wealth', 1))]
    wealth_assets = [a for a in assets if int(a.get('include_in_net_worth', 1))]
    for observed in sorted(dates):
        net = 0
        has_value = False
        for account in wealth_accounts:
            row = conn.execute(
                'SELECT balance_cents FROM account_balance_history WHERE account_id=? AND balance_date<=? ORDER BY balance_date DESC,id DESC LIMIT 1',
                (account['id'], observed),
            ).fetchone()
            if not row:
                continue
            has_value = True
            value = int(row['balance_cents'])
            if (account.get('kind') or '').lower() in {'loan', 'debt'}:
                net -= abs(value)
            else:
                net += value
        for asset in wealth_assets:
            row = conn.execute(
                'SELECT value_cents,debt_cents FROM wealth_asset_history WHERE asset_id=? AND valuation_date<=? ORDER BY valuation_date DESC,id DESC LIMIT 1',
                (asset['id'], observed),
            ).fetchone()
            if not row:
                continue
            has_value = True
            net += int(row['value_cents']) - int(row['debt_cents'])
        if has_value:
            result.append({'date': observed, 'net_worth_cents': net})
    return result


@router.get('/wealth')
def wealth():
    today = date.today()
    with connection() as conn:
        ensure_v22_schema(conn)
        accounts = [dict(r) for r in conn.execute('SELECT * FROM accounts WHERE is_active=1 ORDER BY id').fetchall()]
        assets = [dict(r) for r in conn.execute('SELECT * FROM wealth_assets ORDER BY asset_type,name').fetchall()]
        goals = [dict(r) for r in conn.execute('SELECT * FROM financial_goals WHERE is_active=1 ORDER BY priority,id').fetchall()]
        allocations = {r['goal_id']: int(r['total']) for r in conn.execute('SELECT goal_id,COALESCE(SUM(amount_cents),0) total FROM goal_allocations GROUP BY goal_id').fetchall()}
        history = _history(conn, accounts, assets)
    groups = _account_groups(accounts)
    physical_assets = sum(int(a['value_cents']) for a in assets if int(a['include_in_net_worth']))
    asset_debt = sum(int(a['debt_cents']) for a in assets if int(a['include_in_net_worth']))
    financial_assets = groups['cash_cents'] + groups['savings_cents'] + groups['investments_cents']
    total_assets = financial_assets + physical_assets
    total_debt = groups['liabilities_cents'] + asset_debt
    net_worth = total_assets - total_debt
    goal_views = [_goal_view(goal, allocations.get(goal['id'], 0), today) for goal in goals]
    return {
        'as_of': today.isoformat(), 'accounts': accounts, 'assets': assets, 'goals': goal_views, 'history': history,
        **groups, 'physical_assets_cents': physical_assets, 'asset_debt_cents': asset_debt,
        'total_assets_cents': total_assets, 'total_debt_cents': total_debt, 'net_worth_cents': net_worth,
    }


@router.post('/assets', status_code=201)
def create_asset(payload: WealthAssetIn):
    observed = (payload.valuation_date or date.today()).isoformat()
    with connection() as conn:
        ensure_v22_schema(conn)
        cur = conn.execute(
            'INSERT INTO wealth_assets(name,asset_type,value_cents,debt_cents,valuation_date,include_in_net_worth,note) VALUES(?,?,?,?,?,?,?)',
            (payload.name, payload.asset_type, payload.value_cents, payload.debt_cents, observed, int(payload.include_in_net_worth), payload.note),
        )
        conn.execute('INSERT OR REPLACE INTO wealth_asset_history(asset_id,valuation_date,value_cents,debt_cents) VALUES(?,?,?,?)',
                     (cur.lastrowid, observed, payload.value_cents, payload.debt_cents))
        row = conn.execute('SELECT * FROM wealth_assets WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


@router.patch('/assets/{asset_id}')
def update_asset(asset_id: int, payload: WealthAssetPatch):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, 'No changes supplied')
    observed = data.pop('valuation_date', None) or date.today()
    updates, params = [], []
    for key, value in data.items():
        if key == 'include_in_net_worth': value = int(value)
        updates.append(f'{key}=?'); params.append(value)
    updates.extend(['valuation_date=?', 'updated_at=CURRENT_TIMESTAMP']); params.append(observed.isoformat())
    params.append(asset_id)
    with connection() as conn:
        ensure_v22_schema(conn)
        if not conn.execute('SELECT 1 FROM wealth_assets WHERE id=?', (asset_id,)).fetchone():
            raise HTTPException(404, 'Asset not found')
        conn.execute(f"UPDATE wealth_assets SET {', '.join(updates)} WHERE id=?", params)
        row = conn.execute('SELECT * FROM wealth_assets WHERE id=?', (asset_id,)).fetchone()
        conn.execute('INSERT OR REPLACE INTO wealth_asset_history(asset_id,valuation_date,value_cents,debt_cents) VALUES(?,?,?,?)',
                     (asset_id, observed.isoformat(), row['value_cents'], row['debt_cents']))
    return dict(row)


@router.post('/goals', status_code=201)
def create_goal(payload: GoalIn):
    with connection() as conn:
        ensure_v22_schema(conn)
        cur = conn.execute(
            'INSERT INTO financial_goals(name,goal_type,target_cents,current_cents,target_date,monthly_contribution_cents,priority,is_active) VALUES(?,?,?,?,?,?,?,1)',
            (payload.name, payload.goal_type, payload.target_cents, payload.current_cents,
             payload.target_date.isoformat() if payload.target_date else None, payload.monthly_contribution_cents, payload.priority),
        )
        goal = dict(conn.execute('SELECT * FROM financial_goals WHERE id=?', (cur.lastrowid,)).fetchone())
    return _goal_view(goal, 0, date.today())


@router.patch('/goals/{goal_id}')
def update_goal(goal_id: int, payload: GoalPatch):
    data = payload.model_dump(exclude_unset=True)
    if not data:
        raise HTTPException(400, 'No changes supplied')
    updates, params = [], []
    for key, value in data.items():
        if isinstance(value, date): value = value.isoformat()
        if key == 'is_active': value = int(value)
        updates.append(f'{key}=?'); params.append(value)
    params.append(goal_id)
    with connection() as conn:
        ensure_v22_schema(conn)
        if not conn.execute('SELECT 1 FROM financial_goals WHERE id=?', (goal_id,)).fetchone():
            raise HTTPException(404, 'Goal not found')
        conn.execute(f"UPDATE financial_goals SET {', '.join(updates)} WHERE id=?", params)
        goal = dict(conn.execute('SELECT * FROM financial_goals WHERE id=?', (goal_id,)).fetchone())
        allocated = int(conn.execute('SELECT COALESCE(SUM(amount_cents),0) total FROM goal_allocations WHERE goal_id=?', (goal_id,)).fetchone()['total'])
    return _goal_view(goal, allocated, date.today())
