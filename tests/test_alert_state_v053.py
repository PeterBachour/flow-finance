import sqlite3
from datetime import datetime, timezone

from app.alert_state import alert_fingerprint, ensure_alert_schema, snooze_alert, sync_alerts


def db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute('CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
    ensure_alert_schema(conn)
    return conn


def sample(message='Risque A'):
    return {'code':'risk','severity':'warning','title':'Alerte','message':message,'action':'Agir'}


def test_same_alert_can_be_snoozed():
    conn=db();now=datetime(2026,9,8,tzinfo=timezone.utc)
    assert len(sync_alerts(conn,[sample()],now))==1
    snooze_alert(conn,'risk',1,now)
    assert sync_alerts(conn,[sample()],now)==[]


def test_changed_alert_reappears_even_if_snoozed():
    conn=db();now=datetime(2026,9,8,tzinfo=timezone.utc)
    sync_alerts(conn,[sample()],now);snooze_alert(conn,'risk',7,now)
    visible=sync_alerts(conn,[sample('Risque B')],now)
    assert len(visible)==1
    assert visible[0]['fingerprint']==alert_fingerprint(sample('Risque B'))


def test_resolved_alert_is_recorded():
    conn=db();now=datetime(2026,9,8,tzinfo=timezone.utc)
    sync_alerts(conn,[sample()],now)
    sync_alerts(conn,[],now)
    row=conn.execute("SELECT event FROM alert_history ORDER BY id DESC LIMIT 1").fetchone()
    assert row['event']=='resolved'
