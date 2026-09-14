#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.notion_dataset import GOALS, REFERENCE_SOURCE_ID, REFERENCE_SOURCE_URL, RULES


def cents(value):
    if value is None:
        return None
    return round(float(value) * 100)


def _upsert_rule(conn: sqlite3.Connection, item: dict, now: str) -> None:
    existing = conn.execute(
        'SELECT id FROM financial_rules WHERE source_key=? LIMIT 1',
        (item['key'],),
    ).fetchone()

    values = (
        item['type'], item['name'], item.get('text'), item.get('cents'), item.get('start'), item.get('end'),
        item['status'], item['comment'], 'notion', REFERENCE_SOURCE_ID, REFERENCE_SOURCE_URL,
        item.get('start') or '2026-08-01', 'documented', 0.95, item['key'], now,
    )

    if existing:
        conn.execute(
            '''UPDATE financial_rules SET
                rule_type=?,name=?,value_text=?,value_cents=?,start_date=?,end_date=?,status=?,comment=?,
                source_type=?,source_id=?,source_url=?,source_date=?,source_status=?,confidence=?,source_key=?,imported_at=?
               WHERE id=?''',
            values + (existing['id'],),
        )
    else:
        conn.execute(
            '''INSERT INTO financial_rules(
                rule_type,name,value_text,value_cents,start_date,end_date,status,comment,
                source_type,source_id,source_url,source_date,source_status,confidence,source_key,imported_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            values,
        )


def _upsert_goal(conn: sqlite3.Connection, item: dict, now: str) -> None:
    existing = conn.execute(
        'SELECT id FROM financial_goals WHERE source_key=? OR lower(name)=lower(?) ORDER BY source_key IS NOT NULL DESC LIMIT 1',
        (item['key'], item['name']),
    ).fetchone()

    values = (
        item['name'], cents(item['target']), item['date'], item['priority'], item['active'],
        cents(item['current']), cents(item['monthly']), 'notion', item['source_id'], item['source_url'],
        '2026-07-20', 'documented', 1.0, item['key'], now,
    )

    if existing:
        conn.execute(
            '''UPDATE financial_goals SET
                name=?,target_cents=?,target_date=?,priority=?,is_active=?,current_cents=?,monthly_contribution_cents=?,
                source_type=?,source_id=?,source_url=?,source_date=?,source_status=?,confidence=?,source_key=?,imported_at=?
               WHERE id=?''',
            values + (existing['id'],),
        )
    else:
        conn.execute(
            '''INSERT INTO financial_goals(
                name,target_cents,target_date,priority,is_active,current_cents,monthly_contribution_cents,
                source_type,source_id,source_url,source_date,source_status,confidence,source_key,imported_at
            ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            values,
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Rehydrate only documentary financial rules and goals into a Flow staging DB'
    )
    parser.add_argument('--db', type=Path, required=True)
    args = parser.parse_args()

    db_path = args.db.resolve()
    production = (PROJECT_ROOT / 'data' / 'flow.db').resolve()
    if db_path == production:
        print('error=refusing to modify production flow.db')
        return 2
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 3

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    required = {'financial_rules', 'financial_goals'}
    existing_tables = {
        row['name'] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    missing = sorted(required - existing_tables)
    if missing:
        print(f"error=missing tables: {','.join(missing)}")
        conn.close()
        return 4

    goal_columns = {row['name'] for row in conn.execute('PRAGMA table_info(financial_goals)').fetchall()}
    required_goal_columns = {
        'name', 'target_cents', 'target_date', 'priority', 'is_active', 'current_cents',
        'monthly_contribution_cents', 'source_type', 'source_id', 'source_url', 'source_date',
        'source_status', 'confidence', 'source_key', 'imported_at',
    }
    missing_goal_columns = sorted(required_goal_columns - goal_columns)
    if missing_goal_columns:
        print(f"error=financial_goals missing columns: {','.join(missing_goal_columns)}")
        conn.close()
        return 5

    now = datetime.now(timezone.utc).isoformat()
    before_transactions = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]

    try:
        conn.execute('BEGIN')
        for item in RULES:
            _upsert_rule(conn, item, now)
        for item in GOALS:
            _upsert_goal(conn, item, now)
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise

    rule_count = conn.execute("SELECT COUNT(*) FROM financial_rules WHERE source_type='notion'").fetchone()[0]
    goal_count = conn.execute("SELECT COUNT(*) FROM financial_goals WHERE source_type='notion'").fetchone()[0]
    active_goal_count = conn.execute(
        "SELECT COUNT(*) FROM financial_goals WHERE source_type='notion' AND is_active=1"
    ).fetchone()[0]
    monthly_goal_total = conn.execute(
        "SELECT COALESCE(SUM(monthly_contribution_cents),0) FROM financial_goals WHERE source_type='notion' AND is_active=1"
    ).fetchone()[0]
    after_transactions = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]

    print(f'rules applied={len(RULES)} notion_rows={rule_count}')
    print(
        f'goals applied={len(GOALS)} notion_rows={goal_count} active={active_goal_count} '
        f'raw_monthly={monthly_goal_total/100:.2f}'
    )
    print(
        f'transactions_untouched before={before_transactions} after={after_transactions} '
        f'unchanged={str(before_transactions == after_transactions).lower()}'
    )
    print('upsert_mode=select_then_update_or_insert no_unique_constraint_dependency=true')
    print(f'summary integrity={integrity} mode=documentary_rules_goals_only')
    conn.close()
    return 0 if integrity == 'ok' and before_transactions == after_transactions else 6


if __name__ == '__main__':
    raise SystemExit(main())
