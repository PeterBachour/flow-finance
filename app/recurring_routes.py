from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import connection
from .recurring_detection import detect_recurring_suggestions

router = APIRouter()


class AcceptRecurringIn(BaseModel):
    account_id: int
    label: str = Field(min_length=1, max_length=180)
    amount_cents: int
    day_of_month: int = Field(ge=1, le=31)
    category: str | None = None
    tolerance_cents: int = Field(default=0, ge=0)
    certainty: str = 'expected'


@router.get('/api/recurring/suggestions')
def recurring_suggestions():
    with connection() as conn:
        return detect_recurring_suggestions(conn)


@router.post('/api/recurring/suggestions/accept', status_code=201)
def accept_recurring(payload: AcceptRecurringIn):
    with connection() as conn:
        if not conn.execute('SELECT 1 FROM accounts WHERE id=? AND is_active=1', (payload.account_id,)).fetchone():
            raise HTTPException(404, 'Compte introuvable')
        existing = conn.execute('SELECT id FROM recurring_transactions WHERE account_id=? AND label=? AND is_active=1', (payload.account_id, payload.label)).fetchone()
        if existing:
            raise HTTPException(409, 'Cette récurrence existe déjà')
        if payload.category == 'Salaire' and payload.amount_cents > 0:
            kind = 'salary'
        else:
            kind = 'income' if payload.amount_cents > 0 else 'commitment'
        cur = conn.execute(
            'INSERT INTO recurring_transactions(account_id,label,amount_cents,day_of_month,category,kind,certainty,tolerance_cents) VALUES(?,?,?,?,?,?,?,?)',
            (payload.account_id, payload.label, payload.amount_cents, payload.day_of_month, payload.category, kind, payload.certainty, payload.tolerance_cents),
        )
        row = conn.execute('SELECT * FROM recurring_transactions WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)
