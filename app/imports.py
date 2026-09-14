import csv
import hashlib
import io
import json
import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation

from pypdf import PdfReader

from .lcl_parser_v2 import parse_lcl_pdf_layout


OPERATION_PREFIXES = (
    'CB ', 'PRLV ', 'VIR ', 'VIR.', 'VIREMENT ', 'PRET ', 'CHEQUE ', 'RETRAIT ',
    'REMBOURSEMENT ', 'VERSEMENT ', 'COTISATION ', 'FRAIS ', 'COMMISSION ',
)
DATE_ROW = re.compile(r'^(\d{2}\.\d{2})\s+(\d{2}\.\d{2}\.\d{2})\s+(.*)$')
AMOUNT = re.compile(r'(\d[\d ]*,\d{2})')
CARD_DATE = re.compile(r'\s+\d{2}/\d{2}/\d{2}$')

IMPORT_COLUMNS = {
    'period_start': 'TEXT',
    'period_end': 'TEXT',
    'opening_balance_cents': 'INTEGER',
    'closing_balance_cents': 'INTEGER',
    'debit_total_cents': 'INTEGER NOT NULL DEFAULT 0',
    'credit_total_cents': 'INTEGER NOT NULL DEFAULT 0',
    'auto_classified_rows': 'INTEGER NOT NULL DEFAULT 0',
    'quality_status': "TEXT NOT NULL DEFAULT 'unverified'",
    'quality_message': 'TEXT',
}


