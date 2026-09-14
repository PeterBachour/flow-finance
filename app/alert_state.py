import hashlib
import json
from datetime import date, datetime, timedelta, timezone


DEFAULT_PREFS = {
    'snapshot_max_age_days': 3,
    'upcoming_window_days': 7,
}


def ensure_alert_schema(conn) -> None:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS alert_state (
        code TEXT PRIMARY KEY,
        fingerprint TEXT NOT NULL,
        title TEXT NOT NULL,
        severity TEXT NOT NULL,
        first_seen_at TEXT NOT NULL,
        last_seen_at TEXT NOT NULL,
        snoozed_until TEXT,
        resolved_at TEXT
    );
    CREATE TABLE IF NOT EXISTS alert_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT NOT NULL,
        fingerprint TEXT NOT NULL,
        title TEXT NOT NULL,
        severity TEXT NOT NULL,
        event TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    """)
    for key, value in DEFAULT_PREFS.items():
        conn.execute('INSERT OR IGNORE INTO settings(key,value) VALUES(?,?)', (f'alert_{key}', str(value)))


def alert_fingerprint(alert: dict) -> str:
    payload = json.dumps({
        'code': alert.get('code'),
        'severity': alert.get('severity'),
        'title': alert.get('title'),
        'message': alert.get('message'),
    }, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def get_alert_preferences(conn) -> dict:
    ensure_alert_schema(conn)
    prefs = dict(DEFAULT_PREFS)
    for key in prefs:
        row = conn.execute('SELECT value FROM settings WHERE key=?', (f'alert_{key}',)).fetchone()
        if row:
            try:
                prefs[key] = max(1, int(row['value']))
            except (TypeError, ValueError):
                pass
    return prefs


def save_alert_preferences(conn, *, snapshot_max_age_days: int, upcoming_window_days: int) -> dict:
    ensure_alert_schema(conn)
    values = {
        'snapshot_max_age_days': max(1, min(snapshot_max_age_days, 30)),
        'upcoming_window_days': max(1, min(upcoming_window_days, 31)),
    }
    for key, value in values.items():
        conn.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (f'alert_{key}', str(value)))
    return values


def sync_alerts(conn, alerts: list[dict], now: datetime | None = None) -> list[dict]:
    ensure_alert_schema(conn)
    now = now or datetime.now(timezone.utc)
    now_iso = now.isoformat()
    active_codes = set()
    visible = []
    for alert in alerts:
        code = alert['code']
        active_codes.add(code)
        fingerprint = alert_fingerprint(alert)
        row = conn.execute('SELECT * FROM alert_state WHERE code=?', (code,)).fetchone()
        changed = not row or row['fingerprint'] != fingerprint
        if not row:
            conn.execute('INSERT INTO alert_state(code,fingerprint,title,severity,first_seen_at,last_seen_at) VALUES(?,?,?,?,?,?)', (code, fingerprint, alert['title'], alert['severity'], now_iso, now_iso))
            conn.execute('INSERT INTO alert_history(code,fingerprint,title,severity,event) VALUES(?,?,?,?,?)', (code, fingerprint, alert['title'], alert['severity'], 'opened'))
            snoozed_until = None
        else:
            if changed:
                conn.execute('UPDATE alert_state SET fingerprint=?,title=?,severity=?,last_seen_at=?,snoozed_until=NULL,resolved_at=NULL WHERE code=?', (fingerprint, alert['title'], alert['severity'], now_iso, code))
                conn.execute('INSERT INTO alert_history(code,fingerprint,title,severity,event) VALUES(?,?,?,?,?)', (code, fingerprint, alert['title'], alert['severity'], 'changed'))
                snoozed_until = None
            else:
                conn.execute('UPDATE alert_state SET last_seen_at=?,resolved_at=NULL WHERE code=?', (now_iso, code))
                snoozed_until = row['snoozed_until']
        hidden = False
        if snoozed_until:
            try:
                hidden = datetime.fromisoformat(snoozed_until) > now
            except ValueError:
                hidden = False
        if not hidden:
            visible.append({**alert, 'fingerprint': fingerprint})

    open_rows = conn.execute('SELECT code,fingerprint,title,severity FROM alert_state WHERE resolved_at IS NULL').fetchall()
    for row in open_rows:
        if row['code'] in active_codes:
            continue
        conn.execute('UPDATE alert_state SET resolved_at=?,snoozed_until=NULL WHERE code=?', (now_iso, row['code']))
        conn.execute('INSERT INTO alert_history(code,fingerprint,title,severity,event) VALUES(?,?,?,?,?)', (row['code'], row['fingerprint'], row['title'], row['severity'], 'resolved'))
    return visible


def snooze_alert(conn, code: str, days: int = 1, now: datetime | None = None) -> str:
    ensure_alert_schema(conn)
    now = now or datetime.now(timezone.utc)
    row = conn.execute('SELECT * FROM alert_state WHERE code=? AND resolved_at IS NULL', (code,)).fetchone()
    if not row:
        raise KeyError(code)
    until = now + timedelta(days=max(1, min(days, 30)))
    until_iso = until.isoformat()
    conn.execute('UPDATE alert_state SET snoozed_until=? WHERE code=?', (until_iso, code))
    conn.execute('INSERT INTO alert_history(code,fingerprint,title,severity,event) VALUES(?,?,?,?,?)', (code, row['fingerprint'], row['title'], row['severity'], f'snoozed:{days}d'))
    return until_iso


def alert_history(conn, limit: int = 50) -> list[dict]:
    ensure_alert_schema(conn)
    rows = conn.execute('SELECT * FROM alert_history ORDER BY id DESC LIMIT ?', (max(1, min(limit, 200)),)).fetchall()
    return [dict(row) for row in rows]
