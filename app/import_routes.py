import json
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel

from .bulk_import import commit_batch, ensure_bulk_schema, stage_document
from .db import connection
from .import_identity import (
    ensure_identity_schema,
    find_duplicate_statement,
    import_rows_occurrence_safe,
    statement_fingerprint,
)
from .statement_corpus_preflight import build_batch_preflight
from .imports import (
    apply_rule_to_inbox,
    ensure_import_schema,
    evaluate_import_quality,
    import_review_groups,
    normalize_label,
    preview_rule_impact,
    parse_statement,
    refresh_review_counts,
    statement_metadata,
)

router = APIRouter()
MAX_UPLOAD_BYTES = 12 * 1024 * 1024
MAX_BULK_FILES = 100
MAX_BULK_TOTAL_BYTES = 120 * 1024 * 1024


class ReviewIn(BaseModel):
    category: str
    transaction_type: str | None = None
    create_rule: bool = False
    rule_pattern: str | None = None


@router.post('/api/imports', status_code=201)
async def upload_statement(account_id: int = Form(...), file: UploadFile = File(...)):
    filename = Path(file.filename or 'statement').name
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, 'Fichier trop volumineux (12 Mo maximum)')
    try:
        source_type, bank, rows = parse_statement(filename, data)
        metadata = statement_metadata(data, bank, rows)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    with connection() as conn:
        ensure_import_schema(conn)
        ensure_identity_schema(conn)
        if not conn.execute('SELECT 1 FROM accounts WHERE id=? AND is_active=1', (account_id,)).fetchone():
            raise HTTPException(404, 'Compte introuvable')

        statement_id = statement_fingerprint(account_id, bank, metadata, rows)
        duplicate = find_duplicate_statement(conn, account_id, statement_id)
        if duplicate:
            cur = conn.execute(
                '''INSERT INTO imports(
                     account_id,filename,source_type,bank,status,total_rows,imported_rows,duplicate_rows,review_rows,
                     period_start,period_end,opening_balance_cents,closing_balance_cents,debit_total_cents,credit_total_cents,
                     auto_classified_rows,quality_status,quality_message,statement_fingerprint,duplicate_of_import_id
                   ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (
                    account_id, filename, source_type, bank, 'duplicate', len(rows), 0, len(rows), 0,
                    metadata['period_start'], metadata['period_end'], metadata['opening_balance_cents'], metadata['closing_balance_cents'],
                    metadata['debit_total_cents'], metadata['credit_total_cents'], 0, 'ok',
                    f"Relevé déjà importé via {duplicate['filename']}", statement_id, duplicate['id'],
                ),
            )
            return {
                'id': cur.lastrowid,
                'filename': filename,
                'total_rows': len(rows),
                'metadata': metadata,
                'quality': {'status': 'ok', 'message': 'Relevé déjà importé, aucune écriture ajoutée'},
                'imported': 0,
                'duplicates': len(rows),
                'review': 0,
                'auto_classified': 0,
                'duplicate_statement': True,
                'duplicate_of_import_id': duplicate['id'],
            }

        cur = conn.execute(
            '''INSERT INTO imports(account_id,filename,source_type,bank,status,total_rows,period_start,period_end,
               opening_balance_cents,closing_balance_cents,debit_total_cents,credit_total_cents,statement_fingerprint)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                account_id, filename, source_type, bank, 'processing', len(rows), metadata['period_start'], metadata['period_end'],
                metadata['opening_balance_cents'], metadata['closing_balance_cents'], metadata['debit_total_cents'],
                metadata['credit_total_cents'], statement_id,
            ),
        )
        import_id = cur.lastrowid
        conn.execute('SAVEPOINT statement_import')
        try:
            result = import_rows_occurrence_safe(conn, import_id, account_id, rows)
            quality = evaluate_import_quality(conn, account_id, import_id, metadata, result)
            conn.execute('RELEASE SAVEPOINT statement_import')
            conn.execute(
                """UPDATE imports SET status='completed',imported_rows=?,duplicate_rows=?,review_rows=?,auto_classified_rows=?,
                   quality_status=?,quality_message=? WHERE id=?""",
                (result['imported'], result['duplicates'], result['review'], result['auto_classified'], quality['status'], quality['message'], import_id),
            )
        except Exception as exc:
            conn.execute('ROLLBACK TO SAVEPOINT statement_import')
            conn.execute('RELEASE SAVEPOINT statement_import')
            conn.execute("UPDATE imports SET status='failed',error_message=? WHERE id=?", (str(exc)[:500], import_id))
            raise HTTPException(500, 'Import interrompu sans écriture partielle') from exc
    return {
        'id': import_id,
        'filename': filename,
        'total_rows': len(rows),
        'metadata': metadata,
        'quality': quality,
        'duplicate_statement': False,
        **result,
    }


