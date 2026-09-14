from __future__ import annotations

import hashlib
import json
from datetime import date, timedelta
from difflib import SequenceMatcher

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .db import connection
from .imports import ensure_import_schema
from .month_prep import build_month_preparation
from .recurring_detection import detect_recurring_suggestions, recurring_key
from .v3_migrations import log_activity
from .v33_routes import goals_forecast
from .v35_routes import closeout
from .v36_migrations import ensure_v36_schema

router = APIRouter(prefix='/api/v3.6', tags=['Flow V3.6'])


class InboxStatusIn(BaseModel):
    status: str = Field(pattern='^(open|done|dismissed)$')
    note: str | None = Field(default=None, max_length=300)


def _period_month(value: date) -> str:
    return value.strftime('%Y-%m')


def _previous_month(value: date) -> str:
    first = value.replace(day=1)
    previous = first - timedelta(days=1)
    return previous.strftime('%Y-%m')


def _routine_row(conn, routine_key: str, period_key: str):
    return conn.execute(
        'SELECT * FROM financial_routine_runs WHERE routine_key=? AND period_key=?',
        (routine_key, period_key),
    ).fetchone()


def _store_routine(conn, routine_key: str, period_key: str, summary: dict) -> None:
    conn.execute(
        """
        INSERT INTO financial_routine_runs(routine_key,period_key,status,summary_json)
        VALUES(?,?,?,?)
        ON CONFLICT(routine_key,period_key) DO UPDATE SET
          status=excluded.status,summary_json=excluded.summary_json,created_at=CURRENT_TIMESTAMP
        """,
        (routine_key, period_key, 'completed', json.dumps(summary, ensure_ascii=False)),
    )


def _label_similarity(a: str, b: str) -> float:
    ka = recurring_key(a or '')
    kb = recurring_key(b or '')
    if not ka or not kb:
        return 0.0
    if ka == kb:
        return 1.0
    if ka in kb or kb in ka:
        return 0.92
    return SequenceMatcher(None, ka, kb).ratio()


def _match_score(planned, tx) -> tuple[float, int, int, float]:
    due = date.fromisoformat(planned['due_date'])
    booked = date.fromisoformat(tx['booking_date'])
    day_delta = abs((booked - due).days)
    amount_delta = abs(int(tx['amount_cents']) - int(planned['amount_cents']))
    amount_base = max(abs(int(planned['amount_cents'])), 1)
    amount_ratio = amount_delta / amount_base
    label_score = _label_similarity(planned['label'], tx['label'])
    date_score = max(0.0, 1.0 - day_delta / 10)
    amount_score = max(0.0, 1.0 - amount_ratio / 0.12)
    score = label_score * 0.45 + amount_score * 0.4 + date_score * 0.15
    return round(score, 4), day_delta, amount_delta, label_score


def _candidates(conn, planned) -> list[dict]:
    due = date.fromisoformat(planned['due_date'])
    low = (due - timedelta(days=7)).isoformat()
    high = (due + timedelta(days=7)).isoformat()
    sign = 1 if int(planned['amount_cents']) > 0 else -1
    rows = conn.execute(
        """
        SELECT t.* FROM transactions t
        LEFT JOIN planned_transaction_matches m ON m.transaction_id=t.id
        WHERE t.account_id=? AND t.booking_date BETWEEN ? AND ? AND m.id IS NULL
          AND CASE WHEN t.amount_cents>0 THEN 1 ELSE -1 END=?
        ORDER BY t.booking_date,t.id
        """,
        (planned['account_id'], low, high, sign),
    ).fetchall()
    result = []
    for tx in rows:
        score, day_delta, amount_delta, label_score = _match_score(planned, tx)
        tolerance = max(100, round(abs(int(planned['amount_cents'])) * 0.05))
        if amount_delta > tolerance:
            continue
        result.append({
            'transaction': dict(tx),
            'score': score,
            'day_delta': day_delta,
            'amount_delta_cents': amount_delta,
            'label_similarity': round(label_score, 4),
        })
    result.sort(key=lambda x: (-x['score'], x['amount_delta_cents'], x['day_delta']))
    return result


