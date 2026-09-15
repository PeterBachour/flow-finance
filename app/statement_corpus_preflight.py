from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta


@dataclass(frozen=True)
class StatementRecord:
    source: str
    source_id: int
    filename: str
    period_start: str | None
    period_end: str | None
    opening_balance_cents: int | None
    closing_balance_cents: int | None
    status: str
    warning: str | None = None
    staged: bool = False


def _parse_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def _from_existing(row) -> StatementRecord:
    return StatementRecord(
        source='import',
        source_id=int(row['id']),
        filename=row['filename'],
        period_start=row['period_start'],
        period_end=row['period_end'],
        opening_balance_cents=row['opening_balance_cents'],
        closing_balance_cents=row['closing_balance_cents'],
        status=row['status'],
        warning=row['quality_message'],
        staged=False,
    )


def _from_staged(row) -> StatementRecord:
    try:
        summary = json.loads(row['summary_json'] or '{}')
    except json.JSONDecodeError:
        summary = {}
    return StatementRecord(
        source='staged',
        source_id=int(row['id']),
        filename=row['filename'],
        period_start=summary.get('period_start'),
        period_end=summary.get('period_end'),
        opening_balance_cents=summary.get('opening_balance_cents'),
        closing_balance_cents=summary.get('closing_balance_cents'),
        status=row['status'],
        warning=row['warning'],
        staged=True,
    )


def _record_dict(record: StatementRecord) -> dict:
    return {
        'source': record.source,
        'source_id': record.source_id,
        'filename': record.filename,
        'period_start': record.period_start,
        'period_end': record.period_end,
        'opening_balance_cents': record.opening_balance_cents,
        'closing_balance_cents': record.closing_balance_cents,
        'status': record.status,
        'warning': record.warning,
        'staged': record.staged,
    }


def analyze_records(records: list[StatementRecord]) -> dict:
    usable = [
        record for record in records
        if _parse_iso(record.period_start) and _parse_iso(record.period_end)
    ]
    usable.sort(key=lambda record: (_parse_iso(record.period_start), _parse_iso(record.period_end), record.filename))

    issues: list[dict] = []
    invalid = [record for record in records if record.staged and record.status == 'warning' and not (_parse_iso(record.period_start) and _parse_iso(record.period_end))]
    for record in invalid:
        issues.append({
            'type': 'parse_error',
            'severity': 'blocking',
            'file': record.filename,
            'source_id': record.source_id,
            'detail': record.warning or 'Métadonnées de relevé incomplètes.',
        })

    for current, following in zip(usable, usable[1:]):
        current_end = _parse_iso(current.period_end)
        following_start = _parse_iso(following.period_start)
        if current_end is None or following_start is None:
            continue
        expected_start = current_end + timedelta(days=1)
        touches_staged = current.staged or following.staged

        if following_start > expected_start and touches_staged:
            issues.append({
                'type': 'period_gap',
                'severity': 'warning',
                'after_file': current.filename,
                'before_file': following.filename,
                'missing_start': expected_start.isoformat(),
                'missing_end': (following_start - timedelta(days=1)).isoformat(),
                'missing_days': (following_start - expected_start).days,
            })
        elif following_start < expected_start and touches_staged:
            issues.append({
                'type': 'period_overlap',
                'severity': 'blocking',
                'after_file': current.filename,
                'before_file': following.filename,
                'overlap_start': following_start.isoformat(),
                'overlap_end': current_end.isoformat(),
                'overlap_days': (current_end - following_start).days + 1,
            })

        if (
            touches_staged
            and following_start == expected_start
            and current.closing_balance_cents is not None
            and following.opening_balance_cents is not None
            and current.closing_balance_cents != following.opening_balance_cents
        ):
            issues.append({
                'type': 'balance_discontinuity',
                'severity': 'blocking',
                'after_file': current.filename,
                'before_file': following.filename,
                'closing_balance_cents': current.closing_balance_cents,
                'next_opening_balance_cents': following.opening_balance_cents,
                'difference_cents': following.opening_balance_cents - current.closing_balance_cents,
            })

    blocking = [issue for issue in issues if issue['severity'] == 'blocking']
    warnings = [issue for issue in issues if issue['severity'] == 'warning']
    staged = [record for record in records if record.staged]
    return {
        'status': 'blocked' if blocking else ('warning' if warnings else 'ready'),
        'can_commit': not blocking,
        'requires_confirmation': bool(warnings),
        'statement_count': len(usable),
        'staged_statement_count': len(staged),
        'coverage_start': usable[0].period_start if usable else None,
        'coverage_end': usable[-1].period_end if usable else None,
        'blocking_count': len(blocking),
        'warning_count': len(warnings),
        'issues': issues,
        'records': [_record_dict(record) for record in usable],
    }


def build_batch_preflight(conn, batch_id: int) -> dict:
    batch = conn.execute('SELECT id,account_id,status FROM bulk_import_batches WHERE id=?', (batch_id,)).fetchone()
    if not batch:
        raise ValueError('Lot introuvable')

    existing_rows = conn.execute(
        """SELECT id,filename,period_start,period_end,opening_balance_cents,closing_balance_cents,status,quality_message
           FROM imports
           WHERE account_id=? AND status='completed'
           ORDER BY period_start,period_end,id""",
        (batch['account_id'],),
    ).fetchall()
    staged_rows = conn.execute(
        """SELECT id,filename,status,warning,summary_json
           FROM bulk_import_documents
           WHERE batch_id=? AND document_type='statement'
           ORDER BY id""",
        (batch_id,),
    ).fetchall()

    records = [_from_existing(row) for row in existing_rows]
    records.extend(_from_staged(row) for row in staged_rows)
    result = analyze_records(records)
    return {
        'batch_id': int(batch['id']),
        'account_id': int(batch['account_id']),
        'batch_status': batch['status'],
        **result,
    }