@router.post('/api/imports/bulk/analyze', status_code=201)
async def bulk_analyze(account_id: int = Form(...), files: list[UploadFile] = File(...)):
    if not files:
        raise HTTPException(400, 'Aucun fichier sélectionné')
    if len(files) > MAX_BULK_FILES:
        raise HTTPException(413, f'{MAX_BULK_FILES} fichiers maximum par lot')
    prepared = []
    total_bytes = 0
    for upload in files:
        filename = Path(upload.filename or 'document').name
        data = await upload.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, f'{filename}: 12 Mo maximum par fichier')
        total_bytes += len(data)
        if total_bytes > MAX_BULK_TOTAL_BYTES:
            raise HTTPException(413, 'Lot trop volumineux (120 Mo maximum)')
        prepared.append((filename, data))

    with connection() as conn:
        ensure_import_schema(conn)
        ensure_identity_schema(conn)
        ensure_bulk_schema(conn)
        if not conn.execute('SELECT 1 FROM accounts WHERE id=? AND is_active=1', (account_id,)).fetchone():
            raise HTTPException(404, 'Compte introuvable')
        cur = conn.execute('INSERT INTO bulk_import_batches(account_id,total_files) VALUES(?,?)', (account_id, len(prepared)))
        batch_id = cur.lastrowid
        documents = []
        counts = {'statement': 0, 'payroll': 0, 'unknown': 0, 'warning': 0}
        for filename, data in prepared:
            try:
                doc = stage_document(conn, batch_id, account_id, filename, data)
            except Exception as exc:
                doc = {'filename': filename, 'document_type': 'unknown', 'status': 'warning', 'warning': str(exc)}
            documents.append(doc)
            dtype = doc.get('document_type')
            if dtype in counts:
                counts[dtype] += 1
            elif dtype == 'duplicate':
                counts['warning'] += 1
            else:
                counts['unknown'] += 1
            if doc.get('status') == 'warning' or doc.get('warning'):
                counts['warning'] += 1
        conn.execute('''UPDATE bulk_import_batches SET statement_files=?,payroll_files=?,unknown_files=?,warning_files=? WHERE id=?''',
                     (counts['statement'], counts['payroll'], counts['unknown'], counts['warning'], batch_id))
        preflight = build_batch_preflight(conn, batch_id)
    return {'batch_id': batch_id, 'status': 'staging', 'counts': counts, 'documents': documents, 'preflight': preflight}