def ensure_import_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS imports (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER NOT NULL REFERENCES accounts(id),
        filename TEXT NOT NULL,
        source_type TEXT NOT NULL,
        bank TEXT,
        status TEXT NOT NULL DEFAULT 'processing',
        total_rows INTEGER NOT NULL DEFAULT 0,
        imported_rows INTEGER NOT NULL DEFAULT 0,
        duplicate_rows INTEGER NOT NULL DEFAULT 0,
        review_rows INTEGER NOT NULL DEFAULT 0,
        error_message TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS transaction_import_meta (
        transaction_id INTEGER PRIMARY KEY REFERENCES transactions(id) ON DELETE CASCADE,
        import_id INTEGER NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
        fingerprint TEXT NOT NULL UNIQUE,
        normalized_label TEXT NOT NULL,
        review_status TEXT NOT NULL DEFAULT 'needs_review',
        raw_payload TEXT,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE INDEX IF NOT EXISTS idx_import_meta_review ON transaction_import_meta(review_status, transaction_id);
    CREATE INDEX IF NOT EXISTS idx_import_meta_import ON transaction_import_meta(import_id, review_status);
    """)
    existing = {row['name'] for row in conn.execute('PRAGMA table_info(imports)').fetchall()}
    for name, sql_type in IMPORT_COLUMNS.items():
        if name not in existing:
            conn.execute(f'ALTER TABLE imports ADD COLUMN {name} {sql_type}')


def normalize_label(label: str) -> str:
    value = ' '.join((label or '').replace('\u00a0', ' ').split())
    value = CARD_DATE.sub('', value)
    return value.upper().strip()


def normalize_csv_header(value: str) -> str:
    normalized = unicodedata.normalize('NFKD', normalize_label(value))
    return ''.join(char for char in normalized if not unicodedata.combining(char)).replace(' ', '_')


def make_fingerprint(account_id: int, booking_date: str, amount_cents: int, label: str) -> str:
    payload = f'{account_id}|{booking_date}|{amount_cents}|{normalize_label(label)}'
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def parse_money(value: str) -> int:
    cleaned = (value or '').strip().replace('\u00a0', ' ').replace(' ', '').replace(',', '.')
    if not cleaned or cleaned == '.':
        return 0
    try:
        return int(Decimal(cleaned) * 100)
    except InvalidOperation as exc:
        raise ValueError(f'Montant invalide: {value}') from exc


def _date(value: str) -> str:
    value = value.strip()
    for fmt in ('%d/%m/%Y', '%d.%m.%Y', '%Y-%m-%d', '%d/%m/%y', '%d.%m.%y'):
        try:
            return datetime.strptime(value, fmt).date().isoformat()
        except ValueError:
            pass
    raise ValueError(f'Date invalide: {value}')


def parse_csv_bytes(data: bytes) -> list[dict]:
    text = data.decode('utf-8-sig', errors='replace')
    sample = text[:4096]
    header = next((line for line in text.splitlines() if line.strip()), '')
    if ';' in header:
        reader = csv.DictReader(io.StringIO(text), delimiter=';')
    elif '\t' in header:
        reader = csv.DictReader(io.StringIO(text), delimiter='\t')
    else:
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=',')
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    rows = []
    for raw in reader:
        canon = {normalize_csv_header(k): (v or '').strip() for k, v in raw.items() if k}
        date_value = next((canon.get(k) for k in ('DATE', 'DATE_OPERATION', 'BOOKING_DATE', 'DATE_COMPTABLE') if canon.get(k)), None)
        label = next((canon.get(k) for k in ('LIBELLE', 'LABEL', 'DESCRIPTION', 'OPERATION') if canon.get(k)), None)
        debit = next((canon.get(k) for k in ('DEBIT', 'MONTANT_DEBIT') if canon.get(k)), '')
        credit = next((canon.get(k) for k in ('CREDIT', 'MONTANT_CREDIT') if canon.get(k)), '')
        signed = next((canon.get(k) for k in ('MONTANT', 'AMOUNT') if canon.get(k)), '')
        if not date_value or not label:
            continue
        amount = parse_money(signed) if signed else parse_money(credit) - parse_money(debit)
        if amount == 0:
            continue
        rows.append({'booking_date': _date(date_value), 'amount_cents': amount, 'label': label, 'raw': raw})
    return rows


def _lcl_labels(text: str) -> list[str]:
    before_page = text.split('Page ', 1)[0]
    labels = []
    for line in before_page.splitlines():
        clean = ' '.join(line.split()).strip()
        if clean.startswith(OPERATION_PREFIXES):
            labels.append(clean)
    return labels


def _lcl_rows(text: str, year_hint: int) -> list[dict]:
    rows = []
    for line in text.splitlines():
        clean = ' '.join(line.split())
        match = DATE_ROW.match(clean)
        if not match:
            continue
        booking_short, value_date, tail = match.groups()
        amounts = AMOUNT.findall(tail)
        if not amounts:
            continue
        first_amount = tail.find(amounts[0])
        dot_index = tail.find('.')
        credit = dot_index != -1 and dot_index < first_amount
        amount = parse_money(amounts[-1]) * (1 if credit else -1)
        day, month = map(int, booking_short.split('.'))
        year = datetime.strptime(value_date, '%d.%m.%y').year if value_date else year_hint
        rows.append({'booking_date': f'{year:04d}-{month:02d}-{day:02d}', 'amount_cents': amount, 'raw_line': clean})
    return rows


def parse_lcl_pdf_bytes(data: bytes) -> list[dict]:
    """Compatibility wrapper for the validated layout-aware LCL parser V2."""
    rows, _ = parse_lcl_pdf_layout(data)
    return rows


def parse_statement(filename: str, data: bytes) -> tuple[str, str | None, list[dict]]:
    lower = filename.lower()
    if lower.endswith('.csv'):
        rows = parse_csv_bytes(data)
        if not rows:
            raise ValueError('Aucune opération exploitable détectée dans ce CSV')
        return 'csv', None, rows
    if lower.endswith('.pdf'):
        rows, _ = parse_lcl_pdf_layout(data)
        return 'pdf', 'LCL', rows
    raise ValueError('Format non supporté. Utilisez PDF ou CSV.')


def _balance_from_text(text: str, label: str) -> int | None:
    match = re.search(rf'{re.escape(label)}\s+(\d[\d ]*,\d{{2}})', text, re.IGNORECASE)
    return parse_money(match.group(1)) if match else None


def statement_metadata(data: bytes, bank: str | None, rows: list[dict]) -> dict:
    dates = sorted(row['booking_date'] for row in rows)
    metadata = {
        'period_start': dates[0] if dates else None,
        'period_end': dates[-1] if dates else None,
        'opening_balance_cents': None,
        'closing_balance_cents': None,
        'debit_total_cents': sum(-row['amount_cents'] for row in rows if row['amount_cents'] < 0),
        'credit_total_cents': sum(row['amount_cents'] for row in rows if row['amount_cents'] > 0),
    }
    if bank == 'LCL':
        _, parser_meta = parse_lcl_pdf_layout(data)
        metadata['period_start'] = parser_meta.get('period_start') or metadata['period_start']
        metadata['period_end'] = parser_meta.get('period_end') or metadata['period_end']
        metadata['opening_balance_cents'] = parser_meta.get('opening_balance_cents')
        metadata['closing_balance_cents'] = parser_meta.get('closing_balance_cents')
    return metadata


def infer_transaction_type(label: str, amount_cents: int) -> str:
    normalized = normalize_label(label)
    if amount_cents > 0 and normalized.startswith('CB '):
        return 'refund'
    return 'income' if amount_cents > 0 else 'expense'


def classify_row(conn, label: str, amount_cents: int) -> tuple[str | None, str, int, bool]:
    normalized = normalize_label(label)
    rules = conn.execute('SELECT * FROM categorization_rules WHERE is_active=1 ORDER BY priority,rowid').fetchall()
    match = next((r for r in rules if r['pattern'] in normalized), None)
    if match:
        tx_type = match['transaction_type'] or infer_transaction_type(label, amount_cents)
        internal = tx_type == 'transfer' or match['category'] == 'Transfert interne'
        return match['category'], tx_type, int(internal), True
    if normalized.startswith('VIR.PERMANENT COMPTE JOINT'):
        return 'Transfert interne', 'transfer', 1, True
    own_transfer_prefixes = ('VIR SEPA M PETER BACHOUR', 'VIR INST PETER BACHOUR', 'VIREMENT M PETER BACHOUR')
    if normalized.startswith(own_transfer_prefixes):
        return 'Transfert interne', 'transfer', 1, True
    if amount_cents > 0 and (normalized.startswith('VIREMENT KARDHAM DIGITAL') or normalized.startswith('VIREMENT SAS KARDHAM DIGITAL')):
        if amount_cents >= 100000:
            return 'Salaire', 'income', 0, True
        return 'Frais professionnel remboursé', 'reimbursement', 0, True
    if normalized.startswith('CB APPLE.COM/BILL') and amount_cents == -2299:
        return 'Frais professionnel remboursé', 'expense', 0, True
    if amount_cents > 0 and normalized.startswith('REMBOURSEMENT '):
        return 'Remboursement', 'refund', 0, True
    if amount_cents > 0 and normalized.startswith('CB '):
        return None, 'refund', 0, False
    return None, 'income' if amount_cents > 0 else 'expense', 0, False


def _duplicate_exists(conn, account_id: int, booking_date: str, amount_cents: int, label: str, fingerprint: str) -> bool:
    if conn.execute('SELECT 1 FROM transaction_import_meta WHERE fingerprint=?', (fingerprint,)).fetchone():
        return True
    candidates = conn.execute('SELECT label FROM transactions WHERE account_id=? AND booking_date=? AND amount_cents=?', (account_id, booking_date, amount_cents)).fetchall()
    normalized = normalize_label(label)
    return any(normalize_label(row['label']) == normalized for row in candidates)


def _import_arithmetic_is_valid(row) -> bool:
    opening = row['opening_balance_cents']
    closing = row['closing_balance_cents']
    if opening is None or closing is None:
        return False
    calculated = int(opening) + int(row['credit_total_cents'] or 0) - int(row['debit_total_cents'] or 0)
    return calculated == int(closing)


def refresh_review_counts(conn, import_ids: set[int] | None = None) -> None:
    """Synchronize pending-row counters and promote fully reviewed, reconciled statements."""
    if import_ids:
        ids = sorted(import_ids)
    else:
        ids = [row['id'] for row in conn.execute('SELECT id FROM imports').fetchall()]
    for import_id in ids:
        count = int(conn.execute(
            "SELECT COUNT(*) total FROM transaction_import_meta WHERE import_id=? AND review_status='needs_review'",
            (import_id,),
        ).fetchone()['total'])
        row = conn.execute(
            """SELECT quality_status,opening_balance_cents,closing_balance_cents,
                      debit_total_cents,credit_total_cents
               FROM imports WHERE id=?""",
            (import_id,),
        ).fetchone()
        if not row:
            continue
        if (
            count == 0
            and row['quality_status'] in {'review', 'unverified', 'ok'}
            and _import_arithmetic_is_valid(row)
        ):
            conn.execute(
                """UPDATE imports
                   SET review_rows=0,quality_status='verified',
                       quality_message='Revue terminée · rapprochement comptable vérifié'
                   WHERE id=?""",
                (import_id,),
            )
        else:
            conn.execute('UPDATE imports SET review_rows=? WHERE id=?', (count, import_id))


def accept_categorized_import_reviews(
    conn,
    transaction_ids: set[int] | None = None,
) -> int:
    """Accept explicitly categorized imported rows and refresh their statement status."""
    clauses = ["m.review_status='needs_review'", "TRIM(COALESCE(t.category,''))<>''"]
    params: list[object] = []
    if transaction_ids is not None:
        ids = sorted({int(value) for value in transaction_ids})
        if not ids:
            return 0
        clauses.append(f"m.transaction_id IN ({','.join('?' for _ in ids)})")
        params.extend(ids)
    rows = conn.execute(
        f"""SELECT m.transaction_id,m.import_id
            FROM transaction_import_meta m
            JOIN transactions t ON t.id=m.transaction_id
            WHERE {' AND '.join(clauses)}""",
        params,
    ).fetchall()
    if not rows:
        return 0
    transaction_ids_to_accept = [int(row['transaction_id']) for row in rows]
    conn.executemany(
        "UPDATE transaction_import_meta SET review_status='accepted' WHERE transaction_id=?",
        [(transaction_id,) for transaction_id in transaction_ids_to_accept],
    )
    refresh_review_counts(conn, {int(row['import_id']) for row in rows})
    return len(transaction_ids_to_accept)


def apply_rule_to_inbox(conn, pattern: str, category: str, tx_type: str) -> int:
    normalized_pattern = normalize_label(pattern)
    if not normalized_pattern:
        return 0
    rows = conn.execute("SELECT transaction_id,import_id,normalized_label FROM transaction_import_meta WHERE review_status='needs_review'").fetchall()
    affected_imports = set()
    count = 0
    for row in rows:
        if normalized_pattern not in row['normalized_label']:
            continue
        tx = conn.execute('SELECT amount_cents FROM transactions WHERE id=?', (row['transaction_id'],)).fetchone()
        resolved_type = tx_type or infer_transaction_type(row['normalized_label'], tx['amount_cents'])
        internal = int(resolved_type == 'transfer' or category == 'Transfert interne')
        conn.execute('UPDATE transactions SET category=?,transaction_type=?,is_internal_transfer=? WHERE id=?', (category, resolved_type, internal, row['transaction_id']))
        conn.execute("UPDATE transaction_import_meta SET review_status='accepted' WHERE transaction_id=?", (row['transaction_id'],))
        affected_imports.add(row['import_id'])
        count += 1
    refresh_review_counts(conn, affected_imports)
    return count


def import_rows(conn, import_id: int, account_id: int, rows: list[dict]) -> dict:
    imported = duplicates = review = auto_classified = 0
    for row in rows:
        fingerprint = make_fingerprint(account_id, row['booking_date'], row['amount_cents'], row['label'])
        if _duplicate_exists(conn, account_id, row['booking_date'], row['amount_cents'], row['label'], fingerprint):
            duplicates += 1
            continue
        category, tx_type, internal, classified = classify_row(conn, row['label'], row['amount_cents'])
        needs_review = bool(row.get('force_review')) or not classified
        cur = conn.execute('INSERT INTO transactions(account_id,booking_date,amount_cents,label,category,transaction_type,is_internal_transfer) VALUES(?,?,?,?,?,?,?)', (account_id, row['booking_date'], row['amount_cents'], row['label'], category, tx_type, internal))
        conn.execute('INSERT INTO transaction_import_meta(transaction_id,import_id,fingerprint,normalized_label,review_status,raw_payload) VALUES(?,?,?,?,?,?)', (cur.lastrowid, import_id, fingerprint, normalize_label(row['label']), 'needs_review' if needs_review else 'accepted', json.dumps(row.get('raw'), ensure_ascii=False)))
        imported += 1
        review += int(needs_review)
        auto_classified += int(not needs_review)
    return {'imported': imported, 'duplicates': duplicates, 'review': review, 'auto_classified': auto_classified}


def evaluate_import_quality(conn, account_id: int, import_id: int, metadata: dict, result: dict) -> dict:
    messages = []
    status = 'ok'
    opening = metadata.get('opening_balance_cents')
    closing = metadata.get('closing_balance_cents')
    if opening is not None and closing is not None:
        calculated = opening + metadata['credit_total_cents'] - metadata['debit_total_cents']
        if calculated != closing:
            status = 'warning'
            messages.append(f'Écart de rapprochement: {calculated - closing} centimes')
        previous = conn.execute(
            "SELECT closing_balance_cents,period_end FROM imports WHERE account_id=? AND id<>? AND status='completed' AND closing_balance_cents IS NOT NULL AND period_end<? ORDER BY period_end DESC,id DESC LIMIT 1",
            (account_id, import_id, metadata.get('period_start') or '9999-12-31'),
        ).fetchone()
        if previous and previous['closing_balance_cents'] != opening:
            status = 'warning'
            messages.append('Le solde d’ouverture ne correspond pas à la clôture du relevé précédent')
        elif previous:
            messages.append('Continuité avec le relevé précédent vérifiée')
    else:
        status = 'unverified' if result['review'] == 0 else 'review'
        messages.append('Continuité de solde non contrôlable pour ce format')
    if result['review'] > 0 and status == 'ok':
        status = 'review'
    if result['review'] > 0:
        messages.append(f"{result['review']} opération(s) à vérifier")
    if not messages:
        messages.append('Import cohérent')
    return {'status': status, 'message': ' · '.join(messages)}