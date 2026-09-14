#!/usr/bin/env python3
from __future__ import annotations

import argparse
import io
import re
from pathlib import Path

from pypdf import PdfReader

KEYWORDS = (
    'BRUT',
    'NET A PAYER',
    'NET À PAYER',
    'NET PAYE',
    'NET PAYÉ',
    'NET IMPOSABLE',
    'PRELEVEMENT A LA SOURCE',
    'PRÉLÈVEMENT À LA SOURCE',
)


def _clean_lines(text: str, page_no: int) -> list[str]:
    lines: list[str] = []
    for line_no, raw in enumerate(text.splitlines(), start=1):
        line = re.sub(r'\s+', ' ', raw).strip()
        if line:
            lines.append(f'p{page_no}:l{line_no}: {line}')
    return lines


def pdf_lines(path: Path, mode: str) -> list[str]:
    reader = PdfReader(io.BytesIO(path.read_bytes()))
    lines: list[str] = []
    for page_no, page in enumerate(reader.pages, start=1):
        if mode == 'layout':
            try:
                text = page.extract_text(extraction_mode='layout') or ''
            except Exception:
                text = ''
        else:
            text = page.extract_text() or ''
        lines.extend(_clean_lines(text, page_no))
    return lines


def _print_matches(lines: list[str], context: int) -> bool:
    matched: set[int] = set()
    for idx, line in enumerate(lines):
        upper = line.upper()
        if any(keyword in upper for keyword in KEYWORDS):
            for j in range(max(0, idx - context), min(len(lines), idx + context + 1)):
                matched.add(j)
    if not matched:
        return False
    previous = None
    for idx in sorted(matched):
        if previous is not None and idx > previous + 1:
            print('...')
        print(lines[idx])
        previous = idx
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description='Show payroll PDF extraction around gross/net/tax labels without OCR')
    parser.add_argument('--payroll', type=Path, required=True)
    parser.add_argument('--files', nargs='*', default=[])
    parser.add_argument('--context', type=int, default=1)
    parser.add_argument('--raw-lines', type=int, default=40, help='Lines to print when no keyword is found')
    args = parser.parse_args()

    if args.files:
        files = [args.payroll / name for name in args.files]
    else:
        files = sorted(args.payroll.glob('*.pdf'))[:5]

    missing = [str(path) for path in files if not path.exists()]
    if missing:
        print('missing_files=' + repr(missing))
        return 2

    for path in files:
        print(f'--- {path.name} ---')
        layout_lines = pdf_lines(path, 'layout')
        print(f'layout_lines={len(layout_lines)}')
        if _print_matches(layout_lines, args.context):
            continue

        plain_lines = pdf_lines(path, 'plain')
        print(f'plain_lines={len(plain_lines)}')
        if _print_matches(plain_lines, args.context):
            continue

        print('no_target_lines_found')
        print(f'--- raw_extraction_first_{args.raw_lines}_lines ---')
        source = plain_lines or layout_lines
        for line in source[: max(1, args.raw_lines)]:
            print(line)
        if not source:
            print('no_text_extracted')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
