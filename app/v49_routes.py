from __future__ import annotations

import json
from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .db import connection
from .imports import ensure_import_schema

router = APIRouter(prefix='/api/v4.9', tags=['Flow V4.9'])


class MonthCloseIn(BaseModel):
    confirmation: str = Field(pattern='^CLOTURER$')


def ensure_v49_schema(conn) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS monthly_closures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            month TEXT NOT NULL,
            account_id INTEGER NOT NULL REFERENCES accounts(id),
            import_id INTEGER NOT NULL REFERENCES imports(id),
            closing_balance_cents INTEGER NOT NULL,
            period_end TEXT NOT NULL,
            quality_status TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'consolidated',
            evidence_json TEXT NOT NULL DEFAULT '{}',
            closed_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(month, account_id)
        );
        CREATE INDEX IF NOT EXISTS idx_monthly_closures_month ON monthly_closures(month,status);
        """
    )


def _validate_month(value: str) -> str:
    try:
        year, month = map(int, value.split('-'))
        if year < 2000 or month < 1 or month > 12:
            raise ValueError
    except ValueError as exc:
        raise HTTPException(400, 'Mois invalide, format attendu YYYY-MM') from exc
    return value


def _effective_review_rows(conn, import_id: int, stored_review_rows: int) -> int:
    """Use live inbox metadata when it exists; otherwise preserve the import audit value.

    Older/staged imports can legitimately carry a review_rows count without
    transaction_import_meta rows. Recomputing them globally would incorrectly
    erase that blocker and make an import closable.
    """
    meta = conn.execute(
        """SELECT COUNT(*) total,
                  COALESCE(SUM(CASE WHEN review_status='needs_review' THEN 1 ELSE 0 END),0) pending
           FROM transaction_import_meta WHERE import_id=?""",
        (import_id,),
    ).fetchone()
    if meta and int(meta['total'] or 0) > 0:
        return int(meta['pending'] or 0)
    return int(stored_review_rows or 0)


def _candidate_imports(conn, month: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT i.*,a.name account_name
        FROM imports i JOIN accounts a ON a.id=i.account_id
        WHERE i.status='completed'
          AND i.duplicate_of_import_id IS NULL
          AND i.period_end IS NOT NULL
          AND substr(i.period_end,1,7)=?
        ORDER BY i.period_end DESC,i.id DESC
        """,
        (month,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item['review_rows'] = _effective_review_rows(conn, int(item['id']), int(item.get('review_rows') or 0))
        blockers = []
        if int(item.get('review_rows') or 0) > 0:
            blockers.append('review_rows')
        if item.get('closing_balance_cents') is None:
            blockers.append('missing_closing_balance')
        if (item.get('quality_status') or '').lower() not in {'ok', 'warning'}:
            blockers.append('quality_not_validated')
        item['blockers'] = blockers
        item['closable'] = not blockers
        result.append(item)
    return result


def _month_status(conn, month: str) -> dict:
    ensure_import_schema(conn)
    ensure_v49_schema(conn)
    closures = [dict(row) for row in conn.execute(
        """SELECT mc.*,a.name account_name,i.filename
        FROM monthly_closures mc
        JOIN accounts a ON a.id=mc.account_id
        JOIN imports i ON i.id=mc.import_id
        WHERE mc.month=? AND mc.status='consolidated'
        ORDER BY a.name""",
        (month,),
    ).fetchall()]
    candidates = _candidate_imports(conn, month)
    accounts = [dict(row) for row in conn.execute(
        "SELECT id,name,kind,current_balance_cents,balance_as_of FROM accounts WHERE is_active=1 ORDER BY id"
    ).fetchall()]
    relevant = [a for a in accounts if a.get('kind') in {'checking','joint','cash'}]
    closed_ids = {int(row['account_id']) for row in closures}
    ready_ids = {int(row['account_id']) for row in candidates if row['closable']}
    missing_accounts = [a for a in relevant if int(a['id']) not in closed_ids and int(a['id']) not in ready_ids]
    pending_review = sum(int(row.get('review_rows') or 0) for row in candidates)
    if closures and len(closed_ids) >= len(relevant):
        status = 'consolidated'
    elif any(row['closable'] for row in candidates):
        status = 'ready'
    elif candidates:
        status = 'blocked'
    else:
        status = 'statement_missing'
    return {
        'month': month,
        'status': status,
        'closures': closures,
        'candidates': candidates,
        'missing_accounts': missing_accounts,
        'pending_review_rows': pending_review,
        'principle': 'Un mois est consolidé uniquement à partir d’un relevé bancaire validé. Aucun mouvement n’est inventé pendant la clôture.',
    }


@router.get('/month-status')
def month_status(month: str = Query(pattern=r'^\d{4}-\d{2}$')):
    month = _validate_month(month)
    with connection() as conn:
        return _month_status(conn, month)


@router.post('/months/{month}/accounts/{account_id}/close')
def close_month_account(month: str, account_id: int, payload: MonthCloseIn):
    month = _validate_month(month)
    with connection() as conn:
        ensure_import_schema(conn)
        ensure_v49_schema(conn)
        if not conn.execute('SELECT 1 FROM accounts WHERE id=? AND is_active=1', (account_id,)).fetchone():
            raise HTTPException(404, 'Compte introuvable')
        existing = conn.execute(
            "SELECT * FROM monthly_closures WHERE month=? AND account_id=? AND status='consolidated'",
            (month, account_id),
        ).fetchone()
        if existing:
            return {'ok': True, 'already_closed': True, 'closure': dict(existing), 'status': _month_status(conn, month)}
        candidates = [row for row in _candidate_imports(conn, month) if int(row['account_id']) == account_id]
        candidate = next((row for row in candidates if row['closable']), None)
        if not candidate:
            reasons = candidates[0]['blockers'] if candidates else ['statement_missing']
            raise HTTPException(409, {'message': 'Le mois ne peut pas être clôturé pour ce compte', 'blockers': reasons})
        evidence = {
            'filename': candidate['filename'],
            'period_start': candidate.get('period_start'),
            'period_end': candidate.get('period_end'),
            'opening_balance_cents': candidate.get('opening_balance_cents'),
            'closing_balance_cents': candidate.get('closing_balance_cents'),
            'debit_total_cents': candidate.get('debit_total_cents'),
            'credit_total_cents': candidate.get('credit_total_cents'),
            'imported_rows': candidate.get('imported_rows'),
            'duplicate_rows': candidate.get('duplicate_rows'),
            'review_rows': candidate.get('review_rows'),
            'quality_status': candidate.get('quality_status'),
        }
        cur = conn.execute(
            """INSERT INTO monthly_closures(month,account_id,import_id,closing_balance_cents,period_end,quality_status,evidence_json)
            VALUES(?,?,?,?,?,?,?)""",
            (month, account_id, candidate['id'], candidate['closing_balance_cents'], candidate['period_end'], candidate.get('quality_status') or 'unknown', json.dumps(evidence, ensure_ascii=False)),
        )
        closure = conn.execute('SELECT * FROM monthly_closures WHERE id=?', (cur.lastrowid,)).fetchone()
    return {'ok': True, 'already_closed': False, 'closure': dict(closure), 'status': month_status(month)}


@router.get('/consolidated-months')
def consolidated_months(limit: int = Query(default=18, ge=1, le=60)):
    with connection() as conn:
        ensure_v49_schema(conn)
        rows = conn.execute(
            """SELECT month,COUNT(*) account_count,MAX(closed_at) closed_at
            FROM monthly_closures WHERE status='consolidated'
            GROUP BY month ORDER BY month DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]
