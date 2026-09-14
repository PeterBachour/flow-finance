import calendar
from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel, Field

from .db import connection
from .finance import month_key
from .financial_engine_v1 import data_freshness, financial_rule_summary, safe_account_balance_cents
from .forecast import PlannedEvent, build_forecast
from .trend_engine import spending_trend

router = APIRouter()
REALISTIC_CERTAINTIES = {'confirmed', 'expected', 'estimated'}


class SimulationV2In(BaseModel):
    amount_cents: int
    due_date: date
    label: str = Field(default='Simulation', min_length=1, max_length=180)


def _add_months(value: date, months: int) -> tuple[int, int]:
    index = value.year * 12 + value.month - 1 + months
    return index // 12, index % 12 + 1


def _recurring_events(conn, today: date, months_ahead: int = 3) -> list[PlannedEvent]:
    rows = conn.execute('SELECT * FROM recurring_transactions WHERE is_active=1 ORDER BY id').fetchall()
    events: list[PlannedEvent] = []
    for row in rows:
        for offset in range(months_ahead + 1):
            year, month = _add_months(today, offset)
            day = min(row['day_of_month'], calendar.monthrange(year, month)[1])
            due = date(year, month, day)
            if due < today:
                continue
            kind = row['kind']
            if row['category'] == 'Salaire' and row['amount_cents'] > 0:
                kind = 'salary'
            events.append(PlannedEvent(due, row['amount_cents'], row['label'], row['certainty'], kind, 'recurring'))
    return events


def _planned_events(conn, today: date) -> list[PlannedEvent]:
    rows = conn.execute("SELECT due_date,amount_cents,label,certainty,kind FROM planned_transactions WHERE status='planned' AND due_date>=? ORDER BY due_date,id", (today.isoformat(),)).fetchall()
    return [PlannedEvent(date.fromisoformat(row['due_date']), row['amount_cents'], row['label'], row['certainty'], row['kind'], 'planned') for row in rows]


def _dedupe_events(events: list[PlannedEvent]) -> list[PlannedEvent]:
    result: list[PlannedEvent] = []
    seen: set[tuple[str, int, str]] = set()
    for event in sorted(events, key=lambda e: (e.due_date, e.source == 'recurring', e.label)):
        key = (event.due_date.isoformat(), event.amount_cents, event.label.strip().upper())
        if key in seen:
            continue
        seen.add(key)
        result.append(event)
    return result


def dashboard_v2_data(extra_events: list[PlannedEvent] | None = None) -> dict:
    today = date.today()
    current_month = month_key(today)
    with connection() as conn:
        accounts = conn.execute('SELECT * FROM accounts WHERE is_active=1 ORDER BY id').fetchall()
        opening = safe_account_balance_cents(conn)
        reserve_row = conn.execute("SELECT value FROM settings WHERE key='safety_reserve_cents'").fetchone()
        configured_reserve = int(reserve_row['value']) if reserve_row else 0
        allocated = conn.execute("SELECT COALESCE(SUM(g.amount_cents),0) total FROM goal_allocations g JOIN accounts a ON a.id=g.account_id WHERE a.include_in_safe_to_spend=1").fetchone()['total']
        rules = financial_rule_summary(conn, current_month)
        reserve = max(configured_reserve, int(rules.get('minimum_reserve_cents') or 0))
        base_events = _planned_events(conn, today) + _recurring_events(conn, today)
        base_events.extend(extra_events or [])
        events = _dedupe_events(base_events)
        committed_events = [event for event in events if event.certainty == 'confirmed']
        realistic_events = [event for event in events if event.certainty in REALISTIC_CERTAINTIES]
        committed = build_forecast(today=today, opening_balance_cents=opening, events=committed_events, safety_reserve_cents=reserve, allocated_cents=allocated, rule_reserved_cents=rules['rule_reserve_cents'])
        realistic = build_forecast(today=today, opening_balance_cents=opening, events=realistic_events, safety_reserve_cents=reserve, allocated_cents=allocated, rule_reserved_cents=rules['rule_reserve_cents'])
        mk = month_key(today)
        spent = conn.execute("SELECT COALESCE(SUM(-amount_cents),0) total FROM transactions WHERE substr(booking_date,1,7)=? AND amount_cents<0 AND is_internal_transfer=0 AND COALESCE(category,'')<>'Frais professionnel remboursé'", (mk,)).fetchone()['total']
        income = conn.execute("SELECT COALESCE(SUM(amount_cents),0) total FROM transactions WHERE substr(booking_date,1,7)=? AND amount_cents>0 AND is_internal_transfer=0 AND transaction_type NOT IN ('refund','reimbursement')", (mk,)).fetchone()['total']
        freshness = data_freshness(conn, today)
        trend = spending_trend(conn, today)
    return {
        'as_of': today.isoformat(),
        'accounts': [dict(row) for row in accounts],
        'month': {'spent_cents': spent, 'income_cents': income},
        'allocated_cents': allocated,
        'financial_rules': rules,
        'data_freshness': freshness,
        'trend': trend,
        'forecast': realistic,
        'projections': {'committed': committed, 'realistic': realistic},
    }


@router.get('/api/dashboard-v2')
def dashboard_v2():
    return dashboard_v2_data()


@router.post('/api/simulations-v2')
def simulate_v2(payload: SimulationV2In):
    baseline = dashboard_v2_data()
    event = PlannedEvent(payload.due_date, payload.amount_cents, payload.label, 'confirmed', 'commitment', 'simulation')
    simulated = dashboard_v2_data([event])
    base = baseline['projections']['realistic']
    result = simulated['projections']['realistic']
    return {
        'baseline': base,
        'simulated': result,
        'impact': {
            'safe_to_spend_delta_cents': result['safe_to_spend_cents'] - base['safe_to_spend_cents'],
            'low_point_delta_cents': result['low_point']['balance_cents'] - base['low_point']['balance_cents'],
        },
    }
