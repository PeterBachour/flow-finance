import json
import sqlite3
from datetime import date

import app.forecast_accuracy as accuracy


def _forecast(balance_cents=120000):
    timeline = [
        {'date': '2026-09-27', 'balance_cents': balance_cents},
        {'date': '2026-09-28', 'balance_cents': balance_cents - 1000},
    ]
    return {
        'schema_version': '6.2',
        'availability': {'available': True, 'status': 'available'},
        'safe_to_spend': {'total_cents': 50000},
        'horizon': {'end': '2026-09-28'},
        'confidence': {'score': 90, 'level': 'confirmed'},
        'scenarios': {
            mode: {
                'low_point': {'date': '2026-09-28', 'balance_cents': balance_cents - 1000},
                'timeline': timeline,
            }
            for mode in accuracy.SCENARIO_MODES
        },
    }


def _snapshot_db():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
        CREATE TABLE accounts(id INTEGER PRIMARY KEY,is_active INTEGER,include_in_safe_to_spend INTEGER);
        CREATE TABLE forecast_snapshots(
            id INTEGER PRIMARY KEY,as_of TEXT NOT NULL,horizon TEXT NOT NULL,mode TEXT NOT NULL,
            safe_to_spend_cents INTEGER NOT NULL,low_point_cents INTEGER NOT NULL,
            low_point_date TEXT NOT NULL,confidence_score REAL,payload_json TEXT NOT NULL,
            UNIQUE(as_of,horizon,mode)
        );
        CREATE TABLE account_balance_history(
            id INTEGER PRIMARY KEY,account_id INTEGER,balance_cents INTEGER,balance_date TEXT,
            status TEXT,source_type TEXT
        );
    ''')
    conn.execute('INSERT INTO accounts VALUES(1,1,1)')
    return conn


def test_daily_snapshot_capture_is_idempotent_and_omits_event_labels(monkeypatch):
    conn = _snapshot_db()
    monkeypatch.setattr(accuracy, 'build_v6_daily_trajectory', lambda *a, **k: _forecast())
    first = accuracy.capture_daily_forecast(conn, as_of=date(2026, 9, 27))
    assert first['captured_modes'] == ['engaged', 'realistic', 'prudent']
    assert first['status'] == 'captured'

    monkeypatch.setattr(accuracy, 'build_v6_daily_trajectory', lambda *a, **k: _forecast(99000))
    second = accuracy.capture_daily_forecast(conn, as_of=date(2026, 9, 27))
    assert second['captured_modes'] == []
    assert second['status'] == 'already_captured'

    row = conn.execute("SELECT payload_json FROM forecast_snapshots WHERE mode='realistic'").fetchone()
    payload = json.loads(row['payload_json'])
    assert payload['timeline'][0]['balance_cents'] == 120000
    assert 'label' not in payload['timeline'][0]
    assert conn.execute('SELECT COUNT(*) FROM forecast_snapshots').fetchone()[0] == 3
    conn.close()


def test_forecast_accuracy_uses_confirmed_statement_balances_only():
    conn = _snapshot_db()
    timeline = [{'date': '2026-09-11', 'balance_cents': 105000}]
    for mode in accuracy.SCENARIO_MODES:
        conn.execute(
            '''INSERT INTO forecast_snapshots(
               as_of,horizon,mode,safe_to_spend_cents,low_point_cents,low_point_date,confidence_score,payload_json
            ) VALUES(?,?,?,?,?,?,?,?)''',
            ('2026-09-10','2026-09-20',mode,50000,90000,'2026-09-20',90,
             json.dumps({'account_ids':[1,2],'timeline':timeline})),
        )
    conn.execute(
        "INSERT INTO account_balance_history VALUES(1,1,100000,'2026-09-11','confirmed','bank_statement')"
    )

    result = accuracy.build_forecast_accuracy(conn, as_of=date(2026, 9, 20), window_days=30)
    assert result['status'] == 'insufficient_history'
    assert result['skipped_incomplete_actual_count'] == 3
    assert all(mode['comparison_count'] == 0 for mode in result['modes'].values())
    assert result['read_only'] is True
    conn.close()


def test_forecast_accuracy_reports_signed_error_and_mean_absolute_error():
    conn = _snapshot_db()
    payload = {'account_ids':[1],'timeline':[
        {'date':'2026-09-11','balance_cents':105000},
        {'date':'2026-09-12','balance_cents':110000},
    ]}
    conn.execute(
        '''INSERT INTO forecast_snapshots(
           as_of,horizon,mode,safe_to_spend_cents,low_point_cents,low_point_date,confidence_score,payload_json
        ) VALUES(?,?,?,?,?,?,?,?)''',
        ('2026-09-10','2026-09-20','realistic',50000,90000,'2026-09-20',90,json.dumps(payload)),
    )
    conn.executemany(
        "INSERT INTO account_balance_history VALUES(?,?,?,?,?,?)",
        [
            (1,1,100000,'2026-09-11','confirmed','bank_statement'),
            (2,1,115000,'2026-09-12','confirmed','bank_statement'),
        ],
    )

    result = accuracy.build_forecast_accuracy(conn, as_of=date(2026, 9, 20), window_days=30)
    realistic = result['modes']['realistic']
    assert result['status'] == 'available'
    assert realistic['comparison_count'] == 2
    assert realistic['mean_absolute_error_cents'] == 5000
    assert realistic['mean_error_cents'] == 0
    conn.close()