@router.get('/api/imports/bulk/{batch_id}')
def bulk_batch(batch_id: int):
    with connection() as conn:
        ensure_bulk_schema(conn)
        batch = conn.execute('SELECT b.*,a.name account_name FROM bulk_import_batches b LEFT JOIN accounts a ON a.id=b.account_id WHERE b.id=?', (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(404, 'Lot introuvable')
        docs = conn.execute('SELECT id,filename,document_type,period,status,warning,summary_json,committed_entity_id FROM bulk_import_documents WHERE batch_id=? ORDER BY id', (batch_id,)).fetchall()
        preflight = build_batch_preflight(conn, batch_id)
    return {'batch': dict(batch), 'documents': [{**dict(row), 'summary': json.loads(row['summary_json'] or '{}')} for row in docs], 'preflight': preflight}


@router.post('/api/imports/bulk/{batch_id}/commit')
def bulk_commit(batch_id: int):
    with connection() as conn:
        ensure_bulk_schema(conn)
        try:
            preflight = build_batch_preflight(conn, batch_id)
            if not preflight['can_commit']:
                raise HTTPException(
                    409,
                    detail={
                        'message': 'Validation bloquée par une incohérence entre les relevés.',
                        'preflight': preflight,
                    },
                )
            result = commit_batch(conn, batch_id)
        except HTTPException:
            raise
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(500, f'Validation du lot interrompue : {str(exc)[:180]}') from exc
    return {'ok': True, 'batch_id': batch_id, **result}


@router.delete('/api/imports/bulk/{batch_id}')
def bulk_discard(batch_id: int):
    with connection() as conn:
        ensure_bulk_schema(conn)
        batch = conn.execute('SELECT status FROM bulk_import_batches WHERE id=?', (batch_id,)).fetchone()
        if not batch:
            raise HTTPException(404, 'Lot introuvable')
        if batch['status'] == 'committed':
            raise HTTPException(400, 'Un lot déjà validé ne peut pas être supprimé depuis le staging')
        conn.execute('DELETE FROM bulk_import_batches WHERE id=?', (batch_id,))
    return {'ok': True}


@router.get('/api/imports/payroll')
def payroll_history(limit: int = 36):
    limit = min(max(limit, 1), 120)
    with connection() as conn:
        ensure_bulk_schema(conn)
        rows = conn.execute('SELECT * FROM payroll_records ORDER BY period DESC,id DESC LIMIT ?', (limit,)).fetchall()
    return [dict(r) for r in rows]


@router.get('/api/imports')
def list_imports(limit: int = 20):
    limit = min(max(limit, 1), 100)
    with connection() as conn:
        ensure_import_schema(conn)
        ensure_identity_schema(conn)
        refresh_review_counts(conn)
        rows = conn.execute(
            'SELECT i.*,a.name account_name FROM imports i JOIN accounts a ON a.id=i.account_id ORDER BY i.id DESC LIMIT ?',
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]




@router.get('/api/imports/inbox/rule-preview')
def import_rule_preview(pattern: str = Query(min_length=1, max_length=180)):
    with connection() as conn:
        ensure_import_schema(conn)
        ensure_identity_schema(conn)
        return preview_rule_impact(conn, pattern)


@router.get('/api/imports/inbox/groups')
def import_inbox_groups(limit: int = 100):
    limit = min(max(limit, 1), 200)
    with connection() as conn:
        ensure_import_schema(conn)
        ensure_identity_schema(conn)
        return import_review_groups(conn, limit)


@router.get('/api/imports/inbox')
def import_inbox(limit: int = 100):
    limit = min(max(limit, 1), 500)
    with connection() as conn:
        ensure_import_schema(conn)
        ensure_identity_schema(conn)
        rows = conn.execute(
            """
            SELECT t.id,t.booking_date,t.amount_cents,t.label,t.category,t.transaction_type,t.is_internal_transfer,
                   a.name account_name,m.normalized_label,m.review_status,m.import_id
            FROM transaction_import_meta m
            JOIN transactions t ON t.id=m.transaction_id
            JOIN accounts a ON a.id=t.account_id
            WHERE m.review_status='needs_review'
            ORDER BY t.booking_date DESC,t.id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


@router.put('/api/imports/inbox/{transaction_id}')
def review_imported_transaction(transaction_id: int, payload: ReviewIn):
    with connection() as conn:
        ensure_import_schema(conn)
        ensure_identity_schema(conn)
        row = conn.execute(
            'SELECT t.*,m.normalized_label,m.import_id FROM transactions t JOIN transaction_import_meta m ON m.transaction_id=t.id WHERE t.id=?',
            (transaction_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, 'Mouvement importé introuvable')
        tx_type = payload.transaction_type or ('income' if row['amount_cents'] > 0 else 'expense')
        internal = int(tx_type == 'transfer' or payload.category == 'Transfert interne')
        conn.execute('UPDATE transactions SET category=?,transaction_type=?,is_internal_transfer=? WHERE id=?', (payload.category, tx_type, internal, transaction_id))
        conn.execute("UPDATE transaction_import_meta SET review_status='accepted' WHERE transaction_id=?", (transaction_id,))
        auto_classified = 0
        if payload.create_rule:
            pattern = normalize_label(payload.rule_pattern or row['normalized_label'])
            if not pattern:
                raise HTTPException(400, 'Motif de règle vide')
            existing = conn.execute('SELECT 1 FROM categorization_rules WHERE pattern=? AND category=? AND is_active=1', (pattern, payload.category)).fetchone()
            if not existing:
                conn.execute('INSERT INTO categorization_rules(pattern,category,transaction_type,priority) VALUES(?,?,?,?)', (pattern, payload.category, tx_type, 50))
            auto_classified = apply_rule_to_inbox(conn, pattern, payload.category, tx_type)
        refresh_review_counts(conn, {row['import_id']})
    return {'ok': True, 'transaction_id': transaction_id, 'auto_classified': auto_classified}


@router.post('/api/imports/inbox/{transaction_id}/ignore')
def ignore_imported_transaction(transaction_id: int):
    with connection() as conn:
        ensure_import_schema(conn)
        ensure_identity_schema(conn)
        row = conn.execute('SELECT import_id FROM transaction_import_meta WHERE transaction_id=?', (transaction_id,)).fetchone()
        if not row:
            raise HTTPException(404, 'Mouvement importé introuvable')
        conn.execute("UPDATE transaction_import_meta SET review_status='ignored' WHERE transaction_id=?", (transaction_id,))
        refresh_review_counts(conn, {row['import_id']})
    return {'ok': True}
