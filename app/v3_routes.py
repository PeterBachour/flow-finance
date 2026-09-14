from __future__ import annotations

import json
import os
from datetime import date
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .db import DB_PATH, connection
from .financial_engine_v2 import build_decision_cockpit, data_quality, month_totals, monthly_insights
from .v2_migrations import ensure_v2_schema
from .v3_migrations import ensure_v3_schema, log_activity
from .version import VERSION

router = APIRouter(prefix='/api/v3', tags=['Flow V3'])
CHANGELOG = Path(__file__).parent / 'static' / 'changelog.json'
V57_RELEASE = {
    'version': '5.7.0',
    'date': '2026-09-12',
    'title': 'Flow V5.7 — Data Quality Action Center',
    'highlights': [
        'File de remédiation priorisée à partir des trous, revues et doublons de l’historique financier',
        'Priorité aux relevés bancaires récents manquants avant les revues, doublons et fiches de paie',
        'Preuve, document attendu et analyses débloquées exposés pour chaque action',
        'Navigation directe vers l’import ou la revue concernée sans correction financière silencieuse',
        'Backend, runtime principal, manifest, assets et cache PWA synchronisés en 5.7.0',
    ],
}
V55_RELEASE = {
    'version': '5.5.0',
    'date': '2026-09-12',
    'title': 'Flow V5.5 — Couverture historique & import multi-documents',
    'highlights': [
        'Couverture des relevés bancaires et fiches de paie sur une fenêtre configurable, 24 mois par défaut',
        'Détection explicite des mois manquants, périodes à revoir, doublons et mois complètement documentés',
        'Import de plusieurs PDF/CSV depuis Mouvements avec staging sans écriture avant validation explicite',
        'Audit historique en ligne de commande strictement en lecture seule',
        'Synchronisation backend, runtime, manifest et cache PWA en 5.5.0',
    ],
}
KNOWN_RELEASES = {
    V57_RELEASE['version']: V57_RELEASE,
    V55_RELEASE['version']: V55_RELEASE,
}


class ActivityIn(BaseModel):
    event_type: str = Field(min_length=1, max_length=60)
    title: str = Field(min_length=1, max_length=160)
    details: str | None = Field(default=None, max_length=500)
    entity_type: str | None = Field(default=None, max_length=60)
    entity_id: str | None = Field(default=None, max_length=120)
    metadata: dict | None = None


class FeatureFlagIn(BaseModel):
    enabled: bool


def _ready(conn) -> None:
    ensure_v2_schema(conn)
    ensure_v3_schema(conn)


def _health(conn) -> dict:
    today = date.today()
    cockpit = build_decision_cockpit(conn, today)
    quality = data_quality(conn, today)
    month = month_totals(conn, today.strftime('%Y-%m'))
    safe = cockpit['safe_to_spend']

    quality_score = int(quality.get('score') or 0)
    liquidity_score = {
        'comfortable': 100,
        'prudent': 75,
        'tight': 45,
        'critical': 15,
    }.get(safe.get('status'), 55)

    income = int(month.get('income_cents') or 0)
    saving = int(month.get('saving_cents') or 0)
    savings_rate = (saving / income) if income > 0 else 0
    if savings_rate >= .20:
        savings_score = 100
    elif savings_rate >= .10:
        savings_score = 80
    elif savings_rate >= .05:
        savings_score = 60
    elif income > 0:
        savings_score = 35
    else:
        savings_score = 50

    net = int(month.get('net_cents') or 0)
    if income <= 0:
        cashflow_score = 50
    elif net >= 0:
        cashflow_score = 100
    elif net >= -income * .10:
        cashflow_score = 70
    elif net >= -income * .25:
        cashflow_score = 45
    else:
        cashflow_score = 20

    score = round(
        quality_score * .35 + liquidity_score * .30 + savings_score * .20 + cashflow_score * .15
    )
    status = 'excellent' if score >= 85 else ('good' if score >= 70 else ('watch' if score >= 50 else 'fragile'))

    alerts: list[dict] = []
    for issue in quality.get('issues', []):
        alerts.append({
            'kind': 'data_quality',
            'severity': issue.get('severity', 'info'),
            'title': issue.get('title', 'Qualité des données'),
            'detail': f"{issue.get('count', 1)} élément(s) à vérifier",
        })
    if safe.get('status') in {'tight', 'critical'}:
        alerts.append({
            'kind': 'liquidity', 'severity': 'critical' if safe.get('status') == 'critical' else 'warning',
            'title': 'Marge de sécurité réduite',
            'detail': f"Disponible sécurisé : {int(safe.get('until_income_cents') or 0) / 100:.2f} €",
        })
    if income > 0 and savings_rate < .05:
        alerts.append({
            'kind': 'savings', 'severity': 'info', 'title': 'Taux d’épargne faible ce mois-ci',
            'detail': f"{savings_rate * 100:.1f} % des revenus actuellement identifiés",
        })
    return {
        'score': score,
        'status': status,
        'method': 'Heuristique V3 pondérée : qualité des données 35 %, liquidité prévisionnelle 30 %, épargne 20 %, cash-flow mensuel 15 %.',
        'components': {
            'data_quality': quality_score,
            'liquidity': liquidity_score,
            'savings': savings_score,
            'cashflow': cashflow_score,
        },
        'savings_rate': round(savings_rate, 4),
        'alerts': alerts[:8],
    }


