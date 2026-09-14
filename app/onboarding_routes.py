from datetime import date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from .db import connection

router = APIRouter()
LIQUID_KINDS = {'checking', 'cash'}
KNOWN_KINDS = {
    'checking', 'cash', 'joint', 'savings', 'livret', 'ldds',
    'investment', 'pea', 'cto', 'life_insurance', 'loan', 'other',
}


class OnboardingAccountIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    kind: str = 'checking'
    current_balance_cents: int = 0
    balance_as_of: date | None = None
    currency: str = 'EUR'


def readiness(conn) -> dict:
    accounts = [dict(r) for r in conn.execute('SELECT * FROM accounts WHERE is_active=1 ORDER BY id').fetchall()]
    liquid = [a for a in accounts if a['kind'] in LIQUID_KINDS]
    dated_liquid = [a for a in liquid if a.get('balance_as_of')]
    unknown = [a for a in accounts if a['kind'] not in KNOWN_KINDS]
    reserve_row = conn.execute("SELECT value FROM settings WHERE key='safety_reserve_cents'").fetchone()
    reserve = int(reserve_row['value']) if reserve_row else 0

    steps = [
        {'code': 'account', 'label': 'Ajouter un compte courant', 'done': bool(liquid)},
        {'code': 'balance', 'label': 'Renseigner un solde réel daté', 'done': bool(dated_liquid)},
        {'code': 'reserve', 'label': 'Définir une réserve minimale', 'done': reserve > 0},
    ]
    blockers = []
    warnings = []
    if not liquid:
        blockers.append('Aucun compte liquide configuré')
    elif not dated_liquid:
        blockers.append('Aucun solde liquide daté')
    if unknown:
        warnings.append(f"{len(unknown)} compte(s) utilisent un type non reconnu")
    if reserve <= 0:
        warnings.append('Réserve minimale non définie')

    ready = not blockers
    return {
        'ready': ready,
        'status': 'ready' if ready else 'setup_required',
        'steps': steps,
        'blockers': blockers,
        'warnings': warnings,
        'account_count': len(accounts),
        'liquid_account_count': len(liquid),
        'dated_liquid_account_count': len(dated_liquid),
        'reserve_cents': reserve,
        'unknown_account_kinds': [{'id': a['id'], 'name': a['name'], 'kind': a['kind']} for a in unknown],
    }


@router.get('/api/onboarding/status')
def onboarding_status():
    with connection() as conn:
        return readiness(conn)


@router.post('/api/onboarding/accounts', status_code=201)
def onboarding_account(payload: OnboardingAccountIn):
    if payload.kind not in KNOWN_KINDS:
        raise HTTPException(400, 'Type de compte non reconnu')
    observed = (payload.balance_as_of or date.today()).isoformat()
    with connection() as conn:
        cur = conn.execute(
            'INSERT INTO accounts(name,kind,current_balance_cents,balance_as_of,currency) VALUES(?,?,?,?,?)',
            (payload.name, payload.kind, payload.current_balance_cents, observed, payload.currency),
        )
        row = conn.execute('SELECT * FROM accounts WHERE id=?', (cur.lastrowid,)).fetchone()
    return dict(row)
