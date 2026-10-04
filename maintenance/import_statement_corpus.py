#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.bulk_import import commit_batch, ensure_bulk_schema, stage_document
from app.imports import parse_statement, statement_metadata
from app.statement_corpus_preflight import StatementRecord, analyze_records

SUPPORTED_SUFFIXES = {'.pdf', '.csv'}


@dataclass(frozen=True)
class StatementProbe:
    filename: str
    path: str
    period_start: str | None
    period_end: str | None
    opening_balance_cents: int | None
    closing_balance_cents: int | None
    debit_total_cents: int
    credit_total_cents: int
    transaction_count: int
    parse_error: str | None = None


def inspect_statement(path: Path) -> StatementProbe:
    try:
        data = path.read_bytes()
        source_type, bank, rows = parse_statement(path.name, data)
        metadata = statement_metadata(data, bank, rows)
        return StatementProbe(
            filename=path.name,
            path=str(path),
            period_start=metadata.get('period_start'),
            period_end=metadata.get('period_end'),
            opening_balance_cents=metadata.get('opening_balance_cents'),
            closing_balance_cents=metadata.get('closing_balance_cents'),
            debit_total_cents=int(metadata.get('debit_total_cents') or 0),
            credit_total_cents=int(metadata.get('credit_total_cents') or 0),
            transaction_count=len(rows),
        )
    except Exception as exc:  # CLI diagnostic: keep the remaining corpus inspectable.
        return StatementProbe(
            filename=path.name,
            path=str(path),
            period_start=None,
            period_end=None,
            opening_balance_cents=None,
            closing_balance_cents=None,
            debit_total_cents=0,
            credit_total_cents=0,
            transaction_count=0,
            parse_error=str(exc),
        )


def inspect_corpus(source_dir: Path) -> list[StatementProbe]:
    files = sorted(
        path for path in source_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES
    )
    return [inspect_statement(path) for path in files]


def _probe_record(probe: StatementProbe) -> StatementRecord:
    return StatementRecord(
        source='corpus',
        source_id=0,
        filename=probe.filename,
        period_start=probe.period_start,
        period_end=probe.period_end,
        opening_balance_cents=probe.opening_balance_cents,
        closing_balance_cents=probe.closing_balance_cents,
        status='warning' if probe.parse_error else 'ready',
        warning=probe.parse_error,
        staged=True,
    )


def analyze_continuity(probes: list[StatementProbe]) -> dict:
    preflight = analyze_records([_probe_record(probe) for probe in probes])
    parse_errors = [
        {'filename': probe.filename, 'error': probe.parse_error}
        for probe in probes if probe.parse_error
    ]
    issues = preflight['issues']
    return {
        'file_count': len(probes),
        'parsed_statement_count': preflight['statement_count'],
        'parse_errors': parse_errors,
        'coverage_start': preflight['coverage_start'],
        'coverage_end': preflight['coverage_end'],
        'status': preflight['status'],
        'can_commit': preflight['can_commit'],
        'requires_confirmation': preflight['requires_confirmation'],
        'blocking_count': preflight['blocking_count'],
        'warning_count': preflight['warning_count'],
        'duplicate_statement_count': preflight['duplicate_statement_count'],
        'missing_months': preflight['missing_months'],
        'missing_month_count': preflight['missing_month_count'],
        'issues': issues,
        'has_period_gap': any(issue['type'] == 'period_gap' for issue in issues),
        'has_period_overlap': any(issue['type'] == 'period_overlap' for issue in issues),
        'has_balance_discontinuity': any(issue['type'] == 'balance_discontinuity' for issue in issues),
    }


def validate_apply_preflight(probes: list[StatementProbe], *, confirm_warnings: bool = False) -> dict:
    continuity = analyze_continuity(probes)
    parse_errors = [probe for probe in probes if probe.parse_error]
    if parse_errors:
        raise ValueError('Corpus contains parse errors; fix them before --apply.')
    if not continuity['can_commit']:
        raise ValueError('Corpus preflight is blocking; fix period overlaps or balance discontinuities before --apply.')
    if continuity['requires_confirmation'] and not confirm_warnings:
        raise ValueError('Corpus has warning-level gaps; rerun with --confirm-warnings to apply knowingly.')
    return continuity


def apply_corpus(
    db: Path,
    account_id: int,
    source_dir: Path,
    probes: list[StatementProbe],
    *,
    confirm_warnings: bool = False,
) -> dict:
    validate_apply_preflight(probes, confirm_warnings=confirm_warnings)

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        account = conn.execute(
            'SELECT id,name FROM accounts WHERE id=? AND is_active=1',
            (account_id,),
        ).fetchone()
        if not account:
            raise ValueError(f'Active account not found: {account_id}')

        ensure_bulk_schema(conn)
        cur = conn.execute(
            "INSERT INTO bulk_import_batches(account_id,status,total_files) VALUES(?,'staging',?)",
            (account_id, len(probes)),
        )
        batch_id = int(cur.lastrowid)

        staged = []
        statement_files = 0
        payroll_files = 0
        unknown_files = 0
        warning_files = 0
        for probe in probes:
            path = source_dir / probe.filename
            result = stage_document(conn, batch_id, account_id, probe.filename, path.read_bytes())
            staged.append(result)
            document_type = result.get('document_type')
            if document_type == 'statement':
                statement_files += 1
            elif document_type == 'payroll':
                payroll_files += 1
            else:
                unknown_files += 1
            if result.get('status') == 'warning':
                warning_files += 1

        conn.execute(
            '''UPDATE bulk_import_batches
               SET statement_files=?,payroll_files=?,unknown_files=?,warning_files=?
               WHERE id=?''',
            (statement_files, payroll_files, unknown_files, warning_files, batch_id),
        )
        commit_result = commit_batch(conn, batch_id)
        conn.commit()
        return {
            'batch_id': batch_id,
            'account_id': account_id,
            'account_name': account['name'],
            'staged': staged,
            'commit': commit_result,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            'Inspect a directory of bank statements, report period/balance continuity, '
            'and optionally import the corpus through Flow bulk-import safeguards.'
        )
    )
    parser.add_argument('--source-dir', type=Path, required=True)
    parser.add_argument('--db', type=Path)
    parser.add_argument('--account-id', type=int)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--confirm-warnings', action='store_true')
    parser.add_argument('--json-out', type=Path)
    args = parser.parse_args()

    source_dir = args.source_dir.resolve()
    if not source_dir.is_dir():
        print(f'error=source directory not found: {source_dir}', file=sys.stderr)
        return 2

    probes = inspect_corpus(source_dir)
    continuity = analyze_continuity(probes)
    payload: dict = {
        'mode': 'apply' if args.apply else 'dry-run',
        'source_dir': str(source_dir),
        'statements': [asdict(probe) for probe in probes],
        'continuity': continuity,
    }

    if args.apply:
        if args.db is None or args.account_id is None:
            print('error=--db and --account-id are required with --apply', file=sys.stderr)
            return 2
        db = args.db.resolve()
        if not db.exists():
            print(f'error=db not found: {db}', file=sys.stderr)
            return 2
        try:
            payload['import'] = apply_corpus(
                db,
                args.account_id,
                source_dir,
                probes,
                confirm_warnings=args.confirm_warnings,
            )
        except Exception as exc:
            print(f'error={exc}', file=sys.stderr)
            return 1

    rendered = json.dumps(payload, ensure_ascii=False, indent=2)
    print(rendered)
    if args.json_out:
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(rendered + '\n', encoding='utf-8')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
