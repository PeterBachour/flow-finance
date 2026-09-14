#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.bulk_import import ensure_bulk_schema
from app.data_intelligence import refresh_financial_intelligence
from app.db import connection, init_db


def main() -> int:
    init_db()
    with connection() as conn:
        ensure_bulk_schema(conn)
        result = refresh_financial_intelligence(conn)
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]
        payroll_matches = conn.execute('SELECT COUNT(*) FROM payroll_transaction_matches').fetchone()[0]
        recurrings = conn.execute("SELECT COUNT(*) FROM recurring_transactions WHERE detection_status='detected'").fetchone()[0]
        occurrences = conn.execute('SELECT COUNT(*) FROM recurring_occurrences').fetchone()[0]
    print(f'integrity={integrity}')
    print(f'payroll={result["payroll"]}')
    print(f'recurring={result["recurring"]}')
    print(f'payroll_matches={payroll_matches}')
    print(f'detected_recurrings={recurrings}')
    print(f'recurring_occurrences={occurrences}')
    return 0 if integrity == 'ok' else 2


if __name__ == '__main__':
    raise SystemExit(main())
