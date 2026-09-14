from __future__ import annotations

from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import connection
from .v22_migrations import ensure_v22_schema
from .v22_routes import _goal_view

router = APIRouter(prefix='/api/v4.10', tags=['Flow V4.10'])


class GoalProgressIn(BaseModel):
    current_cents: int = Field(ge=0)
    monthly_contribution_cents: int | None = Field(default=None, ge=0)
    target_date: date | None = None
    confirmation: str = Field(pattern='^METTRE_A_JOUR$')


def ensure_v410_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS goal_progress_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            goal_id INTEGER NOT NULL REFERENCES financial_goals(id) ON DELETE CASCADE,
            observed_on TEXT NOT NULL,
            current_cents INTEGER NOT NULL,
            target_cents INTEGER NOT NULL,
            monthly_contribution_cents INTEGER NOT NULL DEFAULT 0,
            target_date TEXT,
            source_type TEXT NOT NULL DEFAULT 'manual',
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(goal_id, observed_on)
        );
        CREATE INDEX IF NOT EXISTS idx_goal_progress_history_goal_date
            ON goal_progress_history(goal_id, observed_on DESC);
        """
    )


def _age_days(value: str | None, today: date) -> int | None:
    if not value:
        return None
    try:
        return (today - date.fromisoformat(value[:10])).days
    except ValueError:
        return None


def _goal_rows(conn, today: date) -> list[dict]:
    ensure_v410_schema(conn)
    goals = [dict(row) for row in conn.execute(
        'SELECT * FROM financial_goals WHERE is_active=1 ORDER BY priority,id'
    ).fetchall()]
    allocations = {
        int(row['goal_id']): int(row['total'] or 0)
        for row in conn.execute(
            'SELECT goal_id,COALESCE(SUM(amount_cents),0) total FROM goal_allocations GROUP BY goal_id'
        ).fetchall()
    }
    output = []
    for goal in goals:
        view = _goal_view(goal, allocations.get(int(goal['id']), 0), today)
        history = [dict(row) for row in conn.execute(
            '''SELECT observed_on,current_cents,target_cents,monthly_contribution_cents,target_date,source_type
               FROM goal_progress_history WHERE goal_id=? ORDER BY observed_on DESC,id DESC LIMIT 12''',
            (goal['id'],),
        ).fetchall()]
        view['history'] = history
        view['history_count'] = len(history)
        output.append(view)
    return output


@router.get('/wealth-readiness')
def wealth_readiness():
    today = date.today()
    with connection() as conn:
        ensure_v22_schema(conn)
        ensure_v410_schema(conn)
        accounts = [dict(row) for row in conn.execute(
            '''SELECT id,name,kind,current_balance_cents,balance_as_of,include_in_wealth
               FROM accounts WHERE is_active=1 ORDER BY name'''
        ).fetchall()]
        goals = _goal_rows(conn, today)

    wealth_accounts = [a for a in accounts if int(a.get('include_in_wealth', 1)) != 0]
    fresh, stale, undated = [], [], []
    for account in wealth_accounts:
        age = _age_days(account.get('balance_as_of'), today)
        item = {**account, 'age_days': age}
        if age is None:
            item['freshness'] = 'undated'
            undated.append(item)
        elif age > 31:
            item['freshness'] = 'stale'
            stale.append(item)
        else:
            item['freshness'] = 'fresh'
            fresh.append(item)

    goal_attention = [g for g in goals if g.get('status') in {'at_risk', 'off_track', 'late'}]
    return {
        'as_of': today.isoformat(),
        'freshness_rule_days': 31,
        'accounts': {'fresh': fresh, 'stale': stale, 'undated': undated},
        'summary': {
            'wealth_accounts': len(wealth_accounts),
            'fresh_accounts': len(fresh),
            'stale_accounts': len(stale),
            'undated_accounts': len(undated),
            'goal_count': len(goals),
            'goals_needing_attention': len(goal_attention),
        },
        'goals': goals,
        'principle': 'Une valeur patrimoniale est considérée fraîche pendant 31 jours. Une valeur ancienne reste visible mais est signalée comme à actualiser.',
    }


@router.post('/goals/{goal_id}/progress')
def update_goal_progress(goal_id: int, payload: GoalProgressIn):
    observed = date.today().isoformat()
    with connection() as conn:
        ensure_v22_schema(conn)
        ensure_v410_schema(conn)
        goal = conn.execute('SELECT * FROM financial_goals WHERE id=? AND is_active=1', (goal_id,)).fetchone()
        if not goal:
            raise HTTPException(404, 'Objectif introuvable')

        monthly = int(payload.monthly_contribution_cents) if payload.monthly_contribution_cents is not None else int(goal['monthly_contribution_cents'] or 0)
        target_date = payload.target_date.isoformat() if payload.target_date else goal['target_date']
        conn.execute(
            'UPDATE financial_goals SET current_cents=?,monthly_contribution_cents=?,target_date=? WHERE id=?',
            (payload.current_cents, monthly, target_date, goal_id),
        )
        refreshed = dict(conn.execute('SELECT * FROM financial_goals WHERE id=?', (goal_id,)).fetchone())
        conn.execute(
            '''INSERT INTO goal_progress_history(
                 goal_id,observed_on,current_cents,target_cents,monthly_contribution_cents,target_date,source_type
               ) VALUES(?,?,?,?,?,?, 'manual')
               ON CONFLICT(goal_id,observed_on) DO UPDATE SET
                 current_cents=excluded.current_cents,
                 target_cents=excluded.target_cents,
                 monthly_contribution_cents=excluded.monthly_contribution_cents,
                 target_date=excluded.target_date,
                 source_type='manual' ''',
            (goal_id, observed, payload.current_cents, refreshed['target_cents'], monthly, target_date),
        )
        allocated = int(conn.execute(
            'SELECT COALESCE(SUM(amount_cents),0) total FROM goal_allocations WHERE goal_id=?', (goal_id,)
        ).fetchone()['total'])
        view = _goal_view(refreshed, allocated, date.today())
        view['history'] = [dict(row) for row in conn.execute(
            '''SELECT observed_on,current_cents,target_cents,monthly_contribution_cents,target_date,source_type
               FROM goal_progress_history WHERE goal_id=? ORDER BY observed_on DESC,id DESC LIMIT 12''',
            (goal_id,),
        ).fetchall()]
    return view
