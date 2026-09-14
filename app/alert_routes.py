from datetime import date

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from .alert_engine import build_actionable_alerts
from .alert_state import alert_history, get_alert_preferences, save_alert_preferences, snooze_alert, sync_alerts
from .db import connection
from .month_prep import build_month_preparation, next_month_key
from .projection_routes import dashboard_v2_data

router = APIRouter()


class SnoozeIn(BaseModel):
    days: int = Field(default=1, ge=1, le=30)


class AlertPreferencesIn(BaseModel):
    snapshot_max_age_days: int = Field(default=3, ge=1, le=30)
    upcoming_window_days: int = Field(default=7, ge=1, le=31)


@router.get('/api/alerts')
def actionable_alerts():
    today = date.today()
    dashboard = dashboard_v2_data()
    with connection() as conn:
        month_prep = build_month_preparation(conn, next_month_key(today), today=today)
        prefs = get_alert_preferences(conn)
        raw_alerts = build_actionable_alerts(
            dashboard=dashboard,
            month_prep=month_prep,
            today=today,
            snapshot_max_age_days=prefs['snapshot_max_age_days'],
            upcoming_window_days=prefs['upcoming_window_days'],
        )
        alerts = sync_alerts(conn, raw_alerts)
    return {
        'as_of': today.isoformat(),
        'count': len(alerts),
        'hidden_count': max(0, len(raw_alerts) - len(alerts)),
        'critical_count': sum(1 for item in alerts if item['severity'] == 'critical'),
        'warning_count': sum(1 for item in alerts if item['severity'] == 'warning'),
        'preferences': prefs,
        'alerts': alerts,
    }


@router.post('/api/alerts/{code}/snooze')
def snooze(code: str, payload: SnoozeIn):
    with connection() as conn:
        try:
            until = snooze_alert(conn, code, payload.days)
        except KeyError as exc:
            raise HTTPException(404, 'Alerte active introuvable') from exc
    return {'ok': True, 'code': code, 'snoozed_until': until}


@router.get('/api/alerts/history')
def history(limit: int = Query(default=50, ge=1, le=200)):
    with connection() as conn:
        return alert_history(conn, limit)


@router.get('/api/alerts/preferences')
def preferences():
    with connection() as conn:
        return get_alert_preferences(conn)


@router.put('/api/alerts/preferences')
def update_preferences(payload: AlertPreferencesIn):
    with connection() as conn:
        return save_alert_preferences(
            conn,
            snapshot_max_age_days=payload.snapshot_max_age_days,
            upcoming_window_days=payload.upcoming_window_days,
        )
