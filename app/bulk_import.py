import hashlib
import io
import json
import re
from datetime import datetime
from pathlib import Path

from pypdf import PdfReader

from .import_identity import ensure_identity_schema, find_duplicate_statement, import_rows_occurrence_safe, statement_fingerprint
from .imports import ensure_import_schema, evaluate_import_quality, parse_money, parse_statement, statement_metadata

PAYROLL_HINTS = ('BULLETIN DE PAIE', 'BULLETIN DE SALAIRE', 'NET A PAYER', 'NET PAYE', 'NET À PAYER', 'NET IMPOSABLE')
MONTHS = {
    'JANVIER': 1, 'FEVRIER': 2, 'FÉVRIER': 2, 'MARS': 3, 'AVRIL': 4, 'MAI': 5, 'JUIN': 6,
    'JUILLET': 7, 'AOUT': 8, 'AOÛT': 8, 'SEPTEMBRE': 9, 'OCTOBRE': 10, 'NOVEMBRE': 11, 'DECEMBRE': 12, 'DÉCEMBRE': 12,
}


def ensure_bulk_schema(conn):
    conn.executescript('''
    CREATE TABLE IF NOT EXISTS bulk_import_batches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        account_id INTEGER REFERENCES accounts(id),
        status TEXT NOT NULL DEFAULT 'staging',
        total_files INTEGER NOT NULL DEFAULT 0,
        statement_files INTEGER NOT NULL DEFAULT 0,
        payroll_files INTEGER NOT NULL DEFAULT 0,
        unknown_files INTEGER NOT NULL DEFAULT 0,
        warning_files INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        committed_at TEXT
    );
    CREATE TABLE IF NOT EXISTS bulk_import_documents (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        batch_id INTEGER NOT NULL REFERENCES bulk_import_batches(id) ON DELETE CASCADE,
        filename TEXT NOT NULL,
        file_hash TEXT NOT NULL,
        document_type TEXT NOT NULL,
        period TEXT,
        status TEXT NOT NULL DEFAULT 'ready',
        warning TEXT,
        summary_json TEXT,
        payload_json TEXT,
        committed_entity_id INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(batch_id,file_hash)
    );
    CREATE INDEX IF NOT EXISTS idx_bulk_docs_batch ON bulk_import_documents(batch_id,status);
    CREATE TABLE IF NOT EXISTS payroll_records (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        period TEXT NOT NULL,
        employer TEXT,
        gross_cents INTEGER,
        net_before_tax_cents INTEGER,
        net_paid_cents INTEGER,
        taxable_net_cents INTEGER,
        withholding_tax_cents INTEGER,
        withholding_rate REAL,
        reimbursements_cents INTEGER,
        bonuses_cents INTEGER,
        source_filename TEXT,
        source_hash TEXT NOT NULL UNIQUE,
        source_status TEXT NOT NULL DEFAULT 'confirmed',
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    ''')


def _pdf_text(data: bytes) -> str:
    reader = PdfReader(io.BytesIO(data))
    return '\n'.join((page.extract_text() or '') for page in reader.pages)


def detect_document(filename: str, data: bytes) -> str:
    lower = filename.lower()
    if lower.endswith('.csv'):
        return 'statement'
    if not lower.endswith('.pdf'):
        return 'unknown'
    text = _pdf_text(data)
    upper = text.upper()
    if 'RELEVE DE COMPTE' in upper or 'RELEVÉ DE COMPTE' in upper or 'DATE LIBELLE VALEUR DEBIT CREDIT' in upper:
        return 'statement'
    if any(token in upper for token in PAYROLL_HINTS):
        return 'payroll'
    return 'unknown'


def _find_money(text: str, labels: tuple[str, ...]) -> int | None:
    for label in labels:
        pattern = rf'{label}[^\d]{{0,30}}(\d[\d\s\.]*[,\.]\d{{2}})'
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            raw = match.group(1).replace('.', '').replace(' ', '')
            if ',' not in raw and raw.count('.') == 1:
                raw = raw.replace('.', ',')
            try:
                return parse_money(raw)
            except ValueError:
                pass
    return None


def _money_tokens(line: str) -> list[int]:
    values: list[int] = []
    for raw in re.findall(r'\d{1,3}(?:[ .]\d{3})*(?:[,.]\d{2})|\d+(?:[,.]\d{2})', line):
        cleaned = raw.replace(' ', '')
        if cleaned.count('.') > 1:
            cleaned = cleaned.replace('.', '')
        elif '.' in cleaned and ',' not in cleaned:
            cleaned = cleaned.replace('.', ',')
        try:
            values.append(parse_money(cleaned))
        except ValueError:
            continue
    return values


