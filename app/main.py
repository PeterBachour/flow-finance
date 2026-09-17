from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .db import connection, init_db
from .finance import budget_status, goal_summary, month_key
from .forecast import PlannedEvent, build_forecast
from .notion_import import bootstrap_if_needed
from .update_routes import router as update_router
from .version import VERSION
from .workspace_routes import router as workspace_router

STATIC = Path(__file__).parent / 'static'
VALID_CERTAINTY = {'confirmed', 'expected', 'estimated'}
VALID_BUDGET_MODES = {'reserved', 'limit', 'tracking_only'}


class AccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = 'checking'
    current_balance_cents: int = 0
    currency: str = 'EUR'


class TransactionIn(BaseModel):
    account_id: int
    booking_date: date
    amount_cents: int
    label: str = Field(min_length=1, max_length=180)
    category: str | None = None
    transaction_type: str = 'expense'
    is_internal_transfer: bool = False


class PlannedIn(BaseModel):
    account_id: int
    due_date: date
    amount_cents: int
    label: str = Field(min_length=1, max_length=180)
    kind: str = 'commitment'
    certainty: str = 'confirmed'


class ReserveIn(BaseModel):
    safety_reserve_cents: int = Field(ge=0)


class CategoryIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    group_name: str = 'life'
    budget_mode: str = 'limit'


class RuleIn(BaseModel):
    pattern: str = Field(min_length=1, max_length=120)
    category: str
    transaction_type: str | None = None
    priority: int = 100


class RecurringIn(BaseModel):
    account_id: int
    label: str = Field(min_length=1, max_length=180)
    amount_cents: int
    day_of_month: int = Field(ge=1, le=31)
    category: str | None = None
    kind: str = 'commitment'
    certainty: str = 'expected'
    tolerance_cents: int = Field(default=0, ge=0)


class BudgetLineIn(BaseModel):
    category: str
    planned_cents: int = Field(ge=0)
    mode: str = 'limit'


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    target_cents: int = Field(gt=0)
    target_date: date | None = None
    priority: int = 100


class AllocationIn(BaseModel):
    account_id: int | None = None
    amount_cents: int = Field(gt=0)
    allocated_on: date
    note: str | None = Field(default=None, max_length=180)


class SimulationIn(BaseModel):
    amount_cents: int
    due_date: date
    label: str = 'Simulation'


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    bootstrap_if_needed()
    yield


app = FastAPI(title='Flow Finance', version=VERSION, lifespan=lifespan)
app.mount('/static', StaticFiles(directory=STATIC), name='static')
app.include_router(workspace_router)
app.include_router(update_router)


@app.get('/')
def index():
    return FileResponse(STATIC / 'index.html')


@app.get('/manifest.webmanifest')
def manifest():
    return FileResponse(STATIC / 'manifest.webmanifest', media_type='application/manifest+json')


@app.get('/sw.js')
def service_worker():
    return FileResponse(STATIC / 'sw.js', media_type='application/javascript')


@app.get('/api/health')
def health():
    return {'status': 'ok', 'version': VERSION}


@app.get('/api/accounts')
def list_accounts():
    with connection() as conn:
        rows = conn.execute('SELECT * FROM accounts WHERE is_active=1 ORDER BY id').fetchall()
    return [dict(r) for r in rows]


