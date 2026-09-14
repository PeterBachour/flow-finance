import sqlite3
from datetime import date

from app.forecast_v6 import build_v6_daily_trajectory
from app.v2_migrations import ensure_v2_schema


def database():
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    CREATE TABLE accounts(
      id INTEGER PRIMARY KEY,name TEXT,kind TEXT,current_balance_cents INTEGER,is_active INTEGER DEFAULT 1,
      balance_as_of TEXT,include_in_safe_to_spend INTEGER DEFAULT 1
    );
    CREATE TABLE transactions(
      id INTEGER PRIMARY KEY,account_id INTEGER,booking_date TEXT,amount_cents INTEGER,label TEXT,
      category TEXT,transaction_type TEXT DEFAULT 'expense',is_internal_transfer INTEGER DEFAULT 0,
      status TEXT DEFAULT 'confirmed'
    );
    CREATE TABLE recurring_transactions(
      id INTEGER PRIMARY KEY,account_id INTEGER,label TEXT,amount_cents INTEGER,day_of_month INTEGER,
      category TEXT,kind TEXT,certainty TEXT,is_active INTEGER DEFAULT 1
    );
    CREATE TABLE financial_goals(id INTEGER PRIMARY KEY,name TEXT,target_cents INTEGER,is_active INTEGER DEFAULT 1);
    CREATE TABLE planned_transactions(
      id INTEGER PRIMARY KEY,account_id INTEGER,due_date TEXT,amount_cents INTEGER,label TEXT,
      kind TEXT DEFAULT 'commitment',certainty TEXT DEFAULT 'confirmed',status TEXT DEFAULT 'planned'
    );
    CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
    CREATE TABLE goal_allocations(id INTEGER PRIMARY KEY,goal_id INTEGER,account_id INTEGER,amount_cents INTEGER,allocated_on TEXT,note TEXT);
    CREATE TABLE financial_rules(id INTEGER PRIMARY KEY,rule_type TEXT,name TEXT,value_text TEXT,value_cents INTEGER,start_date TEXT,end_date TEXT,status TEXT DEFAULT 'active',source_key TEXT);
    ''')
    ensure_v2_schema(conn)
    conn.executescript('''
    ALTER TABLE recurring_transactions ADD COLUMN usual_day INTEGER;
    ALTER TABLE recurring_transactions ADD COLUMN next_expected_date TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN last_seen_date TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN source_type TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN detection_status TEXT NOT NULL DEFAULT 'accepted';
    ALTER TABLE recurring_transactions ADD COLUMN tolerance_cents INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE recurring_transactions ADD COLUMN confidence REAL;
    ALTER TABLE financial_goals ADD COLUMN monthly_contribution_cents INTEGER NOT NULL DEFAULT 0;
    ''')
    conn.execute("INSERT INTO settings VALUES('safety_reserve_cents','10000')")
    conn.execute("INSERT INTO accounts(id,name,kind,current_balance_cents,is_active,balance_as_of,include_in_safe_to_spend) VALUES(1,'Courant','checking',100000,1,'2026-09-14',1)")
    return conn


def test_v62_builds_aligned_daily_scenarios_and_uncertainty_band():
    conn = database()
    conn.execute("INSERT INTO planned_transactions VALUES(1,1,'2026-09-20',-20000,'Loyer','commitment','confirmed','planned')")
    result = build_v6_daily_trajectory(
        conn, as_of=date(2026, 9, 14), horizon_days=10,
        stale_reference_date=date(2026, 9, 14),
    )
    assert result['schema_version'] == '6.2'
    assert len(result['scenarios']['engaged']['timeline']) == 11
    assert len(result['uncertainty_band']) == 11
    assert result['scenarios']['engaged']['low_point'] == {
        'date': '2026-09-20', 'balance_cents': 80000
    }
    assert result['controls']['safety_reserve_is_not_an_outflow'] is True
    assert result['controls']['read_only'] is True


def test_v62_deduplicates_planned_and_recurring_commitments():
    conn = database()
    conn.execute("INSERT INTO planned_transactions VALUES(1,1,'2026-09-20',-20000,'Téléphone','commitment','confirmed','planned')")
    conn.execute(
        """INSERT INTO recurring_transactions(
          id,account_id,label,amount_cents,day_of_month,category,kind,certainty,is_active,
          validation_status,confidence_score,usual_day,next_expected_date,last_seen_date,
          source_type,detection_status,tolerance_cents,confidence
        ) VALUES(1,1,'Téléphone',-20000,20,'Télécom','commitment','expected',1,
          'validated',0.9,20,'2026-09-20','2026-09-01','history','accepted',0,0.9)"""
    )
    result = build_v6_daily_trajectory(
        conn, as_of=date(2026, 9, 14), horizon_days=10,
        stale_reference_date=date(2026, 9, 14),
    )
    events = [
        event for point in result['scenarios']['realistic']['timeline']
        for event in point['events']
    ]
    assert len(events) == 1
    assert events[0]['source'] == 'planned'
    assert result['scenarios']['realistic']['closing_balance_cents'] == 80000


def test_v62_preserves_unavailable_status_for_stale_balance():
    conn = database()
    conn.execute("UPDATE accounts SET balance_as_of='2026-08-01'")
    result = build_v6_daily_trajectory(
        conn, as_of=date(2026, 9, 14), horizon_days=10,
        stale_reference_date=date(2026, 9, 14),
    )
    assert result['availability']['available'] is False
    assert result['safe_to_spend']['total_cents'] is None