def _reconcile(conn, dry_run: bool = False) -> dict:
    ensure_v36_schema(conn)
    planned_rows = conn.execute(
        """
        SELECT * FROM planned_transactions
        WHERE status='planned' AND due_date<=?
        ORDER BY due_date,id
        """,
        ((date.today() + timedelta(days=7)).isoformat(),),
    ).fetchall()
    matched = []
    ambiguous = []
    for planned in planned_rows:
        candidates = _candidates(conn, planned)
        if not candidates:
            continue
        best = candidates[0]
        second_score = candidates[1]['score'] if len(candidates) > 1 else 0.0
        unique_margin = best['score'] - second_score
        auto = best['score'] >= 0.90 and unique_margin >= 0.08
        record = {
            'planned_transaction_id': planned['id'],
            'planned_label': planned['label'],
            'due_date': planned['due_date'],
            'transaction_id': best['transaction']['id'],
            'transaction_label': best['transaction']['label'],
            'booking_date': best['transaction']['booking_date'],
            'amount_cents': planned['amount_cents'],
            'amount_delta_cents': best['amount_delta_cents'],
            'day_delta': best['day_delta'],
            'confidence': best['score'],
        }
        if auto:
            matched.append(record)
            if not dry_run:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO planned_transaction_matches(
                      planned_transaction_id,transaction_id,amount_delta_cents,day_delta,confidence
                    ) VALUES(?,?,?,?,?)
                    """,
                    (planned['id'], best['transaction']['id'], best['amount_delta_cents'], best['day_delta'], best['score']),
                )
                conn.execute("UPDATE planned_transactions SET status='matched' WHERE id=?", (planned['id'],))
        elif best['score'] >= 0.72:
            ambiguous.append(record)
    return {'matched': matched, 'ambiguous': ambiguous, 'dry_run': dry_run}


def _inbox_statuses(conn) -> dict[str, dict]:
    rows = conn.execute('SELECT * FROM decision_inbox_status').fetchall()
    return {str(r['item_key']): dict(r) for r in rows}


def _stale_accounts(conn, today: date) -> list[dict]:
    rows = conn.execute('SELECT id,name,current_balance_cents,balance_as_of FROM accounts WHERE is_active=1 ORDER BY id').fetchall()
    result = []
    for row in rows:
        age = None
        if row['balance_as_of']:
            try:
                age = (today - date.fromisoformat(row['balance_as_of'])).days
            except ValueError:
                age = None
        if age is None or age > 7:
            result.append({**dict(row), 'age_days': age})
    return result


def _recurring_item_key(suggestion: dict) -> str:
    raw = f"{suggestion['account_id']}|{suggestion.get('key') or suggestion['label']}|{1 if suggestion['amount_cents'] > 0 else -1}"
    return 'recurring:' + hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]


@router.get('/routine-status')
def routine_status():
    today = date.today()
    current = _period_month(today)
    previous = _previous_month(today)
    week = f'{today.isocalendar().year}-W{today.isocalendar().week:02d}'
    with connection() as conn:
        ensure_v36_schema(conn)
        current_open = _routine_row(conn, 'month_open', current)
        previous_close = _routine_row(conn, 'month_close', previous)
        weekly_review = _routine_row(conn, 'weekly_review', week)
        uncat = int(conn.execute(
            "SELECT COUNT(*) n FROM transactions WHERE COALESCE(category,'')='' AND COALESCE(is_internal_transfer,0)=0"
        ).fetchone()['n'])
        stale = len(_stale_accounts(conn, today))
    return {
        'current_month': current,
        'previous_month': previous,
        'week': week,
        'routines': [
            {'key': 'month_open', 'label': 'Ouvrir le mois', 'due': not bool(current_open), 'period': current},
            {'key': 'month_close', 'label': 'Clôturer le mois précédent', 'due': not bool(previous_close), 'period': previous},
            {'key': 'weekly_review', 'label': 'Revoir les mouvements non catégorisés', 'due': uncat > 0 and not bool(weekly_review), 'period': week, 'count': uncat},
            {'key': 'balance_refresh', 'label': 'Actualiser les soldes', 'due': stale > 0, 'period': current, 'count': stale},
        ],
    }


@router.post('/open-month')
def open_month(month: str | None = Query(default=None, pattern=r'^\d{4}-\d{2}$')):
    today = date.today()
    period = month or _period_month(today)
    with connection() as conn:
        ensure_v36_schema(conn)
        prep = build_month_preparation(conn, period, today)
        summary = {
            'status': prep['status'],
            'warnings': prep['warnings'],
            'blockers': prep['blockers'],
            'known_outflows_cents': prep['known_outflows_cents'],
            'effective_income_cents': prep['effective_income_cents'],
            'pending_recurring_suggestions': len(prep['pending_recurring_suggestions']),
        }
        _store_routine(conn, 'month_open', period, summary)
        log_activity(conn, 'routine', 'Mois préparé', f'{period} · {prep["status_label"]}', 'month', period)
    return {'period': period, 'preparation': prep, 'summary': summary}


@router.post('/close-month')
def close_month(month: str | None = Query(default=None, pattern=r'^\d{4}-\d{2}$')):
    today = date.today()
    period = month or _previous_month(today)
    summary = closeout(period)
    with connection() as conn:
        ensure_v36_schema(conn)
        _store_routine(conn, 'month_close', period, summary)
        log_activity(conn, 'routine', 'Mois clôturé', f'{period} · écart {summary["variance_cents"]} centimes', 'month', period)
    return summary


@router.post('/weekly-review')
def weekly_review():
    today = date.today()
    week = f'{today.isocalendar().year}-W{today.isocalendar().week:02d}'
    with connection() as conn:
        ensure_v36_schema(conn)
        count = int(conn.execute(
            "SELECT COUNT(*) n FROM transactions WHERE COALESCE(category,'')='' AND COALESCE(is_internal_transfer,0)=0"
        ).fetchone()['n'])
        summary = {'uncategorized_transactions': count}
        _store_routine(conn, 'weekly_review', week, summary)
        log_activity(conn, 'routine', 'Revue hebdomadaire', f'{count} mouvement(s) non catégorisé(s)', 'week', week)
    return {'week': week, **summary}


@router.post('/reconcile')
def reconcile(dry_run: bool = False):
    with connection() as conn:
        result = _reconcile(conn, dry_run=dry_run)
        if result['matched'] and not dry_run:
            log_activity(conn, 'reconciliation', 'Rapprochement automatique', f'{len(result["matched"])} échéance(s) rapprochée(s)')
    return result


@router.get('/decision-inbox')
def decision_inbox(include_closed: bool = False):
    today = date.today()
    with connection() as conn:
        ensure_v36_schema(conn)
        ensure_import_schema(conn)
        statuses = _inbox_statuses(conn)
        items = []

        review_rows = conn.execute(
            """
            SELECT t.id,t.booking_date,t.amount_cents,t.label,a.name account_name
            FROM transaction_import_meta m
            JOIN transactions t ON t.id=m.transaction_id
            JOIN accounts a ON a.id=t.account_id
            WHERE m.review_status='needs_review'
            ORDER BY t.booking_date DESC,t.id DESC LIMIT 100
            """
        ).fetchall()
        for row in review_rows:
            items.append({
                'key': f'import:{row["id"]}', 'type': 'import_review', 'priority': 'high',
                'title': 'Mouvement importé à catégoriser',
                'detail': f'{row["label"]} · {row["account_name"]} · {row["booking_date"]}',
                'amount_cents': row['amount_cents'], 'entity_id': row['id'],
            })

        for suggestion in detect_recurring_suggestions(conn):
            if float(suggestion.get('confidence') or 0) < 0.75:
                continue
            items.append({
                'key': _recurring_item_key(suggestion), 'type': 'recurring_suggestion', 'priority': 'medium',
                'title': 'Récurrence détectée à valider',
                'detail': f'{suggestion["label"]} · {suggestion["occurrences"]} occurrence(s) · confiance {round(suggestion["confidence"]*100)} %',
                'amount_cents': suggestion['amount_cents'], 'suggestion': suggestion,
            })

        reconciliation = _reconcile(conn, dry_run=True)
        for candidate in reconciliation['ambiguous']:
            items.append({
                'key': f'reconcile:{candidate["planned_transaction_id"]}', 'type': 'reconciliation_review', 'priority': 'high',
                'title': 'Rapprochement à confirmer',
                'detail': f'{candidate["planned_label"]} ↔ {candidate["transaction_label"]} · confiance {round(candidate["confidence"]*100)} %',
                'amount_cents': candidate['amount_cents'], 'candidate': candidate,
            })

        overdue = conn.execute(
            """
            SELECT id,due_date,amount_cents,label FROM planned_transactions
            WHERE status='planned' AND due_date<? ORDER BY due_date,id
            """,
            ((today - timedelta(days=3)).isoformat(),),
        ).fetchall()
        for row in overdue:
            items.append({
                'key': f'overdue:{row["id"]}', 'type': 'missing_expected', 'priority': 'high',
                'title': 'Échéance attendue non rapprochée',
                'detail': f'{row["label"]} était prévue le {row["due_date"]}',
                'amount_cents': row['amount_cents'], 'entity_id': row['id'],
            })

        for row in _stale_accounts(conn, today):
            age = f'{row["age_days"]} jours' if row['age_days'] is not None else 'date inconnue'
            items.append({
                'key': f'balance:{row["id"]}', 'type': 'stale_balance', 'priority': 'medium',
                'title': 'Solde à actualiser', 'detail': f'{row["name"]} · {age}',
                'amount_cents': row['current_balance_cents'], 'entity_id': row['id'],
            })

    goal_data = goals_forecast(months=12, scenario_id=None)
    for goal in goal_data['goals']:
        if goal['status'] not in {'at_risk', 'off_track', 'late'}:
            continue
        items.append({
            'key': f'goal:{goal["id"]}', 'type': 'goal_risk',
            'priority': 'high' if goal['status'] in {'off_track', 'late'} else 'medium',
            'title': 'Objectif à ajuster',
            'detail': f'{goal["name"]} · statut {goal["status"]}',
            'amount_cents': goal.get('required_monthly_cents'), 'entity_id': goal['id'],
        })

    enriched = []
    for item in items:
        state = statuses.get(item['key'], {'status': 'open', 'note': None})
        item['status'] = state.get('status', 'open')
        item['note'] = state.get('note')
        if include_closed or item['status'] == 'open':
            enriched.append(item)
    rank = {'high': 0, 'medium': 1, 'low': 2}
    enriched.sort(key=lambda x: (rank.get(x['priority'], 9), x['type'], x['key']))
    return {
        'items': enriched,
        'open_count': sum(1 for x in enriched if x['status'] == 'open'),
        'method': 'La Decision Inbox consolide uniquement les éléments nécessitant une validation ou une action. Les suggestions de récurrence ne sont jamais activées sans validation explicite.',
    }


@router.patch('/decision-inbox/{item_key:path}')
def set_inbox_status(item_key: str, payload: InboxStatusIn):
    with connection() as conn:
        ensure_v36_schema(conn)
        conn.execute(
            """
            INSERT INTO decision_inbox_status(item_key,status,note) VALUES(?,?,?)
            ON CONFLICT(item_key) DO UPDATE SET status=excluded.status,note=excluded.note,updated_at=CURRENT_TIMESTAMP
            """,
            (item_key, payload.status, payload.note),
        )
        log_activity(conn, 'decision_inbox', 'Decision Inbox mise à jour', f'{item_key} → {payload.status}', 'decision_item', item_key)
    return {'key': item_key, 'status': payload.status, 'note': payload.note}