@app.post('/api/accounts', status_code=201)
def create_account(payload: AccountIn):
    with connection() as conn:
        cur = conn.execute('INSERT INTO accounts(name,kind,current_balance_cents,currency) VALUES(?,?,?,?)', (payload.name,payload.kind,payload.current_balance_cents,payload.currency))
        row = conn.execute('SELECT * FROM accounts WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


@app.get('/api/categories')
def list_categories():
    with connection() as conn:
        rows = conn.execute('SELECT * FROM categories WHERE is_active=1 ORDER BY group_name,name').fetchall()
    return [dict(r) for r in rows]


@app.post('/api/categories', status_code=201)
def create_category(payload: CategoryIn):
    if payload.budget_mode not in VALID_BUDGET_MODES:
        raise HTTPException(400, 'Invalid budget mode')
    try:
        with connection() as conn:
            cur = conn.execute('INSERT INTO categories(name,group_name,budget_mode) VALUES(?,?,?)', (payload.name,payload.group_name,payload.budget_mode))
            row = conn.execute('SELECT * FROM categories WHERE id=?', (cur.lastrowid,)).fetchone()
        return dict(row)
    except Exception as exc:
        if 'UNIQUE' in str(exc):
            raise HTTPException(409, 'Category already exists') from exc
        raise


@app.get('/api/rules')
def list_rules():
    with connection() as conn:
        rows = conn.execute('SELECT * FROM categorization_rules WHERE is_active=1 ORDER BY priority,id').fetchall()
    return [dict(r) for r in rows]


@app.post('/api/rules', status_code=201)
def create_rule(payload: RuleIn):
    with connection() as conn:
        cur = conn.execute('INSERT INTO categorization_rules(pattern,category,transaction_type,priority) VALUES(?,?,?,?)', (payload.pattern.upper(),payload.category,payload.transaction_type,payload.priority))
        row = conn.execute('SELECT * FROM categorization_rules WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


@app.get('/api/transactions')
def list_transactions(limit: int = 100):
    limit = min(max(limit, 1), 500)
    with connection() as conn:
        rows = conn.execute('SELECT t.*,a.name account_name FROM transactions t JOIN accounts a ON a.id=t.account_id ORDER BY booking_date DESC,t.id DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in rows]


@app.post('/api/transactions', status_code=201)
def create_transaction(payload: TransactionIn):
    with connection() as conn:
        if not conn.execute('SELECT 1 FROM accounts WHERE id=?', (payload.account_id,)).fetchone():
            raise HTTPException(404, 'Account not found')
        category = payload.category
        transaction_type = payload.transaction_type
        if not category:
            rules = conn.execute('SELECT * FROM categorization_rules WHERE is_active=1 ORDER BY priority,id').fetchall()
            label = payload.label.upper()
            match = next((r for r in rules if r['pattern'] in label), None)
            if match:
                category = match['category']
                transaction_type = match['transaction_type'] or transaction_type
        cur = conn.execute('INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer) VALUES(?,?,?,?,?,?,?)', (payload.account_id,payload.booking_date.isoformat(),payload.amount_cents,payload.label,category,transaction_type,int(payload.is_internal_transfer)))
        conn.execute('UPDATE accounts SET current_balance_cents=current_balance_cents+? WHERE id=?', (payload.amount_cents,payload.account_id))
        row = conn.execute('SELECT * FROM transactions WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


@app.get('/api/planned')
def list_planned():
    with connection() as conn:
        rows = conn.execute("SELECT p.*,a.name account_name FROM planned_transactions p JOIN accounts a ON a.id=p.account_id WHERE status='planned' ORDER BY due_date,p.id").fetchall()
    return [dict(r) for r in rows]


@app.post('/api/planned', status_code=201)
def create_planned(payload: PlannedIn):
    if payload.certainty not in VALID_CERTAINTY:
        raise HTTPException(400, 'Invalid certainty')
    with connection() as conn:
        if not conn.execute('SELECT 1 FROM accounts WHERE id=?', (payload.account_id,)).fetchone():
            raise HTTPException(404, 'Account not found')
        cur = conn.execute('INSERT INTO planned_transactions(account_id,due_date,amount_cents,label,kind,certainty) VALUES(?,?,?,?,?,?)', (payload.account_id,payload.due_date.isoformat(),payload.amount_cents,payload.label,payload.kind,payload.certainty))
        row = conn.execute('SELECT * FROM planned_transactions WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


@app.get('/api/recurring')
def list_recurring():
    with connection() as conn:
        rows = conn.execute('SELECT * FROM recurring_transactions WHERE is_active=1 ORDER BY day_of_month,id').fetchall()
    return [dict(r) for r in rows]


@app.post('/api/recurring', status_code=201)
def create_recurring(payload: RecurringIn):
    if payload.certainty not in VALID_CERTAINTY:
        raise HTTPException(400, 'Invalid certainty')
    with connection() as conn:
        if not conn.execute('SELECT 1 FROM accounts WHERE id=?', (payload.account_id,)).fetchone():
            raise HTTPException(404, 'Account not found')
        cur = conn.execute('INSERT INTO recurring_transactions(account_id,label,amount_cents,day_of_month,category,kind,certainty,tolerance_cents) VALUES(?,?,?,?,?,?,?,?)', (payload.account_id,payload.label,payload.amount_cents,payload.day_of_month,payload.category,payload.kind,payload.certainty,payload.tolerance_cents))
        row = conn.execute('SELECT * FROM recurring_transactions WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


@app.put('/api/settings/reserve')
def set_reserve(payload: ReserveIn):
    with connection() as conn:
        conn.execute("INSERT INTO settings(key,value) VALUES('safety_reserve_cents',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (str(payload.safety_reserve_cents),))
    return payload


@app.get('/api/budgets/{month}')
def get_budget(month: str):
    with connection() as conn:
        budget = conn.execute('SELECT * FROM budgets WHERE month=?', (month,)).fetchone()
        if not budget:
            return {'month': month, 'status': 'draft', 'lines': []}
        rows = conn.execute('SELECT * FROM budget_lines WHERE budget_id=? ORDER BY category', (budget['id'],)).fetchall()
        result = []
        for row in rows:
            spent = conn.execute("SELECT COALESCE(SUM(-amount_cents),0) total FROM transactions WHERE substr(booking_date,1,7)=? AND category=? AND amount_cents<0 AND is_internal_transfer=0", (month,row['category'])).fetchone()['total']
            result.append({'category': row['category'], **budget_status(row['planned_cents'],spent,row['mode'])})
    return {'month': month, 'status': budget['status'], 'lines': result}


@app.post('/api/budgets/{month}/lines')
def upsert_budget_line(month: str, payload: BudgetLineIn):
    if payload.mode not in VALID_BUDGET_MODES:
        raise HTTPException(400, 'Invalid budget mode')
    with connection() as conn:
        conn.execute('INSERT INTO budgets(month) VALUES(?) ON CONFLICT(month) DO NOTHING', (month,))
        budget_id = conn.execute('SELECT id FROM budgets WHERE month=?', (month,)).fetchone()['id']
        conn.execute('INSERT INTO budget_lines(budget_id,category,planned_cents,mode) VALUES(?,?,?,?) ON CONFLICT(budget_id,category) DO UPDATE SET planned_cents=excluded.planned_cents,mode=excluded.mode', (budget_id,payload.category,payload.planned_cents,payload.mode))
    return get_budget(month)


@app.get('/api/goals')
def list_goals():
    today = date.today()
    with connection() as conn:
        goals = conn.execute('SELECT * FROM financial_goals WHERE is_active=1 ORDER BY priority,id').fetchall()
        result = []
        for row in goals:
            allocated = conn.execute('SELECT COALESCE(SUM(amount_cents),0) total FROM goal_allocations WHERE goal_id=?', (row['id'],)).fetchone()['total']
            result.append(goal_summary(dict(row), allocated, today))
    return result


@app.post('/api/goals', status_code=201)
def create_goal(payload: GoalIn):
    with connection() as conn:
        cur = conn.execute('INSERT INTO financial_goals(name,target_cents,target_date,priority) VALUES(?,?,?,?)', (payload.name,payload.target_cents,payload.target_date.isoformat() if payload.target_date else None,payload.priority))
        row = conn.execute('SELECT * FROM financial_goals WHERE id=?', (cur.lastrowid,)).fetchone()
    return goal_summary(dict(row), 0, date.today())


@app.post('/api/goals/{goal_id}/allocations', status_code=201)
def allocate_goal(goal_id: int, payload: AllocationIn):
    with connection() as conn:
        if not conn.execute('SELECT 1 FROM financial_goals WHERE id=?', (goal_id,)).fetchone():
            raise HTTPException(404, 'Goal not found')
        if payload.account_id and not conn.execute('SELECT 1 FROM accounts WHERE id=?', (payload.account_id,)).fetchone():
            raise HTTPException(404, 'Account not found')
        cur = conn.execute('INSERT INTO goal_allocations(goal_id,account_id,amount_cents,allocated_on,note) VALUES(?,?,?,?,?)', (goal_id,payload.account_id,payload.amount_cents,payload.allocated_on.isoformat(),payload.note))
        row = conn.execute('SELECT * FROM goal_allocations WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


def dashboard_data(extra_events: list[PlannedEvent] | None = None) -> dict:
    today = date.today()
    with connection() as conn:
        accounts = conn.execute('SELECT * FROM accounts WHERE is_active=1 ORDER BY id').fetchall()
        opening = sum(r['current_balance_cents'] for r in accounts if r['kind'] in {'checking','cash'})
        reserve_row = conn.execute("SELECT value FROM settings WHERE key='safety_reserve_cents'").fetchone()
        reserve = int(reserve_row['value']) if reserve_row else 0
        rows = conn.execute("SELECT due_date,amount_cents,label,certainty FROM planned_transactions WHERE status='planned' AND due_date>=? ORDER BY due_date", (today.isoformat(),)).fetchall()
        events = [PlannedEvent(date.fromisoformat(r['due_date']),r['amount_cents'],r['label'],r['certainty']) for r in rows]
        events.extend(extra_events or [])
        allocated = conn.execute('SELECT COALESCE(SUM(amount_cents),0) total FROM goal_allocations').fetchone()['total']
        forecast = build_forecast(
            today=today,
            opening_balance_cents=opening,
            events=events,
            safety_reserve_cents=reserve,
            allocated_cents=allocated,
        )
        mk = month_key(today)
        spent = conn.execute("SELECT COALESCE(SUM(-amount_cents),0) total FROM transactions WHERE substr(booking_date,1,7)=? AND amount_cents<0 AND is_internal_transfer=0", (mk,)).fetchone()['total']
        income = conn.execute("SELECT COALESCE(SUM(amount_cents),0) total FROM transactions WHERE substr(booking_date,1,7)=? AND amount_cents>0 AND is_internal_transfer=0", (mk,)).fetchone()['total']
    return {'as_of': today.isoformat(), 'accounts': [dict(r) for r in accounts], 'month': {'spent_cents': spent, 'income_cents': income}, 'allocated_cents': allocated, 'forecast': forecast}


@app.get('/api/dashboard')
def dashboard():
    return dashboard_data()


@app.post('/api/simulations')
def simulate(payload: SimulationIn):
    baseline = dashboard_data()
    simulated = dashboard_data([PlannedEvent(payload.due_date,payload.amount_cents,payload.label,'confirmed')])
    return {
        'baseline': baseline['forecast'],
        'simulated': simulated['forecast'],
        'impact': {
            'safe_to_spend_delta_cents': simulated['forecast']['safe_to_spend_cents'] - baseline['forecast']['safe_to_spend_cents'],
            'low_point_delta_cents': simulated['forecast']['low_point']['balance_cents'] - baseline['forecast']['low_point']['balance_cents'],
        },
    }