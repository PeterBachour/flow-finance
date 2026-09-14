from __future__ import annotations

import json
from datetime import date

from .history_coverage import build_history_coverage


def _json_object(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {'value': parsed}
    except (TypeError, ValueError, json.JSONDecodeError):
        return {'unparsed': value}


def _month_status(row: dict) -> str:
    statement = row['statement']
    payroll = row['payroll']
    if statement['verified'] and payroll['confirmed']:
        return 'complete'
    if statement['present'] and payroll['present']:
        return 'review'
    if statement['present']:
        return 'statement_only'
    if payroll['present']:
        return 'payroll_only'
    return 'missing'


def build_documentary_evidence(conn, *, as_of: date | None = None, months: int = 24) -> dict:
    coverage = build_history_coverage(conn, as_of=as_of, months=months)
    statement_rows = conn.execute(
        '''SELECT i.id,i.account_id,i.filename,i.source_type,i.bank,i.status,i.quality_status,
                  i.quality_message,i.period_start,i.period_end,i.opening_balance_cents,
                  i.closing_balance_cents,i.debit_total_cents,i.credit_total_cents,
                  i.total_rows,i.imported_rows,i.duplicate_rows,i.review_rows,
                  i.statement_fingerprint,i.created_at,
                  COUNT(m.transaction_id) linked_transactions
           FROM imports i
           LEFT JOIN transaction_import_meta m ON m.import_id=i.id
           WHERE i.status IN ('completed','duplicate')
           GROUP BY i.id
           ORDER BY COALESCE(i.period_end,i.period_start),i.id'''
    ).fetchall()
    payroll_rows = conn.execute(
        '''SELECT id,period,employer,gross_cents,net_before_tax_cents,net_paid_cents,
                  taxable_net_cents,withholding_tax_cents,reimbursements_cents,bonuses_cents,
                  source_filename,source_hash,source_status,created_at
           FROM payroll_records
           ORDER BY period,id'''
    ).fetchall()

    statements = []
    for raw in statement_rows:
        row = dict(raw)
        status = 'duplicate' if row['status'] == 'duplicate' else (
            'verified' if row['quality_status'] == 'verified' and int(row['review_rows'] or 0) == 0
            else 'review'
        )
        statements.append({
            **row,
            'document_type': 'statement',
            'period': (row.get('period_end') or row.get('period_start') or '')[:7] or None,
            'evidence_status': status,
            'proof': {
                'source_document': bool(row.get('filename')),
                'source_identity': bool(row.get('statement_fingerprint')),
                'balances': row.get('opening_balance_cents') is not None and row.get('closing_balance_cents') is not None,
                'totals': row.get('debit_total_cents') is not None and row.get('credit_total_cents') is not None,
                'transaction_links': int(row.get('linked_transactions') or 0),
            },
        })

    payrolls = [{
        **dict(raw),
        'document_type': 'payroll',
        'filename': raw['source_filename'],
        'file_hash': raw['source_hash'],
        'evidence_status': 'verified' if raw['source_status'] == 'confirmed' else 'review',
        'proof': {
            'source_document': bool(raw['source_filename']),
            'source_identity': bool(raw['source_hash']),
            'net_paid': raw['net_paid_cents'] is not None,
        },
    } for raw in payroll_rows]

    month_rows = [{**row, 'status': _month_status(row)} for row in coverage['months']]
    verified_statements = sum(item['evidence_status'] == 'verified' for item in statements)
    verified_payrolls = sum(item['evidence_status'] == 'verified' for item in payrolls)
    linked_transactions = sum(int(item['linked_transactions'] or 0) for item in statements)
    expected_transactions = sum(int(item['imported_rows'] or 0) for item in statements if item['status'] == 'completed')

    return {
        'as_of': coverage['as_of'],
        'period_start': coverage['period_start'],
        'period_end': coverage['period_end'],
        'window_months': months,
        'summary': {
            'documents': len(statements) + len(payrolls),
            'statements': len(statements),
            'verified_statements': verified_statements,
            'payrolls': len(payrolls),
            'verified_payrolls': verified_payrolls,
            'linked_transactions': linked_transactions,
            'transaction_evidence_pct': round(linked_transactions / expected_transactions * 100, 1) if expected_transactions else 0.0,
            **coverage['summary'],
        },
        'months': month_rows,
        'documents': {'statements': statements, 'payrolls': payrolls},
        'gaps': coverage['gaps'],
        'duplicates': coverage['duplicates'],
        'actions': coverage['actions'],
        'read_only': True,
    }


def transaction_evidence(conn, transaction_id: int) -> dict | None:
    row = conn.execute(
        '''SELECT t.id transaction_id,t.account_id,t.booking_date,t.amount_cents,t.label,t.category,
                  t.transaction_type,t.source_type,t.source_id,t.source_url,t.source_date,
                  t.source_status,t.confidence,t.source_key,t.imported_at,
                  m.import_id,m.fingerprint,m.row_signature,m.occurrence_index,m.normalized_label,
                  m.review_status,m.raw_payload,
                  i.filename,i.bank,i.period_start,i.period_end,i.statement_fingerprint,
                  i.quality_status,i.quality_message
           FROM transactions t
           LEFT JOIN transaction_import_meta m ON m.transaction_id=t.id
           LEFT JOIN imports i ON i.id=m.import_id
           WHERE t.id=?''',
        (transaction_id,),
    ).fetchone()
    if not row:
        return None
    item = dict(row)
    return {
        'transaction': {
            key: item.get(key) for key in (
                'transaction_id','account_id','booking_date','amount_cents','label','normalized_label',
                'category','transaction_type','review_status','confidence'
            )
        },
        'source': {
            'type': 'bank_statement' if item.get('import_id') else item.get('source_type') or 'manual',
            'import_id': item.get('import_id'),
            'filename': item.get('filename'),
            'bank': item.get('bank'),
            'period_start': item.get('period_start'),
            'period_end': item.get('period_end'),
            'document_identity': item.get('statement_fingerprint'),
            'transaction_identity': item.get('fingerprint') or item.get('source_key'),
            'row_signature': item.get('row_signature'),
            'occurrence_index': item.get('occurrence_index'),
            'source_id': item.get('source_id'),
            'source_url': item.get('source_url'),
            'source_date': item.get('source_date'),
            'source_status': item.get('source_status'),
            'imported_at': item.get('imported_at'),
        },
        'quality': {
            'status': item.get('quality_status') or item.get('source_status') or 'manual',
            'message': item.get('quality_message'),
            'has_document_proof': bool(item.get('filename') and item.get('statement_fingerprint')),
            'has_row_proof': bool(item.get('fingerprint') or item.get('source_key')),
        },
        'raw': _json_object(item.get('raw_payload')),
        'read_only': True,
    }
