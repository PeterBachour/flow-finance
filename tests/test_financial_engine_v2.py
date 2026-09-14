import sqlite3
from datetime import date

from app.financial_engine_v2 import (
    _dedupe,
    _recurring_events,
    build_decision_cockpit,
    category_spending,
    confidence_label,
    month_totals,
    safe_status,
)
from app.forecast import PlannedEvent
from app.safe_to_spend import calculate_safe_to_spend
from app.v2_migrations import ensure_v2_schema


def conn():
    db = sqlite3.connect(':memory:')
    db.row_factory = sqlite3.Row
    db.executescript('''
    CREATE TABLE accounts(id INTEGER PRIMARY KEY,name TEXT,kind TEXT,current_balance_cents INTEGER,is_active INTEGER DEFAULT 1);
    CREATE TABLE transactions(
      id INTEGER PRIMARY KEY,account_id INTEGER,booking_date TEXT,amount_cents INTEGER,label TEXT,
      category TEXT,transaction_type TEXT DEFAULT 'expense',is_internal_transfer INTEGER DEFAULT 0
    );
    CREATE TABLE recurring_transactions(id INTEGER PRIMARY KEY,account_id INTEGER,label TEXT,amount_cents INTEGER,day_of_month INTEGER,category TEXT,kind TEXT,certainty TEXT,is_active INTEGER DEFAULT 1);
    CREATE TABLE financial_goals(id INTEGER PRIMARY KEY,name TEXT,target_cents INTEGER,is_active INTEGER DEFAULT 1);
    ''')
    ensure_v2_schema(db)
    return db


