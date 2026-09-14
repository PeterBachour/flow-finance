from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .db import connection
from .finance import goal_summary
from .financial_routes import router as financial_router
from .statement_corpus_routes import router as statement_corpus_router
from .import_routes import router as import_router
from .month_prep_routes import router as month_prep_router
from .onboarding_routes import router as onboarding_router
from .projection_routes import router as projection_router
from .recurring_routes import router as recurring_router
from .scenario_routes import router as scenario_router
from .v2_routes import router as v2_router
from .v21_routes import router as v21_router
from .v22_routes import router as v22_router
from .v23_routes import router as v23_router
from .v24_routes import router as v24_router
from .v3_routes import router as v3_router
from .v31_routes import router as v31_router
from .v32_routes import router as v32_router
from .v33_routes import router as v33_router
from .v34_routes import router as v34_router
from .v35_routes import router as v35_router
from .v36_routes import router as v36_router
from .v37_routes import router as v37_router
from .v38_routes import router as v38_router
from .v46_routes import router as v46_router
from .v47_routes import router as v47_router
from .v48_routes import router as v48_router
from .v49_routes import router as v49_router
from .v410_routes import router as v410_router
from .v411_routes import router as v411_router
from .v5_routes import router as v5_router
from .v55_routes import router as v55_router
from .v57_routes import router as v57_router

router = APIRouter()
router.include_router(financial_router)
router.include_router(statement_corpus_router)
router.include_router(import_router)
router.include_router(recurring_router)
router.include_router(projection_router)
router.include_router(month_prep_router)
router.include_router(scenario_router)
router.include_router(onboarding_router)
router.include_router(v2_router)
router.include_router(v21_router)
router.include_router(v22_router)
router.include_router(v23_router)
router.include_router(v24_router)
router.include_router(v3_router)
router.include_router(v31_router)
router.include_router(v32_router)
router.include_router(v33_router)
router.include_router(v34_router)
router.include_router(v35_router)
router.include_router(v36_router)
router.include_router(v37_router)
router.include_router(v38_router)
router.include_router(v46_router)
router.include_router(v47_router)
router.include_router(v48_router)
router.include_router(v49_router)
router.include_router(v410_router)
router.include_router(v411_router)
router.include_router(v5_router)
router.include_router(v55_router)
router.include_router(v57_router)


class BalanceIn(BaseModel):
    current_balance_cents: int
    balance_as_of: date | None = None


class LedgerTransactionIn(BaseModel):
    account_id: int
    booking_date: date
    amount_cents: int
    label: str = Field(min_length=1, max_length=180)
    category: str | None = None
    transaction_type: str | None = None
    is_internal_transfer: bool = False


@router.put('/api/accounts/{account_id}/balance')
def set_account_balance(account_id: int, payload: BalanceIn):
    observed = (payload.balance_as_of or date.today()).isoformat()
    with connection() as conn:
        account = conn.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()
        if not account:
            raise HTTPException(404, 'Account not found')
        conn.execute('UPDATE accounts SET current_balance_cents=?,balance_as_of=? WHERE id=?', (payload.current_balance_cents, observed, account_id))
        source_key = f'manual-balance:{account_id}:{observed}'
        conn.execute(
            '''INSERT INTO account_balance_history(account_id,balance_cents,balance_date,status,source_type,source_status,confidence,source_key,imported_at)
               VALUES(?,?,?,'confirmed','manual','confirmed',1.0,?,CURRENT_TIMESTAMP)
               ON CONFLICT(source_key) DO UPDATE SET balance_cents=excluded.balance_cents,status='confirmed',source_status='confirmed',confidence=1.0,imported_at=CURRENT_TIMESTAMP''',
            (account_id, payload.current_balance_cents, observed, source_key),
        )
        row = conn.execute('SELECT * FROM accounts WHERE id=?', (account_id,)).fetchone()
    return dict(row)


