from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from .db import connection
from .import_identity import (
    ensure_identity_schema,
    find_duplicate_statement,
    import_rows_occurrence_safe,
    statement_fingerprint,
)
from .imports import ensure_import_schema, parse_statement, statement_metadata

router = APIRouter(prefix='/api/imports', tags=['imports'])
MAX_UPLOAD_BYTES = 12 * 1024 * 1024


@router.post('/activity', status_code=201)
async def import_current_activity(
    account_id: int = Form(...),
    file: UploadFile = File(...),
):
    """Import recent bank activity without pretending it is a monthly statement.

    The current activity feed is intentionally transaction-only: it advances
    transaction coverage and current-month observability, but never overwrites
    the operational account balance. The user can update that balance through
    the dedicated audited balance snapshot endpoint.
    """
    filename = Path(file.filename or 'activity.csv').name
    if not filename.lower().endswith('.csv'):
        raise HTTPException(400, 'Utilise un export CSV des opérations récentes')

    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, 'Fichier trop volumineux (12 Mo maximum)')

    try:
        parsed_source_type, _, rows = parse_statement(filename, data)
        if parsed_source_type != 'csv':
            raise ValueError('Le fichier doit être un CSV')
        metadata = statement_metadata(data, None, rows)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc

    with connection() as conn:
        ensure_import_schema(conn)
        ensure_identity_schema(conn)
        account = conn.execute(
            'SELECT id,name FROM accounts WHERE id=? AND is_active=1',
            (account_id,),
        ).fetchone()
        if not account:
            raise HTTPException(404, 'Compte introuvable')

        activity_fingerprint = statement_fingerprint(
            account_id,
            'CURRENT_ACTIVITY',
            metadata,
            rows,
        )
        duplicate = find_duplicate_statement(conn, account_id, activity_fingerprint)
        if duplicate:
            return {
                'duplicate_file': True,
                'duplicate_of_import_id': duplicate['id'],
                'filename': filename,
                'period_start': metadata.get('period_start'),
                'period_end': metadata.get('period_end'),
                'imported': 0,
                'duplicates': len(rows),
                'review': 0,
                'auto_classified': 0,
                'transaction_coverage_end': metadata.get('period_end'),
            }

        cur = conn.execute(
            '''INSERT INTO imports(
                   account_id,filename,source_type,bank,status,total_rows,
                   period_start,period_end,debit_total_cents,credit_total_cents,
                   statement_fingerprint,quality_status,quality_message
               ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)''',
            (
                account_id,
                filename,
                'bank_activity',
                'LCL',
                'processing',
                len(rows),
                metadata.get('period_start'),
                metadata.get('period_end'),
                metadata.get('debit_total_cents', 0),
                metadata.get('credit_total_cents', 0),
                activity_fingerprint,
                'unverified',
                'Import incrémental des opérations courantes',
            ),
        )
        import_id = cur.lastrowid

        conn.execute('SAVEPOINT current_activity_import')
        try:
            result = import_rows_occurrence_safe(conn, import_id, account_id, rows)
            tx_ids = [
                row['transaction_id']
                for row in conn.execute(
                    'SELECT transaction_id FROM transaction_import_meta WHERE import_id=?',
                    (import_id,),
                ).fetchall()
            ]
            if tx_ids:
                placeholders = ','.join('?' for _ in tx_ids)
                conn.execute(
                    f'''UPDATE transactions
                        SET source_type='bank_activity',
                            source_id=?,
                            source_date=booking_date,
                            source_status='confirmed',
                            confidence=1.0,
                            imported_at=CURRENT_TIMESTAMP
                        WHERE id IN ({placeholders})''',
                    (f'activity-import:{import_id}', *tx_ids),
                )

            quality_status = 'review' if result['review'] else 'ok'
            quality_message = (
                f"Activité récente importée jusqu'au {metadata.get('period_end')}; "
                f"{result['review']} mouvement(s) à revoir"
            )
            conn.execute(
                '''UPDATE imports
                   SET status='completed',imported_rows=?,duplicate_rows=?,review_rows=?,
                       auto_classified_rows=?,quality_status=?,quality_message=?
                   WHERE id=?''',
                (
                    result['imported'],
                    result['duplicates'],
                    result['review'],
                    result['auto_classified'],
                    quality_status,
                    quality_message,
                    import_id,
                ),
            )
            conn.execute('RELEASE SAVEPOINT current_activity_import')
        except Exception as exc:
            conn.execute('ROLLBACK TO SAVEPOINT current_activity_import')
            conn.execute('RELEASE SAVEPOINT current_activity_import')
            conn.execute(
                "UPDATE imports SET status='failed',error_message=? WHERE id=?",
                (str(exc)[:500], import_id),
            )
            raise HTTPException(500, 'Import interrompu sans écriture partielle') from exc

    return {
        'id': import_id,
        'account_id': account_id,
        'account_name': account['name'],
        'filename': filename,
        'duplicate_file': False,
        'period_start': metadata.get('period_start'),
        'period_end': metadata.get('period_end'),
        'transaction_coverage_end': metadata.get('period_end'),
        **result,
    }