def cockpit_conn(balance_as_of: str | None):
    db = conn()
    db.executescript('''
    ALTER TABLE accounts ADD COLUMN balance_as_of TEXT;
    ALTER TABLE accounts ADD COLUMN include_in_safe_to_spend INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE accounts ADD COLUMN source_key TEXT;
    ALTER TABLE transactions ADD COLUMN status TEXT NOT NULL DEFAULT 'confirmed';
    ALTER TABLE recurring_transactions ADD COLUMN usual_day INTEGER;
    ALTER TABLE recurring_transactions ADD COLUMN next_expected_date TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN last_seen_date TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN source_type TEXT;
    ALTER TABLE recurring_transactions ADD COLUMN detection_status TEXT NOT NULL DEFAULT 'accepted';
    ALTER TABLE recurring_transactions ADD COLUMN tolerance_cents INTEGER NOT NULL DEFAULT 0;
    ALTER TABLE financial_goals ADD COLUMN monthly_contribution_cents INTEGER NOT NULL DEFAULT 0;
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
    db.execute("INSERT INTO settings(key,value) VALUES('safety_reserve_cents','10000')")
    db.execute(
        "INSERT INTO accounts(id,name,kind,current_balance_cents,is_active,balance_as_of,include_in_safe_to_spend) VALUES(1,'Courant','checking',100000,1,?,1)",
        (balance_as_of,),
    )
    return db


def test_confidence_labels_are_explicit():
    assert confidence_label(0.95) == 'confirmed'
    assert confidence_label(0.80) == 'probable'
    assert confidence_label(0.60) == 'estimated'
    assert confidence_label(0.20) == 'uncertain'


def test_safe_status_has_critical_floor():
    assert safe_status(0, 20_000, 2_000) == 'critical'
    assert safe_status(5_000, 20_000, 2_000) == 'tight'
    assert safe_status(25_000, 20_000, 2_000) == 'comfortable'


def test_month_totals_exclude_internal_transfers_and_excluded_rows():
    db = conn()
    db.executemany(
        'INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer,exclude_from_analytics) VALUES(1,?,?,?,?,?,?,?)',
        [
            ('2026-09-02', -5_000, 'Restaurant', 'Restaurants', 'expense', 0, 0),
            ('2026-09-03', -20_000, 'Vers épargne', 'Transfert interne', 'transfer', 1, 0),
            ('2026-09-04', -7_000, 'Exception ignorée', 'Shopping', 'expense', 0, 1),
            ('2026-09-25', 300_000, 'Salaire', 'Salaire', 'income', 0, 0),
        ],
    )
    totals = month_totals(db, '2026-09')
    assert totals['spent_cents'] == 5_000
    assert totals['income_cents'] == 300_000
    assert totals['transfers_cents'] == 20_000
    assert category_spending(db, '2026-09') == {'Restaurants': 5_000}


def test_refunds_reimbursements_and_transfer_types_do_not_pollute_analytics():
    db = conn()
    db.executemany(
        'INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer,exclude_from_analytics) VALUES(1,?,?,?,?,?,?,0)',
        [
            ('2026-09-02', -5_000, 'Restaurant', 'Restaurants', 'expense', 0),
            ('2026-09-03', -8_000, 'Avance pro', 'Restaurants', 'reimbursement', 0),
            ('2026-09-04', -10_000, 'Mouvement compte', 'Épargne', 'transfer', 0),
            ('2026-09-05', -3_000, 'Correction remboursement', 'Shopping', 'refund', 0),
            ('2026-09-06', 8_000, 'Remboursement employeur', 'Remboursement', 'reimbursement', 0),
            ('2026-09-07', 3_000, 'Remboursement carte', 'Remboursement', 'refund', 0),
            ('2026-09-25', 300_000, 'Salaire', 'Salaire', 'income', 0),
        ],
    )
    totals = month_totals(db, '2026-09')
    assert totals['spent_cents'] == 5_000
    assert totals['income_cents'] == 300_000
    assert totals['saving_cents'] == 0
    assert totals['net_cents'] == 295_000
    assert category_spending(db, '2026-09') == {'Restaurants': 5_000}


def test_dedupe_prefers_planned_commitment_with_small_date_amount_and_label_variation():
    events = [
        PlannedEvent(date(2026, 9, 15), -10_000, 'Netflix France', 'confirmed', 'commitment', 'planned'),
        PlannedEvent(date(2026, 9, 17), -9_900, 'Netflix', 'expected', 'commitment', 'recurring'),
    ]
    result = _dedupe(events)
    assert len(result) == 1
    assert result[0].source == 'planned'


def test_dedupe_keeps_distinct_commitments():
    events = [
        PlannedEvent(date(2026, 9, 15), -10_000, 'Netflix', 'confirmed', 'commitment', 'planned'),
        PlannedEvent(date(2026, 9, 16), -10_000, 'Navigo', 'expected', 'commitment', 'recurring'),
    ]
    result = _dedupe(events)
    assert len(result) == 2


def test_recurring_events_exclude_unvalidated_rows():
    db = conn()
    db.execute(
        "INSERT INTO recurring_transactions(account_id,label,amount_cents,day_of_month,category,kind,certainty,is_active,validation_status) VALUES(1,'Draft bill',-5000,20,'Télécom','commitment','expected',1,'pending')"
    )
    db.execute(
        "INSERT INTO recurring_transactions(account_id,label,amount_cents,day_of_month,category,kind,certainty,is_active,validation_status) VALUES(1,'Validated bill',-6000,21,'Télécom','commitment','expected',1,'validated')"
    )
    events = _recurring_events(db, date(2026, 9, 13), months_ahead=0)
    assert [event.label for event in events] == ['Validated bill']


def test_cockpit_hides_safe_to_spend_when_balance_is_stale():
    db = cockpit_conn('2026-09-01')
    result = build_decision_cockpit(db, date(2026, 9, 13))
    safe = result['safe_to_spend']
    assert safe['availability_status'] == 'unavailable_stale_balance'
    assert safe['is_available'] is False
    assert safe['until_income_cents'] is None
    assert safe['today_cents'] is None
    assert safe['week_cents'] is None


def test_cockpit_hides_safe_to_spend_when_balance_date_is_missing():
    db = cockpit_conn(None)
    result = build_decision_cockpit(db, date(2026, 9, 13))
    safe = result['safe_to_spend']
    assert safe['availability_status'] == 'unavailable_no_balance_date'
    assert safe['until_income_cents'] is None


def test_safe_to_spend_requires_balance_date_on_every_included_account():
    db = cockpit_conn('2026-09-13')
    db.execute(
        "INSERT INTO accounts(id,name,kind,current_balance_cents,is_active,balance_as_of,include_in_safe_to_spend) VALUES(2,'Secondaire','checking',50000,1,NULL,1)"
    )
    result = calculate_safe_to_spend(db, as_of=date(2026, 9, 13), stale_reference_date=date(2026, 9, 13))
    assert result.safe_to_spend_status == 'unavailable_no_balance_date'
    assert result.safe_to_spend_cents is None
    assert result.balance_age_days == 999999


def test_safe_to_spend_treats_invalid_balance_date_as_unavailable_not_exception():
    db = cockpit_conn('not-a-date')
    result = calculate_safe_to_spend(db, as_of=date(2026, 9, 13), stale_reference_date=date(2026, 9, 13))
    assert result.safe_to_spend_status == 'unavailable_no_balance_date'
    assert result.safe_to_spend_cents is None


def test_safe_to_spend_excludes_internal_transfer_recurrence():
    db = cockpit_conn('2026-09-13')
    db.execute(
        """INSERT INTO recurring_transactions(
               account_id,label,amount_cents,day_of_month,category,kind,certainty,is_active,
               validation_status,usual_day,next_expected_date,last_seen_date,source_type,detection_status,tolerance_cents
           ) VALUES(1,'Virement épargne',-10000,20,'Transfert interne','commitment','expected',1,
                    'validated',20,'2026-09-20','2026-09-01','history','accepted',0)"""
    )
    result = calculate_safe_to_spend(db, as_of=date(2026, 9, 13), stale_reference_date=date(2026, 9, 13))
    assert result.recurring_commitments_cents == 0
    assert result.safe_to_spend_cents == 90_000


def test_cockpit_uses_validated_safe_to_spend_as_authoritative_base():
    db = cockpit_conn('2026-09-13')
    db.execute(
        "INSERT INTO planned_transactions(account_id,due_date,amount_cents,label,kind,certainty,status) VALUES(1,'2026-09-20',-20000,'Loyer','commitment','confirmed','planned')"
    )
    result = build_decision_cockpit(db, date(2026, 9, 13))
    safe = result['safe_to_spend']
    assert safe['availability_status'] == 'available'
    assert safe['until_income_cents'] == 70_000
    assert result['validated_safe_to_spend']['calculated_safe_to_spend_cents'] == 70_000


def test_funded_goal_allocation_is_informational_not_deducted_twice():
    db = cockpit_conn('2026-09-13')
    db.execute(
        "INSERT INTO financial_goals(id,name,target_cents,is_active,monthly_contribution_cents,include_in_safe_to_spend) VALUES(1,'Apport',300000,1,0,1)"
    )
    db.execute(
        "INSERT INTO goal_allocations(goal_id,account_id,amount_cents,allocated_on,note) VALUES(1,1,30000,'2026-09-10','déjà financé')"
    )
    result = build_decision_cockpit(db, date(2026, 9, 13))
    safe = result['safe_to_spend']
    assert safe['availability_status'] == 'available'
    assert safe['until_income_cents'] == 90_000
    assert safe['explanation']['goal_allocations_cents'] == 30_000
    assert safe['explanation']['goal_allocations_cash_impact_cents'] == 0
    assert safe['explanation']['goal_allocation_mode'] == 'funded_allocation_already_in_balance'


def test_cockpit_is_deterministic_for_identical_data_and_date():
    db = cockpit_conn('2026-09-13')
    db.execute(
        "INSERT INTO planned_transactions(account_id,due_date,amount_cents,label,kind,certainty,status) VALUES(1,'2026-09-20',-20000,'Loyer','commitment','confirmed','planned')"
    )
    db.execute(
        "INSERT INTO recurring_transactions(account_id,label,amount_cents,day_of_month,category,kind,certainty,is_active,validation_status) VALUES(1,'Téléphone',-2500,22,'Télécom','commitment','expected',1,'validated')"
    )
    first = build_decision_cockpit(db, date(2026, 9, 13))
    second = build_decision_cockpit(db, date(2026, 9, 13))
    assert first == second
