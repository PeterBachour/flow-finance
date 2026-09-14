#!/usr/bin/env python3
from __future__ import annotations

import argparse
import calendar
import sqlite3
import sys
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.data_intelligence import ensure_intelligence_schema


VALIDATED = [
    {
        'merchant_key': 'PRLV SEPA SFR',
        'label': 'SFR mobile',
        'amount_cents': -999,
        'usual_day': 12,
        'last_seen_date': '2026-08-12',
        'category': 'Télécom',
        'confidence': 1.0,
        'reason': 'six latest monthly occurrences stable at 9.99 EUR',
    },
    {
        'merchant_key': 'PRLV SEPA NAVIGO ANNUEL - COMUTITRES',
        'label': 'Navigo annuel',
        'amount_cents': -8880,
        'usual_day': 3,
        'last_seen_date': '2026-08-03',
        'category': 'Transport',
        'confidence': 0.99,
        'reason': 'validated active monthly direct debit; current reference amount 88.80 EUR',
    },
    {
        'merchant_key': 'COTISATION MENSUELLE CARTE 2185',
        'label': 'Cotisation carte LCL',
        'amount_cents': -600,
        'usual_day': 26,
        'last_seen_date': '2026-08-26',
        'category': 'Frais bancaires',
        'confidence': 1.0,
        'reason': '26 consecutive monthly occurrences stable at 6.00 EUR',
    },
    {
        'merchant_key': 'PRET IMMOBILIER ECH',
        'label': 'Prêt immobilier',
        'amount_cents': -20720,
        'usual_day': 10,
        'last_seen_date': '2026-08-10',
        'category': 'Crédits',
        'confidence': 1.0,
        'reason': 'current contractual installment validated at 207.20 EUR; historical median ignored',
    },
]

JOINT_FUNDING = {
    'merchant_key': 'VIR INST COMPTE JOINT',
    'label': 'Compte joint',
    'amount_cents': 120000,
    'last_seen_date': '2026-08-29',
    'funded_budget_month': '2026-09',
    'confidence': 1.0,
    'reason': '29 Aug 2026 transfer of 1200 EUR funds September 2026; model by funded budget month, not by day-of-month recurrence',
}


def next_expected(last_seen: date, usual_day: int) -> date:
    year = last_seen.year + (1 if last_seen.month == 12 else 0)
    month = 1 if last_seen.month == 12 else last_seen.month + 1
    day = min(max(1, usual_day), calendar.monthrange(year, month)[1])
    return date(year, month, day)