def _find_line_money(text: str, label_pattern: str, *, value_index: int = 0) -> int | None:
    regex = re.compile(label_pattern, re.IGNORECASE)
    for raw_line in text.splitlines():
        line = re.sub(r'\s+', ' ', raw_line).strip()
        if not line or not regex.search(line):
            continue
        tail = regex.sub('', line, count=1).strip()
        values = _money_tokens(tail)
        if len(values) > value_index:
            return values[value_index]
    return None


def _find_withholding_from_line(text: str) -> tuple[int | None, float | None]:
    pattern = re.compile(r'Imp[oô]t\s+sur\s+le\s+revenu\s+pr[ée]lev[ée]\s+[àa]\s+la\s+source', re.IGNORECASE)
    for raw_line in text.splitlines():
        line = re.sub(r'\s+', ' ', raw_line).strip()
        if not pattern.search(line):
            continue
        values = _money_tokens(line)
        if len(values) >= 3:
            amount = values[2]
            rate_match = re.search(r'(\d{1,2}[,.]\d{2,4})\s+(\d+[,.]\d{2})', line)
            rate = float(rate_match.group(1).replace(',', '.')) if rate_match else None
            return amount, rate
    return None, None


def _find_net_paid(text: str) -> int | None:
    for pattern in (
        r'^MONTANT\s+NET\s+(?:A|À)\s+PAYER\s*\(EN\s+EUROS\)',
        r'^NET\s+(?:A|À)\s+PAYER\s+AU\s+SALARI[ÉE]\b',
    ):
        exact = _find_line_money(text, pattern)
        if exact is not None:
            return exact

    strong_labels = (
        r'NET\s+PAY[ÉE](?:\s+EN\s+EUROS)?',
        r'NET\s+VERS[ÉE]',
        r'MONTANT\s+NET\s+VERS[ÉE]',
    )
    value = _find_money(text, strong_labels)
    if value is not None:
        return value

    pattern = re.compile(
        r'NET\s+(?:A|À)\s+PAYER(?!\s+AVANT\s+IMP[ÔO]T)[^\d]{0,30}(\d[\d\s\.]*[,\.]\d{2})',
        re.IGNORECASE,
    )
    match = pattern.search(text)
    if not match:
        return None
    raw = match.group(1).replace('.', '').replace(' ', '')
    try:
        return parse_money(raw)
    except ValueError:
        return None


def _period_from_text(text: str, filename: str) -> str | None:
    upper = text.upper()
    for name, month in MONTHS.items():
        match = re.search(rf'\b{name}\s+(20\d{{2}})\b', upper)
        if match:
            return f'{int(match.group(1)):04d}-{month:02d}'
    match = re.search(r'\b(0[1-9]|1[0-2])[/.-](20\d{2})\b', text)
    if match:
        return f'{int(match.group(2)):04d}-{int(match.group(1)):02d}'
    match = re.search(r'(20\d{2})[-_]?([01]\d)', filename)
    if match and 1 <= int(match.group(2)) <= 12:
        return f'{match.group(1)}-{match.group(2)}'
    return None


