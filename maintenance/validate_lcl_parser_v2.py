#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.lcl_parser_v2 import parse_lcl_pdf_layout


def validate(path: Path) -> dict:
    data = path.read_bytes()
    rows, parser_meta = parse_lcl_pdf_layout(data)
    opening = parser_meta.get('opening_balance_cents')
    closing = parser_meta.get('closing_balance_cents')
    debit = sum(-row['amount_cents'] for row in rows if row['amount_cents'] < 0)
    credit = sum(row['amount_cents'] for row in rows if row['amount_cents'] > 0)
    expected = opening + credit - debit if opening is not None else None
    delta = expected - closing if expected is not None and closing is not None else None
    return {
        'file': path.name,
        'period_start': parser_meta.get('period_start'),
        'period_end': parser_meta.get('period_end'),
        'transactions': len(rows),
        'debit_cents': debit,
        'credit_cents': credit,
        'opening_cents': opening,
        'closing_cents': closing,
        'reconciliation_delta_cents': delta,
        'warnings': parser_meta.get('warnings') or [],
        'status': 'ok' if delta == 0 and not parser_meta.get('warnings') else ('unverified' if delta is None else 'warning'),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description='Validate Flow LCL layout parser against statement balances')
    parser.add_argument('paths', nargs='+', type=Path, help='PDF files or directories containing PDF statements')
    args = parser.parse_args()
    files: list[Path] = []
    for item in args.paths:
        if item.is_dir():
            files.extend(sorted(item.glob('*.pdf')))
        elif item.suffix.lower() == '.pdf':
            files.append(item)
    files = list(dict.fromkeys(files))
    if not files:
        print('error=no PDF statements found')
        return 2

    warnings = 0
    for path in files:
        try:
            result = validate(path)
        except Exception as exc:
            warnings += 1
            print(f'{path.name}: ERROR {exc}')
            continue
        delta = result['reconciliation_delta_cents']
        print(
            f"{result['file']}: {result['status'].upper()} | "
            f"{result['period_start']} -> {result['period_end']} | "
            f"tx={result['transactions']} | delta_cents={delta} | parser_warnings={len(result['warnings'])}"
        )
        if result['status'] != 'ok':
            warnings += 1
    print(f'summary_files={len(files)} warnings={warnings} ok={len(files)-warnings}')
    return 0 if warnings == 0 else 1


if __name__ == '__main__':
    raise SystemExit(main())
