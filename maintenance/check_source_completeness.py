#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter
from datetime import date
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.bulk_import import parse_payroll
from app.imports import parse_statement, statement_metadata


def _pdfs(path: Path) -> list[Path]:
    if path.is_dir():
        return sorted(path.glob('*.pdf'))
    return [path] if path.suffix.lower() == '.pdf' else []


def _month_iter(start: str, end: str) -> list[str]:
    y, m = map(int, start.split('-'))
    ey, em = map(int, end.split('-'))
    out = []
    while (y, m) <= (ey, em):
        out.append(f'{y:04d}-{m:02d}')
        if m == 12:
            y += 1
            m = 1
        else:
            m += 1
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description='Check continuity and duplicates in Flow bank statement and payroll source PDFs')
    parser.add_argument('--statements', type=Path, required=True)
    parser.add_argument('--payroll', type=Path, required=True)
    args = parser.parse_args()

    statement_files = _pdfs(args.statements)
    payroll_files = _pdfs(args.payroll)
    if not statement_files:
        print('error=no bank statement PDFs found')
        return 2
    if not payroll_files:
        print('error=no payroll PDFs found')
        return 3

    bank_periods: list[str] = []
    bank_errors: list[str] = []
    bank_ranges: list[tuple[str, str, str]] = []
    for path in statement_files:
        try:
            data = path.read_bytes()
            _, bank, rows = parse_statement(path.name, data)
            meta = statement_metadata(data, bank, rows)
            start = meta.get('period_start')
            end = meta.get('period_end')
            if not start or not end:
                raise ValueError('missing statement period metadata')
            period = end[:7]
            bank_periods.append(period)
            bank_ranges.append((path.name, start, end))
        except Exception as exc:
            bank_errors.append(f'{path.name}: {exc}')

    payroll_periods: list[str] = []
    payroll_errors: list[str] = []
    for path in payroll_files:
        try:
            payload, _ = parse_payroll(path.name, path.read_bytes())
            period = payload.get('period')
            if not period:
                raise ValueError('missing payroll period')
            payroll_periods.append(period)
        except Exception as exc:
            payroll_errors.append(f'{path.name}: {exc}')

    bank_counts = Counter(bank_periods)
    payroll_counts = Counter(payroll_periods)
    bank_unique = sorted(bank_counts)
    payroll_unique = sorted(payroll_counts)

    bank_missing = _month_iter(bank_unique[0], bank_unique[-1]) if bank_unique else []
    bank_missing = [p for p in bank_missing if p not in bank_counts]
    payroll_missing = _month_iter(payroll_unique[0], payroll_unique[-1]) if payroll_unique else []
    payroll_missing = [p for p in payroll_missing if p not in payroll_counts]
    bank_duplicates = sorted(p for p, c in bank_counts.items() if c > 1)
    payroll_duplicates = sorted(p for p, c in payroll_counts.items() if c > 1)

    print('BANK')
    if bank_ranges:
        print(f'coverage={min(r[1] for r in bank_ranges)}->{max(r[2] for r in bank_ranges)}')
    print(f'files={len(statement_files)} parsed_periods={len(bank_periods)}')
    print(f'periods={bank_unique}')
    print(f'missing_months={bank_missing}')
    print(f'duplicate_months={bank_duplicates}')
    if bank_errors:
        print(f'errors={bank_errors}')

    print('PAYROLL')
    if payroll_unique:
        print(f'coverage={payroll_unique[0]}->{payroll_unique[-1]}')
    print(f'files={len(payroll_files)} parsed_periods={len(payroll_periods)}')
    print(f'periods={payroll_unique}')
    print(f'missing_months={payroll_missing}')
    print(f'duplicate_months={payroll_duplicates}')
    if payroll_errors:
        print(f'errors={payroll_errors}')

    complete = not bank_missing and not bank_duplicates and not bank_errors and not payroll_missing and not payroll_duplicates and not payroll_errors
    print(f'status={"COMPLETE" if complete else "INCOMPLETE"}')
    return 0 if complete else 1


if __name__ == '__main__':
    raise SystemExit(main())