def parse_payroll(filename: str, data: bytes) -> tuple[dict, list[str]]:
    text = _pdf_text(data)
    normalized = ' '.join(text.split())
    period = _period_from_text(normalized, filename)

    gross = None
    for pattern in (
        r'^MONTANT\s+BRUT\b',
        r'^.*?TOTAL\s+BRUT\s*:?\s*',
    ):
        gross = _find_line_money(text, pattern)
        if gross is not None:
            break
    if gross is None:
        gross = _find_money(normalized, (r'SALAIRE\s+BRUT', r'TOTAL\s+BRUT'))

    net_before_tax = _find_line_money(text, r'^MONTANT\s+NET\s+(?:A|À)\s+PAYER\s+AVANT\s+IMP[ÔO]T\s+SUR\s+LE\s+REVENU\b')
    if net_before_tax is None:
        net_before_tax = _find_line_money(text, r'^NET\s+(?:A|À)\s+PAYER\s+AVANT\s+IMP[ÔO]T\s+SUR\s+LE\s+REVENU\b')
    if net_before_tax is None:
        net_before_tax = _find_money(normalized, (r'NET\s+AVANT\s+IMP[ÔO]T', r'NET\s+A\s+PAYER\s+AVANT\s+IMP[ÔO]T'))

    net_paid = _find_net_paid(text)

    taxable = _find_line_money(text, r'^MONTANT\s+NET\s+IMPOSABLE\b')
    if taxable is None:
        taxable = _find_money(normalized, (r'NET\s+IMPOSABLE', r'NET\s+FISCAL'))

    withholding, rate = _find_withholding_from_line(text)
    if withholding is None:
        withholding = _find_money(normalized, (r'PR[ÉE]L[ÈE]VEMENT\s+A\s+LA\s+SOURCE', r'IMP[ÔO]T\s+SUR\s+LE\s+REVENU'))
    if rate is None:
        rate_match = re.search(r'(?:TAUX|PR[ÉE]L[ÈE]VEMENT)[^%]{0,40}(\d{1,2}[,.]\d{1,3})\s*%', normalized, re.IGNORECASE)
        if rate_match:
            rate = float(rate_match.group(1).replace(',', '.'))

    reimbursements = _find_money(normalized, (r'REMBOURSEMENT\w*\s+DE\s+FRAIS', r'FRAIS\s+PROFESSIONNELS'))
    bonuses = _find_money(normalized, (r'PRIME\w*'))

    employer = None
    employer_match = re.search(r'\b(KARDHAM(?:\s+DIGITAL)?)\b', normalized, re.IGNORECASE)
    if employer_match:
        employer = employer_match.group(1).title()

    warnings = []
    if not period:
        warnings.append('Période de paie non détectée')
    if net_paid is None:
        warnings.append('Net payé non détecté')
    if gross is None:
        warnings.append('Salaire brut non détecté')
    if gross is not None and gross > 2_000_000:
        warnings.append(f'Salaire brut incohérent ({gross} centimes)')
    if net_before_tax is not None and net_paid is not None and net_paid > net_before_tax + 100_000:
        warnings.append('Net payé supérieur au net avant impôt de façon incohérente')
    if withholding is not None and net_before_tax is not None and withholding > net_before_tax:
        warnings.append('Prélèvement à la source incohérent')
    payload = {
        'period': period,
        'employer': employer,
        'gross_cents': gross,
        'net_before_tax_cents': net_before_tax,
        'net_paid_cents': net_paid,
        'taxable_net_cents': taxable,
        'withholding_tax_cents': withholding,
        'withholding_rate': rate,
        'reimbursements_cents': reimbursements,
        'bonuses_cents': bonuses,
    }
    return payload, warnings


def stage_document(conn, batch_id: int, account_id: int, filename: str, data: bytes) -> dict:
    file_hash = hashlib.sha256(data).hexdigest()
    existing = conn.execute('SELECT id FROM bulk_import_documents WHERE batch_id=? AND file_hash=?', (batch_id, file_hash)).fetchone()
    if existing:
        return {'id': existing['id'], 'filename': filename, 'document_type': 'duplicate', 'status': 'duplicate', 'warning': 'Fichier présent deux fois dans le lot'}
    document_type = detect_document(filename, data)
    warning = None
    summary = {}
    payload = {}
    period = None
    status = 'ready'
    if document_type == 'statement':
        try:
            source_type, bank, rows = parse_statement(filename, data)
            metadata = statement_metadata(data, bank, rows)
            period = (metadata.get('period_end') or metadata.get('period_start') or '')[:7] or None
            summary = {
                'bank': bank,
                'source_type': source_type,
                'transactions': len(rows),
                **metadata,
            }
            payload = {'bank': bank, 'source_type': source_type, 'rows': rows, 'metadata': metadata}
            prior = conn.execute("SELECT id,filename FROM imports WHERE account_id=? AND period_start=? AND period_end=? AND status IN ('completed','duplicate') LIMIT 1", (account_id, metadata.get('period_start'), metadata.get('period_end'))).fetchone()
            if prior:
                warning = f"Période déjà présente via {prior['filename']}"
        except Exception as exc:
            status = 'warning'
            warning = str(exc)
    elif document_type == 'payroll':
        try:
            payload, warnings = parse_payroll(filename, data)
            period = payload.get('period')
            summary = payload.copy()
            existing_payroll = conn.execute('SELECT id,source_filename FROM payroll_records WHERE source_hash=?', (file_hash,)).fetchone()
            if existing_payroll:
                warnings.append(f"Fiche déjà importée via {existing_payroll['source_filename']}")
            if warnings:
                warning = ' · '.join(warnings)
                status = 'warning'
        except Exception as exc:
            status = 'warning'
            warning = str(exc)
    else:
        status = 'warning'
        warning = 'Type de document non reconnu'
    cur = conn.execute('''INSERT INTO bulk_import_documents(batch_id,filename,file_hash,document_type,period,status,warning,summary_json,payload_json)
                          VALUES(?,?,?,?,?,?,?,?,?)''', (batch_id, filename, file_hash, document_type, period, status, warning, json.dumps(summary, ensure_ascii=False), json.dumps(payload, ensure_ascii=False)))
    return {'id': cur.lastrowid, 'filename': filename, 'document_type': document_type, 'period': period, 'status': status, 'warning': warning, 'summary': summary}


