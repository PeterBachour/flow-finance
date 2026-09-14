import hashlib
import json
from collections import Counter, defaultdict

from .imports import classify_row, normalize_label


IMPORT_IDENTITY_COLUMNS = {
    'statement_fingerprint': 'TEXT',
    'duplicate_of_import_id': 'INTEGER',
}

META_IDENTITY_COLUMNS = {
    'row_signature': 'TEXT',
    'occurrence_index': 'INTEGER NOT NULL DEFAULT 1',
}


def ensure_identity_schema(conn) -> None:
    import_columns = {row['name'] for row in conn.execute('PRAGMA table_info(imports)').fetchall()}
    for name, sql_type in IMPORT_IDENTITY_COLUMNS.items():
        if name not in import_columns:
            conn.execute(f'ALTER TABLE imports ADD COLUMN {name} {sql_type}')
    meta_columns = {row['name'] for row in conn.execute('PRAGMA table_info(transaction_import_meta)').fetchall()}
    for name, sql_type in META_IDENTITY_COLUMNS.items():
        if name not in meta_columns:
            conn.execute(f'ALTER TABLE transaction_import_meta ADD COLUMN {name} {sql_type}')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_import_statement_fingerprint ON imports(account_id,statement_fingerprint,status)')
    conn.execute('CREATE INDEX IF NOT EXISTS idx_import_meta_signature ON transaction_import_meta(row_signature,occurrence_index)')


def row_signature(account_id: int, booking_date: str, amount_cents: int, label: str) -> str:
    payload = f'{account_id}|{booking_date}|{amount_cents}|{normalize_label(label)}'
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def occurrence_fingerprint(signature: str, occurrence_index: int) -> str:
    return hashlib.sha256(f'{signature}|#{occurrence_index}'.encode('utf-8')).hexdigest()


def statement_fingerprint(account_id: int, bank: str | None, metadata: dict, rows: list[dict]) -> str:
    occurrences = defaultdict(int)
    canonical_rows = []
    for row in rows:
        signature = row_signature(account_id, row['booking_date'], int(row['amount_cents']), row['label'])
        occurrences[signature] += 1
        canonical_rows.append([signature, occurrences[signature]])
    payload = {
        'account_id': account_id,
        'bank': bank or '',
        'period_start': metadata.get('period_start'),
        'period_end': metadata.get('period_end'),
        'opening_balance_cents': metadata.get('opening_balance_cents'),
        'closing_balance_cents': metadata.get('closing_balance_cents'),
        'rows': canonical_rows,
    }
    raw = json.dumps(payload, sort_keys=True, separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(raw.encode('utf-8')).hexdigest()


def find_duplicate_statement(conn, account_id: int, fingerprint: str):
    return conn.execute(
        "SELECT id,filename,created_at FROM imports WHERE account_id=? AND statement_fingerprint=? AND status='completed' ORDER BY id LIMIT 1",
        (account_id, fingerprint),
    ).fetchone()


def _existing_signature_counts(conn, account_id: int, rows: list[dict]) -> Counter:
    wanted = {
        row_signature(account_id, row['booking_date'], int(row['amount_cents']), row['label'])
        for row in rows
    }
    counts = Counter()
    candidates = conn.execute(
        'SELECT booking_date,amount_cents,label FROM transactions WHERE account_id=?',
        (account_id,),
    ).fetchall()
    for row in candidates:
        signature = row_signature(account_id, row['booking_date'], int(row['amount_cents']), row['label'])
        if signature in wanted:
            counts[signature] += 1
    return counts


def import_rows_occurrence_safe(conn, import_id: int, account_id: int, rows: list[dict]) -> dict:
    ensure_identity_schema(conn)
    existing_counts = _existing_signature_counts(conn, account_id, rows)
    incoming_occurrences = defaultdict(int)
    imported = duplicates = review = auto_classified = 0

    for row in rows:
        signature = row_signature(account_id, row['booking_date'], int(row['amount_cents']), row['label'])
        incoming_occurrences[signature] += 1
        occurrence = incoming_occurrences[signature]

        # Existing rows only consume the corresponding number of occurrences.
        # A second identical purchase in the same statement remains importable.
        if occurrence <= existing_counts[signature]:
            duplicates += 1
            continue

        fingerprint = occurrence_fingerprint(signature, occurrence)
        if conn.execute('SELECT 1 FROM transaction_import_meta WHERE fingerprint=?', (fingerprint,)).fetchone():
            duplicates += 1
            continue

        category, tx_type, internal, classified = classify_row(conn, row['label'], int(row['amount_cents']))
        needs_review = bool(row.get('force_review')) or not classified
        cur = conn.execute(
            'INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer) VALUES(?,?,?,?,?,?,?)',
            (account_id, row['booking_date'], int(row['amount_cents']), row['label'], category, tx_type, internal),
        )
        conn.execute(
            '''INSERT INTO transaction_import_meta(
                 transaction_id,import_id,fingerprint,normalized_label,review_status,raw_payload,row_signature,occurrence_index
               ) VALUES(?,?,?,?,?,?,?,?)''',
            (
                cur.lastrowid,
                import_id,
                fingerprint,
                normalize_label(row['label']),
                'needs_review' if needs_review else 'accepted',
                json.dumps(row.get('raw'), ensure_ascii=False),
                signature,
                occurrence,
            ),
        )
        imported += 1
        review += int(needs_review)
        auto_classified += int(not needs_review)

    return {
        'imported': imported,
        'duplicates': duplicates,
        'review': review,
        'auto_classified': auto_classified,
    }