def _apply_joint_budget_rule(conn: sqlite3.Connection, account_id: int) -> None:
    # The joint-account transfer is a monthly budget allocation. The observed
    # 29 Aug transfer already funds September, so treating it as a recurring
    # 29th-of-month cash commitment would double-reserve September and can make
    # Safe-to-spend incorrectly fall to zero before the next salary.
    conn.execute(
        '''INSERT INTO financial_rules(
               rule_type,name,value_text,value_cents,start_date,status,comment,
               source_type,source_status,confidence,source_key,source_date
           ) VALUES(?,?,?,?,?,'active',?,'manual_validated','confirmed',?,?,?)
           ON CONFLICT(source_key) DO UPDATE SET
               name=excluded.name,value_text=excluded.value_text,value_cents=excluded.value_cents,
               start_date=excluded.start_date,status=excluded.status,comment=excluded.comment,
               source_type=excluded.source_type,source_status=excluded.source_status,
               confidence=excluded.confidence,source_date=excluded.source_date''',
        (
            'budget_transfer',
            JOINT_FUNDING['label'],
            f"funded_budget_month={JOINT_FUNDING['funded_budget_month']}",
            JOINT_FUNDING['amount_cents'],
            f"{JOINT_FUNDING['funded_budget_month']}-01",
            JOINT_FUNDING['reason'],
            JOINT_FUNDING['confidence'],
            'manual:budget-transfer:joint-account',
            JOINT_FUNDING['last_seen_date'],
        ),
    )

    row = conn.execute(
        'SELECT id FROM recurring_transactions WHERE account_id=? AND merchant_key=?',
        (account_id, JOINT_FUNDING['merchant_key']),
    ).fetchone()
    if row:
        conn.execute(
            '''UPDATE recurring_transactions
               SET is_active=0,next_expected_date=NULL,detection_status='budget_cycle',
                   source_type='manual_validated',source_status='confirmed',confidence=?
               WHERE id=?''',
            (JOINT_FUNDING['confidence'], row['id']),
        )

    print(
        f"budget_transfer action=upserted key={JOINT_FUNDING['merchant_key']} label={JOINT_FUNDING['label']} "
        f"amount={JOINT_FUNDING['amount_cents']/100:.2f} funded_budget_month={JOINT_FUNDING['funded_budget_month']} "
        f"last_seen={JOINT_FUNDING['last_seen_date']} recurring_projection=disabled confidence={JOINT_FUNDING['confidence']:.2f} "
        f"reason={JOINT_FUNDING['reason']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description='Apply user-validated current recurring commitments to a Flow staging DB')
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
    ensure_intelligence_schema(conn)

    account = conn.execute('''
        SELECT id FROM accounts
        WHERE is_active=1 AND include_in_safe_to_spend=1
        ORDER BY id LIMIT 1
    ''').fetchone()
    if not account:
        print('error=no active safe-to-spend account')
        return 4
    account_id = int(account['id'])

    applied = 0
    created = 0
    updated = 0
    for item in VALIDATED:
        expected = next_expected(date.fromisoformat(item['last_seen_date']), item['usual_day']).isoformat()
        row = conn.execute(
            'SELECT id FROM recurring_transactions WHERE account_id=? AND merchant_key=?',
            (account_id, item['merchant_key']),
        ).fetchone()
        if row:
            conn.execute('''
                UPDATE recurring_transactions
                SET label=?, amount_cents=?, day_of_month=?, usual_day=?, category=?, kind='commitment',
                    certainty='confirmed', tolerance_cents=0, is_active=1, source_type='manual_validated',
                    source_status='confirmed', confidence=?, last_seen_date=?, next_expected_date=?,
                    detection_status='accepted'
                WHERE id=?
            ''', (
                item['label'], item['amount_cents'], item['usual_day'], item['usual_day'], item['category'],
                item['confidence'], item['last_seen_date'], expected, row['id'],
            ))
            action = 'updated'
            updated += 1
        else:
            conn.execute('''
                INSERT INTO recurring_transactions(
                    account_id,label,amount_cents,day_of_month,category,kind,certainty,tolerance_cents,is_active,
                    source_type,source_status,confidence,merchant_key,recurrence_type,usual_day,day_tolerance,
                    amount_min_cents,amount_max_cents,last_seen_date,next_expected_date,occurrence_count,detection_status
                ) VALUES(?,?,?,?,?,'commitment','confirmed',0,1,'manual_validated','confirmed',?,?,'monthly',?,0,?,?,?, ?,0,'accepted')
            ''', (
                account_id, item['label'], item['amount_cents'], item['usual_day'], item['category'],
                item['confidence'], item['merchant_key'], item['usual_day'], item['amount_cents'], item['amount_cents'],
                item['last_seen_date'], expected,
            ))
            action = 'created'
            created += 1
        applied += 1
        print(
            f"commitment action={action} key={item['merchant_key']} label={item['label']} "
            f"amount={abs(item['amount_cents'])/100:.2f} usual_day={item['usual_day']} "
            f"last_seen={item['last_seen_date']} next_expected={expected} confidence={item['confidence']:.2f} "
            f"reason={item['reason']}"
        )

    _apply_joint_budget_rule(conn, account_id)

    # Known historical commitments must remain non-actionable even if an old
    # detector profile exists in the rebuilt DB.
    historical_keys = (
        'PRLV SEPA PREDICA',
        'PRLV SEPA CACI NON LIFE LIMITED',
        'PRLV SEPA BNP PARIBAS PERSONAL FINANCE',
        'PRLV SEPA SARL MAP GESTION',
        'PRLV SEPA SFR FIXE ADSL',
    )
    placeholders = ','.join('?' for _ in historical_keys)
    conn.execute(
        f"UPDATE recurring_transactions SET is_active=0, next_expected_date=NULL WHERE merchant_key IN ({placeholders})",
        historical_keys,
    )

    conn.commit()
    integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
    active = conn.execute(
        "SELECT COUNT(*) FROM recurring_transactions WHERE is_active=1 AND detection_status='accepted'"
    ).fetchone()[0]
    budget_rules = conn.execute(
        "SELECT COUNT(*) FROM financial_rules WHERE rule_type='budget_transfer' AND status='active'"
    ).fetchone()[0]
    print(
        f'summary recurring_applied={applied} created={created} updated={updated} '
        f'active_accepted={active} active_budget_transfer_rules={budget_rules} integrity={integrity}'
    )
    conn.close()
    return 0 if integrity == 'ok' else 5


if __name__ == '__main__':
    raise SystemExit(main())