def commit_batch(conn, batch_id: int) -> dict:
    ensure_import_schema(conn)
    ensure_identity_schema(conn)
    batch = conn.execute('SELECT * FROM bulk_import_batches WHERE id=?', (batch_id,)).fetchone()
    if not batch:
        raise ValueError('Lot introuvable')
    if batch['status'] == 'committed':
        raise ValueError('Lot déjà validé')
    account_id = batch['account_id']
    docs = conn.execute("SELECT * FROM bulk_import_documents WHERE batch_id=? AND status IN ('ready','warning') ORDER BY id", (batch_id,)).fetchall()
    result = {'statements': 0, 'payrolls': 0, 'transactions': 0, 'duplicates': 0, 'warnings_skipped': 0}
    for doc in docs:
        payload = json.loads(doc['payload_json'] or '{}')
        if doc['document_type'] == 'statement':
            rows = payload.get('rows') or []
            metadata = payload.get('metadata') or {}
            if not rows:
                result['warnings_skipped'] += 1
                continue
            statement_id = statement_fingerprint(account_id, payload.get('bank'), metadata, rows)
            duplicate = find_duplicate_statement(conn, account_id, statement_id)
            if duplicate:
                conn.execute("UPDATE bulk_import_documents SET status='duplicate',committed_entity_id=? WHERE id=?", (duplicate['id'], doc['id']))
                result['duplicates'] += 1
                continue
            cur = conn.execute('''INSERT INTO imports(account_id,filename,source_type,bank,status,total_rows,period_start,period_end,
                opening_balance_cents,closing_balance_cents,debit_total_cents,credit_total_cents,statement_fingerprint)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''', (account_id, doc['filename'], payload.get('source_type') or 'pdf', payload.get('bank'), 'processing', len(rows), metadata.get('period_start'), metadata.get('period_end'), metadata.get('opening_balance_cents'), metadata.get('closing_balance_cents'), metadata.get('debit_total_cents') or 0, metadata.get('credit_total_cents') or 0, statement_id))
            import_id = cur.lastrowid
            imported = import_rows_occurrence_safe(conn, import_id, account_id, rows)
            quality = evaluate_import_quality(conn, account_id, import_id, metadata, imported)
            conn.execute("UPDATE imports SET status='completed',imported_rows=?,duplicate_rows=?,review_rows=?,auto_classified_rows=?,quality_status=?,quality_message=? WHERE id=?", (imported['imported'], imported['duplicates'], imported['review'], imported['auto_classified'], quality['status'], quality['message'], import_id))
            conn.execute("UPDATE bulk_import_documents SET status='committed',committed_entity_id=? WHERE id=?", (import_id, doc['id']))
            result['statements'] += 1
            result['transactions'] += imported['imported']
            result['duplicates'] += imported['duplicates']
        elif doc['document_type'] == 'payroll':
            if not payload.get('period') or payload.get('net_paid_cents') is None:
                result['warnings_skipped'] += 1
                continue
            try:
                cur = conn.execute('''INSERT INTO payroll_records(period,employer,gross_cents,net_before_tax_cents,net_paid_cents,taxable_net_cents,
                    withholding_tax_cents,withholding_rate,reimbursements_cents,bonuses_cents,source_filename,source_hash)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (payload.get('period'), payload.get('employer'), payload.get('gross_cents'), payload.get('net_before_tax_cents'), payload.get('net_paid_cents'), payload.get('taxable_net_cents'), payload.get('withholding_tax_cents'), payload.get('withholding_rate'), payload.get('reimbursements_cents'), payload.get('bonuses_cents'), doc['filename'], doc['file_hash']))
                conn.execute("UPDATE bulk_import_documents SET status='committed',committed_entity_id=? WHERE id=?", (cur.lastrowid, doc['id']))
                result['payrolls'] += 1
            except Exception:
                existing = conn.execute('SELECT id FROM payroll_records WHERE source_hash=?', (doc['file_hash'],)).fetchone()
                if existing:
                    conn.execute("UPDATE bulk_import_documents SET status='duplicate',committed_entity_id=? WHERE id=?", (existing['id'], doc['id']))
                    result['duplicates'] += 1
                else:
                    raise
    conn.execute("UPDATE bulk_import_batches SET status='committed',committed_at=CURRENT_TIMESTAMP WHERE id=?", (batch_id,))
    return result
