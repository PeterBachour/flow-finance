from datetime import date
from pathlib import Path
import sqlite3

import app.v5_routes as routes
import app.v52_decisions as decisions


ROOT = Path(__file__).resolve().parents[1]
STATIC = ROOT / 'app' / 'static'


def _conn():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.execute(
        '''CREATE TABLE decision_inbox_status(
             item_key TEXT PRIMARY KEY,
             status TEXT NOT NULL,
             note TEXT,
             updated_at TEXT NOT NULL
           )'''
    )
    return conn


def test_v52_recent_closed_keeps_note_timestamp_and_newest_first():
    conn = _conn()
    conn.executemany(
        'INSERT INTO decision_inbox_status(item_key,status,note,updated_at) VALUES(?,?,?,?)',
        [
            ('goal:7', 'done', 'Contribution ajustée', '2026-09-11 20:00:00'),
            ('overdue:3', 'dismissed', 'Échéance annulée', '2026-09-11 21:00:00'),
        ],
    )
    history = decisions._recent_closed(conn, [
        {'key': 'goal:7', 'type': 'goal_risk', 'priority': 'high', 'title': 'Objectif', 'status': 'done'},
        {'key': 'overdue:3', 'type': 'missing_expected', 'priority': 'high', 'title': 'Échéance', 'status': 'dismissed'},
        {'key': 'balance:1', 'type': 'stale_balance', 'priority': 'medium', 'title': 'Solde', 'status': 'open'},
    ])
    assert [item['key'] for item in history] == ['overdue:3', 'goal:7']
    assert history[0]['note'] == 'Échéance annulée'
    assert history[0]['status_updated_at'] == '2026-09-11 21:00:00'
    assert all(item['status_editable'] is True for item in history)


def test_v52_decision_center_exposes_recent_closed_without_mixing_recommendations(monkeypatch):
    conn = _conn()
    conn.execute(
        'INSERT INTO decision_inbox_status(item_key,status,note,updated_at) VALUES(?,?,?,?)',
        ('goal:7', 'done', 'Traité', '2026-09-11 21:30:00'),
    )
    monkeypatch.setattr(decisions, 'build_v5_recommendations', lambda *a, **k: {
        'recommendations': [{
            'key': 'keep_daily_pace', 'kind': 'pace', 'priority': 'positive',
            'title': 'Maintenir le rythme', 'explanation': 'Stable',
            'suggested_action': 'Continuer', 'source': 'decision_cockpit',
            'impact_cents': 2500, 'evidence': {}, 'read_only': True,
        }]
    })
    result = decisions.build_v52_decision_center(
        conn,
        as_of=date(2026, 9, 11),
        financial_decisions=[],
        closed_decisions=[{
            'key': 'goal:7', 'type': 'goal_risk', 'priority': 'high',
            'title': 'Objectif à ajuster', 'detail': 'Contribution revue', 'status': 'done',
        }],
        quality_review_count=0,
        months=6,
    )
    assert result['recent_closed'][0]['key'] == 'goal:7'
    assert result['recent_closed'][0]['status'] == 'done'
    assert result['recent_closed'][0]['note'] == 'Traité'
    assert result['primary']['key'] == 'keep_daily_pace'


def test_v52_closed_financial_decision_can_be_reopened_with_existing_contract(monkeypatch):
    monkeypatch.setattr(routes, 'financial_decisions', lambda include_closed=False: {
        'items': [{'key': 'goal:7', 'type': 'goal_risk', 'status': 'done'}]
    })
    calls = []

    def fake_set(item_key, payload):
        calls.append((item_key, payload.status, payload.note))
        return {'key': item_key, 'status': payload.status, 'note': payload.note}

    monkeypatch.setattr(routes, 'set_inbox_status', fake_set)
    result = routes.update_decision_center_status(
        'goal:7',
        routes.InboxStatusIn(status='open', note='Contribution ajustée'),
    )
    assert calls == [('goal:7', 'open', 'Contribution ajustée')]
    assert result['status'] == 'open'
    assert result['financial_data_changed'] is False


def test_v52_history_ui_supports_optional_note_and_reopen_without_financial_mutation():
    js = (STATIC / 'v5-recommendations-ui.js').read_text(encoding='utf-8')
    route_source = (ROOT / 'app' / 'v5_routes.py').read_text(encoding='utf-8')
    service = (ROOT / 'app' / 'v52_decisions.py').read_text(encoding='utf-8')
    assert 'recent_closed' in js
    assert 'Historique récent' in js
    assert 'Note facultative' in js
    assert 'data-v52-status="open"' in js
    assert 'Rouvrir' in js
    assert 'closed_decisions=all_decisions.get' in route_source
    assert "status IN ('done','dismissed')" in service
    assert 'INSERT INTO transactions' not in route_source
    assert 'UPDATE transactions' not in route_source