@router.post('/api/ledger/transactions', status_code=201)
def create_ledger_transaction(payload: LedgerTransactionIn):
    with connection() as conn:
        if not conn.execute('SELECT 1 FROM accounts WHERE id=?', (payload.account_id,)).fetchone():
            raise HTTPException(404, 'Account not found')
        category = payload.category
        tx_type = payload.transaction_type or ('income' if payload.amount_cents > 0 else 'expense')
        if not category:
            rules = conn.execute('SELECT * FROM categorization_rules WHERE is_active=1 ORDER BY priority,id').fetchall()
            label = payload.label.upper()
            match = next((r for r in rules if r['pattern'] in label), None)
            if match:
                category = match['category']
                tx_type = match['transaction_type'] or tx_type
        internal = int(payload.is_internal_transfer or tx_type == 'transfer' or category == 'Transfert interne')
        cur = conn.execute('INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer) VALUES(?,?,?,?,?,?,?)', (payload.account_id,payload.booking_date.isoformat(),payload.amount_cents,payload.label,category,tx_type,internal))
        row = conn.execute('SELECT * FROM transactions WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)


@router.get('/api/month')
def month_overview(month: str | None = None):
    month = month or date.today().strftime('%Y-%m')
    with connection() as conn:
        income = conn.execute("SELECT COALESCE(SUM(amount_cents),0) total FROM transactions WHERE substr(booking_date,1,7)=? AND amount_cents>0 AND is_internal_transfer=0 AND transaction_type NOT IN ('refund','reimbursement')", (month,)).fetchone()['total']
        spent = conn.execute("SELECT COALESCE(SUM(-amount_cents),0) total FROM transactions WHERE substr(booking_date,1,7)=? AND amount_cents<0 AND is_internal_transfer=0 AND COALESCE(category,'')<>'Frais professionnel remboursé'", (month,)).fetchone()['total']
        planned = conn.execute("SELECT COALESCE(SUM(-amount_cents),0) total FROM planned_transactions WHERE substr(due_date,1,7)=? AND amount_cents<0 AND status='planned'", (month,)).fetchone()['total']
        budget = conn.execute('SELECT id,status FROM budgets WHERE month=?', (month,)).fetchone()
        lines = []
        if budget:
            rows = conn.execute('SELECT category,planned_cents,mode FROM budget_lines WHERE budget_id=? ORDER BY category', (budget['id'],)).fetchall()
            for row in rows:
                actual = conn.execute("SELECT COALESCE(SUM(-amount_cents),0) total FROM transactions WHERE substr(booking_date,1,7)=? AND category=? AND amount_cents<0 AND is_internal_transfer=0 AND COALESCE(category,'')<>'Frais professionnel remboursé'", (month,row['category'])).fetchone()['total']
                lines.append({**dict(row), 'spent_cents': actual, 'remaining_cents': max(0,row['planned_cents']-actual)})
    return {'month': month, 'income_cents': income, 'spent_cents': spent, 'planned_outflows_cents': planned, 'net_cents': income-spent, 'budget_status': budget['status'] if budget else 'draft', 'lines': lines}


@router.get('/api/movements')
def movements(q: str = '', limit: int = Query(default=100, ge=1, le=500)):
    pattern = f"%{q.strip()}%"
    with connection() as conn:
        if q.strip():
            rows = conn.execute("SELECT t.*,a.name account_name FROM transactions t JOIN accounts a ON a.id=t.account_id WHERE t.label LIKE ? OR COALESCE(t.category,'') LIKE ? ORDER BY booking_date DESC,t.id DESC LIMIT ?", (pattern,pattern,limit)).fetchall()
        else:
            rows = conn.execute('SELECT t.*,a.name account_name FROM transactions t JOIN accounts a ON a.id=t.account_id ORDER BY booking_date DESC,t.id DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in rows]


@router.get('/api/wealth')
def wealth_overview():
    with connection() as conn:
        accounts = [dict(r) for r in conn.execute('SELECT * FROM accounts WHERE is_active=1 ORDER BY id').fetchall()]
        goals = conn.execute('SELECT * FROM financial_goals WHERE is_active=1 ORDER BY priority,id').fetchall()
        goal_rows = []
        for row in goals:
            allocated = conn.execute('SELECT COALESCE(SUM(amount_cents),0) total FROM goal_allocations WHERE goal_id=?', (row['id'],)).fetchone()['total']
            goal_rows.append(goal_summary(dict(row), allocated, date.today()))
    groups = {'liquid_cents': 0, 'savings_cents': 0, 'investments_cents': 0, 'liabilities_cents': 0}
    for account in accounts:
        kind = account['kind']
        if kind in {'checking','cash','joint'}:
            groups['liquid_cents'] += account['current_balance_cents']
        elif kind in {'savings','livret','ldds'}:
            groups['savings_cents'] += account['current_balance_cents']
        elif kind in {'investment','pea','cto','life_insurance'}:
            groups['investments_cents'] += account['current_balance_cents']
        elif kind == 'loan':
            groups['liabilities_cents'] += abs(account['current_balance_cents'])
    assets = groups['liquid_cents'] + groups['savings_cents'] + groups['investments_cents']
    return {'accounts': accounts, 'goals': goal_rows, **groups, 'net_financial_cents': assets - groups['liabilities_cents']}


@router.get('/api/settings')
def settings():
    with connection() as conn:
        rows = conn.execute('SELECT key,value FROM settings ORDER BY key').fetchall()
    return {r['key']: r['value'] for r in rows}