@router.get('/overview')
def overview():
    with connection() as conn:
        _ready(conn)
        cockpit = build_decision_cockpit(conn)
        health = _health(conn)
        insights = monthly_insights(conn)
        activity = [dict(r) for r in conn.execute(
            'SELECT id,event_type,title,details,entity_type,entity_id,created_at FROM activity_log ORDER BY id DESC LIMIT 8'
        ).fetchall()]
    return {'version': VERSION, 'cockpit': cockpit, 'health': health, 'insights': insights, 'activity': activity}


@router.get('/health')
def health():
    with connection() as conn:
        _ready(conn)
        return _health(conn)


@router.get('/activity')
def activity(limit: int = Query(default=50, ge=1, le=200)):
    with connection() as conn:
        _ready(conn)
        rows = conn.execute(
            'SELECT id,event_type,title,details,entity_type,entity_id,metadata_json,created_at FROM activity_log ORDER BY id DESC LIMIT ?',
            (limit,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item['metadata'] = json.loads(item.pop('metadata_json') or '{}')
        except json.JSONDecodeError:
            item['metadata'] = {}
        result.append(item)
    return result


@router.post('/activity', status_code=201)
def create_activity(payload: ActivityIn):
    with connection() as conn:
        _ready(conn)
        log_activity(
            conn, payload.event_type, payload.title, payload.details, payload.entity_type, payload.entity_id,
            json.dumps(payload.metadata or {}, ensure_ascii=False),
        )
        row = conn.execute('SELECT * FROM activity_log ORDER BY id DESC LIMIT 1').fetchone()
    return dict(row)


@router.get('/changelog')
def changelog():
    try:
        data = json.loads(CHANGELOG.read_text(encoding='utf-8'))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(500, 'Changelog indisponible') from exc
    releases = list(data.get('releases') or [])
    current_release = KNOWN_RELEASES.get(VERSION)
    if current_release and (not releases or releases[0].get('version') != VERSION):
        releases.insert(0, current_release)
    return {**data, 'releases': releases}


@router.get('/system')
def system_center():
    with connection() as conn:
        _ready(conn)
        counts = {}
        for table in ('accounts', 'transactions', 'planned_transactions', 'financial_goals', 'imports', 'payroll_records', 'activity_log'):
            try:
                counts[table] = int(conn.execute(f'SELECT COUNT(*) n FROM {table}').fetchone()['n'])
            except Exception:
                counts[table] = None
        flags = [dict(r) for r in conn.execute('SELECT key,enabled,description,updated_at FROM feature_flags ORDER BY key').fetchall()]
    try:
        db_size = DB_PATH.stat().st_size
    except OSError:
        db_size = 0
    return {
        'version': VERSION,
        'commit': os.getenv('FLOW_GIT_COMMIT', ''),
        'database': {'path': str(DB_PATH), 'size_bytes': db_size, 'counts': counts},
        'feature_flags': flags,
        'pwa': {'expected_version': VERSION, 'cache_name': f'flow-v{VERSION}'},
    }


@router.patch('/feature-flags/{key}')
def update_feature_flag(key: str, payload: FeatureFlagIn):
    with connection() as conn:
        _ready(conn)
        if not conn.execute('SELECT 1 FROM feature_flags WHERE key=?', (key,)).fetchone():
            raise HTTPException(404, 'Feature flag introuvable')
        conn.execute('UPDATE feature_flags SET enabled=?,updated_at=CURRENT_TIMESTAMP WHERE key=?', (int(payload.enabled), key))
        log_activity(conn, 'settings', 'Feature flag modifié', f'{key} = {payload.enabled}', 'feature_flag', key)
        row = conn.execute('SELECT key,enabled,description,updated_at FROM feature_flags WHERE key=?', (key,)).fetchone()
    return dict(row)
