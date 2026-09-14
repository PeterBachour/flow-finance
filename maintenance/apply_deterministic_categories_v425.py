#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from datetime import date
from pathlib import Path

# Final automatic batch: only explicit descriptors whose semantic category is
# sufficiently clear to apply without user interpretation.
RULES = (
    ('UEP*U EXPRESS', 'Alimentation', 'explicit U Express grocery descriptor'),
    ('SPORT TICKETING', 'Loisirs', 'explicit ticketing descriptor'),
    ('BURGER_KING', 'Restaurants', 'explicit Burger King restaurant descriptor'),
    ('EATSUSHI', 'Restaurants', 'explicit sushi restaurant descriptor'),
    ('MGP*VINTED', 'Shopping', 'explicit Vinted marketplace descriptor'),
    ('HOTEL DU PALAIS', 'Voyage', 'explicit hotel descriptor'),
)


def normalize(value: str | None) -> str:
    return ' '.join((value or '').upper().split())


def euros(cents: int | None) -> str:
    return f'{int(cents or 0) / 100:.2f}'


def backup_database(conn: sqlite3.Connection, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    backup = sqlite3.connect(destination)
    try:
        conn.backup(backup)
    finally:
        backup.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Dry-run/apply final deterministic historical categories with backup before mutation.'
    )
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--as-of', required=True, help='YYYY-MM-DD')
    parser.add_argument('--months', type=int, default=12)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir', type=Path, default=None)
    args = parser.parse_args()

    db_path = args.db.resolve()
    if not db_path.exists():
        print(f'error=db not found: {db_path}')
        return 2

    as_of = date.fromisoformat(args.as_of)
    months = max(1, min(int(args.months), 36))
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')

    try:
        before_count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
        rows = conn.execute('''
            SELECT id,booking_date,amount_cents,label,category
            FROM transactions
            WHERE booking_date>=date(?, ?, 'start of month')
              AND booking_date<date(?, 'start of month')
              AND amount_cents<0
              AND COALESCE(status,'confirmed')='confirmed'
              AND COALESCE(is_internal_transfer,0)=0
              AND (category IS NULL OR trim(category)='')
            ORDER BY booking_date,id
        ''', (as_of.isoformat(), f'-{months} months', as_of.isoformat())).fetchall()

        matches: list[tuple[sqlite3.Row, str, str, str]] = []
        stats = {pattern: {'rows': 0, 'amount': 0} for pattern, _, _ in RULES}
        for row in rows:
            text = normalize(row['label'])
            match = next(((p, c, r) for p, c, r in RULES if p in text), None)
            if not match:
                continue
            pattern, category, reason = match
            matches.append((row, pattern, category, reason))
            stats[pattern]['rows'] += 1
            stats[pattern]['amount'] += abs(int(row['amount_cents']))

        print(f'db={db_path}')
        print(f'as_of={as_of.isoformat()} months={months} mode={"apply" if args.apply else "dry-run"}')
        print('--- deterministic candidates ---')
        for row, pattern, category, reason in matches:
            print(
                f'id={row["id"]} date={row["booking_date"]} amount={euros(abs(int(row["amount_cents"])))} '
                f'category={category} rule={pattern} reason={reason} label={row["label"]}'
            )

        print('--- rule summary ---')
        for pattern, category, reason in RULES:
            item = stats[pattern]
            print(
                f'rule={pattern} category={category} rows={item["rows"]} '
                f'amount={euros(item["amount"])} reason={reason}'
            )

        backup_path = None
        if args.apply and matches:
            backup_dir = args.backup_dir.resolve() if args.backup_dir else db_path.parent
            stamp = date.today().isoformat().replace('-', '')
            backup_path = backup_dir / f'{db_path.stem}.pre-v425-categories-{stamp}.db'
            backup_database(conn, backup_path)
            conn.execute('BEGIN IMMEDIATE')
            try:
                for row, _, category, _ in matches:
                    conn.execute(
                        "UPDATE transactions SET category=? WHERE id=? AND (category IS NULL OR trim(category)='')",
                        (category, row['id']),
                    )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        after_count = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
        remaining = conn.execute('''
            SELECT COUNT(*) AS rows,COALESCE(SUM(ABS(amount_cents)),0) AS amount
            FROM transactions
            WHERE booking_date>=date(?, ?, 'start of month')
              AND booking_date<date(?, 'start of month')
              AND amount_cents<0
              AND COALESCE(status,'confirmed')='confirmed'
              AND COALESCE(is_internal_transfer,0)=0
              AND (category IS NULL OR trim(category)='')
        ''', (as_of.isoformat(), f'-{months} months', as_of.isoformat())).fetchone()
        integrity = conn.execute('PRAGMA integrity_check').fetchone()[0]

        print('--- result ---')
        print(f'candidates={len(matches)} candidate_amount={euros(sum(abs(int(m[0]["amount_cents"])) for m in matches))}')
        print(f'applied={len(matches) if args.apply else 0}')
        print(f'backup={backup_path or "none"}')
        print(f'remaining_unclassified_rows={remaining["rows"]} remaining_unclassified_amount={euros(remaining["amount"])}')
        print(f'transaction_count_unchanged={str(before_count == after_count).lower()}')
        print('rule=final_automatic_batch_explicit_descriptors_only')
        print('rule=remaining_unknowns_require_manual_review_or_user_validated_rules')
        print(f'integrity={integrity}')
        return 0 if integrity == 'ok' and before_count == after_count else 5
    finally:
        conn.close()


if __name__ == '__main__':
    raise SystemExit(main())
