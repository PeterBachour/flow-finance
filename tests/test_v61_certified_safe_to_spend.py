import sqlite3
from datetime import date

from app.certified_safe_to_spend import build_certified_safe_to_spend
from app.v2_migrations import ensure_v2_schema


def db(balance_as_of='2026-09-14'):
    conn = sqlite3.connect(':memory:')
    conn.row_factory = sqlite3.Row
    conn.executescript('''
    CREATE TABLE accounts(
      id INTEGER PRIMARY KEY,name TEXT,kind TEXT,current_balance_cents INTEGER,
      is_active INTEGER DEFAULT 1,balance_as_of TEXT,include_in_safe_to_spend INTEGER DEFAULT 1
    );
    CREATE TABLE transactions(
      id INTEGER PRIMARY KEY,account_id INTEGER,booking_date TEXT,amount_cents INTEGER,
      label TEXT,category TEXT,transaction_type TEXT DEFAULT 'expense',is_internal_transfer INTEGER DEFAULT 0
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
    CREATE TABLE goal_allocations(
      id INTEGER PRIMARY KEY,goal_id INTEGER,account_id INTEGER,amount_cents INTEGER,allocated_on TEXT,note TEXT
    );
    CREATE TABLE financial_rules(
      id INTEGER PRIMARY KEY,rule_type TEXT,name TEXT,value_text TEXT,value_cents INTEGER,
      start_date TEXT,end_date TEXT,status TEXT DEFAULT 'active',source_key TEXT
    );
    ''')
    ensure_v2_schema(conn)
    conn.executescript('''
    ALTER TABLE recurring_transactions ADD COLUMN usual_day INTEGER;
    ALTER TABLE recurring_transactions ADD COLUMN next_expected_date TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN last_seen_date TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN source_type TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN detection_status TEXT NOT NULL DEFAULT 'accepted';
    ALTER TABLE recurring_transactions ADD COLUMN tolerance_cents INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE financial_goals ADD COLUMN monthly_contribution_cents INTEGER NOT NULL DEFAULT 0;
    ''')
    conn.execute("INSERT INTO settings VALUES('safety_reserve_cents','10000')")
    conn.execute(
        "INSERT INTO accounts VALUES(1,'Courant','checking',100000,1,?,1)",
        (balance_as_of,),
    )
    return conn


def test_v61_reconstructs_every_component_and_three_projections():
    conn = db()
    conn.execute(
        "INSERT INTO planned_transactions VALUES(1,1,'2026-09-20',-20000,'Loyer','commitment','confirmed','planned')"
    )
    conn.execute(
        """INSERT INTO recurring_transactions(
          id,account_id,label,amount_cents,day_of_month,category,kind,certainty,is_active,
          validation_status,confidence_score,usual_day,next_expected_date,last_seen_date,
          source_type,detection_status,tolerance_cents
        ) VALUES(1,1,'Téléphone',-5000,22,'Télécom','commitment','expected',1,
          'validated',0.9,22,'2026-09-22','2026-09-01','history','accepted',0)"""
    )

    result = build_certified_safe_to_spend(
        conn, as_of=date(2026, 9, 14), horizon_days=10,
        stale_reference_date=date(2026, 9, 14),
    )

    assert result['safe_to_spend']['total_cents'] == 65000
    assert result['components'] == {
        'current_balance_cents': 100000,
        'confirmed_commitments_cents': 20000,
        'probable_recurring_cents': 5000,
        'goal_reservations_cents': 0,
        'safety_reserve_cents': 10000,
    }
    assert result['projections']['engaged']['balance_cents'] == 80000
    assert result['projections']['realistic']['balance_cents'] == 75000
    assert result['projections']['prudent']['balance_cents'] == 65000
    assert result['projections']['engaged']['low_point_date'] == '2026-09-20'
    assert result['controls']['read_only'] is True


def test_v61_never_returns_spendable_amount_for_stale_balance():
    conn = db('2026-08-01')
    result = build_certified_safe_to_spend(
        conn, as_of=date(2026, 9, 14), horizon_days=10,
        stale_reference_date=date(2026, 9, 14),
    )
    assert result['availability']['status'] == 'unavailable_stale_balance'
    assert result['safe_to_spend']['total_cents'] is None
    assert result['safe_to_spend']['today_cents'] is None
    assert result['confidence']['level'] == 'unavailable'


def test_v61_funded_goal_is_not_deducted_twice():
    conn = db()
    conn.execute(
        "INSERT INTO financial_goals(id,name,target_cents,is_active,monthly_contribution_cents,include_in_safe_to_spend) VALUES(1,'Apport',300000,1,10000,1)"
    )
    conn.execute(
        "INSERT INTO goal_allocations VALUES(1,1,1,50000,'2026-09-10','déjà financé')"
    )
    result = build_certified_safe_to_spend(
        conn, as_of=date(2026, 9, 14), horizon_days=10,
        stale_reference_date=date(2026, 9, 14),
    )
    assert result['components']['goal_reservations_cents'] == 0
    assert result['safe_to_spend']['total_cents'] == 90000
    assert result['controls']['goals_not_double_counted'] is True
