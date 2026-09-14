#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.imports import (
    accept_categorized_import_reviews,
    ensure_import_schema,
    infer_transaction_type,
    normalize_label,
)


# Conservative rules only. Ambiguous merchants and person-to-person transfers are
# deliberately excluded and remain in the review inbox.
RULES: tuple[tuple[str, str, str | None], ...] = (
    ('CB HELLOFRESH', 'Alimentation', None),
    ('CB SUPER JUMI', 'Alimentation', None),
    ('CB ALIM RICHARDIS', 'Alimentation', None),
    ('CB U EXPRESS', 'Alimentation', None),
    ('CB A SUPER 2000', 'Alimentation', None),
    ('CB MAISONLANDEMAINE', 'Alimentation', None),
    ('CB MAISON LANDEMAIN', 'Alimentation', None),

    ('CB DAMES MAGIC 1', 'Restaurants', None),
    ('CB LES BERTHOM', 'Restaurants', None),
    ('CB LPM TAPROOM', 'Restaurants', None),
    ('CB AMERICAN MEA CIE', 'Restaurants', None),
    ('KFC', 'Restaurants', None),
    ('CB BURGER KING', 'Restaurants', None),
    ("CB MC DONALD'S", 'Restaurants', None),
    ('CB SUB BASTILLE', 'Restaurants', None),
    ('CB AREAS PARIS', 'Restaurants', None),
    ('CB BOIRE ET MANGER', 'Restaurants', None),
    ('CB GATE GOURMET', 'Restaurants', None),
    ('CB LA QUILLE DU 11E', 'Restaurants', None),
    ('CB OSULLIVANS', 'Restaurants', None),
    ('CB PRINCE WILLIAM', 'Restaurants', None),
    ('CB SC-REST.AMELOT', 'Restaurants', None),
    ('CB BEST FALAFEL', 'Restaurants', None),
    ('CB CHEZ MON COUSIN', 'Restaurants', None),
    ('CB GOURMET HAUSSMA', 'Restaurants', None),
    ('CB HORETO-REST', 'Restaurants', None),
    ("CB L'IVRESS", 'Restaurants', None),
    ('CB LA CHAMADE', 'Restaurants', None),
    ('CB LE MOUSK', 'Restaurants', None),
    ('CB LES TROIS FRERES', 'Restaurants', None),

    ('CB TRANSAVIA', 'Transport', None),
    ('CB SNCF-VOYAGEURS', 'Transport', None),
    ('CB AIR FRANCE', 'Transport', None),
    ('CB FIL BLEU', 'Transport', None),
    ('CB STATTELPAYBYPHON', 'Transport', None),
    ('CB UBR*', 'Transport', None),
    ('CB DELIJN', 'Transport', None),
    ('CB DIVIA PASS', 'Transport', None),

    ('CB WEEZEVENT', 'Loisirs', None),
    ('CB CANAL SAT', 'Loisirs', None),
    ('CB PLAYER ONE', 'Loisirs', None),
    ('CB SHOTGUN', 'Loisirs', None),
    ('CB LE FIVE', 'Loisirs', None),

    ('CB RELAY', 'Shopping', None),
    ('CB SMILE&P*EPISODE', 'Shopping', None),

    ('CB TIMBRE FISCAL', 'Impôts', None),
    ('DIRECTION GENERALE DES FINANCES PUBLIQUE', 'Impôts', None),

    ('VIREMENT CPAM 75 PRESTATIONS', 'Remboursement', 'refund'),
    ('VIREMENT GENERATION', 'Remboursement', 'refund'),

    ('VIR.PERMANENT APPART SAINT SABI', 'Logement', 'expense'),
    ('VIR INST IMMOBILIER DE CARNE', 'Logement', 'expense'),
    ('PRET IMMO COMMISSION DE CAUTION', 'Crédits', 'expense'),
)


def suggested_rule(label: str) -> tuple[str, str, str | None] | None:
    normalized = normalize_label(label)
    return next((rule for rule in RULES if rule[0] in normalized), None)


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Classify only high-confidence unresolved import rows.'
    )
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()

    db = args.db.resolve()
    if not db.exists():
        print(f'error=db not found: {db}', file=sys.stderr)
        return 2

    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    try:
        ensure_import_schema(conn)
        rows = conn.execute(
            """SELECT t.id,t.label,t.amount_cents,m.normalized_label
               FROM transaction_import_meta m
               JOIN transactions t ON t.id=m.transaction_id
               WHERE m.review_status='needs_review'
                 AND TRIM(COALESCE(t.category,''))=''
               ORDER BY t.id"""
        ).fetchall()

        candidates = []
        category_counts: Counter[str] = Counter()
        used_rules: set[tuple[str, str, str | None]] = set()
        for row in rows:
            rule = suggested_rule(row['normalized_label'])
            if not rule:
                continue
            pattern, category, transaction_type = rule
            resolved_type = transaction_type or infer_transaction_type(
                row['normalized_label'], int(row['amount_cents'])
            )
            candidates.append((int(row['id']), category, resolved_type))
            category_counts[category] += 1
            used_rules.add(rule)

        accepted = 0
        if args.apply and candidates:
            conn.executemany(
                """UPDATE transactions
                   SET category=?,transaction_type=?,is_internal_transfer=0
                   WHERE id=?""",
                [(category, tx_type, transaction_id)
                 for transaction_id, category, tx_type in candidates],
            )
            for pattern, category, transaction_type in sorted(used_rules):
                exists = conn.execute(
                    """SELECT 1 FROM categorization_rules
                       WHERE pattern=? AND category=? AND is_active=1""",
                    (pattern, category),
                ).fetchone()
                if not exists:
                    conn.execute(
                        """INSERT INTO categorization_rules(
                             pattern,category,transaction_type,priority,is_active
                           ) VALUES(?,?,?,?,1)""",
                        (pattern, category, transaction_type, 60),
                    )
            accepted = accept_categorized_import_reviews(
                conn, {transaction_id for transaction_id, _, _ in candidates}
            )
            conn.commit()
        else:
            conn.rollback()

        mode = 'apply' if args.apply else 'dry-run'
        print(
            f'mode={mode} unresolved={len(rows)} high_confidence={len(candidates)} '
            f'remaining={len(rows) - len(candidates)} accepted={accepted}'
        )
        for category, count in sorted(category_counts.items()):
            print(f'category={category} candidates={count}')
        if not args.apply:
            print('No data changed. Re-run with --apply only after checking these counts.')
    finally:
        conn.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
